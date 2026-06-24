"""OGE Tier-1 graph ingest (build B2; ontology/SCHEMA.md sections A, B, C5/C6 + RATIFIED).

Builds an in-memory Tier-1 knowledge graph from the durable sources and serializes it to
ontology/stores/graph.json (a plain node-list + edge-list, stdlib only, no external graph lib).
Deterministic, local, no model calls.

Sources (Q9: OGE data under ontology/; the rest are the existing durable/config stores):
  ontology/stores/provisions.jsonl        provisions captured by B1 (may be empty)
  durable/learnings/document_dates.json    Document/Case nodes (id = filename; NO abs_path, Q7)
  config/convention_registry.json          Convention nodes (id = CONV-*)
  durable/learnings/citation_convention.json  CitationForm nodes (id = name) + CITES patterns
  durable/learnings/speech_acts_taxonomy.json SpeechAct nodes (id = name) + EXHIBITS patterns

PAYLOAD-FREE (BUILD INVARIANT): ingest reads provisions AS STORED and never unmasks. If B1
stored a provision field masked (sensitive run), the graph node carries the placeholder. The
derivable CITES/EXHIBITS regexes run against the stored text, so a placeholder simply does not
match (correct; no attempt to recover raw text). graph.json never contains abs_path (Q7) and
never unmasks content the source store had masked.

Edges (SCHEMA B + C5/C6):
  HAS_PROVISION    Document -> Provision   (provision document_id; stub Document if no filename match)
  GOVERNED_BY      Provision -> Convention (provision convention_ref -> CONV id; N:1 per Q4)
  CROSS_REFERENCES Provision -> Provision  (context_refs -> ref_id; missing targets become stubs, Q3)
  CITES            Provision -> CitationForm (re.search(form.pattern, original_text AS STORED))
  EXHIBITS         Provision -> SpeechAct    (re.search(act.pattern, original_text AS STORED))
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OGE_STORES_DIR = ROOT / "ontology" / "stores"

DEFAULT_SOURCES = {
    "provisions": OGE_STORES_DIR / "provisions.jsonl",
    "document_dates": ROOT / "durable" / "learnings" / "document_dates.json",
    "conventions": ROOT / "config" / "convention_registry.json",
    "citation_forms": ROOT / "durable" / "learnings" / "citation_convention.json",
    "speech_acts": ROOT / "durable" / "learnings" / "speech_acts_taxonomy.json",
}
DEFAULT_GRAPH_PATH = OGE_STORES_DIR / "graph.json"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _load_jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _safe_compile(pattern):
    """Compile a stored regex pattern AS STORED. A malformed pattern yields None (skipped),
    never a crash. No extra flags are added: the pattern's own behavior is honored."""
    if not pattern:
        return None
    try:
        return re.compile(pattern)
    except re.error:
        return None


def _count_by(items, key):
    out = {}
    for it in items:
        k = it.get(key)
        out[k] = out.get(k, 0) + 1
    return out


