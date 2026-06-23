"""Project Shimmer pipeline driver (genesis Parts XI + XVIII).

Lifecycle:
  - BOOT: load constitution, bus, adaptive_spawn, convention_parser, reference_builder
  - DATE CASCADE: resolve dates for input/context/ documents; apply review_scope cutoff;
                  populate input/operational/ from the operational subset
  - PHASE 1: situation assessment
  - PHASE 3-4: content production (per-doc + corpus-level)
  - PHASE 5: verification + fact-check
  - PHASE 5.5: convention review (PRACTICE_AUDITOR + STYLE_GUARDIAN against conventions)
  - PHASE 6: synthesis — context_summary, operative_summary, amendments JSON, amendments docx
  - PHASE 7: DELTA proposals -> operator escalation
  - PHASE 8: persist, run summary

CLI shortcuts (also): --save-snapshot, --load-snapshot, --reset-snapshot, --list-snapshots
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from agent_wrapper import (AgentWrapper, load_api_keys, decode_items,
                           current_items, make_envelope, is_envelope)
import amendment_render
from audit_synthesizer import AuditSynthesizer
from convention_parser import parse_conventions, write_registry
from sensitivity_layer import redaction_rules
import sensitivity_layer
from corpus_validator import extract_distinctive_terms, validate_corpus_entry
import embedding_store
from cost_tracker import CostTracker, estimate_cost
from document_dating import read_dates, resolve_dates, write_dates
from model_registry import enforce_current_models
from snapshot_manager import (
    list_snapshots, load_snapshot, reset_snapshot, save_snapshot,
)
from orchestrator import OperatorDecision, TopOrchestrator
from pipeline_amendment_validator import validate_amendment_payload
from reference_builder import ReferenceIndex
from sensitivity_layer import redaction_detect
from sensitivity_layer.scrub import (scrub_master_and_body, scrub_text_artifacts_and_verify,
                                     _merge_redaction_proposals)
import redaction_gate
import run_context as run_context_mod
from review_scope import apply_cutoff
from search_router import SearchRouter
from summary_generators import render_context_summary, render_operative_summary
import text_extract


# Distinctive-term extraction is delegated to corpus_validator.extract_distinctive_terms,
# which runtime-detects CJK content and switches between whitespace tokens and
# character bigrams. A single function serves both the context-summary filter
# (FIX 2) and the corpus integrity check (FIX 4).


def _filter_context_refs_for_doc(
    all_context_refs: list[dict],
    doc_text: str,
    min_overlap: int = 2,
    fallback_first_n: int = 30,
    cap: int = 30,
) -> list[dict]:
    """Return context refs whose text_excerpt shares >= min_overlap distinctive
    words with doc_text. Falls back to the first fallback_first_n refs if
    fewer than 5 pass the filter."""
    if not all_context_refs:
        return []
    distinctive = set(extract_distinctive_terms(doc_text, n=20))
    if not distinctive:
        return all_context_refs[:cap]
    kept = []
    for ref in all_context_refs:
        excerpt = (ref.get("text_excerpt") or "").casefold()
        if not excerpt:
            continue
        hits = sum(1 for w in distinctive if w in excerpt)
        if hits >= min_overlap:
            kept.append((hits, ref))
    if len(kept) < 5:
        return all_context_refs[:fallback_first_n]
    kept.sort(key=lambda kv: -kv[0])
    return [ref for _, ref in kept[:cap]]


def _semantic_filter_context_refs(
    all_context_refs: list[dict],
    doc_text: str,
    embed_store: dict | None,
    *,
    n: int = 20,
) -> list[dict] | None:
    """Per Part XXI: when an embedding store is available, retrieve top-n
    context passages by cosine similarity to the operational document's
    first-page text. Map each result's ref_id back to an entry in the
    existing reference_index so citations remain consistent.

    Returns the filtered list, or None if the store isn't available
    (caller falls back to Zipfian filtering).
    """
    if embed_store is None or not all_context_refs or not doc_text:
        return None
    by_ref = {r.get("ref_id"): r for r in all_context_refs if r.get("ref_id")}
    if not by_ref:
        return None
    head = doc_text[:4000]  # the doc's first-page-equivalent slice as the query
    try:
        results = embedding_store.query_store(embed_store, head, n=n)
    except Exception as e:
        print(f"[pipeline] WARN: embedding query failed ({type(e).__name__}: {e}); "
              "Zipfian fallback active", file=sys.stderr, flush=True)
        return None
    if not results:
        return None
    out: list[dict] = []
    seen = set()
    for r in results:
        rid = r.get("ref_id")
        if rid in seen:
            continue
        seen.add(rid)
        if rid in by_ref:
            out.append(by_ref[rid])
        else:
            # Embedding store may have minted its own ref_ids (e.g. when built
            # without a shared reference_index); construct a ref dict so the
            # downstream summary still receives the passage with citation.
            out.append({
                "ref_id": rid, "input_type": "context",
                "document_id": r.get("doc_id", "?"),
                "document_name": r.get("doc_name", "?"),
                "location": {"page": r.get("page", "?"), "paragraph": 0},
                "text_excerpt": (r.get("text") or "")[:200],
            })
    return out or None


def _hit_to_ref_dict(hit: dict, baseline_by_ref: dict) -> dict:
    """Map an embedding-store hit to the reference-dict shape that
    downstream code (context_summary, agent context) expects."""
    rid = hit.get("ref_id")
    if rid and rid in baseline_by_ref:
        merged = dict(baseline_by_ref[rid])
        merged.setdefault("similarity", hit.get("similarity"))
        return merged
    return {
        "ref_id": rid, "input_type": "context",
        "document_id": hit.get("doc_id", "?"),
        "document_name": hit.get("doc_name", "?"),
        "location": {"page": hit.get("page", "?"), "paragraph": 0},
        "text_excerpt": (hit.get("text") or "")[:200],
        "similarity": hit.get("similarity"),
    }


def _provision_aware_context_refs(
    all_context_refs: list[dict],
    doc_text: str,
    provision_texts: list[str],
    embed_store: dict | None,
    *,
    n_baseline: int = 10,
    n_per_provision: int = 5,
    cap: int = 30,
) -> list[dict] | None:
    """Per Part XXI amendment: combine a per-document baseline query with
    per-provision queries (top n_per_provision each) to give agents diverse
    context. Deduplicates by ref_id; preserves baseline-first order.

    Returns the combined list, or None when the embedding store isn't
    available (caller falls back to Zipfian filtering)."""
    if embed_store is None or not doc_text:
        return None
    baseline_by_ref = {r.get("ref_id"): r for r in (all_context_refs or [])
                       if r.get("ref_id")}
    head = doc_text[:4000]
    try:
        baseline_hits = embedding_store.query_store(embed_store, head, n=n_baseline)
    except Exception as e:
        print(f"[pipeline] WARN: baseline embedding query failed "
              f"({type(e).__name__}: {e})", file=sys.stderr, flush=True)
        return None
    out: list[dict] = []
    seen: set[str] = set()
    for h in baseline_hits:
        rid = h.get("ref_id")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        out.append(_hit_to_ref_dict(h, baseline_by_ref))
    # Per-provision queries — each adds up to n_per_provision new refs.
    for prov in (provision_texts or []):
        if not prov:
            continue
        try:
            hits = embedding_store.query_store(embed_store, prov, n=n_per_provision)
        except Exception:
            continue
        for h in hits:
            rid = h.get("ref_id")
            if not rid or rid in seen:
                continue
            seen.add(rid)
            out.append(_hit_to_ref_dict(h, baseline_by_ref))
            if len(out) >= cap:
                return out
    return out[:cap] or None


def _segment_doc_text(text: str, n_segments: int = 5) -> list[str]:
    """Split text into n roughly-equal segments. Used as fallback provision
    texts when no convention list is available."""
    if not text:
        return []
    total = len(text)
    if total <= 500:
        return [text]
    seg_len = max(800, total // n_segments)
    return [text[i:i + seg_len] for i in range(0, total, seg_len) if text[i:i + seg_len].strip()]


def _convention_provision_texts(convention_registry: dict | None) -> list[str]:
    """Treat each convention rule's text as a 'provision' for embedding queries."""
    if not convention_registry:
        return []
    return [c.get("rule", "") for c in convention_registry.get("conventions", [])
            if c.get("rule")]


def _normalize_finding(f: dict) -> dict:
    """Merge cross-agent field-name variants into the canonical reasoning +
    verdict fields the operative summary template expects.

    PRACTICE_AUDITOR uses recommendation/procedure_text; STYLE_GUARDIAN uses
    rationale/suggested_edit; VERIFIER uses finding for the verdict slot.
    """
    out = dict(f)
    out["reasoning"] = (
        f.get("reasoning")
        or f.get("recommendation")
        or f.get("rationale")
        or f.get("suggested_edit")
        or f.get("procedure_text")
        or "(no reasoning provided)"
    )
    out["verdict"] = (
        f.get("verdict")
        or f.get("deviation")
        or f.get("finding")
        or "?"
    )
    return out


PRODUCTION_AGENTS_PER_DOC = ["PROCESSOR", "SPEECH_ACT_TAGGER", "LEGAL_ANALYST"]
PRODUCTION_AGENTS_CORPUS_LEVEL = ["ARCHIVIST", "INST_FINDER", "CITATION_RESOLVER"]
AUDIT_AGENTS_PER_DOC = ["VERIFIER", "FACT_CHECKER"]
CONVENTION_REVIEW_AGENTS = ["PRACTICE_AUDITOR", "STYLE_GUARDIAN"]


# ---------- corpus loading -----------------------------------------------------------------

def _load_corpus(input_dir: Path) -> list[dict]:
    docs = []
    if not input_dir.exists():
        return docs
    # Count stems first so collisions can be disambiguated. The doc id keys every
    # deliverable (output/runs/<run>/deliverables/<id>__*.md); two files sharing a
    # stem (e.g. policy.pdf and policy.docx) would clobber each other if both
    # keyed "policy". Collision-safe rule (Part XXVII §A): keep the bare stem when
    # unique; qualify only on collision as "<stem>__<ext>".
    stem_counts: dict[str, int] = {}
    loaded = []  # (path, name, text)
    for p in sorted(input_dir.iterdir()):
        if not p.is_file():
            continue
        # Shared format family (.pdf/.docx/.html/.htm/.txt/.md/.rst/.log/.json).
        # Unsupported types warn (never silently skipped).
        if not text_extract.is_supported(p):
            text_extract.warn_unsupported(p, where=str(input_dir.name))
            continue
        text = text_extract.extract_text(p)
        if not text.strip():
            continue
        loaded.append((p, p.name, text))
        stem_counts[p.stem] = stem_counts.get(p.stem, 0) + 1
    for p, name, text in loaded:
        doc_id = p.stem if stem_counts.get(p.stem, 0) <= 1 else f"{p.stem}__{p.suffix.lstrip('.').lower()}"
        docs.append({"id": doc_id, "name": name, "text": text,
                     "char_count": len(text), "path": str(p)})
    return docs


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n... [truncated for token budget] ...\n" + text[-half:]


