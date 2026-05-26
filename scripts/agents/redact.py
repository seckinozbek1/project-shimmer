"""Redaction agents — REDACT_CLERK (T1-T2), REDACT_AUTHORITY (T3-T4),
REDACT_GATE (T5). All run on Qwen local per LAW-IV."""

from __future__ import annotations

from agents._base import NamedAgent


class RedactClerk(NamedAgent):
    CLASS_NAME = "REDACT_CLERK"


class RedactAuthority(NamedAgent):
    CLASS_NAME = "REDACT_AUTHORITY"


class RedactGate(NamedAgent):
    CLASS_NAME = "REDACT_GATE"
