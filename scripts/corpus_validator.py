"""Corpus integrity check + shared distinctive-term extractor + download utilities.

Language-agnostic, script-agnostic, mixed-corpus-tolerant. Two extractor paths:

  Whitespace path  (default): split on whitespace, casefold each token, drop
                              short tokens, count frequency, discard the top
                              20 % (function-word band), keep the next N as
                              the document's distinctive terms.

  CJK bigram path  (auto):    when the input is >30 % CJK characters
                              (Chinese, Japanese, Korean), whitespace
                              tokenisation fails because those scripts do
                              not separate words. Switch to a 2-character
                              sliding window, then apply the same Zipfian
                              filter. The mid-frequency bigrams are the
                              document's content terms.

The path is chosen per call via runtime CJK ratio. A single function,
`extract_distinctive_terms()`, returns a list[str] regardless of which
path ran. Mixed-language corpora work without configuration.

This module also hosts the framework's corpus acquisition discipline
(genesis Part XIX): binary validation of downloaded files, fallback-URL
download with browser User-Agent and one retry on timeout, and a
directory-level audit that runs both binary validation and the
content-vs-filename check on every PDF.

Public API:
  extract_distinctive_terms(text, n=20)
  validate_corpus_entry(path, expected_title_keywords=None)
  validate_downloaded_file(path)           -- binary PDF integrity (Part XIX rule 1)
  download_with_fallback(urls, dest)       -- ordered fallback + retry (rules 3-5)
  audit_corpus_directory(context_dir)      -- pre-run sweep over input/context/
  DOWNLOAD_USER_AGENT                       -- browser-like UA string
"""

from __future__ import annotations

import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Iterable


# Browser-like User-Agent. Government and institutional portals reject
# requests with Python's default urllib UA. Per genesis Part XIX rule 3,
# every corpus download must present this string.
DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


_MIN_FILE_BYTES = 10 * 1024
_HTML_MARKERS = ("<!doctype", "<html", "<head")


_CJK_RANGES = [
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs (Chinese, Japanese kanji, Korean hanja)
    (0x3040, 0x309F),   # Hiragana
    (0x30A0, 0x30FF),   # Katakana
    (0xAC00, 0xD7AF),   # Hangul syllables
]


def _is_cjk_char(ch: str) -> bool:
    if not ch:
        return False
    cp = ord(ch)
    for lo, hi in _CJK_RANGES:
        if lo <= cp <= hi:
            return True
    return False


def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if _is_cjk_char(ch))
    return cjk / len(text)


def _whitespace_tokens(text: str, min_token_len: int = 3) -> list[str]:
    """Casefold + strip punctuation. Drop tokens shorter than min_token_len."""
    out = []
    for raw in text.split():
        tok = re.sub(r"^[\W_]+|[\W_]+$", "", raw, flags=re.UNICODE).casefold()
        if len(tok) >= min_token_len:
            out.append(tok)
    return out


def _bigram_tokens(text: str) -> list[str]:
    """2-character sliding window. Skip pairs containing whitespace,
    punctuation, or digits; keep pairs of letters / CJK characters."""
    out = []
    n = len(text)
    for i in range(n - 1):
        a, b = text[i], text[i + 1]
        if (a.isalpha() or _is_cjk_char(a)) and (b.isalpha() or _is_cjk_char(b)):
            out.append(a + b)
    return out


def extract_distinctive_terms(
    text: str,
    n: int = 20,
    *,
    discard_top_fraction: float = 0.20,
    cjk_threshold: float = 0.30,
) -> list[str]:
    """Return the document's `n` distinctive content terms.

    Runtime CJK detection picks the tokenisation strategy. The same Zipfian
    frequency filter (discard top `discard_top_fraction`, keep next `n`)
    runs on whichever token stream the path produced. Caller-agnostic:
    output is always a list of strings to be compared with `in` against
    other strings.
    """
    if not text:
        return []
    if _cjk_ratio(text) > cjk_threshold:
        tokens = _bigram_tokens(text)
    else:
        tokens = _whitespace_tokens(text)
    if not tokens:
        return []
    counts = Counter(tokens)
    ranked = counts.most_common()
    n_discard = int(len(ranked) * discard_top_fraction)
    return [tok for tok, _ in ranked[n_discard:][: max(0, n)]]


def _filename_tokens(filename: str) -> list[str]:
    """Casefold filename stem split on _ - . and whitespace."""
    stem = Path(filename).stem
    return [t.casefold() for t in re.split(r"[_\-.\s]+", stem) if t]


def read_first_page_text(path: Path) -> str:
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        if not reader.pages:
            return ""
        return (reader.pages[0].extract_text() or "")
    except Exception:
        return ""


def validate_corpus_entry(
    path: Path,
    expected_title_keywords: Iterable[str] | None = None,
) -> tuple[bool, str, list[str]]:
    """Return (valid, first_page_excerpt, matched_keywords).

    Default behaviour: extract the top 10 distinctive terms from the
    document's first page (Zipfian + CJK-aware) and check whether at
    least 1 of them appears in the filename slug. If the document was
    a wrong-file download, its content terms will diverge from the slug
    and the check flags it.

    expected_title_keywords overrides the first-page extraction when
    callers want to enforce specific markers.
    """
    first_page = read_first_page_text(path)
    excerpt = (first_page or "")[:600].replace("\n", " ").strip()
    if not first_page.strip():
        return (False, excerpt, [])

    if expected_title_keywords:
        keywords = [str(k).casefold() for k in expected_title_keywords if k]
    else:
        keywords = extract_distinctive_terms(first_page, n=10)

    if not keywords:
        return (True, excerpt, [])

    filename_blob = " ".join(_filename_tokens(path.name))
    matched = [kw for kw in keywords if kw in filename_blob]
    return (len(matched) >= 1, excerpt, matched)