# ---------- cutoff + operational population --------------------------------------------------

def _resolve_review_scope(project_root: Path) -> dict:
    path = project_root / "config" / "review_scope.json"
    if not path.exists():
        return {"cutoff_type": "all"}
    try: return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError: return {"cutoff_type": "all"}


def _populate_operational(project_root: Path, search_router: SearchRouter) -> tuple[list[dict], list[dict]]:
    """Returns (context_records, operational_records). Each record:
       {filename, date, date_source, title, abs_path}."""
    context_dir = project_root / "input" / "context"
    operational_dir = project_root / "input" / "operational"
    operational_dir.mkdir(parents=True, exist_ok=True)
    # Clear operational/ before repopulating per spec
    for f in operational_dir.glob("*"):
        if f.is_file(): f.unlink()
    # Same format family as _load_corpus. Unsupported files are warned there
    # (this loader also scans context_dir); here we just filter to candidates.
    candidate_files = sorted(p for p in context_dir.iterdir()
                             if p.is_file() and text_extract.is_supported(p))
    if not candidate_files:
        return [], []
    dated = resolve_dates(candidate_files, search_router=search_router)
    for record, path in zip(dated, candidate_files):
        record["abs_path"] = str(path)
    write_dates(project_root, dated)
    scope = _resolve_review_scope(project_root)
    operational = apply_cutoff(dated, scope)
    operational_filenames = {r["filename"] for r in operational}
    context_only = [r for r in dated if r["filename"] not in operational_filenames]
    # Copy operational files into input/operational/ and run the content
    # validator on each. The validator is language-agnostic — it derives
    # keywords from the document's own first page (Zipfian filter) and
    # confirms at least 1 of them appears in the filename slug. Failures
    # do NOT skip the document; they record a content_validated flag in
    # document_dates.json so downstream agents and the operator know.
    for record in operational:
        src = Path(record["abs_path"])
        dst = operational_dir / src.name
        shutil.copy2(src, dst)
        record["abs_path"] = str(dst)
        try:
            valid, excerpt, matched = validate_corpus_entry(dst)
        except Exception as e:
            valid, excerpt, matched = False, "", []
            record["validation_error"] = f"{type(e).__name__}: {e}"
        record["content_validated"] = bool(valid)
        record["validation_note"] = (
            f"matched={matched}; first_page_excerpt={excerpt[:200]!r}"
            if matched or excerpt
            else "no first-page text extracted"
        )
        if not valid:
            print(
                f"[pipeline] WARN: {dst.name} may be misclassified — first page does not "
                f"match expected content ({len(matched)} keywords matched)",
                file=sys.stderr, flush=True,
            )
    # Rewrite document_dates.json with validation fields populated (operational
    # entries replace the originals; context-only entries pass through unchanged).
    by_filename = {r["filename"]: r for r in operational}
    merged = [by_filename.get(r["filename"], r) for r in dated]
    write_dates(project_root, merged)
    return context_only, operational


# ---------- agent helpers ------------------------------------------------------------------

def _build_wrapper(name: str, orch: TopOrchestrator, keys: dict) -> AgentWrapper:
    return AgentWrapper(name=name, constitution=orch.constitution, bus=orch.bus,
                        registry=orch.registry, contracts=orch.contracts,
                        keys=keys, cost_tracker=orch.cost_tracker)


async def _run_one(wrapper, work_payload, run_objectives, channel="main", max_tokens=2048,
                   convention_registry=None, reference_index_excerpt=None):
    return await asyncio.to_thread(
        wrapper.run_task, work_payload=work_payload, run_objectives=run_objectives,
        channel=channel, max_tokens=max_tokens,
        convention_registry=convention_registry,
        reference_index_excerpt=reference_index_excerpt,
    )


# ---------- pipeline phases ----------------------------------------------------------------

async def phase_3_4_content_production(orch, keys, op_docs, ctx_docs,
                                        run_objectives, convention_registry,
                                        reference_index, ctx_refs_excerpt,
                                        embed_store=None):
    """Run corpus-level and per-doc production agents."""
    results = []
    # Corpus-level uses both context and operational docs (everything in input/).
    # Per-doc digest is held to 1200 chars to keep large corpora affordable.
    all_docs = op_docs + ctx_docs
    digest = "\n\n=========\n\n".join(
        f"### Document: {d['name']}\n\n{_truncate(d['text'], 1200)}" for d in all_docs
    )
    for agent_name in PRODUCTION_AGENTS_CORPUS_LEVEL:
        wrapper = _build_wrapper(agent_name, orch, keys)
        payload = {"task": "corpus_level_analysis",
                   "documents": [d["name"] for d in all_docs],
                   "corpus_text": digest}
        result = await _run_one(wrapper, payload, run_objectives, channel="main",
                                max_tokens=2048,
                                convention_registry=convention_registry,
                                reference_index_excerpt=ctx_refs_excerpt)
        results.append({"scope": "corpus", "agent": agent_name, **result})
    # Per-doc only for OPERATIONAL docs (context is reference only).
    # Per Part XXI amendment, LEGAL_ANALYST gets provision-aware context refs.
    # Per Part XXVI, LEGAL_ANALYST also receives the structural inventory
    # extracted from the just-completed ARCHIVIST corpus output.
    all_context_refs = [e.as_dict() for e in reference_index.entries
                        if e.input_type == "context"]
    convention_provisions = _convention_provision_texts(convention_registry)
    structural_inventory = _structural_inventory(results)
    if structural_inventory:
        print(f"[pipeline] structural inventory: {len(structural_inventory)} elements "
              f"identified by ARCHIVIST", file=sys.stderr, flush=True)
    for doc in op_docs:
        payload = {"task": "per_document_analysis",
                   "document_id": doc["id"], "document_name": doc["name"],
                   "document_text": _truncate(doc["text"], 7000),
                   "structural_inventory": structural_inventory}
        provisions = convention_provisions or _segment_doc_text(doc["text"])
        provision_refs = _provision_aware_context_refs(
            all_context_refs, doc["text"], provisions, embed_store, cap=30,
        )
        tasks = []
        for agent_name in PRODUCTION_AGENTS_PER_DOC:
            wrapper = _build_wrapper(agent_name, orch, keys)
            if agent_name == "LEGAL_ANALYST" and provision_refs:
                refs_excerpt = provision_refs
            else:
                refs_excerpt = _doc_refs_excerpt(reference_index, doc['id'])
            tasks.append(_run_one(wrapper, payload,
                                  f"{run_objectives}\nDocument: {doc['name']}",
                                  max_tokens=2048,
                                  convention_registry=convention_registry,
                                  reference_index_excerpt=refs_excerpt))
        doc_results = await asyncio.gather(*tasks)
        for name, r in zip(PRODUCTION_AGENTS_PER_DOC, doc_results):
            results.append({"scope": "doc", "doc_id": doc["id"], "agent": name, **r})
    return results


async def phase_5_audit(orch, keys, op_docs, production, run_objectives,
                        convention_registry, reference_index):
    by_doc_agent = {(r["doc_id"], r["agent"]): r
                    for r in production if r.get("scope") == "doc"}
    out = []
    for doc in op_docs:
        proc = by_doc_agent.get((doc["id"], "PROCESSOR"))
        draft = proc.get("parsed") if proc else None
        verifier_payload = {"task": "verify_draft_against_source",
                            "document_name": doc["name"],
                            "source_text": _truncate(doc["text"], 5500),
                            "processor_draft": draft}
        fc_payload = {"task": "extract_and_verify_claims",
                      "document_name": doc["name"], "processor_draft": draft,
                      "source_excerpt": _truncate(doc["text"], 3500)}
        tasks = []
        for name, payload in (("VERIFIER", verifier_payload), ("FACT_CHECKER", fc_payload)):
            wrapper = _build_wrapper(name, orch, keys)
            tasks.append(_run_one(wrapper, payload,
                                  f"{run_objectives}\nDocument: {doc['name']}",
                                  max_tokens=2048,
                                  convention_registry=convention_registry,
                                  reference_index_excerpt=_doc_refs_excerpt(reference_index, doc['id'])))
        audit_results = await asyncio.gather(*tasks)
        for name, r in zip(("VERIFIER", "FACT_CHECKER"), audit_results):
            out.append({"scope": "doc", "doc_id": doc["id"], "agent": name, **r})
    return out


async def phase_5_5_convention_review(orch, keys, op_docs, run_objectives,
                                      convention_registry, reference_index,
                                      embed_store=None, structural_inventory=None):
    """Convention-driven review: PRACTICE_AUDITOR + STYLE_GUARDIAN against the registry.

    Per Part XXI amendment, both agents receive provision-aware context refs
    (baseline doc query + per-convention-rule queries merged). Per Part XXVI,
    PRACTICE_AUDITOR additionally receives the structural inventory in its
    work payload so its absence-detection directive has data to work with.
    """
    out = []
    all_context_refs = [e.as_dict() for e in reference_index.entries
                        if e.input_type == "context"]
    convention_provisions = _convention_provision_texts(convention_registry)
    for doc in op_docs:
        provisions = convention_provisions or _segment_doc_text(doc["text"])
        provision_refs = _provision_aware_context_refs(
            all_context_refs, doc["text"], provisions, embed_store, cap=30,
        )
        refs_excerpt = provision_refs or _doc_refs_excerpt(reference_index, doc['id'])
        base_payload = {"task": "convention_review",
                        "document_id": doc["id"], "document_name": doc["name"],
                        "document_text": _truncate(doc["text"], 6500),
                        "evaluate_against": [c.get("id") for c in convention_registry.get("conventions", [])]}
        tasks = []
        for name in CONVENTION_REVIEW_AGENTS:
            wrapper = _build_wrapper(name, orch, keys)
            payload = dict(base_payload)
            if name == "PRACTICE_AUDITOR" and structural_inventory:
                payload["structural_inventory"] = structural_inventory
            tasks.append(_run_one(wrapper, payload,
                                  f"{run_objectives}\nDocument: {doc['name']}\n"
                                  f"Evaluate against the convention registry. Every finding "
                                  f"MUST cite both CONV-* and REF-*.",
                                  max_tokens=2048,
                                  convention_registry=convention_registry,
                                  reference_index_excerpt=refs_excerpt))
        rev_results = await asyncio.gather(*tasks)
        for name, r in zip(CONVENTION_REVIEW_AGENTS, rev_results):
            out.append({"scope": "doc", "doc_id": doc["id"], "agent": name, **r})
    return out


def _doc_refs_excerpt(reference_index, document_id):
    return [e.as_dict() for e in reference_index.find_by_document(document_id)[:30]]


