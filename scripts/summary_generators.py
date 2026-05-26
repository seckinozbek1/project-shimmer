"""Context summary and operative summary generators (Part XVIII Section C).

Each summary cites specific references (REF-* and CONV-*) so the reader can
trace any claim back to its source. The actual prose is produced by PROCESSOR
in production runs; these helpers provide the deterministic structural shell
that always carries the citation grid.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


def _now(): return datetime.now(timezone.utc).isoformat()


def render_context_summary(
    *,
    document_id: str,
    document_name: str,
    context_refs: list[dict],
    topics: list[str] | None = None,
    body_text: str = "",
) -> str:
    topics = topics or []
    lines = [f"# {document_name} — Context summary", "",
             f"- generated: {_now()}",
             f"- document id: {document_id}",
             f"- context references cited: {len(context_refs)}",
             "",
             "## What the reference corpus establishes about this document's topics",
             ""]
    if topics:
        lines.append("**Topics addressed:**")
        for t in topics:
            lines.append(f"- {t}")
        lines.append("")
    if body_text.strip():
        lines.append(body_text.strip())
        lines.append("")
    lines.append("## Reference citations (from context corpus)")
    lines.append("")
    if not context_refs:
        lines.append("_no context references cited_")
    else:
        for ref in context_refs:
            loc = ref.get("location", {}) or {}
            page = loc.get("page", "?"); para = loc.get("paragraph", "?")
            lines.append(
                f"- **[{ref.get('ref_id')}]** {ref.get('document_name', '?')} "
                f"(p{page}, para {para}): {ref.get('text_excerpt', '')[:240]}"
            )
    return "\n".join(lines)


def render_operative_summary(
    *,
    document_id: str,
    document_name: str,
    conventions_by_category: dict[str, list[dict]],
    findings: list[dict],
    body_text: str = "",
) -> str:
    lines = [f"# {document_name} — Operative summary", "",
             f"- generated: {_now()}",
             f"- document id: {document_id}",
             f"- convention categories evaluated: {len(conventions_by_category)}",
             f"- findings: {len(findings)}",
             "",
             "## What the document says, organized by convention category",
             ""]
    if body_text.strip():
        lines.append(body_text.strip())
        lines.append("")
    for category, conventions in sorted(conventions_by_category.items()):
        lines.append(f"### {category}")
        lines.append("")
        if not conventions:
            lines.append("_no conventions in this category_")
            lines.append("")
            continue
        for c in conventions:
            lines.append(f"- **[{c.get('id')}]** ({c.get('severity', '?')}/{c.get('action', '?')}): "
                         f"{c.get('rule', '')[:240]}")
        category_findings = [f for f in findings if f.get("category") == category]
        if category_findings:
            lines.append("")
            lines.append("**Findings:**")
            for f in category_findings:
                refs = ", ".join(f.get("ref_ids", []) or [])
                lines.append(f"- {f.get('verdict', '?')} on [{f.get('conv_id', '?')}] "
                             f"at refs [{refs}]: {f.get('reasoning', '')[:240]}")
        lines.append("")
    return "\n".join(lines)
