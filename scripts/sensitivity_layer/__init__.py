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
import re
from datetime import datetime, timezone
from pathlib import Path

import durable_paths

# PII-rule production relocated into the privacy home in Phase 1b (was inside the
# editorial convention_parser). Re-exported so callers use `sensitivity_layer.
# redaction_rules`. It consumes the convention registry as DATA and imports nothing
# editorial.
from .rules import redaction_rules, DEFAULT_REDACTION_RULES
# The deterministic, operator-AUTHORIZED span detector (Mechanism 1's detector, reused
# here as the y/x sensitivity SIGNAL for the outbound masking engine). It is operator-
# convention-driven, never a model judge: detect() only fires for shapes an operator
# rule authorizes. INFRA-041 P1 reuses this; it does NOT invent a new sensitivity judge.
from . import redaction_detect

# The full layer's RUNTIME ON-SWITCH. The outbound masking ENGINE (mask_for_external /
# mask_exchange) is BUILT (INFRA-041 P1) and masks based on the explicit `sensitive`
# argument, independent of this flag. LAYER_ACTIVE governs whether the pipeline control
# flow ROUTES outbound payloads through the engine (wiring lands in INFRA-041 P2; a real
# activated sensitive run is proven in P5). Until then the run hard-gate still refuses to
# start unless the operator declares the run non-sensitive (require an override waiver).
LAYER_ACTIVE = False

SCHEMA = "sensitivity_override/v1"
EXPOSURE_SCHEMA = "exposure_ledger/v1"


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


# --- outbound masking engine (INFRA-041 P1): the x/y split + typed placeholders ----
# The protocol: every item that would cross an external (API/web) boundary is split into
#   x = non-sensitive items, passed through unchanged, and
#   y = sensitive items (operator-convention-marked by redaction_detect, NEVER model-judged),
#       HELD LOCAL and replaced outbound by typed placeholders [REDACTED:FIELD] carrying only
#       the field TYPE, never the content.
# Each item gets a per-item exposure TAG (passed | masked) written to the durable governance
# exposure ledger (the LAW-IV audit trail, no raw content). After the external exchange the
# held-local y content is rejoined by the INFRA-037 (item_id, revision) keys and deduped.

# Structural / routing / judgment keys kept REAL on a masked item (no source content): the
# rejoin keys, the timestamp, the item type, the model's confidence, and its verdict. Every
# OTHER field of a sensitive item is content-bearing and is replaced by a typed placeholder.
_PRESERVED_KEYS = frozenset({"item_id", "revision", "ts", "kind", "confidence", "verdict"})
_PLACEHOLDER_RE = re.compile(r"^\[REDACTED(?::[A-Z0-9_]+)?\]$")


def _placeholder_for(field_name):
    """Typed placeholder carrying the FIELD type (e.g. [REDACTED:ORIGINAL_TEXT])."""
    t = re.sub(r"[^A-Z0-9_]+", "_", str(field_name).upper()).strip("_") or "ITEM"
    return f"[REDACTED:{t}]"


def _is_placeholder(v):
    return isinstance(v, str) and bool(_PLACEHOLDER_RE.match(v.strip()))


def _is_envelope(payload):
    return (isinstance(payload, dict) and isinstance(payload.get("agent"), str)
            and isinstance(payload.get("doc_id"), str) and isinstance(payload.get("items"), list))


def _item_text(item):
    """Concatenate an item's content-bearing field values (skip structural keys and
    already-masked placeholders) -- the text the operator-rule detector scans."""
    parts = []
    for k, v in item.items():
        if k in _PRESERVED_KEYS:
            continue
        if isinstance(v, str) and v and not _is_placeholder(v):
            parts.append(v)
        elif isinstance(v, list):
            parts.extend(s for s in v if isinstance(s, str) and s and not _is_placeholder(s))
    return "\n".join(parts)


def _mask_item(item):
    """Replace every content-bearing field of a sensitive item with a typed placeholder.
    Idempotent: a field already holding a placeholder is left as the single placeholder
    (no nesting, no re-wrap). Returns (masked_item, masked_field_names)."""
    masked = dict(item)
    fields = []
    for k, v in item.items():
        if k in _PRESERVED_KEYS:
            continue
        if isinstance(v, str) and v:
            if _is_placeholder(v):
                continue
            masked[k] = _placeholder_for(k)
            fields.append(k)
        elif isinstance(v, list) and any(
                isinstance(e, str) and e and not _is_placeholder(e) for e in v):
            masked[k] = [_placeholder_for(k)]
            fields.append(k)
    return masked, fields


def _item_rule_hits(item, project_root, operator_rules):
    """The y/x SIGNAL: operator-authorized deterministic detector hits on the item's
    content. Non-empty -> the item carries operator-marked sensitive content (y)."""
    text = _item_text(item)
    if not text:
        return []
    return redaction_detect.detect(project_root, text, operator_rules)


def _current_revision(items):
    """INFRA-037 dedupe: highest `revision` per `item_id`, tie-break latest `ts`. Mirrors
    agent_wrapper.current_items (replicated locally so the privacy package does not import
    the heavy agent_wrapper / API-client module)."""
    best, passthrough = {}, []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        key = it.get("item_id")
        if key is None:
            passthrough.append(it)
            continue
        cur = best.get(key)
        rank = (it.get("revision", 1), it.get("ts", ""))
        if cur is None or rank > (cur.get("revision", 1), cur.get("ts", "")):
            best[key] = it
    return list(best.values()) + passthrough


