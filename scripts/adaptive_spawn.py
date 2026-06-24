"""Adaptive asset spawning (genesis Part X + Part XVIII Section F).

Reads from input/context/ (per Part XVIII Section F amendment to Part X).
Each spawn helper is no-op-if-present and never raises.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import durable_paths
import text_extract

# Generic institutional name extractor: capitalized multi-word names ending in
# institution-marker words. Domain-specific institutions (any government, any
# regional bloc, any standards body, any religious-jurisprudential body, etc.)
# are discovered by this pattern at runtime from input/context/. The framework
# never hardcodes the names of specific institutions.
_INSTITUTION_PATTERNS = [
    re.compile(
        r"\b([A-Z][A-Za-z]+(?:\s+(?:of|for|on|and|the)?\s*[A-Z][A-Za-z]+){0,5}\s+"
        r"(?:Assembly|Council|Commission|Committee|Organization|Organisation|Bank|Fund|"
        r"Court|Tribunal|Union|Strategy|Agency|Authority|Institute|Bureau|Office|"
        r"Ministry|Department|Foundation|Society|Convention|Treaty|Pact|Charter|"
        r"Partnership|Forum|Alliance|Conference|Programme|Program|Initiative))\b"
    ),
    # Acronym uppercase 2-6 letters with optional digit suffix, standalone token.
    re.compile(r"\b([A-Z]{2,6}\d?)\b(?=\s+(?:[A-Z][a-z]|[a-z]+\s+(?:of|for|on)))"),
]

_CITATION_PATTERNS = [
    ("UN resolution symbol", re.compile(r"\b[ASE]/RES/\d+(?:/\d+)?(?:\(\d{4}\))?\b")),
    ("UN document symbol", re.compile(r"\b[ASE]/\d+/\d+\b")),
    ("standard reference", re.compile(r"\b(?:ISO|IEC|IEEE|RFC|ANSI|ASTM)[\s/\-]?\d+(?:[-:]\d+)*\b")),
    ("legal section", re.compile(r"\b(?:Article|Section|Chapter|Clause|Annex|Protocol)\s+[A-Z0-9]+(?:\.[A-Z0-9]+)*\b", re.IGNORECASE)),
    ("treaty name", re.compile(r"\b(?:Convention|Treaty|Charter|Declaration|Pact)\s+(?:of|on)\s+[A-Z][\w\s]+", re.IGNORECASE)),
    ("EU regulation", re.compile(r"\bRegulation\s*\(EU\)\s*\d+/\d+\b")),
    ("US executive order", re.compile(r"\bExecutive Order\s*\d+\b", re.IGNORECASE)),
]

_SPEECH_ACT_PATTERNS = [
    ("decide", re.compile(r"\b(decides?|decided)\b", re.IGNORECASE)),
    ("request", re.compile(r"\b(requests?|requested|calls upon|urges?|invites?)\b", re.IGNORECASE)),
    ("affirm", re.compile(r"\b(affirms?|reaffirms?|recognizes?|acknowledges?)\b", re.IGNORECASE)),
    ("condemn", re.compile(r"\b(condemns?|denounces?|deplores?)\b", re.IGNORECASE)),
    ("commit", re.compile(r"\b(commits? to|undertakes?|pledges?)\b", re.IGNORECASE)),
    ("authorize", re.compile(r"\b(authorizes?|empowers?|mandates?)\b", re.IGNORECASE)),
    ("declare", re.compile(r"\b(declares?|proclaims?|announces?)\b", re.IGNORECASE)),
    ("note", re.compile(r"\b(notes?|observes?|takes note of)\b", re.IGNORECASE)),
    ("require", re.compile(r"\b(require[sd]?|must|shall)\b", re.IGNORECASE)),
    ("recommend", re.compile(r"\b(recommend(s|ed|ation)?|suggest(s|ed)?)\b", re.IGNORECASE)),
]


@dataclass
class SpawnReport:
    actions: list = field(default_factory=list)
    corpus_files: list = field(default_factory=list)
    corpus_chars: int = 0

    def record(self, action): self.actions.append(action)

    def as_dict(self):
        return {"actions": self.actions, "corpus_files": self.corpus_files, "corpus_chars": self.corpus_chars,
                "created_count": sum(1 for a in self.actions if a.get("status") == "created"),
                "exists_count": sum(1 for a in self.actions if a.get("status") == "exists"),
                "error_count": sum(1 for a in self.actions if a.get("status") == "error")}


def spawn_all(project_root, *, overwrite=False):
    """Spawn from input/context/ per Part XVIII Section F."""
    report = SpawnReport()
    # Per Part XVIII, adaptive_spawn reads from input/context/. Fall back to input/ for legacy use.
    context_dir = project_root / "input" / "context"
    corpus = _load_corpus(context_dir if context_dir.exists() else project_root / "input")
    report.corpus_files = [name for name, _ in corpus]
    report.corpus_chars = sum(len(text) for _, text in corpus)
    combined = "\n\n".join(text for _, text in corpus)
    report.record(_spawn_situational_awareness(project_root, combined, corpus, overwrite=overwrite))
    report.record(_spawn_linguistic_identity(project_root, combined, corpus, overwrite=overwrite))
    report.record(_spawn_institution_registry(project_root, combined, overwrite=overwrite))
    # institution_registry is CONSUMED at runtime (search_router direct-fetch). The next two
    # (citation_convention, speech_acts_taxonomy) are PRODUCE-ONLY durable reference assets:
    # spawned here from the corpus but intentionally not consumed in the live agent path
    # (parallel to the audit-only SPEECH_ACT_TAGGER / CITATION_RESOLVER outputs). Retained as
    # durable reference / future opt-in hook; wire a consumer only via an operator-ratified change.
    report.record(_spawn_citation_convention(project_root, combined, overwrite=overwrite))
    report.record(_spawn_speech_acts_taxonomy(project_root, combined, overwrite=overwrite))
    report.record(_record_spawn_log(project_root, report))
    return report


def _load_corpus(input_dir):
    if not input_dir.exists(): return []
    out = []
    for p in sorted(input_dir.iterdir()):
        if not p.is_file(): continue
        # Shared format family; unsupported types warn instead of silent skip.
        if not text_extract.is_supported(p):
            text_extract.warn_unsupported(p, where=str(input_dir.name))
            continue
        text = text_extract.extract_text(p)
        if text.strip():
            out.append((p.name, text))
    return out


def _ok(status, path, reason): return {"status": status, "path": str(path), "reason": reason}


def _no_op_if_present(path, overwrite):
    return _ok("exists", path, "no-op-if-present") if (path.exists() and not overwrite) else None


def _spawn_situational_awareness(project_root, combined, corpus, *, overwrite):
    path = durable_paths.situational_awareness_path(project_root)
    if (skipped := _no_op_if_present(path, overwrite)) is not None: return skipped
    try:
        if not corpus: return _ok("skipped", path, "no input documents")
        # PAYLOAD-FREE BY CONSTRUCTION (INFRA-041 P3): institution CATEGORIES (the marker
        # word, e.g. Council/Commission), never the verbatim institution NAMES extracted
        # from operator content. The distribution of institution TYPES stays useful.
        institutions = _institution_category_counts(combined).most_common(10)
        languages = _language_indicators(combined)
        lines = ["# Situational awareness", "", "_Auto-generated by adaptive_spawn._", "",
                 f"- generated: {_now()}", f"- documents: {len(corpus)}",
                 f"- total characters: {len(combined)}", "", "## Languages observed"]
        for lang, conf in languages: lines.append(f"- {lang} (heuristic confidence {conf:.2f})")
        lines.append("\n## Institution categories observed")
        for cat, n in institutions: lines.append(f"- {cat}: {n}")
        lines.append("\n## Source documents")
        for name, _ in corpus: lines.append(f"- {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        return _ok("created", path, f"profile from {len(corpus)} documents")
    except Exception as e:
        return _ok("error", path, f"{type(e).__name__}: {e}")


def _spawn_linguistic_identity(project_root, combined, corpus, *, overwrite):
    path = durable_paths.linguistic_identity_path(project_root)
    if (skipped := _no_op_if_present(path, overwrite)) is not None: return skipped
    try:
        if not corpus:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Linguistic identity\n\n_No input documents yet._\n", encoding="utf-8")
            return _ok("created", path, "placeholder; no input corpus")
        sentences = _sentences(combined)
        register_markers = _register_markers(sentences)
        avg_len = sum(len(s) for s in sentences) / max(1, len(sentences))
        lines = ["# Linguistic identity", "", "_Auto-generated by adaptive_spawn._", "",
                 f"- generated: {_now()}", f"- documents: {len(corpus)}",
                 f"- sentences sampled: {len(sentences)}",
                 f"- average sentence length (chars): {avg_len:.1f}", "", "## Register markers"]
        # Register markers are counts of a FIXED formal-vocabulary list (not extracted
        # content), so they are payload-free. PAYLOAD-FREE BY CONSTRUCTION (INFRA-041 P3):
        # the verbatim "Representative sentences" section (quoted operator content) is DROPPED.
        for marker, count in register_markers.most_common(15): lines.append(f"- `{marker}`: {count}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        return _ok("created", path, f"register profile from {len(sentences)} sentences")
    except Exception as e:
        return _ok("error", path, f"{type(e).__name__}: {e}")


def _spawn_institution_registry(project_root, combined, *, overwrite):
    path = durable_paths.institution_registry_path(project_root)
    if (skipped := _no_op_if_present(path, overwrite)) is not None: return skipped
    try:
        counts = _institution_counts(combined)
        registry = {name: {"mentions": count, "official_url": None, "role": None,
                           "first_seen": _now(), "evidence_in_corpus": True}
                    for name, count in counts.items()}
        data = {"schema_version": "1.0.0", "generated_at": _now(), "source": "adaptive_spawn",
                "institutions": registry}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return _ok("created", path, f"{len(registry)} institutions extracted")
    except Exception as e:
        return _ok("error", path, f"{type(e).__name__}: {e}")


def _spawn_citation_convention(project_root, combined, *, overwrite):
    path = durable_paths.citation_convention_path(project_root)
    if (skipped := _no_op_if_present(path, overwrite)) is not None: return skipped
    try:
        rules = []
        for label, pattern in _CITATION_PATTERNS:
            samples = pattern.findall(combined)
            if not samples: continue
            # PAYLOAD-FREE BY CONSTRUCTION (INFRA-041 P3): store the matched pattern id +
            # count only. The verbatim substring examples were operator-corpus content (a
            # leak surface); they are DROPPED, not masked-after. The pattern + count remain
            # useful (CITES derivation uses the pattern, never the examples).
            rules.append({"name": label, "pattern": pattern.pattern,
                          "sample_count": len(samples)})
        data = {"schema_version": "1.0.0", "generated_at": _now(), "source": "adaptive_spawn", "rules": rules}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return _ok("created", path, f"{len(rules)} citation rules")
    except Exception as e:
        return _ok("error", path, f"{type(e).__name__}: {e}")


def _spawn_speech_acts_taxonomy(project_root, combined, *, overwrite):
    path = durable_paths.speech_acts_taxonomy_path(project_root)
    if (skipped := _no_op_if_present(path, overwrite)) is not None: return skipped
    try:
        acts = []
        for label, pattern in _SPEECH_ACT_PATTERNS:
            samples = pattern.findall(combined)
            if not samples: continue
            flat = []
            for s in samples:
                flat.append(s.lower() if isinstance(s, str) else " ".join(s).lower())
            acts.append({"name": label, "pattern": pattern.pattern,
                         "evidence_count": len(samples),
                         "examples": list(dict.fromkeys(flat))[:5]})
        data = {"schema_version": "1.0.0", "generated_at": _now(), "source": "adaptive_spawn",
                "speech_acts": acts}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return _ok("created", path, f"{len(acts)} speech acts")
    except Exception as e:
        return _ok("error", path, f"{type(e).__name__}: {e}")


def _record_spawn_log(project_root, report):
    """Append a per-run spawn-statistics record to the DURABLE runtime log
    (durable/learnings/spawn_log.jsonl) — NOT to the tracked prompts/project_rules.md.

    This is runtime telemetry about the durable learnings adaptive_spawn produces,
    so it lives co-located in durable/learnings/, is gitignored per the firewall
    (INFRA-030), and is regenerated/cleared with the other resettable learnings.
    The information is unchanged from the prior project_rules stamp (timestamp,
    corpus files, corpus chars, created, exists); only the destination moves out of
    the tracked file so a run can never dirty project_rules.md."""
    path = durable_paths.spawn_log_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": _now(),
            "corpus_files": len(report.corpus_files),
            "corpus_chars": report.corpus_chars,
            "created": sum(1 for a in report.actions if a.get("status") == "created"),
            "exists": sum(1 for a in report.actions if a.get("status") == "exists"),
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return _ok("logged", path, "spawn run recorded to durable runtime log")
    except Exception as e:
        return _ok("error", path, f"{type(e).__name__}: {e}")


def _institution_counts(text):
    c = Counter()
    for pat in _INSTITUTION_PATTERNS:
        for m in pat.finditer(text):
            c[m.group(1) if pat.groups else m.group(0)] += 1
    return c


# Institution-marker words: the CATEGORY vocabulary (the trailing marker of a captured
# institution name). Used so situational awareness stores the institution TYPE, never the
# verbatim operator-content name (INFRA-041 P3, payload-free by construction).
_INSTITUTION_MARKERS = frozenset({
    "Assembly", "Council", "Commission", "Committee", "Organization", "Organisation", "Bank",
    "Fund", "Court", "Tribunal", "Union", "Strategy", "Agency", "Authority", "Institute", "Bureau",
    "Office", "Ministry", "Department", "Foundation", "Society", "Convention", "Treaty", "Pact",
    "Charter", "Partnership", "Forum", "Alliance", "Conference", "Programme", "Program", "Initiative"})


def _institution_category_counts(text):
    """Count institutions by CATEGORY (the marker word in the captured name), never by the
    verbatim name. The acronym pattern (no marker word) is categorized as 'acronym'."""
    c = Counter()
    for pat in _INSTITUTION_PATTERNS:
        for m in pat.finditer(text):
            name = m.group(1) if pat.groups else m.group(0)
            cat = next((w for w in reversed(name.split()) if w in _INSTITUTION_MARKERS), None)
            c[cat or "acronym"] += 1
    return c


_SENT_RE = re.compile(r"(?<=[\.!?])\s+(?=[A-Z0-9])")


def _sentences(text):
    cleaned = re.sub(r"\s+", " ", text).strip()
    raw = _SENT_RE.split(cleaned)
    return [s for s in (r.strip() for r in raw) if 20 <= len(s) <= 400]


def _register_markers(sentences):
    c = Counter()
    formal_tokens = [
        "shall", "hereby", "pursuant to", "with respect to", "in accordance with",
        "notwithstanding", "thereof", "thereby", "hereinafter", "aforementioned",
        "Decides", "Requests", "Reaffirms", "Recalls", "Welcomes", "Calls upon",
        "Resolution", "Article", "Chapter", "Section", "Regulation", "Directive",
    ]
    text = " ".join(sentences)
    for tok in formal_tokens:
        n = len(re.compile(r"\b" + re.escape(tok) + r"\b").findall(text))
        if n: c[tok] = n
    return c


_LANG_HINTS = {
    "english": re.compile(r"\b(the|and|of|to|in|that|this)\b"),
    "french": re.compile(r"\b(le|la|les|une|que|dans|pour)\b"),
    "spanish": re.compile(r"\b(el|la|los|las|que|del|con|por)\b"),
    "arabic_script": re.compile(r"[؀-ۿ]"),
    "cyrillic_script": re.compile(r"[Ѐ-ӿ]"),
    "cjk_script": re.compile(r"[一-鿿]"),
}


def _language_indicators(text):
    if not text: return []
    total = max(1, len(text.split()))
    out = []
    for lang, rx in _LANG_HINTS.items():
        hits = len(rx.findall(text))
        conf = min(1.0, hits / max(50, total / 50))
        if hits: out.append((lang, conf))
    out.sort(key=lambda kv: kv[1], reverse=True)
    return out


def _now(): return datetime.now(timezone.utc).isoformat()
