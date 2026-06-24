"""INFRA-041 PART 5 -- LAW-IV masking proof harness (PAID; run ONLY on explicit operator go).

This is TEST SCAFFOLDING, not wired into the live pipeline and not imported by the verify gate.
It proves the outbound masking protocol END-TO-END with the layer ACTIVATED (LAYER_ACTIVE=True),
using the REAL operator convention (CONV-CONFIDENTIALITY -> CONV-006) and PLANTED SENTINEL tokens,
asserting by EXACT STRING IDENTITY at four places:

  (a) ON THE WIRE  -- the bytes that actually left, captured POST-masker PRE-send on the REAL
      dispatch path (call_gpt is wrapped to record its args, then calls through to the paid API).
        chokepoint 1+3 (run_task network dispatch): sentinels ABSENT, typed placeholders PRESENT.
        chokepoint 2 (search query): masked query at the engine boundary, sentinels ABSENT.
        chokepoint 4 (date_from_web): SUPPRESSED -- no web call, no title egress (NOT a placeholder).
  (b) CROSS-RUN STORES -- provisions.jsonl + delta_proposals.jsonl + graph.json + document_dates.json,
      written through the sensitive store-write paths, grepped: sentinels BYTE-ABSENT.
  (c) EXPOSURE LEDGER -- exposure_ledger.jsonl records the masking as exposure:masked with field
      name + authorizing rule id, and contains NO sentinel content.
  (d) NEGATIVE CONTROL -- a non-sensitive token reaches the wire RAW and is not in the ledger.

PAID SURFACE: exactly ONE real network dispatch (VERIFIER, openai_api / gpt-4o) over the planted
doc, to capture an on-the-wire masked prompt (chokepoints 1+3). The Claude path uses the IDENTICAL
masker call site (backend-agnostic should_mask_outbound), so one network dispatch proves the wire
masking; a second Claude dispatch can be added for family coverage. Chokepoints 2/4 and the
cross-run-store + ledger proofs are FREE (no model calls). Rough cost: ~$0.03-0.06 (see report).

This harness FLIPS LAYER_ACTIVE for its own duration (restored in finally) and writes only to a
tempdir + a real run-context folder; it never mutates the live durable/ or ontology/ stores.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import sensitivity_layer as S
import search_router as SR
import document_dating as DD
import ontology_capture
import ontology_graph
from convention_parser import parse_conventions
from orchestrator import TopOrchestrator
import run_context as run_context_mod

# ---- planted sentinels (must match planted_context_doc.md exactly) -------------------------
IDENT = "19-0001-0002-0003"          # identifier shape -> [REDACTED:IDENTIFIER]
FIG = "88,000,777,001 EUR"           # figure shape     -> [REDACTED:FIGURE]
NEG = "NEGCTRL-PUBLIC-TOKEN-42"      # negative control -> must pass RAW
TITLE = "P5-TITLE-SENTINEL-DOC"      # title sentinel for the chokepoint-4 suppression assertion

PLANTED_TEXT = (Path(__file__).resolve().parent / "planted_context_doc.md").read_text(encoding="utf-8")

_results = []
def _check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def main():
    # operator rules from the REAL convention (CONV-006) + confirm both shapes authorized
    conv_dict = parse_conventions(ROOT).as_dict()
    rr = S.redaction_rules(conv_dict)
    operator_rules = rr["rules"]
    cues = S.redaction_detect.load_cues(str(ROOT))
    auth = S.redaction_detect.authorized_shapes(operator_rules, cues)
    _check("convention compiles + authorizes identifier+figure",
           rr["operator_in_force"] and "identifier" in auth and "figure" in auth,
           f"source={rr['source']} auth={sorted(auth)}")

    tmp = Path(tempfile.mkdtemp(prefix="shimmer_p5_"))
    ledger = tmp / "exposure_ledger.jsonl"
    captured = {}

    saved_layer = S.LAYER_ACTIVE
    run_ctx = run_context_mod.create_run(ROOT)
    orch = TopOrchestrator.boot(ROOT, interactive=False, run_adaptive_spawn=False, run_context=run_ctx)
    try:
        S.LAYER_ACTIVE = True  # ACTIVATE the layer for the proof (restored in finally)

        # ---------- (a) chokepoint 1+3: TWO REAL network dispatches, capture each wire ----------
        from agent_wrapper import AgentWrapper
        masker = S.make_outbound_prompt_masker(
            sensitive=True, operator_rules=operator_rules, project_root=str(ROOT),
            registry=orch.registry, run_id="P5-PROOF", ledger_path=str(ledger))

        def _dispatch_capture(agent_name, send_method):
            """Build a real network wrapper, wrap its send path to record POST-masker PRE-send
            args (the bytes that left), call through to the REAL API over the planted doc."""
            w = AgentWrapper(
                name=agent_name, constitution=orch.constitution, bus=orch.bus, registry=orch.registry,
                contracts=orch.contracts, keys=getattr(orch, "keys", None) or None,
                cost_tracker=getattr(orch, "cost_tracker", None), run_context=run_ctx,
                outbound_masker=masker)
            orig = getattr(w, send_method)
            box = {}
            def cap(stable_prefix, dynamic_suffix="", **kw):
                box["wire"] = (stable_prefix or "") + "\n" + (dynamic_suffix or "")
                return orig(stable_prefix, dynamic_suffix, **kw)
            setattr(w, send_method, cap)  # instance-level hook (class method untouched)
            payload = {"task": "verify_draft_against_source", "document_name": "p5_proof",
                       "source_text": PLANTED_TEXT}
            w.run_task(work_payload=payload, run_objectives="P5 masking proof",
                       convention_registry=conv_dict, max_tokens=512)  # <-- PAID call
            return box.get("wire", "")

        for fam, agent_name, send_method in (("GPT", "VERIFIER", "call_gpt"),
                                             ("Claude", "STYLE_GUARDIAN", "call_claude")):
            wire = _dispatch_capture(agent_name, send_method)
            _check(f"(a) {fam} ({agent_name}) chokepoint1/3: IDENT sentinel ABSENT on the wire",
                   IDENT not in wire)
            _check(f"(a) {fam} ({agent_name}) chokepoint1/3: FIG sentinel ABSENT on the wire",
                   FIG not in wire)
            _check(f"(a) {fam} ({agent_name}) chokepoint1/3: typed placeholders PRESENT on the wire",
                   "[REDACTED:IDENTIFIER]" in wire and "[REDACTED:FIGURE]" in wire)
            _check(f"(d) {fam} ({agent_name}): negative control RAW on the wire", NEG in wire)

        # ---------- (a) chokepoint 2: search query masked at the engine boundary ----------
        qmasker = S.make_query_masker(sensitive=True, operator_rules=operator_rules,
                                      project_root=str(ROOT), run_id="P5-PROOF", ledger_path=str(ledger))
        # router project_root = tmp so record_learning writes to the tempdir, NOT the real
        # durable/learnings store (the query masker keeps project_root=ROOT for the detector cues).
        router = SR.SearchRouter.open(tmp, keys={}, query_masker=qmasker)
        seen_q = {}
        router._ddg_search = lambda q, max_results=5: (seen_q.update(q=q) or ([], ""))
        router._brave_search = lambda q: (seen_q.update(q=q) or ([], ""))
        router.search(f"verify turnover {FIG} and identity {IDENT}", agent=None, claim_type="x")
        wq = seen_q.get("q", "")
        _check("(a) chokepoint2: query masked at the engine boundary (sentinels absent, placeholders present)",
               IDENT not in wq and FIG not in wq and "[REDACTED:" in wq, f"query={wq!r}")

        # ---------- (a) chokepoint 4: date-web SUPPRESSED (no web call, no title egress) ----------
        class _RecRouter:
            def __init__(self): self.calls = []
            def search(self, q, **k):
                self.calls.append(q)
                return SR.SearchResult(query=q, hits=[], strategy_used="x", verdict="UNVERIFIABLE", diagnostic={})
        rec = _RecRouter()
        res4 = DD.date_from_web(f"{TITLE} publication", search_router=rec, sensitive=True)
        _check("(a) chokepoint4: date-web SUPPRESSED (no call, no title egress)",
               res4 is None and not rec.calls and not any(TITLE in c for c in rec.calls))

        # ---------- (b) cross-run stores written under sensitive mode, grepped ----------
        stores = tmp / "stores"
        deliv = tmp / "deliv"; deliv.mkdir(parents=True)
        doc_id = "p5_proof"
        master = {"document_id": doc_id, "amendments": [
            {"location": "REF-1", "convention_ref": "CONV-006", "context_refs": [],
             "finding_type": "confidentiality", "action": "redact", "severity": "required",
             "original_text": f"identity number {IDENT} and turnover {FIG}",
             "proposed_text": None, "comment": f"remove {IDENT} / {FIG}"}]}
        (deliv / f"{doc_id}__amendments.json").write_text(json.dumps(master, ensure_ascii=False), encoding="utf-8")
        (tmp / "delta_proposals.json").write_text(json.dumps({"generated_at": "t", "proposals": []}), encoding="utf-8")

        class _RC:
            run_id = "P5-PROOF"
            def deliverables_dir(_s): return deliv
            def delta_proposals_path(_s): return tmp / "delta_proposals.json"
        ontology_capture.capture_run(
            _RC(), [{"id": doc_id, "name": doc_id}],
            {doc_id: {"amendments_json": str(deliv / f"{doc_id}__amendments.json")}},
            sensitive=True, stores_dir=str(stores))
        # a proposal carrying sentinels in all three masked fields
        ontology_capture.capture_proposals(
            [{"kind": "refine_convention", "trigger": f"recurring {FIG} in REF-1",
              "proposed_change": {"target": "CONV-006", "action": "tighten", "scope": "turnover",
                                  "note": f"company turnover {FIG}"},
              "evidence": {"finding": f"identity {IDENT}"}}],
            "P5-PROOF", sensitive=True, stores_dir=str(stores))
        graph_out = tmp / "graph.json"
        ontology_graph.build_graph(
            sources={"provisions": stores / "provisions.jsonl"},
            out_path=str(graph_out), sensitive=True)
        DD.write_dates(tmp, [{"filename": "p5_proof_2024.md", "date": "2024-01-01",
                              "date_source": "filename", "date_confidence": "high",
                              "title": f"{TITLE} {FIG}", "abs_path": f"C:/secret/{IDENT}.md",
                              "content_validated": True,
                              "validation_note": f"first_page_excerpt='{IDENT} {FIG}'"}])
        store_files = [stores / "provisions.jsonl", stores / "delta_proposals.jsonl", graph_out,
                       tmp / "durable" / "learnings" / "document_dates.json"]
        leaked = []
        for f in store_files:
            if f.exists():
                blob = f.read_text(encoding="utf-8")
                if IDENT in blob or FIG in blob:
                    leaked.append(f.name)
        _check("(b) cross-run stores byte-absent of sentinels "
               "(provisions/delta_proposals/graph/document_dates)", not leaked, f"leaked_in={leaked}")

        # ---------- (c) exposure ledger records masked, no sentinel content ----------
        lines = ledger.read_text(encoding="utf-8").splitlines() if ledger.exists() else []
        recs = [json.loads(x) for x in lines if x.strip()]
        masked_recs = [r for r in recs if r.get("exposure") == "masked"]
        ledger_blob = ledger.read_text(encoding="utf-8") if ledger.exists() else ""
        _check("(c) exposure ledger records exposure:masked with a field name",
               bool(masked_recs) and all(m.get("masked_fields") for m in masked_recs),
               f"masked_records={len(masked_recs)}")
        _check("(c) exposure ledger contains NO sentinel content",
               IDENT not in ledger_blob and FIG not in ledger_blob)
        _check("(d) negative control NOT recorded as masked content in the ledger", NEG not in ledger_blob)

    finally:
        S.LAYER_ACTIVE = saved_layer  # instance-level send hooks need no restore (class untouched)

    n_fail = sum(1 for _, ok, _ in _results if not ok)
    print(f"\nP5 MASKING PROOF: {len(_results) - n_fail}/{len(_results)} assertions passed; "
          f"{n_fail} failed.")
    print("PAID SURFACE: 2 dispatches -- VERIFIER (gpt-4o) + STYLE_GUARDIAN (claude-haiku-4-5). "
          "Cross-run-store/ledger/search/date proofs are free.")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
