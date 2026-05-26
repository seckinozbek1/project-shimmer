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

CLI shortcuts (also): --save-ontology, --load-ontology, --reset-ontology, --list-ontologies
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
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

from agent_wrapper import AgentWrapper, load_api_keys
from audit_synthesizer import AuditSynthesizer
from convention_parser import parse_conventions, write_registry
from corpus_validator import extract_distinctive_terms, validate_corpus_entry
import embedding_store
from cost_tracker import CostTracker, estimate_cost
from docx_builder import build_amendments_docx
from document_dating import read_dates, resolve_dates, write_dates
from ontology_manager import (
    list_ontologies, load_ontology, reset_ontology, save_ontology,
)
from orchestrator import OperatorDecision, TopOrchestrator
from pipeline_amendment_validator import validate_amendment_payload
from reference_builder import ReferenceIndex
from review_scope import apply_cutoff
from search_router import SearchRouter
from summary_generators import render_context_summary, render_operative_summary


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

def _read_pdf(path: Path) -> str:
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:
        print(f"[pipeline] WARN: could not read {path.name}: {e}", file=sys.stderr)
        return ""


def _load_corpus(input_dir: Path) -> list[dict]:
    docs = []
    if not input_dir.exists():
        return docs
    for p in sorted(input_dir.iterdir()):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext == ".pdf":
            text = _read_pdf(p)
        elif ext in {".txt", ".md", ".rst", ".log"}:
            try: text = p.read_text(encoding="utf-8", errors="replace")
            except Exception: text = ""
        else:
            continue
        if not text.strip():
            continue
        docs.append({"id": p.stem, "name": p.name, "text": text,
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
    candidate_files = sorted(p for p in context_dir.iterdir()
                             if p.is_file() and p.suffix.lower() in {".pdf", ".txt", ".md"})
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
    # Per Part XXVII, LEGAL_ANALYST also receives the structural inventory
    # extracted from the just-completed ARCHIVIST corpus output.
    all_context_refs = [e.as_dict() for e in reference_index.entries
                        if e.input_type == "context"]
    convention_provisions = _convention_provision_texts(convention_registry)
    structural_inventory = _extract_structural_inventory(results)
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
    (baseline doc query + per-convention-rule queries merged). Per Part XXVII,
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


def _extract_structural_inventory(production_results: list) -> list[dict]:
    """Per Part XXVII: pull the structural_inventory list out of the
    ARCHIVIST's corpus-level output, if present. Returns [] when missing
    so callers can pass it through without conditional handling."""
    for r in production_results:
        if r.get("scope") != "corpus" or r.get("agent") != "ARCHIVIST":
            continue
        if not r.get("ok"):
            continue
        parsed = r.get("parsed")
        if isinstance(parsed, dict):
            inv = parsed.get("structural_inventory")
            if isinstance(inv, list):
                return inv
        elif isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict) and isinstance(item.get("structural_inventory"), list):
                    return item["structural_inventory"]
    return []


# ---------- phase 6: synthesis ---------------------------------------------------------------

def _flatten(results, agent):
    out = []
    for r in results:
        if r.get("agent") != agent or not r.get("ok"):
            continue
        parsed = r.get("parsed")
        if isinstance(parsed, list):
            out.extend(p for p in parsed if isinstance(p, dict))
        elif isinstance(parsed, dict):
            out.append(parsed)
    return out


def _harvest_amendment_payloads_from_bus(orch) -> dict:
    """Return {document_id: amendments_payload} for any AMENDMENT_DRAFTER
    outputs already present on the bus, so phase 6 can skip re-running them."""
    out = {}
    for msg in orch.bus.read_all():
        if msg.get("sender") != "AMENDMENT_DRAFTER" or msg.get("type") != "INFORM":
            continue
        body = msg.get("body") or {}
        if body.get("event") != "AGENT_OUTPUT":
            continue
        payload = body.get("payload")
        if isinstance(payload, dict) and payload.get("document_id"):
            out[payload["document_id"]] = payload
    return out


async def phase_6_synthesis(orch, keys, op_docs, production, audit, conv_review,
                            run_objectives, convention_registry, reference_index,
                            embed_store=None):
    """Produce context_summary, operative_summary, amendments JSON+md, amendments.docx.

    `embed_store` (genesis Part XXI): when provided, per-doc context filtering
    uses cosine-similarity retrieval instead of Zipfian term matching. The
    REF-* citation format is identical regardless of which path runs.
    """
    deliv_dir = ROOT / "output" / "deliverables"
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
        pa_findings = _filter_doc(conv_review, doc["id"], "PRACTICE_AUDITOR") or []
        sg_findings = _filter_doc(conv_review, doc["id"], "STYLE_GUARDIAN") or []
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
                "findings_from_practice_auditor": _filter_doc(conv_review, doc["id"], "PRACTICE_AUDITOR"),
                "findings_from_style_guardian":   _filter_doc(conv_review, doc["id"], "STYLE_GUARDIAN"),
                "findings_from_verifier":         _filter_doc(audit,       doc["id"], "VERIFIER"),
                "findings_from_fact_checker":     _filter_doc(audit,       doc["id"], "FACT_CHECKER"),
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
            # parsed is populated even on contract_violation (whatever JSON the
            # model produced); don't discard the partial result — filter it.
            amendments_payload = result.get("parsed")
            if isinstance(amendments_payload, list):
                amendments_payload = {"document_id": doc["id"], "amendments": amendments_payload}
            if amendments_payload is None:
                amendments_payload = {"document_id": doc["id"], "amendments": []}

            if result.get("error") == "contract_violation":
                raw_amendments = amendments_payload.get("amendments") or []
                kept = []
                for a in raw_amendments:
                    if not isinstance(a, dict):
                        continue
                    # location, convention_ref, comment are the three fields
                    # that make a finding traceable. Drop anything missing them.
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

        (deliv_dir / f"{doc['id']}__amendments.json").write_text(
            json.dumps(amendments_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        (deliv_dir / f"{doc['id']}__amendments.md").write_text(
            _render_amendments_md(doc, amendments_payload, convention_registry, reference_index),
            encoding="utf-8")

        docx_path = deliv_dir / f"{doc['id']}__amendments.docx"
        try:
            build_amendments_docx(
                title=f"{doc['name']} — Convention review (tracked changes)",
                body_text=doc["text"],
                amendments=amendments_payload.get("amendments", []),
                output_path=docx_path,
            )
        except Exception as e:
            print(f"[pipeline] WARN: docx build failed for {doc['name']}: {e}", file=sys.stderr)

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


def _filter_doc(results, doc_id, agent):
    out = []
    for r in results:
        if r.get("doc_id") != doc_id or r.get("agent") != agent:
            continue
        if not r.get("ok"):
            continue
        parsed = r.get("parsed")
        if isinstance(parsed, list):
            out.extend(p for p in parsed if isinstance(p, dict))
        elif isinstance(parsed, dict):
            out.append(parsed)
    return out


def _category_for_conv(conv_id, registry):
    if not conv_id:
        return None
    for c in registry.get("conventions", []):
        if c.get("id") == conv_id:
            return c.get("category")
    return None


def _render_amendments_md(doc, payload, registry, reference_index):
    n_uncertain = sum(1 for a in payload.get("amendments", []) if a.get("uncertain"))
    lines = [f"# {doc['name']} — Proposed amendments", "",
             f"- generated: {datetime.now(timezone.utc).isoformat()}",
             f"- amendments: {len(payload.get('amendments', []))}",
             f"- uncertain: {n_uncertain}",
             f"- validator errors: {len(payload.get('_validator_errors', []))}"]
    if payload.get("_validator_errors"):
        lines.append("\n## Validator errors\n")
        for e in payload["_validator_errors"]:
            lines.append(f"- {e}")
    lines.append("\n## Amendments\n")
    for i, a in enumerate(payload.get("amendments", []), 1):
        conv = a.get("convention_ref", "?"); loc = a.get("location", "?")
        cat = _category_for_conv(conv, registry) or "?"
        sev = a.get("severity", "?")
        # Genesis Part XXVI: uncertain findings carry an explicit tag in
        # every deliverable section so the operator never sees them
        # silently merged with confident ones.
        uncertain_tag = "[UNCERTAIN] " if a.get("uncertain") else ""
        lines.append(
            f"### {uncertain_tag}Amendment {i} [{conv}] — "
            f"{a.get('finding_type', cat)} ({sev})"
        )
        lines.append("")
        lines.append(f"**Location:** [{loc}]")
        lines.append(f"**Action:** {a.get('action', 'flag')}")
        original = a.get('original_text') or '(unspecified)'
        lines.append(f"**Original:** {str(original)[:500]}")
        proposed = a.get('proposed_text')
        if proposed:
            lines.append(f"**Proposed:** {str(proposed)[:500]}")
        lines.append("")
        lines.append("**Justification:**")
        comment = a.get("comment", "(missing comment)")
        if a.get("uncertain") and not comment.lstrip().startswith("[UNCERTAIN]"):
            comment = "[UNCERTAIN] " + comment
        lines.append(comment)
        lines.append("")
        if a.get("context_refs"):
            lines.append(f"**Context references:** {', '.join(a['context_refs'])}")
        lines.append("")
    return "\n".join(lines)


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

def _build_reference_index(project_root, ctx_docs, op_docs, conv_registry):
    idx_path = project_root / "output" / "audit" / "reference_index.json"
    if idx_path.exists(): idx_path.unlink()
    idx = ReferenceIndex.open(project_root)
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
    parser.add_argument("--save-ontology", metavar="NAME")
    parser.add_argument("--load-ontology", metavar="NAME")
    parser.add_argument("--reset-ontology", action="store_true")
    parser.add_argument("--list-ontologies", action="store_true")
    parser.add_argument("--overwrite-ontology", action="store_true",
                        help="allow --save-ontology to overwrite existing")
    args = parser.parse_args(argv)

    # Ontology shortcuts: take action and exit.
    if args.list_ontologies:
        for o in list_ontologies(ROOT):
            print(f"{o['name']:30s} saved_at={o.get('saved_at', '?')} files={len(o.get('files', []))}")
        return 0
    if args.reset_ontology:
        summary = reset_ontology(ROOT)
        print("[ontology] reset:", json.dumps(summary, indent=2))
        return 0
    if args.load_ontology:
        summary = load_ontology(ROOT, args.load_ontology)
        print(f"[ontology] loaded {args.load_ontology!r}:", json.dumps(summary, indent=2))
        return 0
    if args.save_ontology:
        try:
            target = save_ontology(ROOT, args.save_ontology, overwrite=args.overwrite_ontology)
        except FileExistsError as e:
            print(f"[ontology] {e}", file=sys.stderr); return 2
        print(f"[ontology] saved to {target}")
        return 0

    # Reset toggles
    if args.reset_bus:
        bp = ROOT / "output" / "logs" / "agent_bus.jsonl"
        if bp.exists(): bp.unlink()
    if args.reset_cost:
        for p in (ROOT / "output" / "logs" / "cost_tracker.jsonl",
                  ROOT / "output" / "logs" / "cost_tracker.json"):
            if p.exists(): p.unlink()

    # Cost tracker (must exist before any agent fires)
    cost_tracker = CostTracker.open(ROOT / "output" / "logs", print_live=True)

    # Search router (used by date cascade + downstream agents)
    keys = load_api_keys()
    search_router = SearchRouter.open(ROOT, keys=keys)

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
                                 run_adaptive_spawn=True)
    orch.run_objectives = args.run_objectives

    # Parse conventions -> registry
    conv_registry = parse_conventions(ROOT)
    write_registry(ROOT, conv_registry)
    conv_registry_dict = conv_registry.as_dict()
    convention_review_enabled = bool(conv_registry_dict.get("conventions"))
    print(f"[pipeline] convention registry: {len(conv_registry_dict.get('conventions', []))} rules; "
          f"review enabled={convention_review_enabled}", file=sys.stderr)

    # Reference index
    reference_index = _build_reference_index(ROOT, ctx_docs, op_docs, conv_registry_dict)
    print(f"[pipeline] reference index: {len(reference_index.entries)} entries", file=sys.stderr)

    # Semantic retrieval layer (genesis Part XXI). Loads from
    # output/audit/embedding_store.pkl if present, otherwise tries to build
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
    if op_docs:
        print(f"[pipeline] phase 3-4: content production", file=sys.stderr)
        production = asyncio.run(phase_3_4_content_production(
            orch, keys, op_docs, ctx_docs, run_objectives,
            conv_registry_dict, reference_index,
            [e.as_dict() for e in reference_index.entries if e.input_type == "context"][:30],
            embed_store=embed_store,
        ))
        # Part XXVII: pull the structural inventory ARCHIVIST produced during
        # the corpus-level phase so downstream phases can pass it to
        # PRACTICE_AUDITOR / LEGAL_ANALYST per Part XXIV's directive.
        structural_inventory = _extract_structural_inventory(production)
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
        synth = AuditSynthesizer(project_root=ROOT, bus=orch.bus)
        audit_summary = synth.synthesize(
            verifier_findings=_flatten(audit, "VERIFIER"),
            fact_check_findings=_flatten(audit, "FACT_CHECKER"),
            practice_findings=_flatten(conv_review, "PRACTICE_AUDITOR"),
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
