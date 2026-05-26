"""Citation-format enforcement for AMENDMENT_DRAFTER output.

Original rule (Part XVIII Section D): every amendment.comment must contain
at least one CONV-* and one REF-*. Location must be a REF-* in the
operational document.

Part XXIV (Absence Detection) carve-out: absence findings, by definition,
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
_REF_PATTERN = re.compile(r"\bREF-\d{4,}\b")
_DOCUMENT_LEVEL_SENTINEL = "document-level"


def validate_amendment_comment(comment: str) -> bool:
    """Return True iff comment carries at least one CONV-* and one REF-*."""
    if not isinstance(comment, str):
        return False
    return bool(_CONV_PATTERN.search(comment) and _REF_PATTERN.search(comment))


def _is_valid_location(location: Any) -> bool:
    """Per Part XXIV: location is valid if it is either a REF-* form OR the
    sentinel string 'document-level' (used for absence findings that have
    no natural anchor in the reviewed document)."""
    if not location:
        return False
    s = str(location)
    if s == _DOCUMENT_LEVEL_SENTINEL:
        return True
    return bool(_REF_PATTERN.fullmatch(s))


def validate_amendment(amendment: dict) -> tuple[bool, list[str]]:
    """Validate a single amendment object. Returns (ok, errors)."""
    errors: list[str] = []
    if not isinstance(amendment, dict):
        return False, ["amendment is not an object"]
    for field in ("location", "convention_ref", "comment", "action", "severity"):
        if not amendment.get(field):
            errors.append(f"missing required field: {field}")
    location = amendment.get("location")
    if location and not _is_valid_location(location):
        errors.append(
            f"location must be REF-* form or 'document-level' sentinel, got {location!r}"
        )
    conv = amendment.get("convention_ref")
    if conv and not _CONV_PATTERN.fullmatch(str(conv)):
        errors.append(f"convention_ref must be CONV-* form, got {conv!r}")
    comment = amendment.get("comment", "")
    if not validate_amendment_comment(comment):
        errors.append("amendment.comment must contain >=1 CONV-* and >=1 REF-*")
    return (not errors, errors)


def validate_amendment_payload(payload: dict) -> tuple[bool, list[str]]:
    """Validate the full AMENDMENT_DRAFTER output."""
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
        ok, errs = validate_amendment(a)
        if not ok:
            errors.extend(f"amendment[{i}]: {e}" for e in errs)
    return (not errors, errors)