def _items_for(results, agent, *, doc_id=None, scope=None):
    """THE single results-level adapter over the canonical decoder (INFRA-037).

    Decode every matching agent result's wrapper (body.payload) into its CURRENT
    items (highest revision per item_id) via agent_wrapper.decode_items, and
    concatenate. Replaces the three former normalizers (_filter_doc, _flatten,
    _extract_structural_inventory) — there is no other reader of agent items."""
    out = []
    for r in results:
        if r.get("agent") != agent or not r.get("ok"):
            continue
        if doc_id is not None and r.get("doc_id") != doc_id:
            continue
        if scope is not None and r.get("scope") != scope:
            continue
        out.extend(decode_items(r.get("parsed")))
    return out


def _structural_inventory(production_results: list) -> list[dict]:
    """Per Part XXVI: ARCHIVIST's corpus-level inventory is now one item per
    governance element (kind='inventory'); decode them via the canonical decoder."""
    return [it for it in _items_for(production_results, "ARCHIVIST", scope="corpus")
            if it.get("kind") == "inventory"]


# ---------- phase 6: synthesis ---------------------------------------------------------------


def _harvest_amendment_payloads_from_bus(orch) -> dict:
    """Return {document_id: amendments_master} for any AMENDMENT_DRAFTER outputs
    already on the bus, so phase 6 can skip re-running them. Reads the canonical
    wrapper (INFRA-037) via the decoder and builds the INFRA-033 amendments MASTER
    ({document_id, amendments:[items]}) — the master shape is unchanged."""
    out = {}
    for msg in orch.bus.read_all():
        if msg.get("sender") != "AMENDMENT_DRAFTER" or msg.get("type") != "INFORM":
            continue
        body = msg.get("body") or {}
        if body.get("event") != "AGENT_OUTPUT":
            continue
        payload = body.get("payload")
        if is_envelope(payload):
            out[payload["doc_id"]] = {"document_id": payload["doc_id"],
                                      "amendments": decode_items(payload)}
    return out


async def phase_6_synthesis(orch, keys, op_docs, production, audit, conv_review,
                            run_objectives, convention_registry, reference_index,
                            embed_store=None):
    """Produce context_summary, operative_summary, amendments JSON+md, amendments.docx.

    `embed_store` (genesis Part XXI): when provided, per-doc context filtering
    uses cosine-similarity retrieval instead of Zipfian term matching. The
    REF-* citation format is identical regardless of which path runs.
    """
    # Per-run deliverables folder (Part XXVII §A): output/runs/<run>/deliverables/.
    deliv_dir = orch.run_context.deliverables_dir()
    deliv_dir.mkdir(parents=True, exist_ok=True)
    deliverables = {}
    existing_amendments = _harvest_amendment_payloads_from_bus(orch)
    conventions_by_category = {}
    for c in convention_registry.get("conventions", []):
        conventions_by_category.setdefault(c.get("category", "unclassified"), []).append(c)

    all_context_refs = [e.as_dict() for e in reference_index.entries
                        if e.input_type == "context"]
    n_total_conventions = len(convention_registry.get("conventions", []))
    retrieval_mode = "semantic" if embed_store else "zipfian"
    print(f"[pipeline] phase 6 context retrieval mode: {retrieval_mode}",
          file=sys.stderr, flush=True)

    for doc in op_docs:
        # Findings first — they determine the topical scope for context_summary too.
        pa_findings = _items_for(conv_review, "PRACTICE_AUDITOR", doc_id=doc["id"]) or []
        sg_findings = _items_for(conv_review, "STYLE_GUARDIAN", doc_id=doc["id"]) or []
        findings = []
        categories_with_findings = set()
        for agent, raw_findings in (("PRACTICE_AUDITOR", pa_findings),
                                     ("STYLE_GUARDIAN", sg_findings)):
            for f in raw_findings:
                cat = _category_for_conv(f.get("conv_id"), convention_registry) or "unclassified"
                normalized = _normalize_finding(f)
                normalized["category"] = cat
                normalized["agent"] = agent
                findings.append(normalized)
                categories_with_findings.add(cat)

        # Context summary: doc-specific topical filter on refs + topics from
        # categories where findings actually fired. When a semantic embedding
        # store is available, use cosine similarity (Part XXI); otherwise fall
        # back to Zipfian term matching. Both paths produce REF-* citations.
        ctx_refs = _semantic_filter_context_refs(
            all_context_refs, doc["text"], embed_store, n=20,
        ) or _filter_context_refs_for_doc(all_context_refs, doc["text"])
        topics = sorted(categories_with_findings) if categories_with_findings \
            else list(conventions_by_category.keys())
        ctx_body = (
            f"This document was reviewed against {n_total_conventions} conventions. "
            f"{len(findings)} findings were produced by PRACTICE_AUDITOR and STYLE_GUARDIAN. "
            f"The context references below are filtered for topical relevance to {doc['name']}."
        )
        ctx_summary = render_context_summary(
            document_id=doc["id"], document_name=doc["name"],
            context_refs=ctx_refs, topics=topics, body_text=ctx_body,
        )
        (deliv_dir / f"{doc['id']}__context_summary.md").write_text(ctx_summary, encoding="utf-8")

        op_summary = render_operative_summary(
            document_id=doc["id"], document_name=doc["name"],
            conventions_by_category=conventions_by_category, findings=findings,
            body_text="Findings are produced by PRACTICE_AUDITOR and STYLE_GUARDIAN in PHASE 5.5 "
                       "against the convention registry. Each finding cites the convention ID and "
                       "the operational reference ID(s).",
        )
        (deliv_dir / f"{doc['id']}__operative_summary.md").write_text(op_summary, encoding="utf-8")

        # AMENDMENT_DRAFTER (skip if we have a fresh payload already on the bus)
        if doc["id"] in existing_amendments:
            amendments_payload = dict(existing_amendments[doc["id"]])
            print(f"[pipeline] reusing existing AMENDMENT_DRAFTER output for {doc['id']} "
                  f"({len(amendments_payload.get('amendments', []))} amendments)", file=sys.stderr)
        else:
            amendment_drafter = _build_wrapper("AMENDMENT_DRAFTER", orch, keys)
            amend_payload = {
                "task": "draft_amendments",
                "document_id": doc["id"], "document_name": doc["name"],
                "document_text": _truncate(doc["text"], 5000),
                "findings_from_practice_auditor": _items_for(conv_review, "PRACTICE_AUDITOR", doc_id=doc["id"]),
                "findings_from_style_guardian":   _items_for(conv_review, "STYLE_GUARDIAN", doc_id=doc["id"]),
                "findings_from_verifier":         _items_for(audit, "VERIFIER", doc_id=doc["id"]),
                "findings_from_fact_checker":     _items_for(audit, "FACT_CHECKER", doc_id=doc["id"]),
                "convention_ids_in_scope": [c.get("id") for c in convention_registry.get("conventions", [])],
                "reference_index_excerpt": _doc_refs_excerpt(reference_index, doc["id"]),
            }
            # Per Part XXI amendment: AMENDMENT_DRAFTER gets provision-aware
            # context refs — baseline doc query plus per-convention-rule queries.
            convention_provisions = _convention_provision_texts(convention_registry)
            provisions = convention_provisions or _segment_doc_text(doc["text"])
            amendment_refs = _provision_aware_context_refs(
                all_context_refs, doc["text"], provisions, embed_store, cap=30,
            ) or _doc_refs_excerpt(reference_index, doc["id"])
            result = await _run_one(
                amendment_drafter, amend_payload,
                f"{run_objectives}\nProduce a complete amendments object for {doc['name']}. "
                f"Every amendment.comment MUST contain at least one CONV-* and one REF-*.",
                channel="main", max_tokens=4096,
                convention_registry=convention_registry,
                reference_index_excerpt=amendment_refs,
            )
            # Decode the canonical wrapper (INFRA-037) into the INFRA-033 master.
            # decode_items returns the CURRENT revision per item even on a
            # best-effort (contract_violation) wrapper, so a partial result is not
            # discarded — it is filtered below (phase-6 amendment salvage stays
            # lenient; that asymmetry vs the strict LAW-IV redaction path is
            # intentional).
            parsed = result.get("parsed")
            raw_amendments = decode_items(parsed) if is_envelope(parsed) else []
            amendments_payload = {"document_id": doc["id"], "amendments": raw_amendments}

            if result.get("error") == "contract_violation":
                kept = []
                for a in raw_amendments:
                    if not isinstance(a, dict):
                        continue
                    # location, convention_ref, comment are the three fields
                    # that make an amendment traceable. Drop anything missing them.
                    if (a.get("location") and a.get("convention_ref") and a.get("comment")):
                        kept.append(a)
                dropped = len(raw_amendments) - len(kept)
                if dropped:
                    print(
                        f"[pipeline] WARN: AMENDMENT_DRAFTER for {doc['name']} had "
                        f"{dropped} incomplete amendments filtered out",
                        file=sys.stderr, flush=True,
                    )
                amendments_payload["amendments"] = kept

        ok_payload, errs = validate_amendment_payload(amendments_payload)
        amendments_payload["_validator_errors"] = errs

        # Single canonical master -> on-demand renders (Part XXVII §E / INFRA-033).
        # amendments_payload (also written verbatim as __amendments.json) is the
        # MASTER; the .md and .docx are pure renders DERIVED from it through the one
        # entry point in amendment_render. No render reads amendment content from an
        # independent source, so the three files cannot drift.
        amend = amendment_render.write_amendment_deliverables(
            amendments_payload, deliv_dir=deliv_dir, doc_id=doc["id"],
            document_name=doc["name"], body_text=doc["text"],
            category_for_conv=lambda c: _category_for_conv(c, convention_registry),
        )
        if amend.get("docx_error"):
            print(f"[pipeline] WARN: docx build failed for {doc['name']}: {amend['docx_error']}",
                  file=sys.stderr)
        docx_path = deliv_dir / f"{doc['id']}__amendments.docx"

        # Per-agent deliverable
        per_agent_path = deliv_dir / f"{doc['id']}__deliverable.md"
        per_agent_path.write_text(_render_per_agent_md(doc, production, audit, conv_review),
                                  encoding="utf-8")

        deliverables[doc["id"]] = {
            "context_summary": str(deliv_dir / f"{doc['id']}__context_summary.md"),
            "operative_summary": str(deliv_dir / f"{doc['id']}__operative_summary.md"),
            "amendments_json": str(deliv_dir / f"{doc['id']}__amendments.json"),
            "amendments_md": str(deliv_dir / f"{doc['id']}__amendments.md"),
            "amendments_docx": str(docx_path) if docx_path.exists() else None,
            "per_agent_deliverable": str(per_agent_path),
            "validator_errors": errs,
            "amendment_count": len(amendments_payload.get("amendments", [])),
        }

    return deliverables



# Repo root (scripts/..) — used to locate the language DATA resource for the
# language-neutral redaction detectors/normalizer.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# --- Operator-escalation schema (stable shape for the future operator UI) ------
# One structured object is the SINGLE source of truth for both the machine-readable
# bus message and the human console notice, so the two can never disagree.
ESCALATION_SCHEMA = "operator_escalation/v1"

