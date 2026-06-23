"""LAW-IV full sensitivity-enforcement layer — BUILT BUT UNWIRED (INFRA-038).

This module is the SCAFFOLDING for the full sensitivity philosophy: the pipeline
reasoning about sensitivity as a first-class concept — masking sensitive content
out of any API/web call, and routing sensitive handling only to agents whose
registry flag `may_handle_sensitive` is true. It is built so the wiring is ready,
but it is INERT: `LAYER_ACTIVE` is False and nothing in the pipeline control flow
consumes `mask_for_external` or `may_handle_sensitive` yet. The full philosophy is
DEFERRED to real-life / full deployment (see README, CLAUDE.md).

This is NOT a replacement for what ships in Stage 3a. Stage 3a applies OPERATOR
REDACTION RULES locally (LAW-IV's own phrase, "content marked for redaction") via
the Qwen redactors. This module is the larger, still-dormant layer.

The dormant ON-SWITCH is two-part: flip `LAYER_ACTIVE` to True AND have the
control flow consult `may_handle_sensitive(...)` / `mask_for_external(...)`. Until
then, a run must pass the inactive-layer hard gate (see require_layer_or_override),
which mirrors the Qwen redaction --no-redaction-override hard-gate-plus-logged-
override pattern: refuse to proceed unless the operator declares THIS run
non-sensitive, each override written to the governance ledger.

LAW-IV (cited, NOT modified): "Sensitive content … must be processed exclusively
by offline agents running on local hardware. No sensitive content may traverse a
network, enter an API call, or leave the operator's machine."
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import durable_paths

# The full layer is not active. Flipping this to True is half the on-switch; the
# other half is wiring the helpers below into the control flow (deferred).
LAYER_ACTIVE = False

SCHEMA = "sensitivity_override/v1"


def is_active() -> bool:
    """True only when the full sensitivity-enforcement layer is wired and on.
    Always False in Stage 3a (built-but-unwired)."""
    return bool(LAYER_ACTIVE)


# --- dormant routing / masking (BUILT, not consumed by control flow yet) -------

def may_handle_sensitive(registry: dict, agent: str) -> bool:
    """Dormant routing predicate: whether `agent` is permitted to handle sensitive
    content, per its registry flag. The on-switch for sensitive routing. Defined
    now; not consulted by the pipeline until the layer is activated."""
    agents = registry.get("agents", registry) if isinstance(registry, dict) else {}
    return bool((agents.get(agent) or {}).get("may_handle_sensitive", False))


def mask_for_external(payload, *, registry=None, agent=None):
    """Dormant masking hook: when the layer is active this will strip/mask sensitive
    content before any payload crosses to an API/web boundary (LAW-IV). While the
    layer is inactive it is a transparent pass-through and is NOT called by the
    control flow — present so the call sites have a stable target to wire later."""
    if not is_active():
        return payload  # inert: no masking performed, and nothing calls this yet
    raise NotImplementedError(
        "full sensitivity masking is deferred (INFRA-038): activation is not wired")


# --- inactive-layer hard gate + logged override (mirrors redaction waiver) ------

def record_sensitivity_override(project_root, run_id, *, reason, now_iso=None):
    """Append a per-run sensitivity-layer override to the governance ledger
    (durable/governance/sensitivity_overrides.jsonl — survives reset, never
    deleted). Records that the operator consciously declared THIS run non-sensitive
    while the full LAW-IV sensitivity layer is inactive. Mirrors
    redaction_gate.record_redaction_waiver."""
    path = durable_paths.sensitivity_overrides_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema": SCHEMA,
        "timestamp": now_iso or datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "event": "SENSITIVITY_LAYER_INACTIVE_OVERRIDE",
        "reason": reason,
        "scope": "this run only",
        "note": "operator declared this run non-sensitive and accepted running with the "
                "full LAW-IV sensitivity layer inactive (Stage 3a built-but-unwired)",
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path
