"""Language detection + script direction (Pass D / INFRA-028).

Two concerns, deliberately separate:

* detect_language(text) -> ISO 639-1 code (per document, dominant language).
  Uses the lightweight, offline `langdetect` library (no network, no large
  model). Imported lazily: if it is not installed, detection returns "und"
  with a one-time warning and callers fall back to their default model.

* text_direction(text) -> "rtl" | "ltr", and rtl_script_tag(text). These are
  derived purely from Unicode script ranges — NO dependency, NO hardcoded
  language assumption — so direction-aware output works even when langdetect
  is absent. RTL is decided from the content's own characters.
"""

from __future__ import annotations

import sys

# RTL Unicode blocks: Hebrew, Arabic (+ supplements / presentation forms),
# Syriac, Thaana, NKo, Samaritan, Mandaic, Arabic Math, etc.
_RTL_RANGES = (
    (0x0590, 0x05FF),  # Hebrew
    (0x0600, 0x06FF),  # Arabic
    (0x0700, 0x074F),  # Syriac
    (0x0750, 0x077F),  # Arabic Supplement
    (0x0780, 0x07BF),  # Thaana
    (0x07C0, 0x07FF),  # NKo
    (0x0800, 0x083F),  # Samaritan
    (0x0840, 0x085F),  # Mandaic
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0xFB1D, 0xFB4F),  # Hebrew presentation forms
    (0xFB50, 0xFDFF),  # Arabic presentation forms-A
    (0xFE70, 0xFEFF),  # Arabic presentation forms-B
    (0x10E60, 0x10E7F),  # Rumi numeral symbols
    (0x1EE00, 0x1EEFF),  # Arabic Mathematical Alphabetic Symbols
)

# ISO 639-1/639-3 codes whose primary script is RTL (used only as a helper;
# direction itself is decided from content, not from this list).
_RTL_LANGS = {"ar", "he", "fa", "ur", "ps", "sd", "yi", "dv", "ckb", "ug", "arc"}

_DETECT_WARNED = [False]


def _is_rtl_char(ch: str) -> bool:
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in _RTL_RANGES)


def text_direction(text: str, *, threshold: float = 0.3) -> str:
    """Return "rtl" if RTL-script letters make up at least `threshold` of the
    alphabetic characters, else "ltr". Language-agnostic: decided from the
    content's own script. Empty / non-alphabetic -> "ltr"."""
    if not text:
        return "ltr"
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "ltr"
    rtl = sum(1 for c in letters if _is_rtl_char(c))
    return "rtl" if (rtl / len(letters)) >= threshold else "ltr"


def rtl_script_tag(text: str) -> str | None:
    """Best-effort BCP-47-ish bidi language tag from the dominant RTL script
    block in the text ("ar" or "he"), or None if no RTL content. Derived from
    content, not assumed."""
    arabic = hebrew = 0
    for c in text or "":
        o = ord(c)
        if (0x0590 <= o <= 0x05FF) or (0xFB1D <= o <= 0xFB4F):
            hebrew += 1
        elif ((0x0600 <= o <= 0x06FF) or (0x0750 <= o <= 0x077F)
              or (0x08A0 <= o <= 0x08FF) or (0xFB50 <= o <= 0xFDFF)
              or (0xFE70 <= o <= 0xFEFF)):
            arabic += 1
    if arabic == 0 and hebrew == 0:
        return None
    return "ar" if arabic >= hebrew else "he"


def is_rtl_language(code: str) -> bool:
    return (code or "").lower() in _RTL_LANGS


def detect_language(text: str, *, sample_chars: int = 2000) -> str:
    """Return the dominant ISO 639-1 language code for a document's text, or
    "und" if it cannot be determined (empty text, or langdetect not installed).
    Cheap: only the first `sample_chars` characters are inspected."""
    if not text or not text.strip():
        return "und"
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 0  # deterministic results across runs
    except ImportError:
        if not _DETECT_WARNED[0]:
            print("[language_detect] WARN: optional library 'langdetect' is not "
                  "installed; per-document language detection is disabled "
                  "(treating documents as 'und' -> default embedding model). "
                  "Install it (see requirements.txt) to enable multilingual "
                  "model selection.", file=sys.stderr, flush=True)
            _DETECT_WARNED[0] = True
        return "und"
    try:
        return detect(text[:sample_chars])
    except Exception:
        return "und"
