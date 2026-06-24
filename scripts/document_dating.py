"""Document dating cascade (genesis Part XXIV).

Resolves a publication date for each document via the cascade. Order is
content-first, container-last, per Part XXIV's metadata hierarchy:

  1. Filename date pattern (operator-provided signal — authoritative).
  2. First-page numeric year extraction (content-derived — what the document
     says about itself). Supports both Western Arabic numerals (0-9) and
     Eastern Arabic numerals (٠-٩, U+0660-U+0669).
  3. PDF metadata creation/modification date (container-derived — low
     confidence because metadata is often a re-export artifact).
  4. Web search for "[document title] publication date" (last resort).

Each record carries:
  date              : ISO date string or None
  date_source       : "filename" | "content" | "metadata" | "web" | "unresolved"
  date_confidence   : "high" (filename/content) | "low" (metadata/web) |
                      "uncertain" (multiple conflicting candidates)
  date_candidates   : list of all years found across all sources, populated
                      only when date_confidence == "uncertain"

Stores results in durable/learnings/document_dates.json (protected; INFRA-030).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import text_extract


_FILENAME_PATTERNS = [
    re.compile(r"(\d{4})[-_.](\d{2})[-_.](\d{2})"),  # YYYY-MM-DD / YYYY_MM_DD
    re.compile(r"(\d{4})[-_.](\d{2})\b"),             # YYYY-MM / YYYY_MM
    re.compile(r"\b(20\d{2})\b"),                     # bare year (2000-2099)
    re.compile(r"\b(19\d{2})\b"),                     # bare year (1900-1999)
]


_TEXT_DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
               r"September|October|November|December)\s+(\d{4})\b", re.IGNORECASE),
    re.compile(r"\b(January|February|March|April|May|June|July|August|"
               r"September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b", re.IGNORECASE),
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b"),
    re.compile(r"\b(\d{4})\b"),  # last-resort bare year
]


_MONTHS = {m: i + 1 for i, m in enumerate([
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
])}


def _iso(year: int, month: int = 1, day: int = 1) -> str:
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return datetime(year, 1, 1).strftime("%Y-%m-%d")


def date_from_filename(filename: str) -> str | None:
    name = Path(filename).stem
    for i, pat in enumerate(_FILENAME_PATTERNS):
        m = pat.search(name)
        if m:
            try:
                if i == 0:
                    return _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                if i == 1:
                    return _iso(int(m.group(1)), int(m.group(2)))
                return _iso(int(m.group(1)))
            except ValueError:
                continue
    return None


def date_from_pdf_metadata(path: Path) -> tuple[str | None, str | None]:
    """Returns (iso_date, title_hint) using pypdf metadata."""
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        meta = reader.metadata or {}
    except Exception:
        return None, None
    title_hint = None
    try:
        title_hint = (meta.get("/Title") or "").strip() or None
    except Exception:
        title_hint = None
    raw = meta.get("/CreationDate") or meta.get("/ModDate")
    if not raw:
        return None, title_hint
    raw = str(raw)
    if raw.startswith("D:") and len(raw) >= 10:
        try:
            return _iso(int(raw[2:6]), int(raw[6:8]), int(raw[8:10])), title_hint
        except ValueError:
            return None, title_hint
    return None, title_hint


def date_from_text(text: str) -> str | None:
    text = text[:3000] if text else ""
    for i, pat in enumerate(_TEXT_DATE_PATTERNS):
        m = pat.search(text)
        if not m:
            continue
        try:
            if i == 0:
                return _iso(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
            if i == 1:
                return _iso(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
            if i == 2:
                return _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if i == 3:
                return _iso(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            return _iso(int(m.group(1)))
        except (ValueError, KeyError):
            continue
    return None


def date_from_web(title_hint: str | None, *, search_router=None, sensitive=False) -> str | None:
    """Last-resort: a web search for the document title's publication date.

    Caller passes a SearchRouter instance to keep this module decoupled.
    Returns None when no plausible year is recovered.

    LAW-IV outbound masking (INFRA-041 P2, chokepoint 4): under sensitive mode the web call
    is SUPPRESSED entirely (a masked title is meaningless for a date search, so the safe
    action is to withhold the egress, not mask it). The caller computes `sensitive` from the
    layer-active + run-sensitivity decision; the dating cascade then falls back to the local
    filename/metadata/content sources. `sensitive` defaults False so non-sensitive runs and
    unmodified callers are unchanged.
    """
    if not title_hint or search_router is None:
        return None
    if sensitive:
        return None  # suppress the BOOT web egress under sensitive mode (no title to the web)
    try:
        result = search_router.search(f"{title_hint} publication date",
                                       claim_type="date_event")
    except Exception:
        return None
    snippets = " ".join((h.title + " " + h.snippet) for h in result.hits[:5])
    return date_from_text(snippets)


def read_first_page(path: Path) -> str:
    """First-page text for the content date scan, across the shared format
    family. PDFs use page 1; every other supported format uses the start of its
    extracted text (the cascade scans only the first ~3000 chars). Unsupported
    or unreadable -> '' (the cascade falls back to filename / metadata / web)."""
    p = Path(path)
    if not text_extract.is_supported(p):
        return ""
    if p.suffix.lower() == ".pdf":
        pages = text_extract.extract_pages(p)
        return pages[0][1] if pages else ""
    return text_extract.extract_text(p)


# Eastern Arabic / Arabic-Indic numeral translation table. Per Part XXIV the
# implementation must recognize ٠-٩ in addition to 0-9 when scanning a
# document's first page for its self-stated year.
_EASTERN_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

_YEAR_PATTERN = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_YEAR_RANGE = range(1990, 2031)


def _year_from_filename(filename: str) -> str | None:
    """Genesis Part XXIV: filename year is the operator-provided signal,
    authoritative when present. Any 4-digit numeric sequence in the slug
    that falls in the valid range counts."""
    stem = Path(filename).stem
    stem_translated = stem.translate(_EASTERN_ARABIC_DIGITS)
    candidates = []
    for m in _YEAR_PATTERN.finditer(stem_translated):
        y = int(m.group(1))
        if y in _YEAR_RANGE:
            candidates.append(y)
    if not candidates:
        return None
    # Prefer the most recent year in the slug — operator slugs often include
    # historical references, but the trailing year typically marks the doc.
    return _iso(max(candidates))


def _years_from_first_page(text: str) -> list[int]:
    """Genesis Part XXIV: years are numeric, not linguistic. Extract every
    four-digit sequence (Western or Eastern Arabic) in the valid range from
    the first-page text. Returns the candidate list in document order with
    duplicates preserved so the caller can pick the most recent / vote."""
    if not text:
        return []
    head = text[:3000].translate(_EASTERN_ARABIC_DIGITS)
    out = []
    for m in _YEAR_PATTERN.finditer(head):
        y = int(m.group(1))
        if y in _YEAR_RANGE:
            out.append(y)
    return out


def resolve_dates(documents: list[Path], *, search_router=None, sensitive=False) -> list[dict]:
    """Run the full cascade for each document path per Part XXIV.

    `sensitive` (INFRA-041 P2, chokepoint 4) is threaded to the web last-resort: under
    sensitive mode the web egress is suppressed (the cascade stays local).

    Returns records with: filename, date, date_source, date_confidence,
    date_candidates (only on uncertain), title.

    Cascade order (Part XXIV):
      1. filename (operator signal — high confidence)
      2. content (first-page numeric year scan — high confidence,
         unless multiple conflicting candidates and no filename year)
      3. metadata (container signal — low confidence)
      4. web (last resort — low confidence)

    Uncertain rule: when the first-page scan finds multiple candidate
    years that conflict (e.g., a 2019 document referencing 2024 events),
    the cascade prefers the filename year if available; otherwise records
    all candidates, picks the most recent, and marks confidence="uncertain"
    so downstream consumers know to be skeptical.
    """
    out: list[dict] = []
    for path in documents:
        # Source 0: PDF metadata (still queried — needed for the title hint
        # and as fallback — but no longer trusted for the date).
        _meta_date, title = date_from_pdf_metadata(path)

        # Source 1: filename year (operator-provided, highest priority).
        filename_year_iso = _year_from_filename(path.name)
        filename_year = (
            int(filename_year_iso[:4]) if filename_year_iso else None
        )

        # Source 2: first-page numeric scan (content-derived).
        first_page_text = read_first_page(path)
        content_years = _years_from_first_page(first_page_text)
        content_unique = sorted(set(content_years), reverse=True)

        date: str | None = None
        source: str | None = None
        confidence: str | None = None
        candidates: list[int] = []

        if filename_year_iso:
            date = filename_year_iso
            source = "filename"
            confidence = "high"
            # Verify the filename year against content — if content has years
            # but none match the filename, flag as uncertain.
            if content_unique and filename_year not in content_unique:
                confidence = "uncertain"
                candidates = sorted(
                    set([filename_year] + content_unique), reverse=True
                )
        elif content_unique:
            if len(content_unique) == 1:
                date = _iso(content_unique[0])
                source = "content"
                confidence = "high"
            else:
                date = _iso(content_unique[0])  # most recent
                source = "content"
                confidence = "uncertain"
                candidates = content_unique
        else:
            # Source 3: container metadata (low confidence per Part XXIV).
            if _meta_date:
                date = _meta_date
                source = "metadata"
                confidence = "low"
            else:
                # Source 4: web search (last resort).
                web_date = date_from_web(
                    title or path.stem, search_router=search_router, sensitive=sensitive
                )
                if web_date:
                    date = web_date
                    source = "web"
                    confidence = "low"

        record: dict = {
            "filename": path.name,
            "date": date,
            "date_source": source or "unresolved",
            "date_confidence": confidence or "unresolved",
            "title": title,
        }
        if confidence == "uncertain" and candidates:
            record["date_candidates"] = [_iso(y) for y in candidates]
        out.append(record)
    return out


def write_dates(project_root: Path, dated_documents: list[dict]) -> Path:
    import durable_paths
    path = durable_paths.document_dates_path(project_root)  # protected durable learning (INFRA-030)
    payload = {"schema_version": "1.0.0", "generated_at": datetime.utcnow().isoformat() + "Z",
               "documents": dated_documents}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_dates(project_root: Path) -> list[dict]:
    import durable_paths
    path = durable_paths.document_dates_path(project_root)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("documents", [])
    except json.JSONDecodeError:
        return []
