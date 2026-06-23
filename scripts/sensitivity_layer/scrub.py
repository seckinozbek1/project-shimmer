"""LAW-IV privacy SCRUBBER + leak gate (Mechanism 1, relocated in Phase 1b).

Always-on masking of operator-marked spans to [REDACTED] across every operator-facing
artifact, plus the post-apply grep that VERIFIES no span survives (a survivor BLOCKs,
a span located nowhere BLOCKs). Deterministic and LOCAL: no model, no web. This is the
testable privacy core the live phase and the verify gate both exercise.

BOUNDARY (shape a, INFRA-039 corrective): this module PRODUCES scrubbed content and the
survivor verdict and HANDS THEM BACK to the pipeline; it NEVER renders the deliverable
or looks up convention categories. The editorial render (amendment_render.
write_amendment_deliverables) and convention-category lookup stay on the pipeline side.
There is no dependency edge from here into editorial logic. text_extract is neutral
infrastructure (reads a .docx so the survivor grep can see rendered text).

Mechanism 2 (the dormant mask_for_external engine, LAYER_ACTIVE=False) is a SEPARATE
concern in this package; this scrubber does NOT call it and does NOT depend on it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import text_extract
from . import redaction_detect

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REDACTION_PLACEHOLDER = "[REDACTED]"


# --- Robust, deterministic, LOCAL span matching (no model, no web; LAW-IV) ------
# A 7B clerk's span rarely matches the document byte-for-byte: it drops a leading
# definite article, merges a name with an adjacent id across connective text, and
# varies whitespace/diacritics. Literal `target in text` silently misses those. The
# tolerant matcher below stays deterministic and bounded; it is LANGUAGE-NEUTRAL by
# construction - every script/diacritic/article string it needs comes from the DATA
# resource (redaction_detect.normalization_classes), never from a literal in code.
_NORM_CLASSES = None


def _norm_classes():
    """Language-neutral normalization building blocks, loaded once from the per-
    language DATA resource (config/language_redaction_cues.json). No literals here."""
    global _NORM_CLASSES
    if _NORM_CLASSES is None:
        _NORM_CLASSES = redaction_detect.normalization_classes(_PROJECT_ROOT)
    return _NORM_CLASSES


def _redaction_span_regex(span):
    """Compile a tolerant, BOUNDED regex for one redaction span: optional leading
    definite article (DATA), diacritic-insensitive tokens (DATA), and a bounded
    connective gap between tokens (whitespace + the configured script range from
    DATA + universal ASCII separators). Returns a compiled pattern, or None for an
    empty span. Deterministic and local - no model, no language literal in code."""
    toks = [t for t in re.split(r"\s+", str(span or "").strip()) if t]
    if not toks:
        return None
    nc = _norm_classes()
    diac = nc.get("diacritics_class") or ""
    script = nc.get("script_class") or ""
    articles = [a for a in (nc.get("definite_articles") or []) if a]
    fill = ("[%s]*" % diac) if diac else ""
    tok_pats = [fill.join(re.escape(ch) for ch in tok) for tok in toks]
    # connective gap: whitespace + configured script chars (covers script-native
    # punctuation, e.g. Arabic comma/semicolon, which fall inside the script range)
    # + universal ASCII separators. Bounded so a match can never run away.
    gap = r"[\s%s,/]{0,24}" % script
    body = gap.join(tok_pats)
    prefix = ("(?:%s)?" % "|".join(re.escape(a) for a in articles)) if articles else ""
    try:
        return re.compile(prefix + body, re.IGNORECASE)
    except re.error:
        return None


def _sub_span(text, span, repl):
    """Replace `span` in `text`, tolerating benign Arabic variation. Returns
    (new_text, n_substitutions). Literal first (fast, exact), then the tolerant
    bounded regex."""
    if not isinstance(text, str) or not span:
        return text, 0
    if span in text:                                 # exact path
        return text.replace(span, repl), text.count(span)
    rx = _redaction_span_regex(span)                 # tolerant path
    if rx is None:
        return text, 0
    return rx.subn(repl, text)


def _count_span(text, span):
    """How many times `span` occurs in `text` under the SAME matcher used to scrub
    it (so the post-apply grep sees exactly what the apply targets - never a
    vacuous zero). Counts without mutating."""
    if not isinstance(text, str) or not span:
        return 0
    if span in text:
        return text.count(span)
    rx = _redaction_span_regex(span)
    return len(rx.findall(text)) if rx is not None else 0


def _norm_span_key(span):
    """A normalized de-dupe key for a span (LANGUAGE-NEUTRAL): lowercased, diacritics
    removed (DATA), leading definite article stripped (DATA), whitespace collapsed.
    So a model span and a deterministic span for the same text de-dupe to one. No
    language literal in code - the diacritics/article strings come from the resource."""
    s = " ".join(str(span or "").split()).strip().lower()
    nc = _norm_classes()
    diac = nc.get("diacritics_class") or ""
    if diac:
        s = re.sub("[%s]" % diac, "", s)
    for art in (nc.get("definite_articles") or []):
        a = str(art).lower()
        if a and s.startswith(a):
            s = s[len(a):]
            break
    return s.strip()


def _merge_redaction_proposals(*lists):
    """UNION redaction proposals from multiple sources (deterministic detectors +
    the clerk model), de-duped by NORMALIZED span (reuse the Task 1 normalization).
    Earlier lists win on a key collision, so deterministic items (passed first)
    keep their rule_id/category attribution. Never replaces - it merges, so the
    model still contributes spans the detectors do not cover, and the detectors
    guarantee authorized regular shapes are present regardless of model recall."""
    merged, seen = [], set()
    for lst in lists:
        for it in (lst or []):
            if not isinstance(it, dict):
                continue
            span = (it.get("span") or it.get("text") or "").strip()
            if not span:
                continue
            key = _norm_span_key(span)
            if key in seen:
                continue
            seen.add(key)
            merged.append(it)
    return merged


def _span_list(reds):
    """Normalize a redaction list into [(span, replacement), ...], dropping items
    with no span. `text` is accepted as a span alias (INFRA-037 tolerance)."""
    out = []
    for red in reds or []:
        if not isinstance(red, dict):
            continue
        span = (red.get("span") or red.get("text") or "").strip()
        if span:
            out.append((span, red.get("replacement") or _REDACTION_PLACEHOLDER))
    return out


def _redact_text(text, reds):
    """Scrub every redaction span from a flat text. Returns (new_text, {span: n})."""
    counts = {}
    for span, repl in _span_list(reds):
        text, n = _sub_span(text, span, repl)
        counts[span] = counts.get(span, 0) + n
    return text, counts


def _redact_obj(obj, reds):
    """Recursively scrub every redaction span from EVERY string leaf of a JSON-like
    object (the amendments master), so no master field can leak a span regardless of
    which field it sits in. Returns (new_obj, n_substitutions)."""
    spans = _span_list(reds)
    total = 0

    def walk(o):
        nonlocal total
        if isinstance(o, str):
            t = o
            for span, repl in spans:
                t, n = _sub_span(t, span, repl)
                total += n
            return t
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        return o

    return walk(obj), total


def _apply_redactions_to_master(master, redactions):
    """Apply approved redactions to the canonical amendments master IN PLACE
    (INFRA-033), scrubbing EVERY string leaf - not only original_text/proposed_text/
    comment - so no field can leak a span. Returns the number of substitutions."""
    scrubbed, n = _redact_obj(master, redactions)
    # in-place: preserve identity for callers holding the reference
    master.clear()
    master.update(scrubbed)
    if n:
        master["_redaction_applied"] = True
    return n


def _redaction_outcome(artifacts, reds):
    """PURE (no IO, no model): scrub each redaction span from every artifact text,
    then VERIFY no span survives. `artifacts` is {name: text}. Returns a report:
      proposed     : number of distinct spans
      applied      : spans located (>=1 substitution somewhere)
      dropped      : spans located NOWHERE (failed substitution -> BLOCK, never silent)
      survivors    : {span: [artifact names]} still containing the span AFTER scrub
      by_artifact  : {name: substitutions} (span-based, actual, not proposal count)
      total_subs   : sum of by_artifact
      scrubbed     : {name: scrubbed text}
    Deterministic and local; this is the testable core both the live phase and the
    verify gate exercise."""
    spans = _span_list(reds)
    located = {span: 0 for span, _ in spans}
    by_artifact = {}
    scrubbed = {}
    for name, text in artifacts.items():
        t = text
        here = 0
        for span, repl in spans:
            t, n = _sub_span(t, span, repl)
            located[span] += n
            here += n
        scrubbed[name] = t
        by_artifact[name] = here
    survivors = {}
    for name, t in scrubbed.items():
        for span, _ in spans:
            if _count_span(t, span) > 0:
                survivors.setdefault(span, []).append(name)
    dropped = [span for span, _ in spans if located[span] == 0]
    return {
        "proposed": len(spans),
        "applied": sum(1 for span, _ in spans if located[span] > 0),
        "dropped": dropped,
        "survivors": survivors,
        "by_artifact": by_artifact,
        "total_subs": sum(by_artifact.values()),
        "scrubbed": scrubbed,
    }


# --- shape (a) hand-back: produce scrubbed content, pipeline renders, then verify ---

def scrub_master_and_body(master, reds, doc_text):
    """PRIVACY (shape a, step 1): scrub the canonical amendments master and the body
    canvas. Returns (scrubbed_master, body_red, located, by_artifact). Contains NO
    editorial logic: it does not render or look up convention categories - the
    pipeline renders the scrubbed master AFTER this returns."""
    located = {span: 0 for span, _ in _span_list(reds)}
    scrubbed_master, n_master = _redact_obj(master, reds)
    body_red, body_counts = _redact_text(doc_text or "", reds)
    for span, n in (body_counts or {}).items():
        if span in located:
            located[span] += n
    for span, _ in _span_list(reds):
        before = _count_span(json.dumps(master, ensure_ascii=False), span)
        after = _count_span(json.dumps(scrubbed_master, ensure_ascii=False), span)
        located[span] += max(0, before - after)
    by_artifact = {"amendments_master": n_master}
    return scrubbed_master, body_red, located, by_artifact


def scrub_text_artifacts_and_verify(reds, info, located, by_artifact):
    """PRIVACY (shape a, step 2): scrub the INDEPENDENT text artifacts on disk, then
    VERIFY by re-grepping EVERY final artifact (incl. the rendered docx) for any
    surviving span. The pipeline has already rendered the master deliverables before
    calling this. Returns the report dict (dropped/survivors/...) the caller turns
    into BLOCKs. Reads/writes files and uses text_extract (neutral infra); makes no
    editorial call."""
    def _bump(counts):
        for span, n in (counts or {}).items():
            if span in located:
                located[span] += n

    # (2) independent text artifacts (NOT master-derived): scrub on disk.
    text_artifact_keys = ("per_agent_deliverable", "context_summary", "operative_summary")
    for key in text_artifact_keys:
        p = info.get(key)
        if not p or not Path(p).exists():
            continue
        try:
            original = Path(p).read_text(encoding="utf-8")
        except Exception:
            continue
        new, counts = _redact_text(original, reds)
        _bump(counts)
        by_artifact[key] = sum(counts.values())
        if new != original:
            Path(p).write_text(new, encoding="utf-8")

    # (3) THE REAL GATE: re-read EVERY final on-disk artifact (incl. rendered docx
    #     text) and grep each span. Verify the OUTCOME, not the process.
    survivors = {}
    verify_keys = ("amendments_json", "amendments_md", "amendments_docx",
                   "per_agent_deliverable", "context_summary", "operative_summary")
    for key in verify_keys:
        p = info.get(key)
        if not p or not Path(p).exists():
            continue
        try:
            text = (text_extract.extract_text(Path(p))
                    if str(p).lower().endswith(".docx")
                    else Path(p).read_text(encoding="utf-8"))
        except Exception:
            # if we cannot read an artifact to verify it, we cannot confirm it
            # clean -> treat as a survivor of every span (fail safe, LAW-IV).
            for span, _ in _span_list(reds):
                survivors.setdefault(span, []).append(f"{key} (unreadable)")
            continue
        for span, _ in _span_list(reds):
            if _count_span(text, span) > 0:
                survivors.setdefault(span, []).append(key)

    dropped = [span for span, _ in _span_list(reds) if located[span] == 0]
    return {
        "proposed": len(_span_list(reds)),
        "applied": sum(1 for span, _ in _span_list(reds) if located[span] > 0),
        "dropped": dropped,
        "survivors": survivors,
        "by_artifact": by_artifact,
        "total_subs": sum(by_artifact.values()),
        "located": located,
    }
