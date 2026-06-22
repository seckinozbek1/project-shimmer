"""Canonical-master amendment renders (genesis Part XXVII §E / INFRA-033).

THE SINGLE CANONICAL MASTER for a document's convention-review result is the
`amendments_payload` dict — the same object serialized verbatim as
`<doc_id>__amendments.json`. The human-facing renders (`.md`, `.docx`) are PURE
FUNCTIONS of that master: master in → format out. They read amendment content
from NOWHERE else, so the three files cannot disagree.

`write_amendment_deliverables()` is the SINGLE ENTRY POINT that writes all three
formats from one `payload` object. Every per-run deliverable writer routes
through it; nothing else writes amendments.* files. This is the drift guard: a
future edit cannot reintroduce independent generation without going through (and
contradicting) this one function, which asserts the renders reflect the master.

Presentation-only inputs (NOT amendment content; they cannot change which
amendments appear):
  - document_name : heading text (cosmetic).
  - body_text     : the ORIGINAL document text — the canvas the .docx anchors
                    tracked-change marks into. It positions revision marks; it
                    never supplies an amendment. Amendments that do not anchor in
                    the body still render (in an "Additional amendments" section),
                    so the .docx always reflects the FULL master amendment set.
  - category_for_conv : optional callable conv_id -> human-readable category
                    label, used only to decorate a convention_ref that is ALREADY
                    in the master. Injected so this module stays decoupled from
                    the convention-registry shape.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Master fields every render reads. The renders consult only these keys for
# content; anything else they receive is presentation-only (see module docstring).
CANONICAL_CONTENT_KEYS = ("document_id", "amendments", "_validator_errors")


def render_amendments_md(payload: dict, *, document_name: str = "",
                         category_for_conv: Callable[[str], Any] | None = None) -> str:
    """Pure render of the canonical master `payload` to Markdown.

    Content comes solely from `payload`; `document_name` is the cosmetic heading
    and `category_for_conv` only decorates a convention_ref already in the master.
    """
    amendments = payload.get("amendments", [])
    validator_errors = payload.get("_validator_errors", [])
    n_uncertain = sum(1 for a in amendments if a.get("uncertain"))
    title_name = document_name or payload.get("document_id", "document")
    lines = [f"# {title_name} — Proposed amendments", "",
             f"- generated: {datetime.now(timezone.utc).isoformat()}",
             f"- amendments: {len(amendments)}",
             f"- uncertain: {n_uncertain}",
             f"- validator errors: {len(validator_errors)}"]
    if validator_errors:
        lines.append("\n## Validator errors\n")
        for e in validator_errors:
            lines.append(f"- {e}")
    lines.append("\n## Amendments\n")
    for i, a in enumerate(amendments, 1):
        conv = a.get("convention_ref", "?"); loc = a.get("location", "?")
        cat = (category_for_conv(conv) if category_for_conv else None) or "?"
        sev = a.get("severity", "?")
        # Genesis Part XXV: uncertain findings carry an explicit tag in every
        # deliverable section so the operator never sees them silently merged.
        uncertain_tag = "[UNCERTAIN] " if a.get("uncertain") else ""
        lines.append(
            f"### {uncertain_tag}Amendment {i} [{conv}] — "
            f"{a.get('finding_type', cat)} ({sev})"
        )
        lines.append("")
        lines.append(f"**Location:** [{loc}]")
        lines.append(f"**Action:** {a.get('action', 'flag')}")
        original = a.get('original_text') or '(unspecified)'
        lines.append(f"**Original:** {str(original)[:500]}")
        proposed = a.get('proposed_text')
        if proposed:
            lines.append(f"**Proposed:** {str(proposed)[:500]}")
        lines.append("")
        lines.append("**Justification:**")
        comment = a.get("comment", "(missing comment)")
        if a.get("uncertain") and not comment.lstrip().startswith("[UNCERTAIN]"):
            comment = "[UNCERTAIN] " + comment
        lines.append(comment)
        lines.append("")
        if a.get("context_refs"):
            lines.append(f"**Context references:** {', '.join(a['context_refs'])}")
        lines.append("")
    return "\n".join(lines)


def render_amendments_docx(payload: dict, output_path: Path, *,
                           title: str | None = None, body_text: str = "") -> Path:
    """Pure render of the canonical master `payload` to a tracked-changes .docx.

    The amendment set is taken from `payload["amendments"]`; `body_text` is the
    original-document canvas (see module docstring) and `title` is cosmetic.
    docx_builder is imported lazily so python-docx stays an optional dependency.
    """
    from docx_builder import build_amendments_docx
    title = title or f"{payload.get('document_id', 'document')} — Convention review (tracked changes)"
    return build_amendments_docx(
        title=title,
        body_text=body_text or "",
        amendments=payload.get("amendments", []),
        output_path=output_path,
    )


def _md_amendment_count(md_text: str) -> int:
    """Count rendered amendment sections in a Markdown render (lines like
    '### [UNCERTAIN] Amendment 3 [CONV-1] — ...')."""
    return sum(1 for ln in md_text.splitlines()
               if ln.startswith("### ") and "Amendment " in ln)


def write_amendment_deliverables(payload: dict, *, deliv_dir: Path, doc_id: str,
                                 document_name: str = "", body_text: str = "",
                                 category_for_conv: Callable[[str], Any] | None = None) -> dict:
    """SINGLE ENTRY POINT — write json (master) + md + docx, all DERIVED from the
    one `payload` object passed here. Returns a paths/metadata dict.

    Drift guard: the .md and .docx are produced from the SAME `payload` local
    below — there is no second content source — and an assertion confirms the .md
    reflects the master's amendment count before we return. The .docx amendment
    set is `payload["amendments"]` by construction. If a future edit tries to feed
    a render from elsewhere, it must change THIS function, and the assertion will
    fire if the render stops matching the master.
    """
    deliv_dir = Path(deliv_dir)
    deliv_dir.mkdir(parents=True, exist_ok=True)
    amendments = payload.get("amendments", [])

    json_path = deliv_dir / f"{doc_id}__amendments.json"
    md_path = deliv_dir / f"{doc_id}__amendments.md"
    docx_path = deliv_dir / f"{doc_id}__amendments.docx"

    # (1) master, verbatim
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    # (2) markdown render, pure function of the master
    md_text = render_amendments_md(payload, document_name=document_name,
                                   category_for_conv=category_for_conv)
    md_path.write_text(md_text, encoding="utf-8")
    # (3) docx render, pure function of the master (+ body_text canvas)
    docx_error = None
    try:
        render_amendments_docx(
            payload, docx_path,
            title=f"{document_name or payload.get('document_id', 'document')} — "
                  f"Convention review (tracked changes)",
            body_text=body_text,
        )
    except Exception as e:  # python-docx missing or build failure: never fatal
        docx_error = f"{type(e).__name__}: {e}"

    # Drift guard: the md MUST reflect the master amendment count.
    assert _md_amendment_count(md_text) == len(amendments), (
        "amendment render drifted from canonical master "
        f"(md sections={_md_amendment_count(md_text)}, master amendments={len(amendments)})"
    )

    return {
        "amendments_json": str(json_path),
        "amendments_md": str(md_path),
        "amendments_docx": str(docx_path) if docx_path.exists() else None,
        "amendment_count": len(amendments),
        "docx_error": docx_error,
    }
