"""Review-scope cutoff mechanism (Part XVIII Section C + user date cascade).

Supports cutoff_type in {date, document_number, both, all}. Documents at or
after the cutoff are operational; the rest stay context. For 'both', the
cutoff that captures MORE documents wins (per operator spec).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _parse_date(s):
    if not s: return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None


def _sort_by_date(dated):
    def key(d):
        dt = _parse_date(d.get("date"))
        return (dt is None, dt or datetime.min)
    return sorted(dated, key=key)


def apply_cutoff(dated_documents: list[dict], scope: dict) -> list[dict]:
    """Return the subset of documents that fall at or after the cutoff.

    dated_documents items: {"filename": str, "date": "YYYY-MM-DD", ...}
    scope:
      cutoff_type ∈ {"date", "document_number", "both", "all"}
      cutoff_date: "YYYY-MM-DD" (inclusive — at or after counts as operational)
      cutoff_document_number: int (1-indexed cut point — documents at index
        cutoff_document_number and beyond count as operational, in chrono order)
    """
    if not dated_documents:
        return []
    ordered = _sort_by_date(dated_documents)
    ctype = (scope or {}).get("cutoff_type", "all")
    if ctype == "all":
        return list(ordered)
    if ctype == "date":
        return _apply_date_cutoff(ordered, scope)
    if ctype == "document_number":
        return _apply_number_cutoff(ordered, scope)
    if ctype == "both":
        by_date = _apply_date_cutoff(ordered, scope)
        by_num = _apply_number_cutoff(ordered, scope)
        # whichever captures more documents wins
        return by_date if len(by_date) >= len(by_num) else by_num
    return list(ordered)


def _apply_date_cutoff(ordered, scope):
    cutoff = _parse_date((scope or {}).get("cutoff_date"))
    if cutoff is None:
        return list(ordered)
    out = []
    for d in ordered:
        dt = _parse_date(d.get("date"))
        if dt is not None and dt >= cutoff:
            out.append(d)
    return out


def _apply_number_cutoff(ordered, scope):
    n = (scope or {}).get("cutoff_document_number")
    if not isinstance(n, int) or n < 1:
        return list(ordered)
    # 1-indexed: cutoff_document_number=3 means doc #3 and beyond count.
    # Documents BEFORE position n stay context.
    return list(ordered[n - 1:])
