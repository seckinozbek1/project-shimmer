"""OGE capture-at-run-end hook (build B1; ontology/SCHEMA.md RATIFIED Q1 + Q9).

Reads a FINALIZED run's per-run artifacts (the amendments master and the run's
delta_proposals.json) and appends them to the durable cross-run OGE stores under
ontology/stores/ (Q9: the OGE owns ontology/, kept separate from durable/). The code lives in
scripts/ to follow the project's prevailing flat-module convention (on sys.path, importable by
pipeline + the verify gate); the durable DATA lives under ontology/ per the ratified schema.

Two stores:
  ontology/stores/provisions.jsonl       append-only per-run provision capture (Q1)
  ontology/stores/delta_proposals.jsonl  cross-run proposal ACCUMULATOR (SCHEMA C1): one line
                                         per unique dedup key, merged across runs (occurrence
                                         count + first/last seen + operator status), not duplicated.

Masked-write gate (BUILD INVARIANT, day one, not retrofitted): every RAW field from SCHEMA
table D that this hook writes passes through mask_field(...), keyed on the run's sensitive-mode
signal (the pipeline's run_is_non_sensitive / redaction_enabled; we do NOT invent a new source).
Non-sensitive: real content. Sensitive: a typed placeholder [REDACTED:TYPE]. abs_path is never
written (Q7); provision node id is the composite (document_id, ref_id) (Q2); referenced-only REFs
become stub nodes (Q3).

Deterministic, local, no model calls.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OGE_STORES_DIR = ROOT / "ontology" / "stores"

_PLACEHOLDER = "[REDACTED:%s]"


def _store_paths(stores_dir=None):
    """Resolve the two store paths. `stores_dir` overrides the default ontology/stores
    (the verify gate passes a tempdir so it never mutates the real OGE stores)."""
    d = Path(stores_dir) if stores_dir else OGE_STORES_DIR
    return d / "provisions.jsonl", d / "delta_proposals.jsonl"


def _now():
    return datetime.now(timezone.utc).isoformat()


def mask_field(value, field_type, *, sensitive):
    """The masked-write gate (BUILD INVARIANT). sensitive=False returns the real value;
    sensitive=True returns a typed placeholder [REDACTED:<field_type>]. None passes through
    unchanged (no placeholder for absent content). This is the single mask-or-passthrough
    function every RAW field is written through."""
    if not sensitive:
        return value
    if value is None:
        return None
    return _PLACEHOLDER % field_type


def _mask_evidence(evidence, *, sensitive):
    """Proposal evidence can embed raw findings (SCHEMA table D, DeltaProposal note). Under
    sensitive mode the whole evidence blob is replaced by a typed placeholder; otherwise the
    real evidence is kept."""
    if not sensitive:
        return evidence
    if evidence is None:
        return None
    return {"masked": _PLACEHOLDER % "FINDING_EVIDENCE"}


def _append_jsonl(path, records):
    if not records:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(records)


def _load_accumulator(path):
    """Load the proposal accumulator (one JSON object per line) into {dedup_key: record}."""
    out = {}
    if not Path(path).exists():
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        k = r.get("dedup_key")
        if k:
            out[k] = r
    return out


def _rewrite_accumulator(path, by_key):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, ensure_ascii=False) for r in by_key.values()]
    Path(path).write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")


def _proposal_dedup_key(p):
    """Stable cross-run dedup key for a DELTA proposal (SCHEMA C1). Built from kind + the
    proposed_change target/action/scope so the SAME recurring proposal merges across runs;
    deliberately excludes the per-run id and created_at (which vary every run)."""
    pc = p.get("proposed_change") or {}
    scope = pc.get("scope", pc.get("topic", pc.get("mission", "")))
    return "|".join([str(p.get("kind", "")), str(pc.get("target", "")),
                     str(pc.get("action", "")), str(scope)])


def capture_provisions(master, run_id, *, sensitive):
    """Build provision records from a finalized amendments master. RAW fields (original_text /
    proposed_text / comment, SCHEMA table D) go through the masked-write gate. Composite id
    (document_id, ref_id) per Q2; referenced-only REFs become stub nodes per Q3."""
    document_id = master.get("document_id", "unknown")
    amendments = master.get("amendments", []) or []
    records = []
    seen = set()
    for a in amendments:
        ref_id = a.get("location")
        if not ref_id:
            continue
        seen.add(ref_id)
        records.append({
            "node": "Provision",
            "id": f"{document_id}::{ref_id}",          # Q2 composite id
            "document_id": document_id,                # SAFE
            "ref_id": ref_id,                          # SAFE
            "finding_type": a.get("finding_type"),     # SAFE
            "action": a.get("action"),                 # SAFE
            "severity": a.get("severity"),             # SAFE
            "convention_ref": a.get("convention_ref"), # SAFE (CONV-* -> GOVERNED_BY edge, N:1 per Q4)
            "context_refs": a.get("context_refs", []) or [],  # SAFE (REF-* -> CROSS_REFERENCES)
            # RAW fields (table D) through the masked-write gate:
            "original_text": mask_field(a.get("original_text"), "PROVISION_TEXT", sensitive=sensitive),
            "proposed_text": mask_field(a.get("proposed_text"), "PROVISION_TEXT", sensitive=sensitive),
            "comment": mask_field(a.get("comment"), "ANALYST_COMMENT", sensitive=sensitive),
            "stub": False,
            "run_id": run_id,
            "captured_at": _now(),
        })
    # Q3: referenced-only REFs (appear in context_refs but are never a location) -> stub nodes
    referenced = set()
    for a in amendments:
        for r in (a.get("context_refs") or []):
            referenced.add(r)
    for ref_id in sorted(referenced - seen):
        records.append({
            "node": "Provision",
            "id": f"{document_id}::{ref_id}",
            "document_id": document_id,
            "ref_id": ref_id,
            "stub": True,            # Q3: id only, no text, flagged incomplete
            "incomplete": True,
            "run_id": run_id,
            "captured_at": _now(),
        })
    return records


def capture_proposals(proposals, run_id, *, sensitive, stores_dir=None):
    """Merge a run's DELTA proposals into the cross-run accumulator (SCHEMA C1). Same recurring
    proposal (by dedup key) increments occurrence_count and updates last_seen instead of
    duplicating; status defaults to 'proposed'. RAW evidence is masked under sensitive mode.
    Returns the full accumulator as a list. No rewrite when there is nothing to merge."""
    _, proposals_store = _store_paths(stores_dir)
    existing = _load_accumulator(proposals_store)
    if not proposals:
        return list(existing.values())
    now = _now()
    for p in proposals:
        key = _proposal_dedup_key(p)  # built from the RAW proposal so recurring proposals still merge
        # INFRA-041 P4: the masked-write gate now covers all three content-bearing fields, not just
        # evidence. proposed_change (the full change object) and trigger can quote source spans, so
        # both are masked under sensitive mode (Q-audit cross-run gap). Reuses the existing B1
        # mask_field / _mask_evidence (no second masker). The dedup_key is derived from the raw
        # proposal's structural target/action/scope ids (no source span) so cross-run merge holds.
        masked_evidence = _mask_evidence(p.get("evidence"), sensitive=sensitive)
        masked_change = mask_field(p.get("proposed_change"), "PROPOSAL_CHANGE", sensitive=sensitive)
        masked_trigger = mask_field(p.get("trigger"), "PROPOSAL_TRIGGER", sensitive=sensitive)
        rec = existing.get(key)
        if rec is None:
            existing[key] = {
                "node": "DeltaProposal",
                "dedup_key": key,
                "kind": p.get("kind"),                       # SAFE
                "trigger": masked_trigger,                   # RAW -> masked under sensitive (P4)
                "proposed_change": masked_change,            # RAW -> masked under sensitive (P4)
                "evidence": masked_evidence,                 # RAW -> masked under sensitive
                "occurrence_count": 1,
                "first_seen": now,
                "last_seen": now,
                "first_run_id": run_id,
                "last_run_id": run_id,
                "status": "proposed",                        # operator-decision default (C1)
            }
        else:
            rec["occurrence_count"] = int(rec.get("occurrence_count", 1)) + 1
            rec["last_seen"] = now
            rec["last_run_id"] = run_id
            rec["evidence"] = masked_evidence                # refresh to latest (masked) evidence
            rec["proposed_change"] = masked_change           # refresh (masked under sensitive)
            rec["trigger"] = masked_trigger                  # refresh (masked under sensitive)
            # status is preserved (the operator may have moved it past 'proposed')
    _rewrite_accumulator(proposals_store, existing)
    return list(existing.values())


def capture_run(run_ctx, op_docs, deliverables, *, sensitive, stores_dir=None):
    """Run-end capture hook (Q1). Reads the finalized amendments master per op_doc and the
    run's delta_proposals.json; appends provisions (append-only) and merges proposals (the
    accumulator) into the durable OGE stores. Deterministic, local, no model calls. Returns a
    summary dict. (The pipeline call site wraps this so a capture failure never fails a
    completed run.)"""
    provisions_store, _ = _store_paths(stores_dir)
    run_id = getattr(run_ctx, "run_id", "unknown")

    prov_records = []
    for doc in op_docs:
        info = deliverables.get(doc["id"]) or {}
        mp = info.get("amendments_json")
        if not mp:
            mp = str(run_ctx.deliverables_dir() / f"{doc['id']}__amendments.json")
        p = Path(mp)
        if not p.exists():
            continue
        try:
            master = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        prov_records.extend(capture_provisions(master, run_id, sensitive=sensitive))
    n_prov = _append_jsonl(provisions_store, prov_records)

    proposals = []
    try:
        dp_path = run_ctx.delta_proposals_path()
        if Path(dp_path).exists():
            data = json.loads(Path(dp_path).read_text(encoding="utf-8")) or {}
            proposals = data.get("proposals", []) or []
    except Exception:
        proposals = []
    acc = capture_proposals(proposals, run_id, sensitive=sensitive, stores_dir=stores_dir)

    return {
        "run_id": run_id,
        "provisions_appended": n_prov,
        "proposals_in_run": len(proposals),
        "accumulator_size": len(acc),
        "sensitive": bool(sensitive),
    }