# internal failure_kind -> (message verb, remediation hint). The public taxonomy on
# the object collapses the two contract_violation_* kinds to "contract_violation".
_REDACTION_FAILURE = {
    "contract_violation_parse": (
        "failed to parse",
        "The redactor ran but its output could not be parsed as JSON, even after "
        "tolerant extraction. Inspect the raw output below, then re-run; if the local "
        "model keeps emitting malformed output, repair or replace the Qwen redaction backend."),
    "contract_violation_fields": (
        "failed to satisfy the redaction contract",
        "The redactor ran and returned JSON, but it does not match the required "
        "redactions contract (segment_id / tier / redactions array). Inspect the raw "
        "output below, then re-run; repair the model or prompt if it persists."),
    "redactor_unavailable": (
        "failed to reach the redaction backend",
        "The local Qwen redaction backend was unreachable. Make it reachable (install/"
        "repair torch + transformers and the model) and re-run, or re-run with "
        "--no-redaction-override to consciously waive redaction for a non-sensitive run "
        "(logged to the governance ledger)."),
    "no_resolvable_redaction": (
        "returned items but none resolved to a valid redaction",
        "The redactor returned a valid wrapper with items, but NONE resolved to a usable "
        "redaction (a span plus a replacement / method=REDACT / a redaction category) — "
        "e.g. redactions mis-tagged as kind='finding'. This is NOT a clean 'nothing to "
        "redact' result, so it is BLOCKED rather than silently passed. Inspect the persisted "
        "raw output, fix the clerk prompt/model, and re-run."),
    "span_dropped": (
        "an approved redaction span could not be located in any shipped artifact",
        "A span the clerk proposed (and AUTHORITY+GATE cleared) produced ZERO substitutions "
        "across every operator-facing artifact, even after normalized matching (ال-prefix, "
        "intervening connective text, whitespace, diacritics). A span that cannot be located "
        "is a FAILED substitution, never a silent zero-match: the run BLOCKS so the operator "
        "decides. See `detail.dropped_spans`. Fix the clerk span text/prompt or the matcher, "
        "then re-run."),
    "no_operator_rule": (
        "no operator redaction rule is in force",
        "Redaction is required but NO operator rule compiled, so there is nothing the "
        "operator has declared redactable. The engine does NOT invent default categories "
        "(operator-sovereignty). Supply a compiling redaction convention, or re-run with "
        "--no-redaction-override to consciously declare redact-nothing for THIS run "
        "(logged to the governance ledger). Never a silent default; never a silent ship."),
    "pii_survives_in_deliverable": (
        "an approved redaction span SURVIVED in a shipped artifact after apply",
        "After applying redactions, the post-apply verification grep found an approved span "
        "still present in an operator-facing artifact (deliverable / summary / master / "
        "rendered docx text). 'Applied' must mean verified-absent everywhere shippable, so "
        "this BLOCKS rather than reporting success. See `detail.survivors` for the artifact(s) "
        "and span(s). This is a LAW-IV safety stop."),
    "adversarial_test_failed": (
        "REDACT_AUTHORITY approved the set but its adversarial re-identification test FAILED",
        "AUTHORITY returned approved=true but adversarial_test_passed=false: the model's own "
        "re-identification test says the redaction set can still be reconstructed. An approved-"
        "but-unconfirmable redaction is NOT silently applied — it BLOCKS so the operator decides. "
        "This is distinct from a garbled/missing field (contract_violation): the field was a clean "
        "boolean False, a genuine failed test. Strengthen the redaction set (the clerk's spans / "
        "categories) or the AUTHORITY prompt, then re-run. This is a LAW-IV safety stop."),
}


# Failure kinds that surface to the operator under their own name (the two
# contract_violation_* kinds collapse to "contract_violation"; everything else
# passes through verbatim).
_REDACTION_PUBLIC_KINDS = frozenset({
    "redactor_unavailable", "no_resolvable_redaction",
    "span_dropped", "pii_survives_in_deliverable", "no_operator_rule",
    "adversarial_test_failed",
})


def build_redaction_escalation(*, doc_id, document_name, stage, failure_kind,
                               raw_output_path, detail=None):
    """Build the structured, machine-readable operator-escalation object for a
    redaction that could not be confirmed clean (LAW-IV). Reusable schema
    (`operator_escalation/v1`); the bus message and the console notice both derive
    from this one object. `detail` (optional) carries application-layer specifics
    (e.g. dropped spans / survivors per artifact) without changing the schema."""
    public_kind = (failure_kind if failure_kind in _REDACTION_PUBLIC_KINDS
                   else "contract_violation")
    verb, remediation = _REDACTION_FAILURE.get(
        failure_kind, _REDACTION_FAILURE["contract_violation_fields"])
    esc = {
        "schema": ESCALATION_SCHEMA,
        "kind": "REDACTION_BLOCKED",
        "severity": "BLOCK",
        "needs_operator": True,
        "phase": "redaction",
        "stage": stage,                  # the agent/step that failed, e.g. REDACT_CLERK
        "doc_id": doc_id,
        "document_name": document_name,
        "failure_kind": public_kind,     # contract_violation | redactor_unavailable | span_dropped | pii_survives_in_deliverable
        "raw_output_path": raw_output_path,
        "message": f"redaction did not pass: {verb}",
        "remediation": remediation,
    }
    if detail is not None:
        esc["detail"] = detail
    return esc


def render_escalation_notice(esc):
    """Human-readable BLOCK notice, derived from the SAME structured escalation
    object so console and bus never disagree."""
    lines = [
        "",
        "================ REDACTION BLOCK (LAW-IV) ================",
        f"  BLOCKED deliverable: {esc['document_name']!r} (doc id: {esc['doc_id']})",
        f"  Why:    {esc['message']}  (failure_kind = {esc['failure_kind']})",
        f"  Where:  phase {esc['phase']!r}, agent {esc['stage']}",
    ]
    if esc.get("raw_output_path"):
        lines.append(f"  Raw output: {esc['raw_output_path']}")
    lines.append(f"  Next:   {esc['remediation']}")
    lines.append("  This deliverable was NOT confirmed clean — it is BLOCKED, not skipped.")
    lines.append("=========================================================")
    return "\n".join(lines)


def _post_redaction_block(orch, esc):
    """Post the structured escalation to the bus (machine-readable, type ESCALATE)
    AND print the human notice derived from the same object."""
    orch._post_orchestrator(
        recipient="OPERATOR", channel="escalation", msg_type="ESCALATE",
        body={"event": "REDACTION_BLOCKED", "escalation": esc},
        constitution_check={"laws_consulted": ["LAW-IV", "LAW-V"], "result": "UNRESOLVED",
                            "resolution": "redaction could not be confirmed clean; operator must decide"})
    print(render_escalation_notice(esc), file=sys.stderr, flush=True)


def _redaction_result_block(orch, doc, result, *, stage, required_key):
    """LAW-IV strict guard: confirm a redaction agent's result is a CONTRACT-VALID
    canonical wrapper (INFRA-037) carrying at least one item with `required_key`.
    If so, return None. Otherwise (run_task failed, the payload is not the wrapper,
    or no item carries the field) emit the strict LAW-IV BLOCK — reusing
    build_redaction_escalation + _post_redaction_block (no second copy) — and
    return the escalation dict so the caller records state=BLOCKED and stops.

    failure_kind distinguishes contract_violation (the agent RAN but returned an
    unparseable / non-wrapper / field-missing result) from redactor_unavailable
    (the agent did not run / backend unreachable). Reading goes through the one
    canonical decoder; nothing bypasses it."""
    parsed = result.get("parsed")
    if result.get("ok") and is_envelope(parsed):
        if any(isinstance(it, dict) and required_key in it for it in decode_items(parsed)):
            return None
    if not result.get("ok"):
        if result.get("error") == "contract_violation":
            miss = result.get("contract_missing") or []
            parse_failed = any(str(m).startswith("json parse failure")
                               or str(m) == "no JSON object found in output" for m in miss)
            failure_kind = ("contract_violation_parse" if parse_failed
                            else "contract_violation_fields")
        else:
            failure_kind = "redactor_unavailable"
    else:
        # ran (ok=True) but the result is not a wrapper carrying the field
        failure_kind = "contract_violation_fields"
    esc = build_redaction_escalation(
        doc_id=doc["id"], document_name=doc["name"], stage=stage,
        failure_kind=failure_kind, raw_output_path=result.get("raw_text_path"))
    _post_redaction_block(orch, esc)
    return esc


def _post_redaction(orch, doc_id, event, body):
    """Post an auditable redaction-decision event to the run bus (LAW-IV)."""
    orch._post_orchestrator(
        recipient="OPERATOR", channel="redaction", msg_type="INFORM",
        body={"event": event, "document_id": doc_id, **body},
        constitution_check={"laws_consulted": ["LAW-IV", "LAW-V"], "result": "RESOLVED",
                            "resolution": "redaction screening at the output boundary"})


_REDACTION_CATEGORY_HINTS = ("confiden", "redact", "privacy", "pii")


def _norm_redaction_category(cat) -> str:
    """Normalize a redaction category string so 'conv-confidentiality' and
    'confidentiality' do not diverge: strip a leading 'conv-' and lowercase."""
    c = str(cat or "").strip().lower()
    if c.startswith("conv-"):
        c = c[len("conv-"):]
    return c


def _is_redaction_proposal(it) -> bool:
    """STRUCTURAL redaction detection (defense in depth): an item is a redaction
    proposal if it carries a non-empty `span` AND any redaction signal — a
    `replacement`, method=REDACT/MASK/REMOVE, or a redaction `category` — OR it is
    explicitly kind='redaction'. A free-text `kind` label from a 7B is never the
    SOLE gate on this safety-critical filter (a redaction mis-tagged kind='finding'
    is still detected and applied)."""
    if not isinstance(it, dict):
        return False
    if str(it.get("kind", "")).strip().lower() == "redaction":
        return True
    span = it.get("span")
    if not (isinstance(span, str) and span.strip()):
        return False
    method = str(it.get("method", "")).strip().lower()
    cat = _norm_redaction_category(it.get("category"))
    return (bool(it.get("replacement"))
            or method in ("redact", "mask", "remove")
            or any(h in cat for h in _REDACTION_CATEGORY_HINTS))


def _classify_clerk_items(items):
    """Classify the clerk's decoded items into a redaction outcome (no model call):
      ([], ...)                          -> ("NONE", [])     legitimate 'nothing to redact'
      non-empty, none is a redaction     -> ("BLOCK", [])    non-empty-but-unresolved (LOUD, never silent)
      one or more redaction proposals    -> ("PROPOSE", reds) the structurally-detected redactions
    Each returned redaction has its category normalized."""
    items = [it for it in (items or []) if isinstance(it, dict)]
    if not items:
        return ("NONE", [])
    reds = []
    for it in items:
        if _is_redaction_proposal(it):
            r = dict(it)
            r["category"] = _norm_redaction_category(it.get("category"))
            reds.append(r)
    if not reds:
        return ("BLOCK", [])
    return ("PROPOSE", reds)


