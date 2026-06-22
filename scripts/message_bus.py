"""Message bus for Project Shimmer.

Append-only JSONL at the path supplied by the caller — per run, that is
output/runs/<run>/logs/agent_bus.jsonl (Part XXVII §A). Every message must
include a constitution_check field (LAW-V) or the bus rejects it.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


VALID_TYPES = {
    "PROPOSE", "REQUEST", "OFFER", "CHALLENGE", "INFORM", "YIELD", "BLOCK", "CONFIRM",
    "ESCALATE", "MEMORY_HIT", "DEDUP_ALERT", "CHARTER_PROPOSE", "CHARTER_APPROVE",
    "CHARTER_DENY", "DISSOLVE", "PRECEDENT_APPLIED", "LAW_CREATED", "API_DISCOVERED",
}
VALID_ROLES = {"agent", "supervisor", "orchestrator", "operator"}


class ProtocolViolation(ValueError):
    pass


@dataclass
class MessageBus:
    path: Path
    _lock: threading.RLock = field(default_factory=threading.RLock)

    @classmethod
    def open(cls, path):
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.touch()
        return cls(path=p)

    def post(self, msg):
        validated = self._validate(msg)
        line = json.dumps(validated, ensure_ascii=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return validated

    def read_all(self):
        with self._lock:
            if not self.path.exists():
                return []
            with self.path.open("r", encoding="utf-8") as fh:
                return [json.loads(ln) for ln in fh if ln.strip()]

    def stream(self):
        with self._lock:
            text = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        for ln in text.splitlines():
            if ln.strip():
                yield json.loads(ln)

    def query(self, sender=None, recipient=None, channel=None, msg_type=None, types=None, since=None, limit=None):
        type_set = set(types) if types else None
        if msg_type:
            type_set = (type_set or set()) | {msg_type}
        out = []
        for m in self.read_all():
            if sender and m.get("sender") != sender: continue
            if recipient and m.get("recipient") != recipient: continue
            if channel and m.get("channel") != channel: continue
            if type_set and m.get("type") not in type_set: continue
            if since and m.get("timestamp", "") < since: continue
            out.append(m)
        if limit is not None:
            out = out[-limit:]
        return out

    def recent(self, limit=50, channel=None):
        return self.query(channel=channel, limit=limit)

    def summarize(self):
        msgs = self.read_all()
        by_type, by_sender, by_channel = {}, {}, {}
        for m in msgs:
            by_type[m.get("type", "?")] = by_type.get(m.get("type", "?"), 0) + 1
            by_sender[m.get("sender", "?")] = by_sender.get(m.get("sender", "?"), 0) + 1
            by_channel[m.get("channel", "?")] = by_channel.get(m.get("channel", "?"), 0) + 1
        return {"total": len(msgs), "by_type": by_type, "by_sender": by_sender, "by_channel": by_channel,
                "first_timestamp": msgs[0]["timestamp"] if msgs else None,
                "last_timestamp": msgs[-1]["timestamp"] if msgs else None}

    @staticmethod
    def _validate(msg):
        required = {"sender", "sender_role", "recipient", "channel", "type", "body"}
        missing = required - set(msg.keys())
        if missing:
            raise ProtocolViolation(f"message missing required fields: {sorted(missing)}")
        if "constitution_check" not in msg:
            raise ProtocolViolation("every message must include constitution_check (LAW-V)")
        cc = msg["constitution_check"]
        if not isinstance(cc, dict) or "result" not in cc:
            raise ProtocolViolation("constitution_check must be a dict with at least a 'result' key")
        if cc["result"] not in {"RESOLVED", "UNRESOLVED"}:
            raise ProtocolViolation(f"constitution_check.result must be RESOLVED or UNRESOLVED, got {cc['result']!r}")
        if msg["sender_role"] not in VALID_ROLES:
            raise ProtocolViolation(f"sender_role must be one of {sorted(VALID_ROLES)}, got {msg['sender_role']!r}")
        if msg["type"] not in VALID_TYPES:
            raise ProtocolViolation(f"type must be one of {sorted(VALID_TYPES)}, got {msg['type']!r}")
        # Genesis Part XXV: optional uncertain flag. When present it must be
        # a bool. Defaults to False on the validated output so consumers can
        # always rely on the key existing without performing a key-presence check.
        if "uncertain" in msg and not isinstance(msg["uncertain"], bool):
            raise ProtocolViolation(
                f"uncertain must be a bool when present, got {type(msg['uncertain']).__name__}"
            )
        out = dict(msg)
        out.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        out.setdefault("uncertain", False)
        return out
