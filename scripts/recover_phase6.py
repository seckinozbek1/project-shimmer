"""Recovery harness: re-runs phase 6 (synthesis + deliverables) using already-paid-for
agent outputs harvested from a run's logs/agent_bus.jsonl (output/runs/<run>/;
--run selects the folder, default latest).

Replays AMENDMENT_DRAFTER for any document that doesn't already have its
amendments.json deliverable. Re-generates all summaries + docx + amendments .md
from the existing data.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent_wrapper import AgentWrapper, load_api_keys
from convention_parser import parse_conventions
from cost_tracker import CostTracker
from docx_builder import build_amendments_docx
from orchestrator import TopOrchestrator
from pipeline import (
    _build_reference_index, _filter_doc, _load_corpus, _render_amendments_md,
    _render_per_agent_md, phase_6_synthesis, _truncate,
)
from pipeline_amendment_validator import validate_amendment_payload
import run_context as run_context_mod
from summary_generators import render_context_summary, render_operative_summary


def _harvest_agent_outputs_from_bus(bus_path: Path) -> dict:
    """Return {agent_name: [parsed_payloads...]} from INFORM messages where
    body.event == AGENT_OUTPUT. Each payload is the contract-shaped JSON
    the agent emitted at run time."""
    out = {}
    if not bus_path.exists():
        return out
    for line in bus_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try: msg = json.loads(line)
        except json.JSONDecodeError: continue
        if msg.get("type") != "INFORM":
            continue
        body = msg.get("body") or {}
        if body.get("event") != "AGENT_OUTPUT":
            continue
        sender = msg.get("sender")
        payload = body.get("payload")
        if sender and payload is not None:
            out.setdefault(sender, []).append(payload)
    return out


def _shape_results_from_bus(bus_outputs: dict, op_docs: list[dict],
                            production_agents: list[str], audit_agents: list[str],
                            conv_review_agents: list[str]) -> tuple[list, list, list]:
    """Bus only records sender + payload, not doc_id. Heuristic: match
    parsed payloads to docs by inspecting doc-name-bearing fields in the
    payload. If unmatched, attach to the next-available doc in order."""
    production, audit, conv_review = [], [], []
    # We need to pair each payload with a doc. Strategy: per agent, payloads
    # come in chronological order; for per-doc agents we process the operational
    # docs in the same order. So zip them.
    for agent_name in production_agents + audit_agents + conv_review_agents:
        payloads = bus_outputs.get(agent_name, [])
        target = production if agent_name in production_agents else (
            audit if agent_name in audit_agents else conv_review)
        for idx, payload in enumerate(payloads):
            doc_id = None
            if isinstance(payload, dict):
                doc_id = payload.get("document_id") or payload.get("doc_id")
            if doc_id is None and idx < len(op_docs):
                doc_id = op_docs[idx]["id"]
            target.append({"scope": "doc", "doc_id": doc_id, "agent": agent_name,
                           "ok": True, "parsed": payload, "raw_text": "",
                           "contract_missing": [], "error": None})
    return production, audit, conv_review


async def _recover_and_synthesize(op_docs, ctx_docs, production, audit, conv_review,
                                   conv_registry_dict, reference_index, run_objectives,
                                   run_ctx):
    cost_tracker = CostTracker.open(run_ctx.logs_dir(), print_live=True)
    orch = TopOrchestrator.boot(
        ROOT, interactive=False, operator_handler=None,
        cost_tracker=cost_tracker, run_adaptive_spawn=False, run_context=run_ctx,
    )
    orch.run_objectives = run_objectives
    keys = load_api_keys()
    deliv = await phase_6_synthesis(
        orch, keys, op_docs, production, audit, conv_review,
        run_objectives, conv_registry_dict, reference_index,
    )
    cost_tracker.finalize_line()
    return deliv, cost_tracker


def main():
    ap = argparse.ArgumentParser(description="Re-run phase 6 from a run's harvested bus outputs")
    ap.add_argument("--run", help="run folder name under output/runs/ (default: latest run)")
    args = ap.parse_args()
    if args.run:
        run_ctx = run_context_mod.for_run_dir(ROOT, run_context_mod.runs_root(ROOT) / args.run)
    else:
        run_ctx = run_context_mod.latest_run(ROOT)
    if run_ctx is None or not run_ctx.run_dir.is_dir():
        print("[recover] no run folder found under output/runs/. Pass --run <name>.",
              file=sys.stderr)
        return 2
    print(f"[recover] target run: {run_ctx.run_dir.relative_to(ROOT)}", file=sys.stderr)

    bus_path = run_ctx.bus_path()
    bus_outputs = _harvest_agent_outputs_from_bus(bus_path)
    print("[recover] bus outputs by sender:", file=sys.stderr)
    for k, v in sorted(bus_outputs.items()):
        print(f"  {k:20s} {len(v)} payloads", file=sys.stderr)

    op_docs = _load_corpus(ROOT / "input" / "operational")
    ctx_docs = _load_corpus(ROOT / "input" / "context")
    if not op_docs:
        print("[recover] no operational docs found.", file=sys.stderr); return 2

    conv_registry = parse_conventions(ROOT)
    conv_dict = conv_registry.as_dict()
    reference_index = _build_reference_index(ROOT, ctx_docs, op_docs, conv_dict,
                                             run_context=run_ctx)
    print(f"[recover] {len(op_docs)} operational docs, {len(ctx_docs)} context docs, "
          f"{len(conv_dict.get('conventions', []))} conventions, "
          f"{len(reference_index.entries)} reference entries", file=sys.stderr)

    production, audit, conv_review = _shape_results_from_bus(
        bus_outputs, op_docs,
        production_agents=["PROCESSOR", "SPEECH_ACT_TAGGER", "LEGAL_ANALYST",
                            "ARCHIVIST", "INST_FINDER", "CITATION_RESOLVER"],
        audit_agents=["VERIFIER", "FACT_CHECKER"],
        conv_review_agents=["PRACTICE_AUDITOR", "STYLE_GUARDIAN"],
    )
    print(f"[recover] reconstructed: production={len(production)} audit={len(audit)} "
          f"conv_review={len(conv_review)}", file=sys.stderr)

    run_objectives = (
        "Review each operational document against the convention registry. "
        "Produce all deliverables specified in Part XVIII Sections C and D. "
        "Every finding must cite convention rules (CONV-*) and source passages (REF-*)."
    )
    deliv, cost_tracker = asyncio.run(_recover_and_synthesize(
        op_docs, ctx_docs, production, audit, conv_review,
        conv_dict, reference_index, run_objectives, run_ctx))

    print("\n=== recovery summary ===", file=sys.stderr)
    for doc_id, paths in deliv.items():
        print(f"  -> {doc_id}: amendments={paths['amendment_count']}, "
              f"validator_errors={len(paths['validator_errors'])}, "
              f"docx={'yes' if paths.get('amendments_docx') else 'no'}", file=sys.stderr)
    final = cost_tracker.get_live_state()
    print(f"\n  recovery added: ${final['total_cost_usd']:.4f}  "
          f"calls: {final['total_calls']}  failures: {final['total_failures']}",
          file=sys.stderr)

    # Post-recovery audit: every operational document must have all 6
    # deliverable files. Print a warning for any missing file. The
    # context_summary and operative_summary are deterministic (no API
    # cost), so if they are missing the recovery is incomplete.
    expected_suffixes = (
        "__context_summary.md", "__operative_summary.md",
        "__amendments.json", "__amendments.md", "__amendments.docx",
        "__deliverable.md",
    )
    deliv_dir = run_ctx.deliverables_dir()
    missing_count = 0
    for doc in op_docs:
        for suffix in expected_suffixes:
            path = deliv_dir / f"{doc['id']}{suffix}"
            if not path.exists():
                print(f"[recover] MISSING: {path.relative_to(ROOT)}",
                      file=sys.stderr, flush=True)
                missing_count += 1
    if missing_count == 0:
        print(f"\n[recover] post-recovery audit: all 6 deliverable files present "
              f"for all {len(op_docs)} operational docs.", file=sys.stderr)
    else:
        print(f"\n[recover] post-recovery audit: {missing_count} deliverable file(s) "
              f"missing across {len(op_docs)} operational docs.",
              file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
