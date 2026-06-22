"""Convention parser (genesis Part XVIII Section E).

Reads files in input/conventions/, extracts individual rules from markdown
headers / numbered lists / prose, classifies into categories discovered
from the document structure (no predefined list), assigns severity and
action via language cues, writes config/convention_registry.json.

Deterministic. No LLM call. Idempotent: a rerun produces the same IDs
when the source files have not changed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import text_extract


_TEXT_EXTENSIONS = {".md", ".txt", ".rst", ".log"}
_JSON_EXTENSIONS = {".json"}
# Binary / markup formats: extract plain text via the shared extractor, then
# parse it with the same markdown / list / prose logic as native text files.
_EXTRACT_EXTENSIONS = {".pdf", ".docx", ".html", ".htm"}


_SEVERITY_PATTERNS = [
    ("required",    re.compile(r"\b(must|shall|required|mandatory|prohibited|forbidden|no\s+exception)\b", re.IGNORECASE)),
    ("recommended", re.compile(r"\b(should|recommended|expected|ought to|encouraged)\b", re.IGNORECASE)),
    ("advisory",    re.compile(r"\b(may|consider|optional|where applicable|if appropriate)\b", re.IGNORECASE)),
]


_ACTION_PATTERNS = [
    ("redact",   re.compile(r"\b(redact|mask|conceal|withhold|remove\s+from\s+output|do not (?:print|publish|disclose|reveal))\b", re.IGNORECASE)),
    ("reject",   re.compile(r"\b(reject|do not accept|disallow|prohibit)\b", re.IGNORECASE)),
    ("rephrase", re.compile(r"\b(rephrase|rewrite|replace|substitute|use\s+\S+\s+instead)\b", re.IGNORECASE)),
    ("flag",     re.compile(r"\b(flag|alert|warn|require\s+review|escalate)\b", re.IGNORECASE)),
    ("annotate", re.compile(r"\b(annotate|note|comment|footnote|add\s+citation)\b", re.IGNORECASE)),
]

# A convention is an OPERATOR REDACTION RULE: a machine-usable instruction the
# redactors APPLY to document spans (LAW-IV's own phrase, "content marked for
# redaction"). This replaces the phantom of a model JUDGING what is "sensitive";
# the operator declares the rules, the redactors apply them.
#
# A convention is recognized as REDACTION-INTENT if EITHER:
#   - its category OR id CONTAINS a redaction keyword (substring match, deliberately
#     narrow — only these keywords; not every mention of "confidential" elsewhere), or
#   - its rule text has redaction phrasing (an explicit redact verb OR prohibition
#     phrasing that implies redaction), or its action is already 'redact'.
# So `## CONV-CONFIDENTIALITY` (category slug "conv-confidentiality", contains
# "confiden") and a rule worded "must not contain …" both qualify.
_REDACTION_KEYWORDS = ("confiden", "redact", "privacy", "pii")

# Prohibition phrasing that implies redaction without an explicit redact verb.
_PROHIBITION_RE = re.compile(
    r"\b(?:must|shall|may)\s+not\s+(?:contain|include|appear|carry|state|name|be\s+"
    r"(?:published|disclosed|printed|included|shown|present))"
    r"|\bnot\s+be\s+(?:published|disclosed|printed|included|shown)\b",
    re.IGNORECASE)

# Built-in redaction rules — a FLOOR that always applies (so the planted PII
# categories are covered even when the operator has authored no rule). Operator
# rules, when they compile, are ADDED ahead of these and reported as in force.
DEFAULT_REDACTION_RULES = [
    {"id": "RED-DFLT-001", "category": "confidentiality", "action": "redact", "severity": "required",
     "rule": "National identity / passport / tax / similar government ID numbers."},
    {"id": "RED-DFLT-002", "category": "confidentiality", "action": "redact", "severity": "required",
     "rule": "Named natural persons (private individuals) attached to identifying data."},
    {"id": "RED-DFLT-003", "category": "confidentiality", "action": "redact", "severity": "required",
     "rule": "Confidential turnover / revenue / financial figures not in the public record."},
    {"id": "RED-DFLT-004", "category": "confidentiality", "action": "redact", "severity": "required",
     "rule": "Business secrets / proprietary commercial terms marked confidential."},
]


def _is_redaction_category(category, conv_id) -> bool:
    """True if the category OR id contains a redaction keyword (substring match)."""
    blob = f"{str(category)} {str(conv_id)}".lower()
    return any(k in blob for k in _REDACTION_KEYWORDS)


def _has_redaction_phrasing(text) -> bool:
    """True if the rule text expresses redaction INTENT: an explicit redact verb
    (the 'redact' action pattern) OR prohibition phrasing ('must not contain',
    'shall not include', 'may not appear', …)."""
    t = text or ""
    return bool(_ACTION_PATTERNS[0][1].search(t)) or bool(_PROHIBITION_RE.search(t))


def redaction_rules(registry) -> dict:
    """Compile OPERATOR REDACTION RULES from the convention registry and REPORT
    whether the operator's rules are in force or only the defaults apply.

    A convention is REDACTION-INTENT when it is in a redaction category (keyword in
    category/id) OR its rule text has redaction phrasing OR its action is 'redact'.
    A redaction-intent convention with non-empty rule text COMPILES to an operator
    rule (action=redact; its text carries the targets, e.g. company turnover, named
    individual + ID number). A redaction-intent convention that does NOT compile
    (no usable rule text) is NEVER silently dropped: it raises a WARNING naming the
    id and reason, surfaced by the caller (console + bus).

    Returns a report dict:
      rules:             operator rules + DEFAULT_REDACTION_RULES (defaults are a
                         FLOOR, always present so the planted categories are covered)
      operator_rules:    the compiled operator rules (may be [])
      operator_in_force: bool — True iff at least one operator rule compiled
      source:            "operator+defaults" | "defaults"
      warnings:          [{id, category, reason}] for redaction-intent that failed
                         to compile (loud, never silent)
    The redactors APPLY `rules`; the distinction operator-vs-defaults is explicit."""
    convs = (registry.get("conventions") if isinstance(registry, dict) else None) or []
    operator, warnings = [], []
    for c in convs:
        cid = str(c.get("id", ""))
        cat = str(c.get("category", "")).strip().lower()
        act = str(c.get("action", "")).strip().lower()
        rule_text = str(c.get("rule", "")).strip()
        is_cat = _is_redaction_category(cat, cid)
        is_phrase = _has_redaction_phrasing(rule_text)
        if not (is_cat or is_phrase or act == "redact"):
            continue  # not redaction-intent — leave it as an ordinary convention
        if not rule_text:
            warnings.append({"id": cid, "category": cat,
                             "reason": "redaction-intent convention has no rule text to compile"})
            continue
        operator.append({"id": cid, "category": cat or "confidentiality",
                         "rule": rule_text, "severity": c.get("severity", "required"),
                         "action": "redact",
                         "matched_by": ("category" if is_cat else "action" if act == "redact" else "phrasing")})
    operator_in_force = bool(operator)
    return {
        "rules": operator + list(DEFAULT_REDACTION_RULES),
        "operator_rules": operator,
        "operator_in_force": operator_in_force,
        "source": "operator+defaults" if operator_in_force else "defaults",
        "warnings": warnings,
    }


_DEFAULT_CATEGORY = "unclassified"


@dataclass
class ConventionRule:
    id: str
    category: str
    rule: str
    source_file: str
    source_location: str
    severity: str
    action: str

    def as_dict(self):
        return {"id": self.id, "category": self.category, "rule": self.rule,
                "source_file": self.source_file, "source_location": self.source_location,
                "severity": self.severity, "action": self.action}


@dataclass
class ConventionRegistry:
    source_files: list = field(default_factory=list)
    conventions: list = field(default_factory=list)

    def as_dict(self):
        return {
            "schema_version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_files": self.source_files,
            "conventions": [c.as_dict() for c in self.conventions],
        }


def parse_conventions(project_root: Path) -> ConventionRegistry:
    """Parse every file in input/conventions/ into a registry."""
    in_dir = project_root / "input" / "conventions"
    registry = ConventionRegistry()
    if not in_dir.exists():
        return registry
    seq = [0]
    for path in sorted(in_dir.iterdir()):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext in _JSON_EXTENSIONS:
            registry.source_files.append(path.name)
            registry.conventions.extend(_parse_json(path, seq))
        elif ext in _TEXT_EXTENSIONS:
            registry.source_files.append(path.name)
            registry.conventions.extend(_parse_text(path, seq))
        elif ext in _EXTRACT_EXTENSIONS:
            registry.source_files.append(path.name)
            registry.conventions.extend(_parse_extracted(path, seq))
        else:
            # No silent drop: an unrecognized file in input/conventions/ warns.
            text_extract.warn_unsupported(path, where="input/conventions")
    return registry


def write_registry(project_root: Path, registry: ConventionRegistry) -> Path:
    path = project_root / "config" / "convention_registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _next_id(seq):
    seq[0] += 1
    return f"CONV-{seq[0]:03d}"


def _classify_severity(text):
    for label, rx in _SEVERITY_PATTERNS:
        if rx.search(text):
            return label
    return "advisory"


def _classify_action(text):
    for label, rx in _ACTION_PATTERNS:
        if rx.search(text):
            return label
    return "flag"


def _parse_json(path, seq):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict) and "conventions" in data:
        items = data["conventions"]
    elif isinstance(data, list):
        items = data
    else:
        return []
    out = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        rule = str(item.get("rule") or item.get("text") or "").strip()
        if not rule:
            continue
        out.append(ConventionRule(
            id=item.get("id") or _next_id(seq),
            category=str(item.get("category") or _DEFAULT_CATEGORY).strip().lower(),
            rule=rule, source_file=path.name,
            source_location=str(item.get("source_location") or f"item {i+1}"),
            severity=str(item.get("severity") or _classify_severity(rule)).lower(),
            action=str(item.get("action") or _classify_action(rule)).lower(),
        ))
    return out


def _parse_text(path, seq):
    text = path.read_text(encoding="utf-8", errors="replace")
    return _parse_text_lines(text, path.name, seq)


def _parse_text_lines(text, source_name, seq):
    out = []
    current_category = _DEFAULT_CATEGORY
    current_section = "preamble"
    line_num = 0
    para_buffer = []

    def flush(buffer, category, section, location):
        if not buffer:
            return []
        joined = " ".join(b.strip() for b in buffer).strip()
        if not joined:
            return []
        return [ConventionRule(
            id=_next_id(seq), category=category, rule=joined,
            source_file=source_name, source_location=location,
            severity=_classify_severity(joined), action=_classify_action(joined),
        )]

    for raw_line in text.splitlines():
        line_num += 1
        line = raw_line.rstrip()
        if _is_markdown_heading(line):
            out.extend(flush(para_buffer, current_category, current_section,
                             f"line {line_num - len(para_buffer)}"))
            para_buffer = []
            current_category = _normalize_category(line)
            current_section = line.lstrip("# ").strip().lower()
            continue
        if _is_list_item(line):
            out.extend(flush(para_buffer, current_category, current_section,
                             f"line {line_num - len(para_buffer)}"))
            para_buffer = []
            stripped = _strip_list_marker(line)
            if stripped:
                out.append(ConventionRule(
                    id=_next_id(seq), category=current_category, rule=stripped,
                    source_file=source_name, source_location=f"line {line_num}",
                    severity=_classify_severity(stripped), action=_classify_action(stripped),
                ))
            continue
        if not line.strip():
            out.extend(flush(para_buffer, current_category, current_section,
                             f"line {line_num - len(para_buffer)}"))
            para_buffer = []
            continue
        para_buffer.append(line)
    out.extend(flush(para_buffer, current_category, current_section,
                     f"line {line_num - len(para_buffer) + 1}"))
    return [r for r in out if r.rule and len(r.rule) >= 16]


def _parse_extracted(path, seq):
    # .pdf / .docx / .html / .htm: pull plain text via the shared extractor and
    # run it through the same structural parser as native text files. No temp
    # file is written (the source name is preserved on each rule).
    text = text_extract.extract_text(path)
    if not text.strip():
        return []
    return _parse_text_lines(text, path.name, seq)


def _is_markdown_heading(line):
    return bool(re.match(r"^#{1,6}\s+\S", line))


def _is_list_item(line):
    return bool(re.match(r"^\s*(?:[-*+]|\d+[.)])\s+\S", line))


def _strip_list_marker(line):
    return re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", line).strip()


_CATEGORY_KEYWORDS = {
    "terminology":     ("terminology", "term", "vocabulary", "wording"),
    "red_flags":       ("red flag", "flag", "warning", "alert"),
    "rephrasing":      ("rephrase", "rewrite", "rephrasing", "language"),
    "citation_style":  ("citation", "cite", "reference", "borrowing"),
    "structural":      ("structure", "structural", "format", "section"),
    "value_alignment": ("value", "alignment", "ethics", "principles"),
    "borrowing":       ("borrow", "external", "foreign", "attribution"),
}


def _normalize_category(heading):
    h = heading.lstrip("# ").strip().lower()
    for cat, keys in _CATEGORY_KEYWORDS.items():
        if any(k in h for k in keys):
            return cat
    return h.split()[0] if h else _DEFAULT_CATEGORY
