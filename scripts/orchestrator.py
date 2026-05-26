"""Top Orchestrator (pure Python — no LLM call).

Boot, deliberation, charter lifecycle (propose / form / amend / dissolve),
BLOCK gate, asyncio parallel execution, operator escalation, run summary,
DELTA proposal escalation. Hooks adaptive_spawn at first-run BOOT.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from agent_wrapper import AgentWrapper, load_api_keys, project_root
from block_gate import BlockGate, BlockHandle
from bus_reader import BACKEND_BUDGETS, assemble_context
from constitution import Constitution, MatchResult
from cost_tracker import CostTracker
from message_bus import MessageBus


CHARTER_AUTO_APPROVE = 0.80
CHARTER_OPERATOR_REVIEW = 0.50


@dataclass
class OperatorDecision:
    decision: str
    rationale: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class TaskForce:
    id: str
    charter: dict
    supervisor: str
    channel: str
    members: list
    state: str = "ACTIVE"
    matched_law_id: str | None = None
    formed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    dissolved_at: str | None = None
    completion_report: dict | None = None

    def as_dict(self):
        return {"id": self.id, "charter": self.charter, "supervisor": self.supervisor,
                "channel": self.channel, "members": self.members, "state": self.state,
                "matched_law_id": self.matched_law_id, "formed_at": self.formed_at,
                "dissolved_at": self.dissolved_at, "completion_report": self.completion_report}


@dataclass
class TopOrchestrator:
    root: Path
    constitution: Constitution
    bus: MessageBus
    registry: dict
    contracts: dict
    run_objectives: str = ""
    operator_handler: Any = None
    interactive: bool = True
    task_forces: dict = field(default_factory=dict)
    block_gate: BlockGate = field(default_factory=BlockGate)
    cost_tracker: CostTracker | None = None
    _tf_seq: int = 0

    @classmethod
    def boot(cls, root=None, *, interactive=True, operator_handler=None,
             cost_tracker=None, run_adaptive_spawn=True):
        root = root or project_root()
        constitution = Constitution.load(root / "config" / "constitution.json")
        bus = MessageBus.open(root / "output" / "logs" / "agent_bus.jsonl")
        with (root / "config" / "agent_registry.json").open("r", encoding="utf-8") as fh:
            registry = json.load(fh).get("agents", {})
        with (root / "config" / "agent_contracts.json").open("r", encoding="utf-8") as fh:
            contracts = json.load(fh).get("contracts", {})
        orch = cls(root=root, constitution=constitution, bus=bus, registry=registry,
                   contracts=contracts, interactive=interactive, operator_handler=operator_handler,
                   cost_tracker=cost_tracker)
        orch._post_orchestrator(
            recipient="BROADCAST", channel="main", msg_type="INFORM",
            body={"event": "BOOT", "constitution_layers": {
                "seed_laws": len(constitution.seed_laws()),
                "task_force_laws": len(constitution.task_force_laws()),
                "precedents": len(constitution.precedents()),
                "amendments": len(constitution.amendments())},
                "agents_registered": sorted(registry.keys())},
            constitution_check={"laws_consulted": ["LAW-0", "LAW-V"], "result": "RESOLVED",
                                "resolution": "boot logs initial state per LAW-V"})
        if run_adaptive_spawn and _is_first_run(root):
            orch._run_adaptive_spawn_at_boot()
        return orch

    def _run_adaptive_spawn_at_boot(self):
        try:
            from adaptive_spawn import spawn_all
            report = spawn_all(self.root, overwrite=False)
        except Exception as e:
            self._post_orchestrator(recipient="BROADCAST", channel="main", msg_type="INFORM",
                                    body={"event": "ADAPTIVE_SPAWN_ERROR", "error": f"{type(e).__name__}: {e}"},
                                    constitution_check={"laws_consulted": ["LAW-V"], "result": "RESOLVED",
                                                        "resolution": "spawn raised; pipeline continues"})
            return
        self._post_orchestrator(recipient="BROADCAST", channel="main", msg_type="INFORM",
                                body={"event": "ADAPTIVE_SPAWN_COMPLETED", "summary": report.as_dict()},
                                constitution_check={"laws_consulted": ["LAW-V", "LAW-VI"], "result": "RESOLVED",
                                                    "resolution": "first-run bootstrap"})

    def list_input_documents(self):
        """Returns documents under input/operational/ (Part XVIII).
        Falls back to flat input/ for backward compatibility tests."""
        operational = self.root / "input" / "operational"
        if operational.exists():
            files = sorted(p for p in operational.iterdir() if p.is_file())
            if files: return files
        in_dir = self.root / "input"
        if in_dir.exists():
            return sorted(p for p in in_dir.iterdir() if p.is_file())
        return []

    def deliberation_round(self, work_payload, *, channel="main"):
        keys = load_api_keys()
        wrappers = {}
        for name in self.registry:
            wrapper = AgentWrapper(name=name, constitution=self.constitution, bus=self.bus,
                                   registry=self.registry, contracts=self.contracts,
                                   keys=keys, cost_tracker=self.cost_tracker)
            wrappers[name] = wrapper
            situation = {"agent": name, "action": "self_assess",
                         "tags": ["situation_assessment", wrapper.spec.get("category", "")]}
            check = wrapper.check_constitution(situation)
            self._post_orchestrator(
                recipient=name, channel=channel, msg_type="REQUEST",
                body={"ask": "self_assess", "work_summary": _summarize_payload(work_payload)},
                constitution_check={"laws_consulted": ["LAW-V", "LAW-VI"],
                                    "result": check.layer or "UNRESOLVED",
                                    "resolution": ("no governing rule yet — open"
                                                   if not check.resolved
                                                   else f"governed by {check.rule_id}")})
        return wrappers

    def evaluate_charter(self, charter):
        details = {"law_vi_check": True, "law_ii_check": True}
        if not charter.get("members") or not charter.get("mission"):
            details["law_vi_check"] = False
            details["law_vi_reason"] = "charter must have members and mission"
            self._post_orchestrator(recipient=charter.get("proposed_by", "BROADCAST"), channel="main",
                                    msg_type="CHARTER_DENY", body={"charter": charter, "details": details},
                                    constitution_check={"laws_consulted": ["LAW-VI"], "result": "RESOLVED",
                                                        "resolution": "law VI requires well-formed charters"})
            return ("DENY", MatchResult(confidence=0.0), details)
        for m in charter.get("members", []):
            if m.get("agent") not in self.registry:
                details["law_ii_check"] = False
                details["law_ii_reason"] = f"unknown agent {m.get('agent')!r}"
                self._post_orchestrator(recipient=charter.get("proposed_by", "BROADCAST"), channel="main",
                                        msg_type="CHARTER_DENY", body={"charter": charter, "details": details},
                                        constitution_check={"laws_consulted": ["LAW-II"], "result": "RESOLVED",
                                                            "resolution": "law II forbids unknown agents"})
                return ("DENY", MatchResult(confidence=0.0), details)
        match = self.constitution.match_tf_law(charter)
        if match.confidence >= CHARTER_AUTO_APPROVE:
            decision = "AUTO_APPROVE"; self.constitution.increment_tf_law_reuse(match.law["id"])
        elif match.confidence >= CHARTER_OPERATOR_REVIEW:
            decision = "APPROVE_WITH_REVIEW"
        else:
            decision = "ESCALATE"
        details["match"] = match.as_dict()
        if decision in ("AUTO_APPROVE", "APPROVE_WITH_REVIEW"):
            self._post_orchestrator(recipient="BROADCAST", channel="main", msg_type="CHARTER_APPROVE",
                                    body={"charter": charter, "details": details, "decision": decision},
                                    constitution_check={"laws_consulted": ["LAW-VI", match.law["id"] if match.law else "n/a"],
                                                        "result": "RESOLVED",
                                                        "resolution": f"matched TF-law {match.law['id']} at {match.confidence}"
                                                        if match.law else "approved with operator review"})
            return (decision, match, details)
        op_decision = self.escalate_to_operator(topic="charter_silent_in_constitution",
                                                payload={"charter": charter, "match": match.as_dict()},
                                                laws_consulted=["LAW-VI"])
        approved = op_decision.decision.strip().upper() in {"APPROVE", "APPROVED", "OK", "YES", "FORM"}
        details["operator_decision"] = {"decision": op_decision.decision, "rationale": op_decision.rationale, "approved": approved}
        if approved:
            self._post_orchestrator(recipient="BROADCAST", channel="main", msg_type="CHARTER_APPROVE",
                                    body={"charter": charter, "details": details, "decision": "APPROVED_BY_OPERATOR"},
                                    constitution_check={"laws_consulted": ["LAW-0", "LAW-VI"], "result": "RESOLVED",
                                                        "resolution": "operator approval recorded"})
            return ("APPROVED_BY_OPERATOR", match, details)
        self._post_orchestrator(recipient=charter.get("proposed_by", "BROADCAST"), channel="main",
                                msg_type="CHARTER_DENY",
                                body={"charter": charter, "details": details, "decision": "DENIED_BY_OPERATOR"},
                                constitution_check={"laws_consulted": ["LAW-0", "LAW-VI"], "result": "RESOLVED",
                                                    "resolution": f"operator declined ({op_decision.decision!r})"})
        return ("DENIED_BY_OPERATOR", match, details)

    def propose_charter(self, charter, *, auto_form=True):
        charter = dict(charter)
        charter.setdefault("id", self._next_tf_id())
        proposer = charter.get("proposed_by")
        self._post_orchestrator(recipient="BROADCAST", channel="main", msg_type="CHARTER_PROPOSE",
                                body={"charter": charter},
                                constitution_check={"laws_consulted": ["LAW-VI"], "result": "RESOLVED",
                                                    "resolution": "charter posted for confirmation"})
        named = [m.get("agent") for m in charter.get("members", []) if m.get("agent")]
        confirmations = set(charter.get("confirmations") or [])
        if proposer: confirmations.add(proposer)
        missing = [a for a in named if a not in confirmations]
        if missing:
            self._post_orchestrator(recipient=proposer or "BROADCAST", channel="main", msg_type="CHARTER_DENY",
                                    body={"charter": charter, "reason": "missing CONFIRM", "missing": missing},
                                    constitution_check={"laws_consulted": ["LAW-VI"], "result": "RESOLVED",
                                                        "resolution": "task force requires opt-in"})
            return ("DENY", MatchResult(confidence=0.0), None)
        decision, match, _ = self.evaluate_charter(charter)
        forming = {"AUTO_APPROVE", "APPROVE_WITH_REVIEW", "APPROVED_BY_OPERATOR"}
        if decision not in forming or not auto_form:
            return (decision, match, None)
        tf = self.form_task_force(charter, decision=decision, match=match)
        return (decision, match, tf)

    def form_task_force(self, charter, *, decision, match):
        tf_id = charter.get("id") or self._next_tf_id()
        supervisor = charter.get("supervisor") or _pick_supervisor(charter, self.registry)
        members = [m.get("agent") for m in charter.get("members", []) if m.get("agent")]
        channel = f"tf_{tf_id}"
        tf = TaskForce(id=tf_id, charter=charter, supervisor=supervisor, channel=channel,
                       members=members, matched_law_id=(match.law or {}).get("id") if match else None)
        self.task_forces[tf_id] = tf
        self._post_orchestrator(recipient="BROADCAST", channel="main", msg_type="CONFIRM",
                                body={"event": "TASK_FORCE_FORMED", "task_force": tf.as_dict(), "decision": decision},
                                constitution_check={"laws_consulted": ["LAW-VI"], "result": "RESOLVED",
                                                    "resolution": f"formed on scoped channel {channel}"})
        self._post_orchestrator(recipient=supervisor, channel=channel, msg_type="INFORM",
                                body={"event": "SUPERVISOR_APPOINTED", "task_force_id": tf_id, "members": members},
                                constitution_check={"laws_consulted": ["LAW-VI"], "result": "RESOLVED",
                                                    "resolution": "supervisor coordinates scoped channel"})
        return tf

    def dissolve_task_force(self, tf_id, *, completion_report, learnings=None):
        tf = self.task_forces.get(tf_id)
        if tf is None: raise KeyError(f"unknown task force {tf_id!r}")
        tf.state = "DISSOLVED"; tf.completion_report = completion_report
        tf.dissolved_at = datetime.now(timezone.utc).isoformat()
        law = self.constitution.add_tf_law(tf.charter, learnings or {})
        self._post_orchestrator(recipient="BROADCAST", channel=tf.channel, msg_type="DISSOLVE",
                                body={"task_force_id": tf_id, "completion_report": completion_report,
                                      "codified_law_id": law.get("id")},
                                constitution_check={"laws_consulted": ["LAW-VI"], "result": "RESOLVED",
                                                    "resolution": "no structure persists past purpose"})
        self._post_orchestrator(recipient="BROADCAST", channel="main", msg_type="LAW_CREATED",
                                body={"law_id": law.get("id"), "source_task_force": tf_id,
                                      "mission": tf.charter.get("mission"), "members": tf.members,
                                      "learnings": learnings or {}},
                                constitution_check={"laws_consulted": ["LAW-VI"], "result": "RESOLVED",
                                                    "resolution": "codified as TF-law"})
        return law

    def amend_charter(self, tf_id, *, amendment, proposed_by):
        tf = self.task_forces.get(tf_id)
        if tf is None: raise KeyError(f"unknown task force {tf_id!r}")
        if tf.state != "ACTIVE": raise ValueError(f"task force {tf_id} not active")
        candidate = dict(tf.charter)
        candidate.update({k: v for k, v in amendment.items() if k not in {"id", "proposed_by"}})
        candidate["amended_from"] = tf.charter.get("id"); candidate["amended_by"] = proposed_by
        candidate["amended_at"] = datetime.now(timezone.utc).isoformat()
        self._post_orchestrator(recipient="BROADCAST", channel=tf.channel, msg_type="CHARTER_PROPOSE",
                                body={"kind": "AMENDMENT", "task_force_id": tf_id,
                                      "from": tf.charter, "to": candidate, "proposed_by": proposed_by},
                                constitution_check={"laws_consulted": ["LAW-VI"], "result": "RESOLVED",
                                                    "resolution": "amendments follow charter flow"})
        decision, _match, _details = self.evaluate_charter(candidate)
        if decision not in {"AUTO_APPROVE", "APPROVE_WITH_REVIEW", "APPROVED_BY_OPERATOR"}:
            return (decision, tf.charter)
        tf.charter = candidate
        self._post_orchestrator(recipient="BROADCAST", channel=tf.channel, msg_type="CONFIRM",
                                body={"event": "CHARTER_AMENDED", "task_force_id": tf_id,
                                      "decision": decision, "charter": candidate},
                                constitution_check={"laws_consulted": ["LAW-VI"], "result": "RESOLVED",
                                                    "resolution": "amendment merged"})
        return (decision, candidate)

    def raise_block(self, *, raised_by, channel, reason, agent=None):
        handle = self.block_gate.raise_block(raised_by=raised_by, channel=channel, reason=reason, agent=agent)
        self._post_orchestrator(recipient="BROADCAST", channel=channel, msg_type="BLOCK",
                                body={"block_id": handle.id, "raised_by": raised_by, "agent": agent, "reason": reason},
                                constitution_check={"laws_consulted": ["LAW-V", "LAW-VI"], "result": "RESOLVED",
                                                    "resolution": "stop and consult"})
        return handle

    def release_block(self, block_id, *, reason):
        handle = self.block_gate.release(block_id, reason=reason)
        if handle is None: return None
        self._post_orchestrator(recipient="BROADCAST", channel=handle.channel, msg_type="CONFIRM",
                                body={"event": "BLOCK_RELEASED", "block_id": handle.id,
                                      "raised_by": handle.raised_by, "agent": handle.agent,
                                      "release_reason": reason},
                                constitution_check={"laws_consulted": ["LAW-V"], "result": "RESOLVED",
                                                    "resolution": "block lifted"})
        return handle

    async def execute_parallel(self, groups, *, group_channels=None, timeout_per_group=None):
        if group_channels is None: group_channels = ["main"] * len(groups)
        if len(group_channels) != len(groups):
            raise ValueError("group_channels length must match groups length")
        async def run_one(item):
            try:
                if asyncio.iscoroutine(item): return await item
                if asyncio.iscoroutinefunction(item): return await item()
                if callable(item): return await asyncio.to_thread(item)
                return item
            except Exception as e: return e
        async def run_group(group, channel):
            await self.block_gate.wait_clear_async(channel=channel, timeout=timeout_per_group)
            return await asyncio.gather(*(run_one(it) for it in group))
        return await asyncio.gather(*(run_group(g, ch) for g, ch in zip(groups, group_channels)))

    def execute_parallel_sync(self, groups, *, group_channels=None, timeout_per_group=None):
        return asyncio.run(self.execute_parallel(groups, group_channels=group_channels,
                                                 timeout_per_group=timeout_per_group))

    def _next_tf_id(self):
        self._tf_seq += 1
        return f"TF-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{self._tf_seq:03d}"

    def escalate_to_operator(self, *, topic, payload, laws_consulted):
        self._post_orchestrator(recipient="OPERATOR", channel="escalation", msg_type="ESCALATE",
                                body={"topic": topic, "payload": payload},
                                constitution_check={"laws_consulted": laws_consulted, "result": "UNRESOLVED",
                                                    "resolution": "operator must decide"})
        decision = self._collect_operator_decision(topic, payload)
        self._post_operator(recipient="BROADCAST", channel="escalation", type="LAW_CREATED",
                            body={"topic": topic, "decision": decision.decision, "rationale": decision.rationale},
                            constitution_check={"laws_consulted": ["LAW-0"], "result": "RESOLVED",
                                                "resolution": "operator decision recorded"})
        return decision

    def escalate_delta_proposals(self, delta_proposals):
        results = []
        for proposal in delta_proposals:
            decision = self.escalate_to_operator(topic=f"delta_proposal:{proposal.get('kind')}",
                                                 payload={"proposal": proposal}, laws_consulted=["LAW-0", "LAW-VI"])
            verdict = decision.decision.strip().upper()
            approved = verdict in {"APPROVE", "APPROVED", "OK", "YES", "ENACT"}
            entry = {"delta_id": proposal.get("id"), "kind": proposal.get("kind"),
                     "decision": decision.decision, "rationale": decision.rationale, "approved": approved}
            if approved:
                self.constitution.add_amendment({
                    "title": f"Operator-approved DELTA {proposal.get('id')}",
                    "text": proposal.get("proposed_change", {}).get("reason", ""),
                    "source_delta": proposal, "operator_rationale": decision.rationale,
                })
            results.append(entry)
        return results

    def _collect_operator_decision(self, topic, payload):
        if self.operator_handler is not None: return self.operator_handler(topic, payload)
        if not self.interactive:
            return OperatorDecision(decision="DEFERRED", rationale="non-interactive run")
        print(f"\n=== OPERATOR ESCALATION: {topic} ===", file=sys.stderr)
        print(json.dumps(payload, indent=2, ensure_ascii=False), file=sys.stderr)
        try:
            decision = input("Decision (text, or blank for DEFERRED): ").strip()
            rationale = input("Rationale: ").strip()
        except EOFError:
            decision, rationale = "DEFERRED", "no operator input available"
        return OperatorDecision(decision=decision or "DEFERRED", rationale=rationale or "")

    def run_summary(self):
        summary = self.bus.summarize()
        summary["constitution"] = {
            "seed_laws": len(self.constitution.seed_laws()),
            "task_force_laws": len(self.constitution.task_force_laws()),
            "precedents": len(self.constitution.precedents()),
            "amendments": len(self.constitution.amendments()),
        }
        summary["input_documents"] = [p.name for p in self.list_input_documents()]
        summary["task_forces"] = [tf.as_dict() for tf in self.task_forces.values()]
        summary["escalations"] = [
            {"timestamp": m.get("timestamp"), "topic": (m.get("body") or {}).get("topic"),
             "channel": m.get("channel")} for m in self.bus.query(msg_type="ESCALATE")
        ]
        summary["blocks"] = [b.as_dict() for b in self.block_gate.blocks.values()]
        mem = self._collect_memory_stats()
        if mem is not None: summary["memory"] = mem
        out_path = (self.root / "output" / "logs"
                    / f"run_summary_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md")
        out_path.write_text(_format_summary_md(summary), encoding="utf-8")
        self._post_orchestrator(recipient="OPERATOR", channel="main", msg_type="INFORM",
                                body={"event": "RUN_SUMMARY", "path": str(out_path),
                                      "summary_keys": sorted(summary.keys())},
                                constitution_check={"laws_consulted": ["LAW-0"], "result": "RESOLVED",
                                                    "resolution": "summary delivered to operator"})
        return summary

    def _collect_memory_stats(self):
        try:
            from memory import VerificationMemory
            return VerificationMemory.open(self.root).stats()
        except Exception:
            return None

    def _post_orchestrator(self, *, recipient, channel, msg_type, body, constitution_check):
        return self.bus.post({"timestamp": datetime.now(timezone.utc).isoformat(),
                              "sender": "ORCHESTRATOR", "sender_role": "orchestrator",
                              "recipient": recipient, "channel": channel, "type": msg_type,
                              "body": body, "constitution_check": constitution_check})

    def _post_operator(self, **kwargs):
        return self.bus.post({"timestamp": datetime.now(timezone.utc).isoformat(),
                              "sender": "OPERATOR", "sender_role": "operator", **kwargs})


def _is_first_run(root):
    sentinels = [root / "reference" / "LINGUISTIC_IDENTITY.md",
                 root / "config" / "institution_registry.json",
                 root / "config" / "speech_acts_taxonomy.json"]
    return any(not p.exists() for p in sentinels)


def _pick_supervisor(charter, registry):
    members = [m.get("agent") for m in charter.get("members", []) if m.get("agent")]
    if not members: raise ValueError("charter has no members")
    mission_tokens = {t for t in (charter.get("mission") or "").lower().split() if len(t) > 3}
    best, best_score = members[0], -1
    for name in members:
        does_text = " ".join(registry.get(name, {}).get("does", [])).lower()
        overlap = sum(1 for tok in mission_tokens if tok in does_text)
        if overlap > best_score:
            best_score = overlap; best = name
    return best


def _summarize_payload(p):
    if isinstance(p, str): return p[:200]
    if isinstance(p, dict): return f"dict with keys {sorted(p.keys())}"
    if isinstance(p, list): return f"list of {len(p)} items"
    return str(p)[:200]


def _format_summary_md(s):
    lines = ["# Run summary", "", f"- generated: {datetime.now(timezone.utc).isoformat()}",
             f"- total messages: {s.get('total', 0)}",
             f"- first message: {s.get('first_timestamp')}",
             f"- last message: {s.get('last_timestamp')}", ""]
    lines.append("## Constitution layers")
    for k, v in (s.get("constitution") or {}).items(): lines.append(f"- {k}: {v}")
    lines.append("\n## Input documents")
    for d in s.get("input_documents", []): lines.append(f"- {d}")
    lines.append("\n## Task forces")
    tfs = s.get("task_forces") or []
    if not tfs: lines.append("_none formed this run_")
    else:
        for tf in tfs:
            lines.append(f"- {tf['id']} [{tf['state']}] supervisor={tf['supervisor']} "
                         f"members={tf['members']} channel={tf['channel']}")
    lines.append("\n## Escalations")
    escs = s.get("escalations") or []
    if not escs: lines.append("_no escalations this run_")
    else:
        for e in escs:
            lines.append(f"- [{e['timestamp']}] topic={e['topic']!r} channel={e['channel']}")
    lines.append("\n## BLOCK events")
    blocks = s.get("blocks") or []
    if not blocks: lines.append("_no BLOCK events this run_")
    else:
        for b in blocks:
            status = "released" if b.get("released") else "active"
            lines.append(f"- {b['id']} [{status}] raised_by={b['raised_by']} channel={b['channel']} "
                         f"agent={b.get('agent')} reason={b['reason']!r}")
    if "memory" in s:
        lines.append("\n## Verification memory")
        m = s["memory"]
        lines.append(f"- tier 1 entries: {m.get('tier1', 0)}")
        lines.append(f"- tier 2 entries: {m.get('tier2', 0)}")
        lines.append(f"- tier 3 entries: {m.get('tier3', 0)}")
    lines.append("\n## Messages by type")
    for k, v in sorted((s.get("by_type") or {}).items()): lines.append(f"- {k}: {v}")
    lines.append("\n## Messages by sender")
    for k, v in sorted((s.get("by_sender") or {}).items()): lines.append(f"- {k}: {v}")
    lines.append("\n## Messages by channel")
    for k, v in sorted((s.get("by_channel") or {}).items()): lines.append(f"- {k}: {v}")
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description="Project Shimmer Top Orchestrator")
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    orch = TopOrchestrator.boot(interactive=not args.non_interactive)
    docs = orch.list_input_documents()
    print(f"[shimmer] {len(docs)} input document(s) detected")
    if args.dry_run or not docs:
        summary = orch.run_summary()
        print(f"[shimmer] summary written: {summary.get('total', 0)} bus messages")
        return 0
    orch.deliberation_round({"document_names": [d.name for d in docs],
                             "document_count": len(docs), "phase": "situation_assessment"})
    summary = orch.run_summary()
    print(f"[shimmer] summary written: {summary.get('total', 0)} bus messages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