def _write_exposure_ledger(records, *, run_id, agent, doc_id, project_root, ledger_path):
    """Append one per-item exposure record per item to the durable governance ledger
    (the LAW-IV audit trail). Records carry the exposure decision + masked field NAMES +
    authorizing rule ids only -- NEVER raw content."""
    if ledger_path is not None:
        path = Path(ledger_path)
    elif project_root is not None:
        path = durable_paths.exposure_ledger_path(project_root)
    else:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as fh:
        for r in records:
            rec = {"schema": EXPOSURE_SCHEMA, "timestamp": now, "run_id": run_id,
                   "agent": agent, "doc_id": doc_id, **r}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def mask_exchange(payload, *, sensitive=False, operator_rules=None, project_root=None,
                  run_id=None, agent=None, doc_id=None, ledger_path=None, write_ledger=True):
    """The full outbound masking engine. Splits a canonical envelope (or a bare item list)
    into x (passed) and y (masked + held local), writes the per-item exposure ledger, and
    returns {outbound, held, tags, sensitive}.

      outbound: the payload safe to send (y items carry typed placeholders).
      held:     {(item_id, revision): original_item} for every masked item (LOCAL only).
      tags:     per-item exposure tags (passed | masked), no raw content.

    INERT when sensitive is False: returns the payload unchanged, empty held, no ledger
    write -- the layer does not mask a run declared non-sensitive. Under sensitive mode the
    operator-convention inputs (operator_rules + project_root) are REQUIRED; their absence
    RAISES rather than silently passing raw content (LAW-IV: no silent ship)."""
    if not sensitive:
        return {"outbound": payload, "held": {}, "tags": [], "sensitive": False}
    if operator_rules is None or project_root is None:
        raise ValueError(
            "mask_exchange under sensitive mode requires operator_rules + project_root "
            "(operator-convention sensitivity source; no silent passthrough of raw content)")

    if _is_envelope(payload):
        env_agent, env_doc = agent or payload.get("agent"), doc_id or payload.get("doc_id")
        items, as_env = list(payload.get("items") or []), True
    elif isinstance(payload, list):
        env_agent, env_doc, items, as_env = agent, doc_id, list(payload), False
    else:
        raise ValueError(
            "mask_exchange under sensitive mode requires a canonical envelope or an item list "
            "(a non-envelope sensitive payload is never passed through raw)")

    held, tags, out_items = {}, [], []
    for it in items:
        if not isinstance(it, dict):
            out_items.append(it)
            continue
        iid, rev = it.get("item_id"), it.get("revision", 1)
        hits = _item_rule_hits(it, project_root, operator_rules)
        if hits:
            masked, fields = _mask_item(it)
            if iid is not None:
                held[(iid, rev)] = dict(it)  # hold the ORIGINAL local; never sent
            out_items.append(masked)
            tag = {"item_id": iid, "revision": rev, "exposure": "masked",
                   "type": it.get("kind"), "masked_fields": fields,
                   "rule_ids": sorted({h.get("rule_id") for h in hits if h.get("rule_id")}),
                   "detector_hits": len(hits)}
        else:
            out_items.append(it)
            tag = {"item_id": iid, "revision": rev, "exposure": "passed",
                   "type": it.get("kind"), "masked_fields": [], "rule_ids": [], "detector_hits": 0}
        tags.append(tag)

    if write_ledger:
        _write_exposure_ledger(tags, run_id=run_id, agent=env_agent, doc_id=env_doc,
                               project_root=project_root, ledger_path=ledger_path)
    outbound = {"agent": env_agent, "doc_id": env_doc, "items": out_items} if as_env else out_items
    return {"outbound": outbound, "held": held, "tags": tags, "sensitive": True}


def mask_for_external(payload, *, sensitive=False, **kwargs):
    """Mask an outbound payload for an external (API/web) boundary and return the OUTBOUND
    payload only. Thin wrapper over mask_exchange for fire-and-forget egress (no rejoin);
    callers that must rejoin held y content use mask_exchange directly. Inert when sensitive
    is False: returns the input unchanged (so a non-sensitive run is never altered)."""
    return mask_exchange(payload, sensitive=sensitive, **kwargs)["outbound"]


def rejoin_after_external(items, held, *, dedupe=True):
    """Rejoin held-local y items back into a set of items by (item_id, revision), then
    (default) reduce to the current revision per item_id (INFRA-037 rejoin + dedupe). Used
    after an external exchange to restore the content that was held local during the call."""
    if _is_envelope(items):
        items = items.get("items") or []
    restored = []
    for it in (items or []):
        if not isinstance(it, dict):
            restored.append(it)
            continue
        key = (it.get("item_id"), it.get("revision", 1))
        restored.append(dict(held[key]) if key in held else it)
    return _current_revision(restored) if dedupe else restored


# --- inactive-layer hard gate + logged override (mirrors redaction waiver) ------

def record_sensitivity_override(project_root, run_id, *, reason, now_iso=None):
    """Append a per-run sensitivity-layer override to the governance ledger
    (durable/governance/sensitivity_overrides.jsonl — survives reset, never
    deleted). Records that the operator consciously declared THIS run non-sensitive
    while the full LAW-IV sensitivity layer is inactive. Mirrors
    record_redaction_waiver (same module)."""
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


def record_redaction_waiver(project_root, run_id, *, reason, now_iso=None):
    """Append a per-run redaction-waiver record to the governance ledger
    (durable/governance/redaction_waivers.jsonl - survives reset, never deleted).
    Records that the operator consciously waived the always-on LAW-IV scrub
    (Mechanism 1) for THIS run only. Relocated into the privacy home in Phase 1b
    (was scripts/redaction_gate.py); the gate's default-BLOCK and logged-waiver
    behaviors both live with the scrubber now."""
    path = durable_paths.redaction_waivers_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": now_iso or datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "event": "REDACTION_WAIVED",
        "reason": reason,
        "scope": "this run only",
        "note": "operator declared this run non-sensitive and accepted running with no redaction",
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path