def build_graph(sources=None, out_path=None):
    """Build the Tier-1 graph from the durable sources and write graph.json. `sources` overrides
    individual source paths (the verify gate passes tempdir fixtures); `out_path` overrides the
    output (the gate writes to a tempdir, never the real ontology/stores/graph.json). Returns the
    graph dict. Safe on empty inputs (produces a valid graph with whatever nodes exist)."""
    src = dict(DEFAULT_SOURCES)
    if sources:
        src.update(sources)

    nodes = {}   # (type, id) -> node dict
    edges = []

    def add_node(ntype, nid, **attrs):
        key = (ntype, nid)
        if key not in nodes:
            nodes[key] = {"type": ntype, "id": nid, **attrs}
        return nodes[key]

    def has(ntype, nid):
        return (ntype, nid) in nodes

    # ----- PHASE 1: materialize all nodes (so edges never dangle) -----

    # Document nodes (id = filename; abs_path deliberately excluded, Q7)
    for d in (_load_json(src["document_dates"], {}).get("documents") or []):
        fn = d.get("filename")
        if not fn:
            continue
        add_node("Document", fn, date=d.get("date"), date_source=d.get("date_source"),
                 date_confidence=d.get("date_confidence"), title=d.get("title"), stub=False)

    # Convention nodes (id = CONV-*)
    for c in (_load_json(src["conventions"], {}).get("conventions") or []):
        cid = c.get("id")
        if not cid:
            continue
        add_node("Convention", cid, category=c.get("category"), rule=c.get("rule"),
                 source_file=c.get("source_file"), source_location=c.get("source_location"),
                 severity=c.get("severity"), action=c.get("action"))

    # CitationForm nodes (id = name) + compiled CITES patterns
    citation_patterns = []
    for r in (_load_json(src["citation_forms"], {}).get("rules") or []):
        nm = r.get("name")
        if not nm:
            continue
        add_node("CitationForm", nm, pattern=r.get("pattern"),
                 sample_count=r.get("sample_count"), examples=r.get("examples", []) or [])
        citation_patterns.append((nm, _safe_compile(r.get("pattern"))))

    # SpeechAct nodes (id = name) + compiled EXHIBITS patterns
    speechact_patterns = []
    for a in (_load_json(src["speech_acts"], {}).get("speech_acts") or []):
        nm = a.get("name")
        if not nm:
            continue
        add_node("SpeechAct", nm, pattern=a.get("pattern"),
                 evidence_count=a.get("evidence_count"), examples=a.get("examples", []) or [])
        speechact_patterns.append((nm, _safe_compile(a.get("pattern"))))

    # Provision nodes (provisions.jsonl, AS STORED; dedup by id, prefer non-stub then latest)
    by_id = {}
    for rec in _load_jsonl(src["provisions"]):
        pid = rec.get("id")
        if not pid:
            continue
        prev = by_id.get(pid)
        if prev is None:
            by_id[pid] = rec
            continue
        prev_stub, rec_stub = bool(prev.get("stub")), bool(rec.get("stub"))
        if prev_stub and not rec_stub:
            by_id[pid] = rec
        elif prev_stub == rec_stub and str(rec.get("captured_at", "")) >= str(prev.get("captured_at", "")):
            by_id[pid] = rec
    for pid, rec in by_id.items():
        if rec.get("stub"):
            add_node("Provision", pid, document_id=rec.get("document_id"),
                     ref_id=rec.get("ref_id"), stub=True, incomplete=True)
        else:
            add_node("Provision", pid, document_id=rec.get("document_id"), ref_id=rec.get("ref_id"),
                     finding_type=rec.get("finding_type"), action=rec.get("action"),
                     severity=rec.get("severity"), convention_ref=rec.get("convention_ref"),
                     context_refs=rec.get("context_refs", []) or [],
                     # text AS STORED (masked or real; ingest never unmasks):
                     original_text=rec.get("original_text"), proposed_text=rec.get("proposed_text"),
                     comment=rec.get("comment"), stub=False)

    # Stub Provisions for referenced-only REFs (Q3): any context_ref target not materialized
    for n in [v for (t, _), v in nodes.items() if t == "Provision" and not v.get("stub")]:
        did = n.get("document_id")
        for ref in (n.get("context_refs") or []):
            tgt = f"{did}::{ref}"
            if not has("Provision", tgt):
                add_node("Provision", tgt, document_id=did, ref_id=ref, stub=True, incomplete=True)

    # Stub Documents for provision document_ids with no document_dates filename match
    for n in [v for (t, _), v in nodes.items() if t == "Provision"]:
        did = n.get("document_id")
        if did and not has("Document", did):
            add_node("Document", did, stub=True, incomplete=True,
                     note="materialized from provision document_id (no document_dates filename match)")

    # ----- PHASE 2: build edges over the complete node set -----
    provisions = [v for (t, _), v in nodes.items() if t == "Provision"]

    for n in provisions:
        did = n.get("document_id")
        if did and has("Document", did):
            edges.append({"type": "HAS_PROVISION", "source_type": "Document", "source": did,
                          "target_type": "Provision", "target": n["id"]})

    stats = {"unmatched_convention_refs": 0}
    for n in provisions:
        if n.get("stub"):
            continue
        cref = n.get("convention_ref")
        if not cref:
            continue
        if has("Convention", cref):
            edges.append({"type": "GOVERNED_BY", "source_type": "Provision", "source": n["id"],
                          "target_type": "Convention", "target": cref})
        else:
            stats["unmatched_convention_refs"] += 1

    for n in provisions:
        if n.get("stub"):
            continue
        did = n.get("document_id")
        for ref in (n.get("context_refs") or []):
            tgt = f"{did}::{ref}"
            edges.append({"type": "CROSS_REFERENCES", "source_type": "Provision", "source": n["id"],
                          "target_type": "Provision", "target": tgt})

    # Derivable CITES (C5) + EXHIBITS (C6): regex over original_text AS STORED.
    for n in provisions:
        if n.get("stub"):
            continue
        text = n.get("original_text") or ""
        if not text:
            continue
        for form_name, rx in citation_patterns:
            if rx is not None and rx.search(text):
                edges.append({"type": "CITES", "source_type": "Provision", "source": n["id"],
                              "target_type": "CitationForm", "target": form_name})
        for act_name, rx in speechact_patterns:
            if rx is not None and rx.search(text):
                edges.append({"type": "EXHIBITS", "source_type": "Provision", "source": n["id"],
                              "target_type": "SpeechAct", "target": act_name})

    node_list = list(nodes.values())
    graph = {
        "schema": "oge_graph/v1",
        "tier": 1,
        "generated_at": _now(),
        "nodes": node_list,
        "edges": edges,
        "stats": {
            "nodes_total": len(node_list),
            "nodes_by_type": _count_by(node_list, "type"),
            "edges_total": len(edges),
            "edges_by_type": _count_by(edges, "type"),
            "stub_provisions": sum(1 for n in node_list if n["type"] == "Provision" and n.get("stub")),
            "stub_documents": sum(1 for n in node_list if n["type"] == "Document" and n.get("stub")),
            **stats,
        },
    }

    target = Path(out_path) if out_path else DEFAULT_GRAPH_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    return graph


if __name__ == "__main__":
    g = build_graph()
    s = g["stats"]
    print(f"OGE Tier-1 graph: {s['nodes_total']} nodes {s['nodes_by_type']}, "
          f"{s['edges_total']} edges {s['edges_by_type']} -> {DEFAULT_GRAPH_PATH}")
