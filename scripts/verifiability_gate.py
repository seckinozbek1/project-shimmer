"""OPT-1 verifiability gate (pipeline behavior; no DELTA).

A finalize pass that catches a finding which makes a CONFIDENT positive affirmation while
citing nothing, and downgrades it to UNCERTAIN. It fires ONLY on unambiguous positive
affirmations that claim solid ground and show none (claims grounded, cites nothing, an
internal inconsistency). Flagged-and-kept, never dropped.

It reuses the existing honest channel (genesis Part XXV UNCERTAIN: enters the escalation
cascade and is surfaced with the [UNCERTAIN] tag), the existing genesis REF rule, and
INFRA-037 supersession (a revision+1 item supersedes the original; the bus keeps the
original as history). It changes no seed law and no governed genesis rule.

It does NOT touch pipeline_amendment_validator.py: amendments stay REF-gated there.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from agent_wrapper import decode_items  # THE canonical INFRA-037 reader (current revision per item_id)

# FIRE-SET: the UNAMBIGUOUS positive affirmations per agent. An item carrying one of these
# verdicts that cites nothing is internally inconsistent (claims solid ground, shows none).
AFFIRMATIVE_VERDICTS = {
    "LEGAL_ANALYST": frozenset({"GROUNDED"}),
    "PRACTICE_AUDITOR": frozenset({"ALIGNED", "COMPLIANT", "VIOLATION", "ANTI_PATTERN"}),
    "FACT_CHECKER": frozenset({"CONFIRMED"}),
}

# EXCLUDED BY DESIGN (the gate does NOT fire), because each is ALREADY an honest signal and
# downgrading it would double-flag something already flagged:
#   - THIN (LEGAL_ANALYST): self-hedges, already says grounding is thin.
#   - OUTDATED (PRACTICE_AUDITOR / FACT_CHECKER): asserts a state-change (superseded), often
#     has no clean REF by nature.
#   - DISPUTED (FACT_CHECKER): says a claim is contested, already a hedge, treated as honest.
#   - The self-flagging "no support" verdicts UNSUPPORTED, OUT_OF_SCOPE (LEGAL_ANALYST),
#     NO_REFERENCE_AVAILABLE, AMBIGUOUS (PRACTICE_AUDITOR), UNVERIFIABLE (FACT_CHECKER).
# Never fire on: PROCESSOR extractions (no verdict), SPEECH_ACT tags, VERIFIER (uses a
# MATCH/DIVERGENCE/ADDITION/OMISSION finding field, an internal draft-vs-source QA, not an
# external-standard affirmation), AMENDMENT_DRAFTER amendments (already REF-gated by
# pipeline_amendment_validator + check_35; not duplicated here).

# Per-agent cited web-source field: a non-empty value counts as grounding so a legitimately
# web-grounded finding is not mis-flagged. WEB-REF as a first-class citation FORM is OPT-2's
# job; here a non-empty source simply counts as grounding so OPT-1 does not mis-fire.
_WEB_SOURCE_FIELD = {"FACT_CHECKER": "source_url", "PRACTICE_AUDITOR": "reference_url"}

# Same REF-* form the amendment validator uses (no duplication of the validator itself).
_REF_PATTERN = re.compile(r"\bREF-\d{4,}\b")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _is_ref(value) -> bool:
    return isinstance(value, str) and bool(_REF_PATTERN.search(value))


def fires_on(agent, item) -> bool:
    """True iff the item is an unambiguous positive affirmation in this agent's fire-set.
    Extractions, tags, other agents, and excluded/self-flagging verdicts return False."""
    verdicts = AFFIRMATIVE_VERDICTS.get(agent)
    if not verdicts:
        return False
    return item.get("verdict") in verdicts


def is_grounded(agent, item) -> bool:
    """A fired-on item is grounded if ANY of: ref is a REF-*; any ref_ids entry is a REF-*
    (this counts CONTEXT refs, so a valid absence finding citing the norm-establishing
    context is grounded and is NOT mis-flagged); or the agent's cited web-source field is
    non-empty."""
    if _is_ref(item.get("ref")):
        return True
    for r in (item.get("ref_ids") or []):
        if _is_ref(r):
            return True
    field = _WEB_SOURCE_FIELD.get(agent)
    if field:
        v = item.get(field)
        if isinstance(v, str) and v.strip():
            return True
    return False


def _already_downgraded(item) -> bool:
    """Idempotency guard: an item already on the UNCERTAIN channel is not re-downgraded."""
    return bool(item.get("uncertain")) or str(item.get("confidence", "")).upper() == "UNCERTAIN"


def _downgrade(agent, item) -> dict:
    """Build the INFRA-037 superseding item: same item_id, revision+1, confidence=UNCERTAIN,
    uncertain=true, and a flat unverifiable_reason naming the agent and verdict."""
    sup = dict(item)
    sup["revision"] = int(item.get("revision", 1)) + 1
    sup["ts"] = _now()
    sup["confidence"] = "UNCERTAIN"
    sup["uncertain"] = True
    sup["unverifiable_reason"] = (
        f"{agent} {item.get('verdict')} finding carries no REF or cited source")
    return sup


def apply_verifiability_gate(results) -> dict:
    """Finalize pass over a list of agent RESULT wrappers ({agent, ok, parsed:{items}}).

    For each fired-on, ungrounded item, append an INFRA-037 superseding revision+1 item
    (downgraded to UNCERTAIN) to the SAME wrapper's items list, so every decode_items
    consumer (current revision per item_id) sees the downgrade while the original remains
    as history. Mutates the wrappers in place. Returns {downgraded, reasons}."""
    downgraded, reasons = 0, []
    for r in (results or []):
        if not isinstance(r, dict) or not r.get("ok"):
            continue
        agent = r.get("agent")
        if agent not in AFFIRMATIVE_VERDICTS:
            continue
        parsed = r.get("parsed")
        if not (isinstance(parsed, dict) and isinstance(parsed.get("items"), list)):
            continue
        supersessions = []
        for item in decode_items(parsed):  # current revision per item_id only
            if not isinstance(item, dict):
                continue
            if fires_on(agent, item) and not is_grounded(agent, item) and not _already_downgraded(item):
                sup = _downgrade(agent, item)
                supersessions.append(sup)
                downgraded += 1
                reasons.append(sup["unverifiable_reason"])
        parsed["items"].extend(supersessions)
    return {"downgraded": downgraded, "reasons": reasons}
