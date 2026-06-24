"""Two-tier durable verification cache (genesis Part IX).

Tier-2 (project) and tier-3 (global) both live under durable/ (INFRA-030). The
former within-run tier-1 session cache was retired (INFRA-034): it was opened but
never written by any run, so it carried no state and only added wiring.

INTENTIONALLY DISCONNECTED FROM THE VERIFICATION PATH (design choice, NOT decay):
`store()`/`lookup()` are deliberately NOT called by the live pipeline — FACT_CHECKER
re-verifies every claim on every run. This is the correctness-over-speed default for
defect-intolerant legal review: a stale cached verdict could mask a re-check on a
changed source document, and a missed re-check is a worse failure than a redundant
search. The class is retained as (a) the run-summary stats hook
(orchestrator._collect_memory_stats -> stats()) and (b) a future opt-in caching hook,
to be wired only by an explicit operator-ratified change. `store`/`lookup` therefore
have no live callers by design (the verify gate exercises them directly, check 17).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TTL_DAYS = {
    "legal_regulatory": 365, "status": 365, "institutional": 180, "convention": 180,
    "standard_ref": 90, "statistic": 30, "date_event": 30, "attribution": 60,
    "procedure": 60, "currency": 30, "anti_pattern": 180,
}
DEFAULT_TTL_DAYS = 30


@dataclass
class CacheHit:
    tier: int
    record: dict
    age_days: float
    ttl_days: int


@dataclass
class VerificationCache:
    project_root: Path
    tier2_path: Path
    tier3_path: Path
    _lock: threading.RLock = field(default_factory=threading.RLock)

    @classmethod
    def open(cls, project_root):
        import durable_paths
        # Two protected durable tiers (INFRA-030): tier-2 (project) and tier-3
        # (global). The within-run tier-1 session cache was retired (INFRA-034).
        return cls(project_root=project_root,
                   tier2_path=durable_paths.verification_cache_path(project_root),
                   tier3_path=durable_paths.verification_cache_global_path(project_root))

    def lookup(self, dedup_key, claim_type):
        with self._lock:
            for tier_no, path in ((2, self.tier2_path), (3, self.tier3_path)):
                data = self._load(path)
                entry = (data.get("entries") or {}).get(dedup_key)
                if not entry: continue
                age = _age_days(entry.get("stored_at", ""))
                ttl = TTL_DAYS.get(claim_type, DEFAULT_TTL_DAYS)
                if age <= ttl:
                    return CacheHit(tier=tier_no, record=entry, age_days=age, ttl_days=ttl)
        return None

    def store(self, dedup_key, *, claim_type, verdict, evidence, source_url=None,
              confidence=1.0, tiers=(2, 3), extra=None):
        record = {"dedup_key": dedup_key, "claim_type": claim_type, "verdict": verdict,
                  "evidence": evidence, "source_url": source_url,
                  "confidence": float(confidence), "stored_at": _now()}
        if extra: record["extra"] = extra
        with self._lock:
            for tier_no in tiers:
                path = self._path_for_tier(tier_no)
                data = self._load(path)
                data.setdefault("entries", {})[dedup_key] = record
                self._save(path, data)
        return record

    def evict_expired(self):
        counts = {2: 0, 3: 0}
        with self._lock:
            for tier_no in (2, 3):
                path = self._path_for_tier(tier_no)
                data = self._load(path)
                kept = {}
                for k, v in (data.get("entries") or {}).items():
                    ttl = TTL_DAYS.get(v.get("claim_type", ""), DEFAULT_TTL_DAYS)
                    if _age_days(v.get("stored_at", "")) <= ttl:
                        kept[k] = v
                    else:
                        counts[tier_no] += 1
                data["entries"] = kept
                self._save(path, data)
        return counts

    def stats(self):
        with self._lock:
            return {
                "tier2": len((self._load(self.tier2_path).get("entries") or {})),
                "tier3": len((self._load(self.tier3_path).get("entries") or {})),
                "ttl_days": dict(TTL_DAYS), "default_ttl_days": DEFAULT_TTL_DAYS,
            }

    def _path_for_tier(self, n): return {2: self.tier2_path, 3: self.tier3_path}[n]

    def _load(self, path):
        if not path.exists(): return {"entries": {}}
        try: return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError: return {"entries": {}}

    def _save(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def _now(): return datetime.now(timezone.utc).isoformat()


def _age_days(iso_ts):
    if not iso_ts: return float("inf")
    try: dt = datetime.fromisoformat(iso_ts)
    except ValueError: return float("inf")
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
