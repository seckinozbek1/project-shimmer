"""Three-tier verification memory (genesis Part IX)."""

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
class MemoryHit:
    tier: int
    record: dict
    age_days: float
    ttl_days: int


@dataclass
class VerificationMemory:
    project_root: Path
    tier1_path: Path
    tier2_path: Path
    tier3_path: Path
    _lock: threading.RLock = field(default_factory=threading.RLock)

    @classmethod
    def open(cls, project_root):
        return cls(project_root=project_root,
                   tier1_path=project_root / "output" / "audit" / "search_cache.json",
                   tier2_path=project_root / "config" / "verification_memory.json",
                   tier3_path=project_root / "config" / "global_verification_memory.json")

    def reset_tier1(self):
        with self._lock:
            self._save(self.tier1_path, {"entries": {}, "reset_at": _now()})

    def lookup(self, dedup_key, claim_type):
        with self._lock:
            for tier_no, path in ((1, self.tier1_path), (2, self.tier2_path), (3, self.tier3_path)):
                data = self._load(path)
                entry = (data.get("entries") or {}).get(dedup_key)
                if not entry: continue
                age = _age_days(entry.get("stored_at", ""))
                ttl = TTL_DAYS.get(claim_type, DEFAULT_TTL_DAYS)
                if age <= ttl:
                    return MemoryHit(tier=tier_no, record=entry, age_days=age, ttl_days=ttl)
        return None

    def store(self, dedup_key, *, claim_type, verdict, evidence, source_url=None,
              confidence=1.0, tiers=(1, 2, 3), extra=None):
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
        counts = {1: 0, 2: 0, 3: 0}
        with self._lock:
            for tier_no in (1, 2, 3):
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
                "tier1": len((self._load(self.tier1_path).get("entries") or {})),
                "tier2": len((self._load(self.tier2_path).get("entries") or {})),
                "tier3": len((self._load(self.tier3_path).get("entries") or {})),
                "ttl_days": dict(TTL_DAYS), "default_ttl_days": DEFAULT_TTL_DAYS,
            }

    def _path_for_tier(self, n): return {1: self.tier1_path, 2: self.tier2_path, 3: self.tier3_path}[n]

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