def _persist_redactor_output(run_ctx, stage, doc_id, result) -> "str | None":
    """Persist a redactor's raw + parsed output to the run audit dir on EVERY path
    (not only on contract violation), so a future anomaly is diagnosable from disk,
    not only the bus. Closes the raw_text_path=None gap on the ok/NONE path. Returns
    the path, or None if run_ctx is unavailable / the write failed (best-effort,
    never raises)."""
    if run_ctx is None:
        return None
    try:
        out_dir = run_ctx.audit_dir() / "redaction"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{stage}_{doc_id}.json"
        path.write_text(json.dumps({
            "stage": stage, "doc_id": doc_id, "ok": result.get("ok"),
            "error": result.get("error"), "parsed": result.get("parsed"),
            "raw_text": result.get("raw_text", ""),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
    except Exception:
        return None


def _classify_adversarial(auth_items):
    """Read the VALUE of REDACT_AUTHORITY's adversarial_test_passed and keep THREE
    cases distinct (baseline cleanup before Stage 3b — enforce the adversarial gate):

      (i)  any item's adversarial_test_passed is present but NOT a clean boolean
           (null / string / number) -> the model garbled the field -> BLOCK with the
           EXISTING failure_kind 'contract_violation_fields'. Like a missing required
           field, a malformed one is a contract-shape failure regardless of approved.
      (ii) approved AND every adversarial_test_passed is boolean True -> proceed.
      (iii) approved AND any adversarial_test_passed is boolean False -> a GENUINE
           failed re-identification test -> BLOCK 'adversarial_test_failed' (distinct
           from a garbled field). Never silently applied (LAW-IV).

    A MISSING field never reaches here: it is contract-required, so run_task already
    BLOCKed it upstream as contract_violation_fields (the field's presence is enforced
    by the parser; this reads its value). When approved is False the model declined to
    approve at all — the existing NOT_APPLIED path handles it, so no adversarial BLOCK
    fires (the test value is moot). Returns (approved: bool, block_failure_kind|None)."""
    approved = bool(auth_items) and all(bool(it.get("approved")) for it in auth_items)
    adv = [it.get("adversarial_test_passed") for it in auth_items]
    if any(not isinstance(v, bool) for v in adv):
        return approved, "contract_violation_fields"
    if approved and not all(v is True for v in adv):
        return approved, "adversarial_test_failed"
    return approved, None


def phase_9_redaction(orch, keys, op_docs, deliverables, run_ctx, convention_registry,
                      *, redaction_enabled=True):
    """FINAL always-on pass (Part II redaction agents, LAW-IV). Runs every run,
    regardless of whether anything is redacted. The three Qwen agents screen each
    document's deliverables and APPLY the operator redaction rules (LAW-IV's own
    phrase, "content marked for redaction") — the model does NOT judge sensitivity
    on its own; it applies the rules the operator declared (INFRA-038):

      REDACT_CLERK   proposes tier 1-2 redactions,
      REDACT_AUTHORITY approves tier 3-4 + adversarial test,
      REDACT_GATE    final pass/fail.

    When a redaction is approved AND passed, it is applied THROUGH the canonical
    amendments master and the .md/.docx are re-rendered from it (INFRA-033), so
    the formats stay consistent. Writes only inside the run folder (run_ctx);
    never touches durable/. Every decision is posted to the run bus.

    Degrades safely (INFRA-034): the agents run on the local Qwen backend; if it
    is unreachable, run_task returns ok=False and the phase posts REDACTION_SKIPPED
    and continues — it never crashes a keyless environment. (The Qwen-required
    startup gate is INFRA-035.)

    When redaction is WAIVED for the run (operator passed --no-redaction-override
    at the startup gate), this phase still runs structurally but performs no
    redaction: it records REDACTION_SKIPPED (operator_waived) per document on the
    bus, consistent with the safe-degrade behavior above."""
    summary = {}
    if not redaction_enabled:
        for doc in op_docs:
            _post_redaction(orch, doc["id"], "REDACTION_SKIPPED", {"reason": "operator_waived"})
            summary[doc["id"]] = {"redacted": False, "state": "SKIPPED", "reason": "operator_waived"}
        return summary
    # OPERATOR REDACTION RULES (INFRA-038): compile the machine-usable rule set the
    # redactors APPLY, and REPORT whether the operator's rules are in force or only
    # the defaults apply. A redaction-intent convention that fails to compile is
    # surfaced LOUDLY (console + a structured bus note) — never a silent fallback.
    rr = redaction_rules(convention_registry)
    red_rules = rr["rules"]
    print(f"[redaction-rules] operator_in_force={rr['operator_in_force']} source={rr['source']} "
          f"({len(rr['operator_rules'])} operator rule(s))", file=sys.stderr)
    # 1c defense-in-depth: never run the ladder with NO operator rule in force. The
    # pre-run gate already hard-stops (or the operator declared redact-nothing, which
    # waives redaction_enabled). If we somehow reach here with no operator rule, BLOCK
    # every doc — never silently default, never silently ship unredacted.
    if not rr["operator_in_force"]:
        for doc in op_docs:
            esc = build_redaction_escalation(
                doc_id=doc["id"], document_name=doc["name"], stage="REDACT_RULES",
                failure_kind="no_operator_rule", raw_output_path=None,
                detail={"warnings": rr["warnings"]})
            _post_redaction_block(orch, esc)
            summary[doc["id"]] = {"redacted": False, "state": "BLOCKED",
                                  "failure_kind": esc["failure_kind"], "escalation": esc}
        return summary
    for w in rr["warnings"]:
        print(f"[redaction-rules] WARNING: convention {w['id']} ({w['category']}) is redaction-intent "
              f"but did NOT compile: {w['reason']} — operator rule NOT applied.", file=sys.stderr)
    orch._post_orchestrator(
        recipient="OPERATOR", channel="redaction", msg_type="INFORM",
        body={"event": "REDACTION_RULES_COMPILED", "source": rr["source"],
              "operator_in_force": rr["operator_in_force"],
              "operator_rule_ids": [r.get("id") for r in rr["operator_rules"]],
              "warnings": rr["warnings"]},
        constitution_check={"laws_consulted": ["LAW-IV", "LAW-V"], "result": "RESOLVED",
                            "resolution": "operator redaction rules compiled for the redaction pass"})
    for doc in op_docs:
        info = deliverables.get(doc["id"]) or {}
        master_path = info.get("amendments_json")
        if not master_path:
            continue
        try:
            master = json.loads(Path(master_path).read_text(encoding="utf-8"))
        except Exception:
            continue
        amendments = master.get("amendments", [])

        clerk = _build_wrapper("REDACT_CLERK", orch, keys)
        clerk_r = clerk.run_task(
            work_payload={"task": "apply_redaction_rules", "document_id": doc["id"],
                          "document_name": doc["name"], "amendments": amendments,
                          # Operator redaction rules + the document spans to apply
                          # them to (minimal read-radius unblind for rule application;
                          # the full ladder radius is Stage 3b).
                          "redaction_rules": red_rules,
                          "document_text": _truncate(doc["text"], 4000)},
            run_objectives="Apply the OPERATOR REDACTION RULES (in your context) to the spans of "
                           "this document and its deliverable. For EVERY span that matches a rule, emit "
                           "one item with kind=\"redaction\" (NEVER kind=\"finding\"), span set to the "
                           "exact matched text (verbatim), category set to the matched rule's category "
                           "verbatim, replacement=\"[REDACTED]\", method=\"REDACT\", and rule_id set to "
                           "the id of the rule that matched (e.g. CONV-006 or RED-DFLT-001). Emit ONE "
                           "item per DISTINCT sensitive span — a named individual is its own span, an "
                           "identity/ID number is its own SEPARATE span, and a company name and a "
                           "financial figure are each their own span. NEVER merge a person's name with "
                           "an adjacent ID number (or a company with a figure) into a single span; split "
                           "them into separate items, each with its own exact verbatim span text. Do NOT "
                           "judge whether content is 'sensitive' on your own — apply the rules as written. "
                           "If and only if NO span matches any rule, return items: [].",
            channel="redaction", max_tokens=1024,
            convention_registry=convention_registry)
        # Persist the clerk's raw + parsed output on EVERY path (INFRA-038 gap
        # close): diagnosable from disk, not only the bus.
        clerk_raw_path = _persist_redactor_output(run_ctx, "REDACT_CLERK", doc["id"], clerk_r)
        # LAW-IV strict gate (INFRA-037): the clerk result must be a CONTRACT-VALID
        # canonical wrapper, or the run BLOCKS and escalates — never silently
        # skipped. Distinguish a backend that could not be reached
        # (redactor_unavailable) from a model that ran but produced unparseable /
        # non-wrapper output (contract_violation). This strictness is LAW-IV-specific
        # to redaction; phase-6 amendment salvage stays lenient.
        parsed = clerk_r.get("parsed")
        if not (clerk_r.get("ok") and is_envelope(parsed)):
            if not clerk_r.get("ok") and clerk_r.get("error") == "contract_violation":
                miss = clerk_r.get("contract_missing") or []
                parse_failed = any(str(m).startswith("json parse failure")
                                   or str(m) == "no JSON object found in output" for m in miss)
                failure_kind = ("contract_violation_parse" if parse_failed
                                else "contract_violation_fields")
            elif not clerk_r.get("ok"):
                failure_kind = "redactor_unavailable"
            else:
                failure_kind = "contract_violation_fields"  # ok but not a wrapper
            esc = build_redaction_escalation(
                doc_id=doc["id"], document_name=doc["name"], stage="REDACT_CLERK",
                failure_kind=failure_kind,
                raw_output_path=clerk_r.get("raw_text_path") or clerk_raw_path)
            _post_redaction_block(orch, esc)
            summary[doc["id"]] = {"redacted": False, "state": "BLOCKED",
                                  "failure_kind": esc["failure_kind"], "escalation": esc}
            continue
        # Valid wrapper. Detect redactions STRUCTURALLY (span + replacement/method/
        # category), not by the kind tag alone — a redaction mis-tagged kind='finding'
        # is still applied. Classify into NONE / BLOCK / PROPOSE:
        #   - items:[]                 -> legitimate REDACTION_NONE
        #   - items but none resolve   -> BLOCK (non-empty-but-unresolved; never a
        #                                 silent NONE — this was the silent-pass bug)
        outcome, clerk_reds = _classify_clerk_items(decode_items(parsed))
        if outcome == "BLOCK":
            esc = build_redaction_escalation(
                doc_id=doc["id"], document_name=doc["name"], stage="REDACT_CLERK",
                failure_kind="no_resolvable_redaction",
                raw_output_path=clerk_r.get("raw_text_path") or clerk_raw_path)
            _post_redaction_block(orch, esc)
            summary[doc["id"]] = {"redacted": False, "state": "BLOCKED",
                                  "failure_kind": esc["failure_kind"], "escalation": esc,
                                  "reason": "non-empty but no item resolved to a valid redaction"}
            continue
        # 1b: DETERMINISTIC local detection for operator-AUTHORIZED regular shapes
        # (identifier / figure) + name-via-local-cues. Runs over the document text,
        # authorized purely by the operator rules (engine never judges sensitivity).
        # UNION with the model's proposals, de-duped by normalized span — the model
        # still proposes; detection guarantees authorized shapes are never missed.
        det_items = redaction_detect.detect(_PROJECT_ROOT, doc["text"], rr["operator_rules"])
        redactions = _merge_redaction_proposals(
            det_items, clerk_reds if outcome == "PROPOSE" else [])
        if not redactions:
            # genuine NONE: the clerk found nothing AND no authorized shape detected
            _post_redaction(orch, doc["id"], "REDACTION_NONE",
                            {"screened_amendments": len(amendments), "raw_output_path": clerk_raw_path})
            summary[doc["id"]] = {"redacted": False, "state": "NONE", "redactions": 0}
            continue

        authority = _build_wrapper("REDACT_AUTHORITY", orch, keys)
        auth_r = authority.run_task(
            work_payload={"task": "approve_redactions", "document_id": doc["id"],
                          "redactions": redactions},
            run_objectives="Approve only defensible redactions; run the adversarial test.",
            channel="redaction", max_tokens=1024)
        esc = _redaction_result_block(orch, doc, auth_r, stage="REDACT_AUTHORITY",
                                      required_key="approved")
        if esc is not None:
            summary[doc["id"]] = {"redacted": False, "state": "BLOCKED",
                                  "failure_kind": esc["failure_kind"], "escalation": esc}
            continue
        auth_items = [it for it in decode_items(auth_r["parsed"]) if "approved" in it]
        # Audit (issues logging): surface the AUTHORITY decision incl. diagnostic
        # `issues` on the bus, regardless of the outcome below. `issues` is an
        # optional contract field nothing gated on before; it is now visible.
        auth_issues = [iss for it in auth_items for iss in (it.get("issues") or [])]
        _post_redaction(orch, doc["id"], "REDACTION_AUTHORITY_DECISION",
                        {"approved": all(bool(it.get("approved")) for it in auth_items),
                         "adversarial_test_passed": [it.get("adversarial_test_passed") for it in auth_items],
                         "issues": auth_issues})
        # ENFORCE the adversarial test (LAW-IV): approval now requires approved=true
        # AND adversarial_test_passed=true. Three distinct cases (see
        # _classify_adversarial): genuine failed test -> adversarial_test_failed BLOCK;
        # garbled field -> contract_violation_fields BLOCK; both true -> proceed.
        approved, adv_block = _classify_adversarial(auth_items)
        if adv_block is not None:
            esc = build_redaction_escalation(
                doc_id=doc["id"], document_name=doc["name"], stage="REDACT_AUTHORITY",
                failure_kind=adv_block,
                raw_output_path=auth_r.get("raw_text_path"),
                detail={"issues": auth_issues} if auth_issues else None)
            _post_redaction_block(orch, esc)
            summary[doc["id"]] = {"redacted": False, "state": "BLOCKED",
                                  "failure_kind": esc["failure_kind"], "escalation": esc}
            continue

        gate = _build_wrapper("REDACT_GATE", orch, keys)
        gate_r = gate.run_task(
            work_payload={"task": "final_gate", "deliverable_id": doc["id"],
                          "redactions": redactions, "approved": approved},
            run_objectives="Final pass/fail on the redaction set.",
            channel="redaction", max_tokens=512)
        esc = _redaction_result_block(orch, doc, gate_r, stage="REDACT_GATE",
                                      required_key="pass")
        if esc is not None:
            summary[doc["id"]] = {"redacted": False, "state": "BLOCKED",
                                  "failure_kind": esc["failure_kind"], "escalation": esc}
            continue
        gate_items = [it for it in decode_items(gate_r["parsed"]) if "pass" in it]
        passed = bool(gate_items) and all(bool(it.get("pass")) for it in gate_items)
        # Audit (reason logging): `reason` is now optional (relaxed from required;
        # `pass` remains the safety verdict). Capture the justification for audit
        # without it being a BLOCK trigger.
        gate_reasons = [it.get("reason") for it in gate_items if it.get("reason")]
        _post_redaction(orch, doc["id"], "REDACTION_GATE_DECISION",
                        {"passed": passed, "reason": gate_reasons})

        if not (approved and passed):
            _post_redaction(orch, doc["id"], "REDACTION_NOT_APPLIED",
                            {"approved": approved, "passed": passed, "proposed": len(redactions)})
            summary[doc["id"]] = {"redacted": False, "state": "NOT_APPLIED",
                                  "approved": approved, "passed": passed}
            continue

        # APPLY across EVERY operator-facing artifact, conserve spans (a span that lands
        # nowhere BLOCKS — never a silent zero-match), then VERIFY by re-grepping every
        # shipped artifact. Shape (a) hand-back (INFRA-039 Phase 1b): the privacy home
        # PRODUCES the scrubbed master + body, the pipeline RENDERS the deliverable
        # (editorial: write_amendment_deliverables + _category_for_conv), then the
        # privacy home scrubs the text artifacts and VERIFIES the outcome. The scrubber
        # never renders and never looks up conventions; no privacy->editorial edge.
        scrubbed_master, body_red, located, by_artifact = scrub_master_and_body(
            master, redactions, doc.get("text", ""))
        master.clear(); master.update(scrubbed_master)
        amendment_render.write_amendment_deliverables(
            scrubbed_master, deliv_dir=run_ctx.deliverables_dir(), doc_id=doc["id"],
            document_name=doc["name"], body_text=body_red,
            category_for_conv=lambda c: _category_for_conv(c, convention_registry))
        rep = scrub_text_artifacts_and_verify(redactions, info, located, by_artifact)
        if rep["dropped"]:
            esc = build_redaction_escalation(
                doc_id=doc["id"], document_name=doc["name"], stage="REDACT_APPLY",
                failure_kind="span_dropped",
                raw_output_path=clerk_r.get("raw_text_path") or clerk_raw_path,
                detail={"dropped_spans": rep["dropped"], "by_artifact": rep["by_artifact"]})
            _post_redaction_block(orch, esc)
            summary[doc["id"]] = {"redacted": False, "state": "BLOCKED",
                                  "failure_kind": esc["failure_kind"], "escalation": esc}
            continue
        if rep["survivors"]:
            esc = build_redaction_escalation(
                doc_id=doc["id"], document_name=doc["name"], stage="REDACT_APPLY",
                failure_kind="pii_survives_in_deliverable",
                raw_output_path=clerk_r.get("raw_text_path") or clerk_raw_path,
                detail={"survivors": rep["survivors"], "by_artifact": rep["by_artifact"]})
            _post_redaction_block(orch, esc)
            summary[doc["id"]] = {"redacted": False, "state": "BLOCKED",
                                  "failure_kind": esc["failure_kind"], "escalation": esc}
            continue
        # APPLIED means: every proposed span located and VERIFIED ABSENT from every
        # shipped artifact. Report spans, not documents (defect D); reconcile so
        # proposed/applied cannot silently diverge.
        _post_redaction(orch, doc["id"], "REDACTION_APPLIED",
                        {"proposed_spans": rep["proposed"], "applied_spans": rep["applied"],
                         "substitutions": rep["total_subs"], "by_artifact": rep["by_artifact"]})
        summary[doc["id"]] = {"redacted": True, "state": "APPLIED",
                              "proposed_spans": rep["proposed"], "applied_spans": rep["applied"],
                              "substitutions": rep["total_subs"]}
    return summary



def _category_for_conv(conv_id, registry):
    if not conv_id:
        return None
    for c in registry.get("conventions", []):
        if c.get("id") == conv_id:
            return c.get("category")
    return None


def _render_amendments_md(doc, payload, registry, reference_index=None):
    """Back-compat wrapper. The canonical Markdown render now lives in
    amendment_render.render_amendments_md, a pure function of the master `payload`.
    This delegates to it so the master stays the single content source
    (reference_index is unused; kept only for signature compatibility)."""
    return amendment_render.render_amendments_md(
        payload, document_name=doc.get("name", ""),
        category_for_conv=lambda c: _category_for_conv(c, registry))


def _render_per_agent_md(doc, production, audit, conv_review):
    lines = [f"# {doc['name']} — per-agent deliverable", "",
             f"- generated: {datetime.now(timezone.utc).isoformat()}"]
    all_results = (production + audit + conv_review)
    by_agent = {}
    for r in all_results:
        if r.get("doc_id") == doc["id"]:
            by_agent.setdefault(r["agent"], []).append(r)
    for agent in ("PROCESSOR", "SPEECH_ACT_TAGGER", "LEGAL_ANALYST",
                  "VERIFIER", "FACT_CHECKER",
                  "PRACTICE_AUDITOR", "STYLE_GUARDIAN"):
        lines.append(f"\n## {agent}")
        if agent not in by_agent:
            lines.append("_(agent did not run)_"); continue
        for r in by_agent[agent]:
            if not r.get("ok"):
                lines.append(f"_(failed: {r.get('error')})_"); continue
            lines.append("```json")
            lines.append(json.dumps(r.get("parsed"), indent=2, ensure_ascii=False))
            lines.append("```")
    return "\n".join(lines)


# ---------- BOOT helpers --------------------------------------------------------------------

def _build_reference_index(project_root, ctx_docs, op_docs, conv_registry, run_context=None):
    # Per-run, regenerated, disposable (Part XXVII §A): write into the current
    # run's audit/ folder when a run context is given; else legacy output/audit.
    index_path = run_context.reference_index_path() if run_context is not None else None
    idx_path = index_path or (project_root / "output" / "audit" / "reference_index.json")
    if idx_path.exists(): idx_path.unlink()
    idx = ReferenceIndex.open(project_root, index_path=index_path)
    for d in ctx_docs:
        idx.index_document(input_type="context", document_id=d["id"],
                           document_name=d["name"], text=d["text"], max_paragraphs=120)
    for d in op_docs:
        idx.index_document(input_type="operational", document_id=d["id"],
                           document_name=d["name"], text=d["text"], max_paragraphs=200)
    for c in conv_registry.get("conventions", []):
        idx.add(input_type="convention", document_id=c.get("source_file", "conventions"),
                document_name=c.get("source_file", "conventions"),
                location={"page": 1, "paragraph": c.get("id", "?"),
                          "sentence": 1, "char_start": 0, "char_end": 0},
                text_excerpt=c.get("rule", "")[:200])
    idx.save()
    return idx


# ---------- escalation handler --------------------------------------------------------------

def _interactive_handler(topic, payload):
    print(f"\n=== OPERATOR ESCALATION: {topic} ===", file=sys.stderr)
    print(json.dumps(payload, indent=2, ensure_ascii=False)[:4000], file=sys.stderr)
    try:
        decision = input("Decision (APPROVE / DENY / DEFER): ").strip()
        rationale = input("Rationale: ").strip()
    except EOFError:
        decision, rationale = "DEFERRED", "no input available"
    return OperatorDecision(decision=decision or "DEFERRED", rationale=rationale or "")


# ---------- main ----------------------------------------------------------------------------

def _cost_projection(num_op_docs, num_ctx_docs):
    claude_calls = (len(PRODUCTION_AGENTS_PER_DOC) * num_op_docs
                    + len(PRODUCTION_AGENTS_CORPUS_LEVEL)
                    + len(CONVENTION_REVIEW_AGENTS) * num_op_docs  # style_guardian via Claude
                    + num_op_docs)  # AMENDMENT_DRAFTER
    gpt_calls = (len(AUDIT_AGENTS_PER_DOC) + 1) * num_op_docs  # +1 for PRACTICE_AUDITOR (gpt)
    return estimate_cost(claude_calls=claude_calls, claude_in=5500, claude_out=1800,
                         gpt_calls=gpt_calls, gpt_in=5500, gpt_out=1500)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Project Shimmer pipeline")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--skip-confirmation", action="store_true")
    parser.add_argument("--max-docs", type=int, default=0)
    parser.add_argument("--reset-bus", action="store_true")
    parser.add_argument("--reset-cost", action="store_true")
    parser.add_argument("--run-objectives", default="")
    parser.add_argument("--save-snapshot", metavar="NAME")
    parser.add_argument("--load-snapshot", metavar="NAME")
    parser.add_argument("--reset-snapshot", action="store_true")
    parser.add_argument("--list-snapshots", action="store_true")
    parser.add_argument("--overwrite-snapshot", action="store_true",
                        help="allow --save-snapshot to overwrite existing")
    parser.add_argument("--skip-model-check", action="store_true",
                        help="skip the live deprecated-model gate (e.g. offline runs)")
    parser.add_argument("--no-redaction-override", action="store_true",
                        help="per-run waiver: declare THIS run non-sensitive and run with NO "
                             "redaction (required to proceed when the Qwen backend is unavailable; "
                             "each use is logged to the governance ledger)")
    parser.add_argument("--sensitivity-layer-inactive-override", action="store_true",
                        help="per-run override: the FULL LAW-IV sensitivity layer is built but "
                             "UNWIRED (INFRA-038); declare THIS run non-sensitive to proceed with "
                             "it inactive. Each use is logged to the governance ledger.")
    args = parser.parse_args(argv)

    # Snapshot shortcuts: take action and exit.
    if args.list_snapshots:
        for o in list_snapshots(ROOT):
            print(f"{o['name']:30s} saved_at={o.get('saved_at', '?')} files={len(o.get('files', []))}")
        return 0
    if args.reset_snapshot:
        summary = reset_snapshot(ROOT)
        print("[snapshot] reset:", json.dumps(summary, indent=2))
        return 0
    if args.load_snapshot:
        # Thread the operator handler so the amendment tripwire can prompt for
        # approval if a snapshot's constitution would change existing amendments.
        summary = load_snapshot(
            ROOT, args.load_snapshot,
            operator_handler=(None if args.non_interactive else _interactive_handler),
            interactive=not args.non_interactive,
        )
        print(f"[snapshot] loaded {args.load_snapshot!r}:", json.dumps(summary, indent=2))
        return 0
    if args.save_snapshot:
        try:
            target = save_snapshot(ROOT, args.save_snapshot, overwrite=args.overwrite_snapshot)
        except FileExistsError as e:
            print(f"[snapshot] {e}", file=sys.stderr); return 2
        print(f"[snapshot] saved to {target}")
        return 0

    # Per-run output isolation (Part XXVII §A): every run gets its own folder
    # output/runs/<UTC-timestamp>__<run-id>/. Two runs never overwrite each other.
    # Durable/protected assets live under durable/ and are never written here.
    run_ctx = run_context_mod.create_run(ROOT)
    print(f"[pipeline] run folder: {run_ctx.run_dir.relative_to(ROOT)}", file=sys.stderr)

    # Sensitivity-layer inactive HARD GATE (INFRA-038). The FULL LAW-IV sensitivity
    # layer (reasoning about sensitivity as a first-class concept; masking sensitive
    # content from API/web; may_handle_sensitive routing) is BUILT BUT UNWIRED. Until
    # it is activated, the run REFUSES to start unless the operator declares THIS run
    # non-sensitive via --sensitivity-layer-inactive-override, mirroring the Qwen
    # redaction hard-gate-plus-logged-override. (Stage 3a applies operator redaction
    # rules locally; the full philosophy is deferred — see README.)
    if not sensitivity_layer.is_active():
        print("[sensitivity-gate] WARNING: the full LAW-IV sensitivity layer is BUILT BUT "
              "INACTIVE (INFRA-038); the pipeline reasoning about sensitivity as a first-class "
              "concept is deferred. Stage 3a applies operator redaction rules locally only.",
              file=sys.stderr)
        if not args.sensitivity_layer_inactive_override:
            print("[sensitivity-gate] STOP: refusing to start with the full sensitivity layer "
                  "inactive. Re-run with --sensitivity-layer-inactive-override to declare THIS run "
                  "non-sensitive and proceed (logged to the governance ledger).", file=sys.stderr)
            return 6
        if not args.non_interactive:
            try:
                confirm = input("--sensitivity-layer-inactive-override: declare THIS run "
                                "NON-SENSITIVE and proceed with the full sensitivity layer "
                                "inactive? (yes/no): ").strip().lower()
            except EOFError:
                confirm = "no"
            if confirm not in {"yes", "y"}:
                print("[sensitivity-gate] override not confirmed; aborting.", file=sys.stderr)
                return 6
        led = sensitivity_layer.record_sensitivity_override(
            ROOT, run_ctx.run_id, reason="operator_declared_non_sensitive_layer_inactive")
        print(f"[sensitivity-gate] OVERRIDE accepted for this run; logged to {led.name}.",
              file=sys.stderr)

    # Reset toggles. With per-run folders each run starts empty, so these only
    # matter if a caller re-points at an existing run; they act on this run's paths.
    if args.reset_bus:
        bp = run_ctx.bus_path()
        if bp.exists(): bp.unlink()
    if args.reset_cost:
        for p in (run_ctx.cost_jsonl_path(), run_ctx.cost_json_path()):
            if p.exists(): p.unlink()

    # Cost tracker (must exist before any agent fires)
    cost_tracker = CostTracker.open(run_ctx.logs_dir(), print_live=True)

    # Search router (used by date cascade + downstream agents)
    keys = load_api_keys()
    search_router = SearchRouter.open(ROOT, keys=keys)

    # Deprecated-model gate + self-resolution (INFRA-026): resolve every agent's
    # configured FAMILY KEY against the provider's CURRENT live list. A family key
    # that matches exactly one concrete live id binds to it automatically (in-memory
    # only -- never written to the tracked registry); zero or ambiguous matches STOP
    # and require operator approval. Never swaps to a different model. Backends whose
    # live list is unavailable (no key / local Qwen) are skipped gracefully.
    resolved_agents = None  # threaded into boot so agents run the bound concrete ids
    if not args.skip_model_check:
        registry_path = ROOT / "config" / "agent_registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        handler = None if args.non_interactive else _interactive_handler
        gate = enforce_current_models(
            ROOT, registry, keys, interactive=not args.non_interactive,
            operator_handler=handler, registry_path=registry_path,
        )
        for s in gate["skipped"]:
            print(f"[model-gate] skipped {s['agent']} ({s['backend']}): "
                  f"cannot verify {s['model']!r} (no key / local backend)", file=sys.stderr)
        for a in gate["approved"]:
            print(f"[model-gate] operator-approved swap: {a['agent']} "
                  f"{a['from']!r} -> {a['to']!r}", file=sys.stderr)
        if not gate["ok"]:
            dead = [f"{f['agent']}={f['dead_model']!r}" for f in gate["findings"]]
            print(f"[model-gate] STOP: models not auto-resolvable / not approved: {dead}. "
                  f"Approve a replacement, pin a live snapshot in agent_registry.json, "
                  f"or pass --skip-model-check to override.", file=sys.stderr)
            return 3
        # Apply live family-key -> concrete-id bindings to the in-memory registry
        # ONLY (the tracked file keeps family keys). The gate's own persist already
        # ran above with family keys intact, so this never writes a dated id to disk.
        bindings = gate.get("bindings", [])
        for b in bindings:
            registry["agents"][b["agent"]]["model"] = b["to"]
            print(f"[model-gate] resolved {b['agent']} ({b['backend']}): "
                  f"{b['from']!r} -> {b['to']!r} (live binding)", file=sys.stderr)
        if bindings:
            # Log the bindings to the run record (per-run, gitignored; not a tracked file).
            rec = run_ctx.logs_dir() / "model_bindings.json"
            rec.parent.mkdir(parents=True, exist_ok=True)
            rec.write_text(json.dumps({"bindings": bindings}, indent=2, ensure_ascii=False),
                           encoding="utf-8")
        resolved_agents = registry["agents"]

    # Qwen-required startup gate (INFRA-035): redaction is the always-on final pass
    # (INFRA-034) and runs on the local Qwen backend. Refuse to start if Qwen is not
    # reachable/configured, UNLESS the operator waives redaction for THIS run.
    qstat = redaction_gate.qwen_backend_status(ROOT)
    waive = bool(args.no_redaction_override)
    redaction_enabled = True
    if waive and not args.non_interactive:
        # A waiver must be confirmed in interactive mode (conscious, per-run choice).
        try:
            confirm = input("--no-redaction-override: declare THIS run NON-SENSITIVE and run with "
                            "NO redaction? (yes/no): ").strip().lower()
        except EOFError:
            confirm = "no"
        if confirm not in {"yes", "y"}:
            print("[redaction-gate] override not confirmed; aborting.", file=sys.stderr)
            return 4
    if not qstat["configured"] and not waive:
        print(f"[redaction-gate] STOP: the local Qwen redaction backend is not reachable/configured "
              f"({qstat['detail']}). Redaction is a required final pass. Set up Qwen "
              f"(install torch + transformers and the model Qwen/Qwen2.5-7B-Instruct), or re-run "
              f"with --no-redaction-override to declare this run non-sensitive and proceed without "
              f"redaction. Pre-run check verifies: {qstat['verified_now']}; actual model load is "
              f"verified at first call.", file=sys.stderr)
        return 4
    if waive:
        redaction_enabled = False
        reason = "operator_declared_non_sensitive" if qstat["configured"] else "qwen_unavailable"
        ledger = sensitivity_layer.record_redaction_waiver(ROOT, run_ctx.run_id, reason=reason)
        print(f"[redaction-gate] WAIVED for this run (no redaction; reason={reason}); "
              f"logged to {ledger.name}.", file=sys.stderr)
    elif qstat["configured"] and not qstat["gpu"]:
        # SOFT reminder only — never blocks, never recorded.
        print("[redaction-gate] note: Qwen reachable but no GPU detected — redaction will be slow "
              "on CPU.", file=sys.stderr)

    # Date cascade + cutoff -> populate input/operational/
    print("[pipeline] date cascade + cutoff", file=sys.stderr)
    context_records, operational_records = _populate_operational(ROOT, search_router)

    # Load text for context + operational
    ctx_docs = _load_corpus(ROOT / "input" / "context")
    op_docs = _load_corpus(ROOT / "input" / "operational")
    if args.max_docs > 0:
        op_docs = op_docs[: args.max_docs]
    if not op_docs:
        print("[pipeline] no operational documents resolved from cutoff; nothing to review.",
              file=sys.stderr)
        # Still complete BOOT so the operator can inspect state
    print(f"[pipeline] context docs: {len(ctx_docs)}; operational docs: {len(op_docs)}",
          file=sys.stderr)

    projection = _cost_projection(len(op_docs), len(ctx_docs))
    print("\n=== PROJECT SHIMMER — pre-run estimate ===", file=sys.stderr)
    print(f"  Operational documents: {len(op_docs)}", file=sys.stderr)
    print(f"  Context documents:     {len(ctx_docs)}", file=sys.stderr)
    print(f"  Estimated Claude:      ${projection['claude_cost_usd']:.4f}", file=sys.stderr)
    print(f"  Estimated GPT-4o:      ${projection['gpt_cost_usd']:.4f}", file=sys.stderr)
    print(f"  Estimated TOTAL:       ${projection['total_usd']:.4f}", file=sys.stderr)
    print("===========================================\n", file=sys.stderr)

    if not args.skip_confirmation and not args.non_interactive:
        try: ans = input("Proceed with live API calls? (yes/no): ").strip().lower()
        except EOFError: ans = "no"
        if ans not in {"yes", "y"}:
            print("[pipeline] aborted by operator.", file=sys.stderr); return 0

    # BOOT orchestrator (adaptive_spawn fires if first run)
    handler = None if args.non_interactive else _interactive_handler
    orch = TopOrchestrator.boot(ROOT, interactive=not args.non_interactive,
                                 operator_handler=handler, cost_tracker=cost_tracker,
                                 run_adaptive_spawn=True, run_context=run_ctx,
                                 registry=resolved_agents)
    orch.run_objectives = args.run_objectives

    # Parse conventions -> registry
    conv_registry = parse_conventions(ROOT)
    write_registry(ROOT, conv_registry)
    conv_registry_dict = conv_registry.as_dict()
    convention_review_enabled = bool(conv_registry_dict.get("conventions"))
    print(f"[pipeline] convention registry: {len(conv_registry_dict.get('conventions', []))} rules; "
          f"review enabled={convention_review_enabled}", file=sys.stderr)

    # 1c — OPERATOR-RULE HARD-STOP (operator-sovereignty, mirrors the qwen / sensitivity
    # gates). Redaction may act ONLY on what a compiled operator rule declares redactable;
    # there is NO silent fallback to engine-defined default categories. If redaction is
    # required (not waived) but no operator rule compiles, REFUSE the run here — before
    # any paid agent — unless the operator consciously declared redact-nothing via
    # --no-redaction-override (which already logged the waiver to the governance ledger).
    if redaction_enabled and op_docs:
        rr_pre = redaction_rules(conv_registry_dict)
        if not rr_pre["operator_in_force"]:
            warn = "; ".join(f"{w['id']}: {w['reason']}" for w in rr_pre["warnings"]) or "none"
            print("[redaction-rules] STOP: no operator redaction rule in force; the engine does "
                  "NOT apply default categories on its own (operator-sovereignty). Supply a "
                  "compiling redaction convention (a confidentiality/redaction category or "
                  "'must not contain …' phrasing with rule text), or re-run with "
                  "--no-redaction-override to consciously declare redact-nothing for THIS run "
                  f"(logged to the governance ledger). Redaction-intent that failed to compile: {warn}.",
                  file=sys.stderr)
            return 4

    # Reference index
    reference_index = _build_reference_index(ROOT, ctx_docs, op_docs, conv_registry_dict,
                                             run_context=run_ctx)
    print(f"[pipeline] reference index: {len(reference_index.entries)} entries", file=sys.stderr)

    # Semantic retrieval layer (genesis Part XXI). Loads from
    # durable/cache/embedding_store.pkl if present, otherwise tries to build
    # from input/context/. Graceful degradation: None means Zipfian fallback.
    embed_store = embedding_store.get_or_build(ROOT, reference_index=reference_index)
    if embed_store is not None:
        print(f"[pipeline] embedding store loaded: {len(embed_store.get('passages', []))} passages",
              file=sys.stderr)
    else:
        print("[pipeline] embedding store unavailable; Zipfian retrieval active",
              file=sys.stderr)

    # PHASE 1
    orch.deliberation_round({"phase": "situation_assessment",
                             "context_count": len(ctx_docs),
                             "operational_count": len(op_docs),
                             "convention_count": len(conv_registry_dict.get("conventions", []))})

    run_objectives = args.run_objectives or (
        "Review each operational document against the convention registry. "
        "Produce all deliverables specified in Part XVIII Sections C and D. "
        "Every finding must cite convention rules (CONV-*) and source passages (REF-*)."
    )

    production, audit, conv_review = [], [], []
    deliverables = {}
    if op_docs:
        print(f"[pipeline] phase 3-4: content production", file=sys.stderr)
        production = asyncio.run(phase_3_4_content_production(
            orch, keys, op_docs, ctx_docs, run_objectives,
            conv_registry_dict, reference_index,
            [e.as_dict() for e in reference_index.entries if e.input_type == "context"][:30],
            embed_store=embed_store,
        ))
        # Part XXVI: pull the structural inventory ARCHIVIST produced during
        # the corpus-level phase so downstream phases can pass it to
        # PRACTICE_AUDITOR / LEGAL_ANALYST per Part XXIII's directive.
        structural_inventory = _structural_inventory(production)
        print(f"[pipeline] structural inventory elements: {len(structural_inventory)}",
              file=sys.stderr)
        print(f"[pipeline] phase 5: verification + fact-check", file=sys.stderr)
        audit = asyncio.run(phase_5_audit(orch, keys, op_docs, production, run_objectives,
                                          conv_registry_dict, reference_index))
        if convention_review_enabled:
            print(f"[pipeline] phase 5.5: convention review", file=sys.stderr)
            conv_review = asyncio.run(phase_5_5_convention_review(
                orch, keys, op_docs, run_objectives, conv_registry_dict, reference_index,
                embed_store=embed_store, structural_inventory=structural_inventory))
        else:
            print(f"[pipeline] phase 5.5: SKIPPED (no conventions)", file=sys.stderr)

        cost_tracker.finalize_line()
        print(f"[pipeline] phase 6: synthesis + deliverables", file=sys.stderr)
        deliverables = asyncio.run(phase_6_synthesis(
            orch, keys, op_docs, production, audit, conv_review,
            run_objectives, conv_registry_dict, reference_index,
            embed_store=embed_store))
        for doc_id, paths in deliverables.items():
            print(f"  -> {doc_id}: {len(paths)} files; "
                  f"amendments={paths['amendment_count']}; "
                  f"validator_errors={len(paths['validator_errors'])}",
                  file=sys.stderr)

        # Phase 7: audit synthesis + DELTA escalations
        synth = AuditSynthesizer(project_root=ROOT, bus=orch.bus, run_context=run_ctx)
        audit_summary = synth.synthesize(
            verifier_findings=_items_for(audit, "VERIFIER"),
            fact_check_findings=_items_for(audit, "FACT_CHECKER"),
            practice_findings=_items_for(conv_review, "PRACTICE_AUDITOR"),
        )
        print(f"[pipeline] audit synthesis: {len(audit_summary['findings'])} findings, "
              f"{len(audit_summary['delta_proposals'])} DELTAs", file=sys.stderr)
        if audit_summary["delta_proposals"]:
            print(f"[pipeline] phase 7: escalating {len(audit_summary['delta_proposals'])} DELTA(s)",
                  file=sys.stderr)
            decisions = orch.escalate_delta_proposals(audit_summary["delta_proposals"])
            for d in decisions:
                print(f"  -> {d['delta_id']} {d['kind']}: {d['decision']} (approved={d['approved']})",
                      file=sys.stderr)

    # Phase 9: redaction (ALWAYS runs — final pass over the deliverables, LAW-IV).
    # The Qwen agents APPLY the operator redaction rules to spans (INFRA-038); they
    # do not judge sensitivity. Any approved redaction flows through the amendments
    # master and re-renders md/docx.
    print(f"[pipeline] phase 9: redaction screening"
          f"{' (WAIVED for this run)' if not redaction_enabled else ''}", file=sys.stderr)
    redaction_summary = phase_9_redaction(orch, keys, op_docs, deliverables, run_ctx,
                                          conv_registry_dict, redaction_enabled=redaction_enabled)

    def _count_state(*states):
        return sum(1 for v in redaction_summary.values() if v.get("state") in states)
    n_total = len(redaction_summary)
    n_applied = sum(1 for v in redaction_summary.values() if v.get("redacted"))
    n_none = _count_state("NONE")
    n_blocked = _count_state("BLOCKED")
    n_skipped = _count_state("SKIPPED")          # operator-waived (conscious no-op)
    n_not_applied = _count_state("NOT_APPLIED")  # proposed but authority/gate declined
    # BLOCKED is visibly distinct from "nothing to redact" (NONE) and from a waiver.
    print(f"[pipeline] redaction: applied={n_applied} none={n_none} BLOCKED={n_blocked} "
          f"skipped(waived)={n_skipped} not_applied={n_not_applied} of {n_total} "
          f"(phase always runs; LAW-IV strict)", file=sys.stderr)
    if n_blocked:
        blocked_docs = [d for d, v in redaction_summary.items() if v.get("state") == "BLOCKED"]
        print(f"[pipeline] LAW-IV BLOCK: {n_blocked} deliverable(s) could not be confirmed "
              f"clean by redaction and were BLOCKED (not skipped): {blocked_docs}. "
              f"See the REDACTION BLOCK notice(s) above and the ESCALATE message(s) on the "
              f"bus (channel 'escalation'). Run exits non-zero.", file=sys.stderr)

    # Phase 8: persist
    print(f"\n[pipeline] phase 8: persist + run summary", file=sys.stderr)
    summary = orch.run_summary()
    final = cost_tracker.get_live_state()
    print("\n=== final cost ===", file=sys.stderr)
    print(f"  Claude:   ${final['by_family'].get('claude', {}).get('cost_usd', 0):.4f}", file=sys.stderr)
    print(f"  GPT-4o:   ${final['by_family'].get('gpt', {}).get('cost_usd', 0):.4f}", file=sys.stderr)
    print(f"  TOTAL:    ${final['total_cost_usd']:.4f}", file=sys.stderr)
    print(f"  calls: {final['total_calls']}  failures: {final['total_failures']}", file=sys.stderr)
    print(f"  bus messages: {summary.get('total', 0)}", file=sys.stderr)
    # LAW-IV: a redaction BLOCK must not be silent — fail the run so it surfaces.
    return 5 if n_blocked else 0


if __name__ == "__main__":
    sys.exit(main())
