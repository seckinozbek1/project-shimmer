"""Constitution engine for Project Shimmer.

Four layers of legislation ordered by authority: seed_laws, task_force_laws,
precedents, amendments. Pure stdlib. No domain knowledge. No hardcoded paths.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LAYER_ORDER = ("seed_laws", "task_force_laws", "precedents", "amendments")


@dataclass
class CheckResult:
    resolved: bool
    layer: str | None = None
    rule_id: str | None = None
    rule: dict[str, Any] | None = None
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"resolved": self.resolved, "layer": self.layer, "rule_id": self.rule_id, "rationale": self.rationale}


@dataclass
class MatchResult:
    confidence: float
    law: dict[str, Any] | None = None
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"confidence": self.confidence, "law_id": (self.law or {}).get("id"), "rationale": self.rationale}


@dataclass
class Constitution:
    path: Path
    _data: dict[str, Any] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    @classmethod
    def load(cls, path: str | Path) -> "Constitution":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"constitution not found at {p}")
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        for layer in LAYER_ORDER:
            data.setdefault(layer, [])
        return cls(path=p, _data=data)

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, ensure_ascii=False)
            tmp.replace(self.path)

    def seed_laws(self): return list(self._data.get("seed_laws", []))
    def task_force_laws(self): return list(self._data.get("task_force_laws", []))
    def precedents(self): return list(self._data.get("precedents", []))
    def amendments(self): return list(self._data.get("amendments", []))

    def check(self, situation: dict[str, Any]) -> CheckResult:
        with self._lock:
            for layer in LAYER_ORDER:
                for rule in self._data.get(layer, []):
                    if self._rule_matches(rule, situation):
                        return CheckResult(resolved=True, layer=layer, rule_id=rule.get("id"), rule=rule,
                                           rationale=rule.get("match_rationale", f"matched in layer {layer}"))
        return CheckResult(resolved=False, rationale="no rule matched in any layer")

    @staticmethod
    def _rule_matches(rule, situation):
        if rule.get("always"):
            return True
        sit_tags = set(situation.get("tags", []) or [])
        rule_tags = set(rule.get("applies_to", []) or [])
        if sit_tags and rule_tags and sit_tags & rule_tags:
            return True
        for key in ("action", "agent", "topic"):
            if situation.get(key) and rule.get(key) == situation.get(key):
                return True
        return False

    def add_precedent(self, precedent):
        with self._lock:
            entry = dict(precedent); entry.setdefault("id", self._next_id("PREC")); entry.setdefault("created", _now())
            self._data.setdefault("precedents", []).append(entry); self.save(); return entry

    def add_tf_law(self, charter, learnings=None):
        with self._lock:
            entry = {"id": self._next_id("TFL"), "created": _now(), "source_charter": charter,
                     "learnings": learnings or {}, "reuse_count": 0}
            self._data.setdefault("task_force_laws", []).append(entry); self.save(); return entry

    def add_amendment(self, amendment):
        with self._lock:
            entry = dict(amendment); entry.setdefault("id", self._next_id("AMEND")); entry.setdefault("created", _now())
            self._data.setdefault("amendments", []).append(entry); self.save(); return entry

    def match_tf_law(self, charter):
        with self._lock:
            best = MatchResult(confidence=0.0, law=None, rationale="no candidate")
            charter_members = {m.get("agent") for m in charter.get("members", []) if m.get("agent")}
            charter_kw = _tokenize(charter.get("mission", ""))
            for law in self._data.get("task_force_laws", []):
                src = law.get("source_charter", {})
                law_members = {m.get("agent") for m in src.get("members", []) if m.get("agent")}
                law_kw = _tokenize(src.get("mission", ""))
                m_score = _jaccard(charter_members, law_members); k_score = _jaccard(charter_kw, law_kw)
                score = (m_score + k_score) / 2.0
                if score > best.confidence:
                    best = MatchResult(confidence=round(score, 3), law=law,
                                       rationale=f"members_overlap={m_score:.2f}, mission_overlap={k_score:.2f}")
            return best

    def increment_tf_law_reuse(self, law_id):
        with self._lock:
            for law in self._data.get("task_force_laws", []):
                if law.get("id") == law_id:
                    law["reuse_count"] = int(law.get("reuse_count", 0)) + 1; self.save(); return

    def _next_id(self, prefix):
        layer_map = {"PREC": "precedents", "TFL": "task_force_laws", "AMEND": "amendments"}
        n = len(self._data.get(layer_map[prefix], [])) + 1
        return f"{prefix}-{n:04d}"

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps(self._data))


def _now(): return datetime.now(timezone.utc).isoformat()
def _tokenize(s): return {tok for tok in (s or "").lower().split() if len(tok) > 3}
def _jaccard(a, b):
    union = a | b
    return len(a & b) / len(union) if union else 0.0
