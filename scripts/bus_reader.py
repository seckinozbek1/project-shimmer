"""Context package assembly per genesis Part VI.

Builds a curated context package for an agent call:
  governance + objectives + precedents + charter + recent_bus + summary + payload
Token budgets per backend; Qwen restricted to LAW-II + LAW-IV with no bus history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from constitution import Constitution
from message_bus import MessageBus


BACKEND_BUDGETS = {
    "claude_api": {"governance": 3000, "bus": 2000, "work": 8000},
    "openai_api": {"governance": 2000, "bus": 1500, "work": 6000},
    "qwen_local": {"governance": 200, "bus": 0, "work": 6000},
}
QWEN_ALLOWED_LAW_IDS = {"LAW-II", "LAW-IV"}
CHARS_PER_TOKEN = 4


def _estimate_tokens(text): return max(1, len(text) // CHARS_PER_TOKEN)


def _truncate_by_tokens(text, max_tokens):
    max_chars = max_tokens * CHARS_PER_TOKEN
    return text if len(text) <= max_chars else text[:max_chars] + "\n... [truncated]"


@dataclass
class ContextPackage:
    backend: str
    governance_text: str
    objectives_text: str
    precedents_text: str
    charter_text: str
    recent_bus_text: str
    rolling_summary_text: str
    work_payload: Any
    convention_text: str = ""
    reference_index_text: str = ""

    def token_estimate(self):
        return {
            "governance": _estimate_tokens(self.governance_text),
            "objectives": _estimate_tokens(self.objectives_text),
            "precedents": _estimate_tokens(self.precedents_text),
            "charter": _estimate_tokens(self.charter_text),
            "recent_bus": _estimate_tokens(self.recent_bus_text),
            "rolling_summary": _estimate_tokens(self.rolling_summary_text),
            "conventions": _estimate_tokens(self.convention_text),
            "references": _estimate_tokens(self.reference_index_text),
        }

    def as_prompt_sections(self):
        s = []
        if self.governance_text: s.append(("CONSTITUTION", self.governance_text))
        if self.objectives_text: s.append(("RUN_OBJECTIVES", self.objectives_text))
        if self.precedents_text: s.append(("PRECEDENTS", self.precedents_text))
        if self.charter_text: s.append(("TASK_FORCE_CHARTER", self.charter_text))
        if self.convention_text: s.append(("CONVENTION_REGISTRY", self.convention_text))
        if self.reference_index_text: s.append(("REFERENCE_INDEX", self.reference_index_text))
        if self.rolling_summary_text: s.append(("OLDER_BUS_SUMMARY", self.rolling_summary_text))
        if self.recent_bus_text: s.append(("RECENT_BUS", self.recent_bus_text))
        s.append(("WORK_PAYLOAD", _stringify(self.work_payload)))
        return s

    def as_text(self):
        return "\n\n".join(f"=== {h} ===\n{b}" for h, b in self.as_prompt_sections())

    # Prompt-caching split (INFRA-036): the context sections that are IDENTICAL
    # across an agent's calls within a run (constitution + compiled conventions)
    # vs. the per-call dynamic sections (objectives, precedents, retrieved
    # passages, recent bus, work payload). The stable sections join the agent's
    # stable prompt prefix; the dynamic sections go in the per-call suffix. NO
    # dynamic content (timestamp / run id / per-call text) may be classed stable.
    _STABLE_HEADERS = ("CONSTITUTION", "CONVENTION_REGISTRY")

    def stable_sections(self):
        return [(h, b) for h, b in self.as_prompt_sections() if h in self._STABLE_HEADERS]

    def dynamic_sections(self):
        return [(h, b) for h, b in self.as_prompt_sections() if h not in self._STABLE_HEADERS]

    def stable_text(self):
        return "\n\n".join(f"=== {h} ===\n{b}" for h, b in self.stable_sections())

    def dynamic_text(self):
        return "\n\n".join(f"=== {h} ===\n{b}" for h, b in self.dynamic_sections())


def _stringify(p):
    return p if isinstance(p, str) else json.dumps(p, ensure_ascii=False, indent=2)


def assemble_context(
    backend, constitution, bus, work_payload, run_objectives="", charter=None,
    relevant_precedent_ids=None, channel=None, recent_bus_limit=50,
    convention_registry=None, reference_index_excerpt=None,
):
    if backend not in BACKEND_BUDGETS:
        raise ValueError(f"unknown backend: {backend}")
    budgets = BACKEND_BUDGETS[backend]
    governance_text = _render_governance(constitution, backend, budgets["governance"])
    objectives_text = _truncate_by_tokens(run_objectives, 200)
    precedents_text = _render_precedents(constitution, relevant_precedent_ids, budget=500 if backend != "qwen_local" else 0)
    charter_text = _render_charter(charter) if charter else ""
    convention_text = _render_conventions(convention_registry, budget=1500 if backend != "qwen_local" else 0)
    reference_index_text = _render_reference_index(reference_index_excerpt, budget=1500 if backend != "qwen_local" else 0)
    if budgets["bus"] > 0:
        recent_bus_msgs = bus.recent(limit=recent_bus_limit, channel=channel)
        recent_bus_text, summary_text = _render_bus(recent_bus_msgs, budgets["bus"])
    else:
        recent_bus_text, summary_text = "", ""
    return ContextPackage(
        backend=backend, governance_text=governance_text, objectives_text=objectives_text,
        precedents_text=precedents_text, charter_text=charter_text,
        recent_bus_text=recent_bus_text, rolling_summary_text=summary_text,
        work_payload=work_payload, convention_text=convention_text,
        reference_index_text=reference_index_text,
    )


def _render_governance(c, backend, budget_tokens):
    seed_laws = c.seed_laws()
    if backend == "qwen_local":
        seed_laws = [law for law in seed_laws if law.get("id") in QWEN_ALLOWED_LAW_IDS]
        lines = ["# Constitution (privacy-critical excerpt)", "Only LAW-II and LAW-IV are surfaced to local-model agents.", ""]
        for law in seed_laws:
            lines.append(f"## {law['id']} — {law['title']}"); lines.append(law["text"]); lines.append("")
        return _truncate_by_tokens("\n".join(lines), budget_tokens)
    lines = ["# Constitution", "\n## Seed laws (immutable)\n"]
    for law in seed_laws:
        lines.append(f"### {law['id']} — {law['title']}"); lines.append(law["text"]); lines.append("")
    if c.task_force_laws():
        lines.append("## Task-force laws\n")
        for tfl in c.task_force_laws()[-10:]:
            mission = tfl.get("source_charter", {}).get("mission", "")
            lines.append(f"- {tfl.get('id')} (reuse={tfl.get('reuse_count', 0)}): {mission}")
        lines.append("")
    if c.amendments():
        lines.append("## Operator amendments\n")
        for a in c.amendments()[-20:]:
            lines.append(f"- {a.get('id')}: {a.get('title', '')} — {a.get('text', '')}")
        lines.append("")
    return _truncate_by_tokens("\n".join(lines), budget_tokens)


def _render_precedents(c, ids, budget):
    if budget <= 0: return ""
    precs = c.precedents()
    if ids:
        idset = set(ids); precs = [p for p in precs if p.get("id") in idset]
    if not precs: return ""
    lines = ["# Relevant precedents"]
    for p in precs[-20:]:
        lines.append(f"- {p.get('id')}: {p.get('title', '')} — {p.get('ruling', p.get('text', ''))}")
    return _truncate_by_tokens("\n".join(lines), budget)


def _render_charter(charter): return "# Task force charter\n" + json.dumps(charter, ensure_ascii=False, indent=2)


def _render_conventions(registry, budget):
    if budget <= 0 or not registry:
        return ""
    convs = registry.get("conventions") if isinstance(registry, dict) else []
    if not convs:
        return ""
    lines = ["# Convention registry", f"Total rules: {len(convs)}", ""]
    for c in convs[:40]:
        lines.append(f"- {c.get('id')} [{c.get('category', '?')}/{c.get('severity', '?')}/{c.get('action', '?')}]: "
                     f"{c.get('rule', '')[:240]}")
    return _truncate_by_tokens("\n".join(lines), budget)


def _render_reference_index(excerpt, budget):
    if budget <= 0 or not excerpt:
        return ""
    if isinstance(excerpt, str):
        return _truncate_by_tokens(excerpt, budget)
    lines = ["# Reference index excerpt"]
    for ref in (excerpt or [])[:30]:
        lines.append(f"- {ref.get('ref_id')} [{ref.get('input_type', '?')}/{ref.get('document_name', '?')}"
                     f"/p{ref.get('location', {}).get('page', '?')}/para{ref.get('location', {}).get('paragraph', '?')}]: "
                     f"{(ref.get('text_excerpt') or '')[:160]}")
    return _truncate_by_tokens("\n".join(lines), budget)


def _render_bus(msgs, budget_tokens):
    if not msgs: return "", ""
    body_budget = int(budget_tokens * 0.85); summary_budget = budget_tokens - body_budget
    rendered = []; used = 0; older = []
    for m in reversed(msgs):
        line = _format_bus_msg(m); cost = _estimate_tokens(line)
        if used + cost > body_budget:
            older.append(m); continue
        rendered.append(line); used += cost
    rendered.reverse()
    summary = ""
    if older:
        by_type = {}
        for m in older:
            by_type[m.get("type", "?")] = by_type.get(m.get("type", "?"), 0) + 1
        ts = ", ".join(f"{k}={v}" for k, v in sorted(by_type.items()))
        summary = _truncate_by_tokens(f"Older bus traffic ({len(older)} messages): {ts}.", summary_budget)
    return "\n".join(rendered), summary


def _format_bus_msg(m):
    cc = m.get("constitution_check", {})
    body_str = _stringify(m.get('body', ''))[:240]
    return (f"[{m.get('timestamp', '')}] {m.get('sender', '?')} -> {m.get('recipient', '?')} "
            f"({m.get('channel', '?')}) {m.get('type', '?')}: {body_str}  "
            f"[check={cc.get('result', '?')}: {','.join(cc.get('laws_consulted', []) or [])}]")
