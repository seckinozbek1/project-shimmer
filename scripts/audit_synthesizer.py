"""Audit synthesis + DELTA proposal logic (genesis Part X)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from message_bus import MessageBus


@dataclass
class DeltaProposal:
    id: str
    kind: str
    trigger: str
    evidence: dict
    proposed_change: dict
    requires_operator_approval: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self): return self.__dict__


@dataclass
class AuditFinding:
    category: str
    severity: str
    summary: str
    evidence: dict


@dataclass
class AuditSynthesizer:
    project_root: Path
    bus: MessageBus

    def synthesize(self, *, write_outputs=True, verifier_findings=None,
                   fact_check_findings=None, practice_findings=None):
        bus_messages = self.bus.read_all()
        findings, deltas = [], []
        seq = [1]
        def next_id():
            s = seq[0]; seq[0] += 1
            return f"DELTA-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{s:03d}"

        disputed_by_source = _count_disputed_by_source(fact_check_findings or [])
        for source, n in disputed_by_source.items():
            if n >= 3:
                findings.append(AuditFinding("claim_verification", "medium",
                                             f"source {source!r} produced {n} DISPUTED",
                                             {"source": source, "count": n}))
                deltas.append(DeltaProposal(id=next_id(), kind="reduce_ttl",
                                            trigger=f"{n} disputed from {source}",
                                            evidence={"source": source, "disputed_count": n},
                                            proposed_change={"target": "memory.TTL_DAYS",
                                                             "action": "reduce_for_source",
                                                             "scope": source, "factor": 0.5,
                                                             "reason": "high dispute rate"}))

        anti = [f for f in (practice_findings or []) if f.get("verdict") in ("ANTI_PATTERN", "VIOLATION")]
        groups = {}
        for f in anti:
            key = (f.get("recommendation") or f.get("procedure_text") or "")[:80]
            groups.setdefault(key, []).append(f)
        for pattern, instances in groups.items():
            if len(instances) >= 2:
                findings.append(AuditFinding("practice", "medium",
                                             f"repeated anti-pattern: {pattern[:60]!r} ({len(instances)})",
                                             {"pattern": pattern, "count": len(instances)}))
                deltas.append(DeltaProposal(id=next_id(), kind="append_project_rule",
                                            trigger=f"anti-pattern recurred {len(instances)} times",
                                            evidence={"pattern": pattern, "instances": instances[:5]},
                                            proposed_change={"target": "prompts/project_rules.md",
                                                             "action": "append_rule",
                                                             "rule_text": f"AVOID: {pattern}",
                                                             "reason": "repeated PRACTICE_AUDITOR verdict"}))

        escalations = [m for m in bus_messages if m.get("type") == "ESCALATE"]
        topic_counts = {}
        for m in escalations:
            topic = (m.get("body") or {}).get("topic", "unknown")
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
        for topic, count in topic_counts.items():
            if count >= 3:
                findings.append(AuditFinding("governance", "high",
                                             f"escalation topic {topic!r} recurred {count} times",
                                             {"topic": topic, "count": count}))
                deltas.append(DeltaProposal(id=next_id(), kind="propose_amendment",
                                            trigger=f"repeated escalation: {topic}",
                                            evidence={"topic": topic, "count": count},
                                            proposed_change={"target": "config/constitution.json#amendments",
                                                             "action": "add_amendment", "topic": topic,
                                                             "draft_text": (f"Codify default ruling for "
                                                                            f"recurring escalations on {topic!r}."),
                                                             "reason": f"operator interrupted {count} times"}))

        charter_proposals = [m for m in bus_messages if m.get("type") == "CHARTER_PROPOSE"]
        mission_counts = {}
        for m in charter_proposals:
            mission = ((m.get("body") or {}).get("charter") or {}).get("mission", "")
            mission_counts[mission] = mission_counts.get(mission, 0) + 1
        for mission, count in mission_counts.items():
            if count >= 2 and mission:
                findings.append(AuditFinding("governance", "low",
                                             f"charter pattern proposed {count} times: {mission[:60]!r}",
                                             {"mission": mission, "count": count}))
                deltas.append(DeltaProposal(id=next_id(), kind="codify_tf_law",
                                            trigger=f"charter repeated {count} times",
                                            evidence={"mission": mission, "count": count},
                                            proposed_change={"target": "constitution.task_force_laws",
                                                             "action": "codify_pattern", "mission": mission,
                                                             "reason": "pattern has reuse value"}))

        if verifier_findings:
            high_omissions = [f for f in verifier_findings
                              if f.get("finding") == "OMISSION" and f.get("severity") == "high"]
            if len(high_omissions) >= 2:
                findings.append(AuditFinding("content", "high",
                                             f"{len(high_omissions)} high-severity OMISSIONs",
                                             {"count": len(high_omissions)}))
                deltas.append(DeltaProposal(id=next_id(), kind="tighten_processor_prompt",
                                            trigger=f"{len(high_omissions)} high omissions",
                                            evidence={"count": len(high_omissions)},
                                            proposed_change={"target": "PROCESSOR draft prompt",
                                                             "action": "add_completeness_check",
                                                             "reason": "repeated source omissions"}))

        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "bus_messages": len(bus_messages),
            "findings": [f.__dict__ for f in findings],
            "delta_proposals": [d.as_dict() for d in deltas],
            "stats": {
                "verifier_findings": len(verifier_findings or []),
                "fact_check_findings": len(fact_check_findings or []),
                "practice_findings": len(practice_findings or []),
                "escalations": len(escalations), "charter_proposals": len(charter_proposals),
            },
        }
        if write_outputs: self._write_outputs(summary)
        return summary

    def _write_outputs(self, summary):
        audit_dir = self.project_root / "output" / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        (audit_dir / "audit_synthesis.md").write_text(_render_md(summary), encoding="utf-8")
        (audit_dir / "delta_proposals.json").write_text(
            json.dumps({"generated_at": summary["generated_at"], "proposals": summary["delta_proposals"]},
                       indent=2, ensure_ascii=False), encoding="utf-8")


def _count_disputed_by_source(findings):
    from urllib.parse import urlparse
    out = {}
    for f in findings:
        if f.get("verdict") != "DISPUTED": continue
        src = f.get("source_url") or f.get("evidence", "")
        host = ""
        if src:
            try: host = urlparse(src).netloc.lower()
            except ValueError: host = ""
        out[host or "unknown"] = out.get(host or "unknown", 0) + 1
    return out


def _render_md(summary):
    lines = ["# Audit synthesis", "", f"- generated: {summary['generated_at']}",
             f"- bus messages: {summary['bus_messages']}",
             f"- findings: {len(summary['findings'])}",
             f"- DELTA proposals: {len(summary['delta_proposals'])}", "", "## Findings"]
    if not summary["findings"]: lines.append("_no findings this run_")
    else:
        for f in summary["findings"]:
            lines.append(f"- [{f['severity'].upper()}] ({f['category']}) {f['summary']}")
    lines.append("\n## DELTA proposals")
    if not summary["delta_proposals"]: lines.append("_no DELTAs proposed this run_")
    else:
        for d in summary["delta_proposals"]:
            lines.append(f"### {d['id']} — {d['kind']}")
            lines.append(f"- trigger: {d['trigger']}")
            lines.append(f"- proposed change: {d['proposed_change'].get('action')}")
            lines.append(f"- target: {d['proposed_change'].get('target')}")
            lines.append(f"- requires operator approval: {d['requires_operator_approval']}\n")
    return "\n".join(lines)
