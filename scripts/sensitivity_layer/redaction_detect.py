"""Deterministic, LOCAL redaction detectors (INFRA-038).

TWO NON-NEGOTIABLE PRINCIPLES, enforced by construction:

1. OPERATOR DEFINES SENSITIVITY, ENGINE NEVER JUDGES. A detector fires ONLY for a
   regular shape that a COMPILED OPERATOR RULE authorizes. Authorization is decided
   by scanning the operator rule's own text for operator-extensible "shape cue"
   words (in the DATA resource). No operator cue -> no detector. There are no
   engine-side default categories asserting sensitivity here.

2. LANGUAGE-NEUTRAL BY CONSTRUCTION. This module contains ZERO natural-language
   literals. The CODE carries only universal shapes (grouped digits; number +
   magnitude/currency). EVERY language-specific string (titles/honorifics,
   magnitude/scale words, currency words, connectives, definite articles, script/
   diacritic ranges, and the shape-authorization cues) is loaded at runtime from
   config/language_redaction_cues.json. The operator extends a language by editing
   that DATA file, never this code.

NO NEW EXTERNAL SURFACE: detection and cue computation are pure local string/regex
work over in-memory text. This module imports only json/re/pathlib/functools - no
socket, no http/requests/urllib, no API client, no translator. (Verified by the
gate's import grep.)

Each match emits a canonical INFRA-037 redaction item carrying the authorizing
operator rule's category + rule_id; replacement; method=REDACT; kind="redaction".
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_REPLACEMENT = "[REDACTED]"
_SHAPES = ("identifier", "figure", "name")


# --------------------------------------------------------------------------- data
@lru_cache(maxsize=8)
def load_cues(project_root: str) -> dict:
    """Load the per-language DATA resource (the ONLY place language strings live).
    Returns {} if absent - callers then authorize nothing (fail closed)."""
    p = Path(project_root) / "config" / "language_redaction_cues.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("languages", data) if isinstance(data, dict) else {}


def _union_list(cues: dict, key: str) -> list:
    out = []
    for entry in cues.values():
        v = entry.get(key) if isinstance(entry, dict) else None
        if isinstance(v, list):
            out.extend(str(x) for x in v if str(x).strip())
    # longest-first so multi-word vocabulary matches before its prefix
    return sorted(set(out), key=lambda s: (-len(s), s))


def _union_shape_cue(cues: dict, shape: str) -> list:
    out = []
    for entry in cues.values():
        sc = (entry.get("shape_cues") if isinstance(entry, dict) else None) or {}
        v = sc.get(shape)
        if isinstance(v, list):
            out.extend(str(x) for x in v if str(x).strip())
    return sorted(set(out), key=lambda s: (-len(s), s))


def _union_class(cues: dict, key: str) -> str:
    """Concatenate regex char-class fragments (script_class / diacritics_class)
    across languages into one class body."""
    frags = []
    for entry in cues.values():
        v = entry.get(key) if isinstance(entry, dict) else None
        if isinstance(v, str) and v:
            frags.append(v)
    return "".join(frags)


# ------------------------------------------------------------------- authorization
def authorized_shapes(operator_rules: list, cues: dict) -> dict:
    """Decide which regular-shape detectors each operator rule AUTHORIZES, by scanning
    the rule's own text for shape-cue vocabulary (DATA). Returns {shape: (rule_id,
    category)} using the first authorizing rule per shape. Engine asserts nothing on
    its own: with no operator rule (or no cue match) the result is empty."""
    auth = {}
    for shape in _SHAPES:
        cue_words = [c.lower() for c in _union_shape_cue(cues, shape)]
        if not cue_words:
            continue
        for r in operator_rules or []:
            text = str(r.get("rule", "")).lower()
            if any(cw in text for cw in cue_words):
                auth[shape] = (r.get("id"), r.get("category") or "confidentiality")
                break
    return auth


# ------------------------------------------------------------------- shape detect
# Universal SHAPE primitives. CODE carries only ASCII numeric/separator shapes; any
# script-specific EXTENSION (e.g. Arabic-Indic digits, Arabic decimal marks, extra
# dash glyphs) is sourced from the DATA resource at runtime, so this module holds no
# language/script literal. Identifier shape = >=3 digit groups (each >=2 digits)
# joined by a separator; figure shape = number adjacent to a DATA scale/currency word.
_ASCII_DIGIT = "0-9"
_ASCII_DECIMAL = ".,"
_ASCII_SEP = r"-\s"


def _digit_class(cues):
    return "[" + _ASCII_DIGIT + _union_class(cues, "digit_class_ext") + "]"


def _identifier_re(cues):
    d = _digit_class(cues)
    sep = "[" + _ASCII_SEP + _union_class(cues, "separator_ext") + "]"
    return re.compile(rf"{d}{{2,}}(?:{sep}{d}{{2,}}){{2,}}")


def _number_pat(cues):
    d = _digit_class(cues)
    dec = "[" + _ASCII_DECIMAL + _union_class(cues, "decimal_ext") + "]"
    return rf"{d}+(?:{dec}{d}+)*"


def _detect_identifiers(text: str, cues):
    for m in _identifier_re(cues).finditer(text):
        yield (m.group(0).strip(), m.start(), m.end())


def _detect_figures(text: str, scale_words: list, cues):
    """number + scale/currency word, OR scale/currency word + number (DATA words)."""
    if not scale_words:
        return
    num = _number_pat(cues)
    alt = "|".join(re.escape(w) for w in scale_words)
    pats = (re.compile(rf"{num}\s*(?:{alt})", re.IGNORECASE),
            re.compile(rf"(?:{alt})\s*{num}", re.IGNORECASE))
    seen = set()
    for pat in pats:
        for m in pat.finditer(text):
            key = (m.start(), m.end())
            if key not in seen:
                seen.add(key)
                yield (m.group(0).strip(), m.start(), m.end())


def _letter_tokens(text: str, letter_class: str):
    """LETTER-ONLY tokens (no punctuation/digits), using the DATA letter class so a
    name token never swallows a trailing comma/separator."""
    cls = (letter_class or "") + "A-Za-z"
    return [(m.group(0), m.start(), m.end())
            for m in re.finditer(rf"[{cls}]{{2,}}", text)]


def _detect_names(text, titles, name_stop, link_vocab, letter_class, id_spans,
                  *, max_tokens=3, id_tokens=2, window=40):
    """Propose a personal-name span from LOCAL cues only (no web, no translation),
    CONSERVATIVELY so it never corrupts ordinary prose/headings:
      (a) TITLE adjacency  - a title/honorific (DATA) immediately followed by up to
          max_tokens letter-only name tokens. High precision.
      (b) ID adjacency, LINK-GATED - the <=id_tokens letter tokens nearest a detected
          identifier, accepted ONLY when the gap between them and the id is a LINK:
          it contains at least one link word (connective / id-label vocabulary, DATA)
          and consists of nothing but link words + separators. A bare whitespace gap
          is NOT a link, so words merely sitting next to an id (a heading, trailing
          prose) are never grabbed. A name token is a letter-only run not in the
          name-stop vocabulary (titles / magnitudes / currencies / connectives /
          shape-cue label words - all DATA).
    Returns [(span, start, end, cue)]."""
    toks = _letter_tokens(text, letter_class)
    stop = {s.lower() for s in name_stop}
    titleset = {t.lower() for t in titles}
    link = sorted({c.lower() for c in link_vocab if c}, key=lambda s: (-len(s), s))
    out = []

    def _name_like(tok):
        return tok.lower() not in stop and len(tok) >= 2

    # (a) title adjacency
    for i, (tok, s, e) in enumerate(toks):
        if tok.lower() in titleset:
            picked = []
            for (t2, s2, e2) in toks[i + 1:i + 1 + max_tokens]:
                if _name_like(t2) and t2.lower() not in titleset:
                    picked.append((t2, s2, e2))
                else:
                    break
            if picked:
                out.append((text[picked[0][1]:picked[-1][2]], picked[0][1], picked[-1][2], "name:title"))

    # (b) id adjacency, LINK-gated (must contain a link word, not just whitespace)
    def _is_link(seg):
        s = seg.lower()
        if not any(w in s for w in link):
            return False               # no link word -> not a labelled name
        for w in link:
            s = s.replace(w, " ")
        return re.sub(r"[\s,/;:.\-]+", "", s) == ""

    for (_, ids, ide) in id_spans:
        before = [t for t in toks if ids - window <= t[2] <= ids
                  and _name_like(t[0]) and t[0].lower() not in titleset]
        if len(before) >= 2:
            run = before[-id_tokens:]
            if _is_link(text[run[-1][2]:ids]):
                out.append((text[run[0][1]:run[-1][2]], run[0][1], run[-1][2], "name:id-adjacency"))
        after = [t for t in toks if ide <= t[1] <= ide + window
                 and _name_like(t[0]) and t[0].lower() not in titleset]
        if len(after) >= 2:
            run = after[:id_tokens]
            if _is_link(text[ide:run[0][1]]):
                out.append((text[run[0][1]:run[-1][2]], run[0][1], run[-1][2], "name:id-adjacency"))

    uniq, seen = [], set()
    for span, s, e, cue in out:
        if span.strip() and (s, e) not in seen:
            seen.add((s, e))
            uniq.append((span.strip(), s, e, cue))
    return uniq


# ------------------------------------------------------------------------- emit
def _item(span, rule_id, category, detector):
    return {"ref": "document-level", "kind": "redaction", "confidence": "CONFIDENT",
            "span": span, "category": category, "replacement": _REPLACEMENT,
            "method": "REDACT", "rule_id": rule_id, "ref_ids": [],
            "source": "deterministic", "detector": detector}


def detect(project_root, text: str, operator_rules: list) -> list:
    """Run the deterministic local detectors over `text`, but ONLY for shapes an
    operator rule authorizes. Returns canonical INFRA-037 redaction items. Pure,
    local, no network/API/translator."""
    if not text or not operator_rules:
        return []
    cues = load_cues(str(project_root))
    if not cues:
        return []
    auth = authorized_shapes(operator_rules, cues)
    if not auth:
        return []

    items = []
    id_spans = []
    if "identifier" in auth:
        rid, cat = auth["identifier"]
        for span, s, e in _detect_identifiers(text, cues):
            id_spans.append((span, s, e))
            items.append(_item(span, rid, cat, "identifier"))
    else:
        # still locate identifiers for name-adjacency cues, but do NOT emit them
        id_spans = [(m.group(0), m.start(), m.end()) for m in _identifier_re(cues).finditer(text)]

    if "figure" in auth:
        rid, cat = auth["figure"]
        scale = _union_list(cues, "magnitude_words") + _union_list(cues, "currency_words")
        for span, s, e in _detect_figures(text, scale, cues):
            items.append(_item(span, rid, cat, "figure"))

    if "name" in auth:
        rid, cat = auth["name"]
        titles = _union_list(cues, "titles")
        connectives = _union_list(cues, "connectives")
        # shape-cue LABEL words (id-label phrases) tokenized -- they
        # (e.g. an id-label phrase) are neither names nor connectives, but they LINK a
        # name to an id and must not be swallowed as name tokens. All DATA.
        cue_tokens = set()
        for shape in _SHAPES:
            for phrase in _union_shape_cue(cues, shape):
                cue_tokens.update(phrase.lower().split())
        name_stop = set(titles) | set(connectives) | cue_tokens \
            | set(_union_list(cues, "magnitude_words")) | set(_union_list(cues, "currency_words"))
        link_vocab = set(connectives) | cue_tokens
        letter_class = _union_class(cues, "letter_class")
        for span, s, e, cue in _detect_names(text, titles, name_stop, link_vocab, letter_class, id_spans):
            items.append(_item(span, rid, cat, cue))
    return items


# ------------------------------------------------------------- normalization data
def normalization_classes(project_root) -> dict:
    """Expose the language-neutral building blocks the span-normalizer needs, sourced
    from DATA (so the normalizer in pipeline.py carries no language literals):
    a unioned diacritics class, a unioned script class, and the definite-article list."""
    cues = load_cues(str(project_root))
    return {
        "diacritics_class": _union_class(cues, "diacritics_class"),
        "script_class": _union_class(cues, "script_class"),
        "definite_articles": _union_list(cues, "definite_articles"),
        "connectives": _union_list(cues, "connectives"),
    }
