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


_TEXT_EXTENSIONS = {".md", ".txt", ".rst"}
_JSON_EXTENSIONS = {".json"}
_PDF_EXTENSIONS = {".pdf"}


_SEVERITY_PATTERNS = [
    ("required",    re.compile(r"\b(must|shall|required|mandatory|prohibited|forbidden|no\s+exception)\b", re.IGNORECASE)),
    ("recommended", re.compile(r"\b(should|recommended|expected|ought to|encouraged)\b", re.IGNORECASE)),
    ("advisory",    re.compile(r"\b(may|consider|optional|where applicable|if appropriate)\b", re.IGNORECASE)),
]


_ACTION_PATTERNS = [
    ("reject",   re.compile(r"\b(reject|do not accept|disallow|prohibit)\b", re.IGNORECASE)),
    ("rephrase", re.compile(r"\b(rephrase|rewrite|replace|substitute|use\s+\S+\s+instead)\b", re.IGNORECASE)),
    ("flag",     re.compile(r"\b(flag|alert|warn|require\s+review|escalate)\b", re.IGNORECASE)),
    ("annotate", re.compile(r"\b(annotate|note|comment|footnote|add\s+citation)\b", re.IGNORECASE)),
]


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
        registry.source_files.append(path.name)
        if ext in _JSON_EXTENSIONS:
            registry.conventions.extend(_parse_json(path, seq))
        elif ext in _TEXT_EXTENSIONS:
            registry.conventions.extend(_parse_text(path, seq))
        elif ext in _PDF_EXTENSIONS:
            registry.conventions.extend(_parse_pdf(path, seq))
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
            source_file=path.name, source_location=location,
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
                    source_file=path.name, source_location=f"line {line_num}",
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


def _parse_pdf(path, seq):
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return []
    tmp_path = path.with_suffix(".pdf.parsed.txt")
    tmp_path.write_text(text, encoding="utf-8")
    try:
        return _parse_text(tmp_path, seq)
    finally:
        try: tmp_path.unlink()
        except FileNotFoundError: pass


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