# ---------------------------------------------------------------------------
# Corpus acquisition discipline (genesis Part XIX)
# ---------------------------------------------------------------------------


def validate_downloaded_file(path: Path) -> tuple[bool, str]:
    """Binary PDF integrity check per Part XIX rule 1.

    Returns (valid, reason). Valid iff:
      - file exists and size > 10KB
      - first 4 bytes are b"%PDF"
      - first 100 bytes (decoded latin-1, casefolded) contain none of
        "<!doctype", "<html", "<head"

    Government portals frequently serve HTML landing pages from URLs that
    look like PDF endpoints. This catches them before they enter input/context/.
    """
    if not path.exists():
        return (False, "too small or missing")
    try:
        size = path.stat().st_size
    except OSError as e:
        return (False, f"stat failed: {e}")
    if size <= _MIN_FILE_BYTES:
        return (False, "too small or missing")
    try:
        with path.open("rb") as fh:
            head = fh.read(100)
    except OSError as e:
        return (False, f"read failed: {e}")
    if not head.startswith(b"%PDF"):
        return (False, "not a PDF header")
    head_text = head.decode("latin-1", errors="replace").casefold()
    if any(marker in head_text for marker in _HTML_MARKERS):
        return (False, "HTML not PDF")
    return (True, "ok")


def _attempt_download(url: str, dest: Path, timeout: int) -> tuple[bool, str]:
    """Single download attempt. Returns (success, message)."""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": DOWNLOAD_USER_AGENT, "Accept": "application/pdf,*/*"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            blob = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        return (False, f"{type(e).__name__}: {e}")
    except Exception as e:
        return (False, f"{type(e).__name__}: {e}")
    if not blob:
        return (False, "empty body")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
    except OSError as e:
        return (False, f"write failed: {e}")
    return (True, f"wrote {len(blob)} bytes")


def _is_transient_error(message: str) -> bool:
    """Identify timeout / connection errors worth retrying once (rule 5)."""
    m = (message or "").lower()
    return (
        "timeout" in m
        or "timed out" in m
        or "connection" in m
        or "reset" in m
        or "urlerror" in m
    )


def download_with_fallback(
    urls: list[str], dest: Path, timeout: int = 30,
) -> tuple[bool, str, str]:
    """Try each URL in order with a browser UA. On transient errors, sleep
    10s and retry once. Validate the result with validate_downloaded_file
    before accepting; on validation failure, delete the file and move on.

    Returns (success, winning_url, reason).
    """
    for url in urls:
        ok, msg = _attempt_download(url, dest, timeout=timeout)
        if not ok and _is_transient_error(msg):
            # Part XIX rule 5: retry once after a brief pause.
            print(f"[corpus] transient on {url[:80]}: {msg}; sleeping 10s and retrying once",
                  file=sys.stderr, flush=True)
            time.sleep(10)
            ok, msg = _attempt_download(url, dest, timeout=timeout)
        if not ok:
            if dest.exists():
                try: dest.unlink()
                except OSError: pass
            continue
        valid, reason = validate_downloaded_file(dest)
        if not valid:
            try: dest.unlink()
            except OSError: pass
            continue
        return (True, url, "ok")
    return (False, "", "all URLs failed")


def audit_corpus_directory(
    context_dir: Path,
) -> list[tuple[str, bool, str]]:
    """Sweep input/context/ and report (filename, valid, reason) for each PDF.

    Combines the binary check (validate_downloaded_file) and the
    content-vs-filename check (validate_corpus_entry). A file is valid
    only when both checks pass. Prints a summary table to stderr and
    returns the list so callers can act on it.
    """
    out: list[tuple[str, bool, str]] = []
    if not context_dir.exists():
        print(f"[corpus] audit target does not exist: {context_dir}", file=sys.stderr)
        return out
    pdfs = sorted(p for p in context_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    if not pdfs:
        print(f"[corpus] audit found no PDFs in {context_dir}", file=sys.stderr)
        return out

    print(f"\n=== corpus audit: {context_dir} ({len(pdfs)} PDFs) ===", file=sys.stderr)
    name_w = max(len(p.name) for p in pdfs)
    print(f"{'file'.ljust(name_w)}  status   detail", file=sys.stderr)
    print("-" * (name_w + 40), file=sys.stderr)
    n_ok = n_bad_binary = n_bad_content = 0
    for path in pdfs:
        bin_ok, bin_reason = validate_downloaded_file(path)
        if not bin_ok:
            out.append((path.name, False, f"binary: {bin_reason}"))
            n_bad_binary += 1
            status = "BAD-BIN"
            detail = bin_reason
        else:
            content_ok, _excerpt, matched = validate_corpus_entry(path)
            if content_ok:
                out.append((path.name, True, f"ok ({len(matched)} keyword(s) matched)"))
                n_ok += 1
                status = "OK"
                detail = f"{len(matched)} keyword(s) matched filename"
            else:
                out.append((path.name, False, f"content: 0 keywords matched filename"))
                n_bad_content += 1
                status = "MISMATCH"
                detail = "first-page keywords do not appear in filename"
        print(f"{path.name.ljust(name_w)}  {status:8s} {detail}", file=sys.stderr)

    print(
        f"\n[corpus] audit summary: OK={n_ok}  MISMATCH={n_bad_content}  BAD-BIN={n_bad_binary}  "
        f"TOTAL={len(pdfs)}",
        file=sys.stderr, flush=True,
    )
    return out
