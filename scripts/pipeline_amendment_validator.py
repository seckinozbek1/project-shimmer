"""Citation-format enforcement for AMENDMENT_DRAFTER output.

Original rule (Part XVIII Section D): every amendment.comment must contain
at least one CONV-* and one REF-*. Location must be a REF-* in the
operational document.

Part XXIII (Absence Detection) carve-out: absence findings, by definition,
have no REF-* in the reviewed document because the provision is missing.
The validator now accepts the sentinel string "document-level" as a valid
`location` for such findings. The comment-citation rule (>=1 CONV-* and
>=1 REF-*) is unchanged — absence findings cite REF-* entries from the
context documents that establish the norm.
"""

from __future__ import annotations

import re
from typing import Any


_CONV_PATTERN = re.compile(r"\bCONV-\d{3,}\b")
# INFRA-042: tightened with (?<!WEB-) so a WEB-REF-NNNN id is never matched as a corpus REF.
_REF_PATTERN = re.compile(r"(?<!WEB-)\bREF-\d{4,}\b")
_WEBREF_PATTERN = re.compile(r"\bWEB-REF-\d{4,}\b")
_DOCUMENT_LEVEL_SENTINEL = "document-level"


def validate_amendment_comment(comment: str, *, registry_empty: bool = False) -> bool:
    """Return True iff the comment is adequately grounded.

    Non-empty registry (the default): the rule holds UNCHANGED, at least one CONV-* AND one REF-*.
    Empty registry (INFRA-042 carve-out, conventions list empty or absent): a CONV-* is unsatisfiable
    because none exist, so the comment grounds on at least one REF-* OR at least one WEB-REF-*; the
    CONV-* requirement is relaxed in this state ONLY."""
    if not isinstance(comment, str):
        return False
    has_ref = bool(_REF_PATTERN.search(comment))
    has_webref = bool(_WEBREF_PATTERN.search(comment))
    if registry_empty:
        return has_ref or has_webref
    return bool(_CONV_PATTERN.search(comment)) and has_ref


def _is_valid_location(location: Any) -> bool:
    """Per Part XXIII: location is valid if it is either a REF-* form OR the
    sentinel string 'document-level' (used for absence findings that have
    no natural anchor in the reviewed document)."""
    if not location:
        return False
    s = str(location)
    if s == _DOCUMENT_LEVEL_SENTINEL:
        return True
    return bool(_REF_PATTERN.fullmatch(s))


def validate_amendment(amendment: dict, *, registry_empty: bool = False) -> tuple[bool, list[str]]:
    """Validate a single amendment object. Returns (ok, errors).

    INFRA-042 empty-registry carve-out: when registry_empty, convention_ref is NOT required (no
    convention exists to cite), and the comment grounds on a REF-* OR a WEB-REF-*. location and the
    other required fields are unchanged. When conventions exist, the rule holds unchanged."""
    errors: list[str] = []
    if not isinstance(amendment, dict):
        return False, ["amendment is not an object"]
    required = ("location", "comment", "action", "severity")
    if not registry_empty:
        required = required + ("convention_ref",)
    for fname in required:
        if not amendment.get(fname):
            errors.append(f"missing required field: {fname}")
    location = amendment.get("location")
    if location and not _is_valid_location(location):
        errors.append(
            f"location must be REF-* form or 'document-level' sentinel, got {location!r}"
        )
    conv = amendment.get("convention_ref")
    if conv and not _CONV_PATTERN.fullmatch(str(conv)):
        errors.append(f"convention_ref must be CONV-* form, got {conv!r}")
    comment = amendment.get("comment", "")
    if not validate_amendment_comment(comment, registry_empty=registry_empty):
        if registry_empty:
            errors.append("amendment.comment must contain >=1 REF-* or >=1 WEB-REF-* (empty registry)")
        else:
            errors.append("amendment.comment must contain >=1 CONV-* and >=1 REF-*")
    return (not errors, errors)


def validate_amendment_payload(payload: dict, *, registry_empty: bool = False) -> tuple[bool, list[str]]:
    """Validate the full AMENDMENT_DRAFTER output. `registry_empty` threads the INFRA-042 carve-out."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return False, ["payload not an object"]
    if not payload.get("document_id"):
        errors.append("missing document_id")
    amendments = payload.get("amendments")
    if not isinstance(amendments, list):
        errors.append("amendments not a list")
        return False, errors
    for i, a in enumerate(amendments):
        ok, errs = validate_amendment(a, registry_empty=registry_empty)
        if not ok:
            errors.extend(f"amendment[{i}]: {e}" for e in errs)
    return (not errors, errors)
