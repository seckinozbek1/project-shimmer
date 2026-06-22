"""Constitutional-amendment tripwire (INFRA-029 enforcement).

Intercepts any attempt to MODIFY or DELETE an existing entry in
config/constitution.json `amendments[]` or `seed_laws`. Appending a NEW amendment
(the normal operator-approved DELTA path) is allowed. A modify/delete STOPS and
requires explicit operator approval via the operator-escalation pattern used
elsewhere in the codebase (an `operator_handler(topic, payload)` that returns an
APPROVE/DENY decision). Without an approving operator decision the change does
NOT happen.

No code path may bypass this: every writer of constitution.json routes through
`check_constitution_change` (Constitution.save and the snapshot load path). An
agent cannot bypass it — agents have no direct write path to constitution.json,
and the guard DENIES any protected change that arrives without an approving
operator handler (the safe default is refusal).

NOTE: when a UI is built, this approval MUST surface there too. A protected
constitutional edit must never proceed without an explicit human decision,
regardless of interface (terminal prompt today, UI later).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# Sections whose existing entries are protected from in-place modify/delete.
_PROTECTED_SECTIONS = ("seed_laws", "amendments")

# Governance ledger of guard decisions. Lives in the protected durable/governance
# tree (INFRA-030); reset/load never touch it (structural protection by location).
GUARD_LOG_NAME = "constitution_guard_log.jsonl"


class GuardError(Exception):
    """Raised when a protected constitutional change is attempted without
    operator approval. The write must not proceed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _by_id(entries) -> dict:
    out = {}
    for e in entries or []:
        if isinstance(e, dict) and e.get("id") is not None:
            out[str(e["id"])] = e
    return out


def protected_violations(old: dict, new: dict) -> list[str]:
    """Return human-readable descriptions of protected changes between two
    constitution dicts. A violation is: an existing seed_law/amendment id that is
    REMOVED, or whose content CHANGED. Adding a new id is NOT a violation."""
    violations: list[str] = []
    for section in _PROTECTED_SECTIONS:
        old_map = _by_id(old.get(section, []))
        new_map = _by_id(new.get(section, []))
        for eid, entry in old_map.items():
            if eid not in new_map:
                violations.append(f"{section}: {eid} would be DELETED")
            elif new_map[eid] != entry:
                violations.append(f"{section}: {eid} would be MODIFIED")
    return violations


def _is_approved(decision) -> bool:
    # Accept an OperatorDecision-like object (.decision) or a bare string.
    val = getattr(decision, "decision", decision)
    return str(val).strip().lower() in {"approve", "approved", "yes", "y", "true"}


def _log_decision(project_root, record) -> None:
    try:
        import durable_paths
        # Protected durable governance ledger (INFRA-030): survives reset.
        path = durable_paths.constitution_guard_log_path(project_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # logging is best-effort; never block on it


def check_constitution_change(
    current_path,
    proposed_data: dict,
    *,
    operator_handler=None,
    interactive: bool = False,
    reason: str = "",
    project_root=None,
):
    """Decide whether writing `proposed_data` over the constitution at
    `current_path` is permitted.

    - No protected modify/delete (append-only or unchanged) -> allowed, silently.
    - A protected modify/delete -> requires an APPROVE from operator_handler in
      interactive mode. No handler / not interactive / not approved -> DENIED.

    Returns {"allowed": bool, "violations": [...], "approved": bool}. Never
    writes anything itself; the caller performs the write only when allowed.
    """
    current_path = Path(current_path)
    if project_root is None:
        # config/constitution.json -> project root is two parents up.
        project_root = current_path.parent.parent
    if not current_path.exists():
        return {"allowed": True, "violations": [], "approved": False}
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
    except Exception:
        # If the current file is unreadable, treat as no protections to compare.
        return {"allowed": True, "violations": [], "approved": False}

    violations = protected_violations(current, proposed_data)
    if not violations:
        return {"allowed": True, "violations": [], "approved": False}

    payload = {"violations": violations, "reason": reason,
               "message": ("A protected constitutional change (modify/delete of an "
                           "existing amendment or seed law) was attempted. Explicit "
                           "operator approval is required before it can proceed.")}
    approved = False
    if interactive and operator_handler is not None:
        decision = operator_handler("CONSTITUTION_AMENDMENT_GUARD", payload)
        approved = _is_approved(decision)
    _log_decision(project_root, {
        "timestamp": _now(), "reason": reason, "violations": violations,
        "approved": approved,
    })
    return {"allowed": approved, "violations": violations, "approved": approved}
