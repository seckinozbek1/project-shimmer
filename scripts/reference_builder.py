"""Reference builder (genesis Part XVIII Section B).

Splits documents into paragraphs and sentences, assigns stable REF-* IDs,
and maintains the index across pipeline phases.

ref_id pattern: REF-XXXX, monotonically increasing per index instance.
The index is persisted to the run's audit/reference_index.json (the pipeline
passes the per-run path; INFRA-032) and can be
extended idempotently across pipeline phases.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_PARA_RE = re.compile(r"\n\s*\n")
_SENT_RE = re.compile(r"(?<=[\.!?])\s+(?=[A-Z0-9])")


def _now(): return datetime.now(timezone.utc).isoformat()


@dataclass
class ReferenceEntry:
    ref_id: str
    input_type: str  # context | operational | convention
    document_id: str
    document_name: str
    location: dict
    text_excerpt: str
    cited_by: list = field(default_factory=list)
    first_indexed: str = field(default_factory=_now)

    def as_dict(self):
        return {"ref_id": self.ref_id, "input_type": self.input_type,
                "document_id": self.document_id, "document_name": self.document_name,
                "location": self.location, "text_excerpt": self.text_excerpt,
                "cited_by": self.cited_by, "first_indexed": self.first_indexed}


@dataclass
class WebReferenceEntry:
    """A search-discovered web reference (INFRA-042; backs genesis Part XX [WEB-REF]). Minted with a
    monotonic WEB-REF-NNNN id, parallel to REF-NNNN, and citable in ref_ids exactly like a REF-*."""
    web_ref_id: str
    url: str
    title: str = ""
    issuing_body: str = ""
    year: str = ""
    cited_by: list = field(default_factory=list)
    first_indexed: str = field(default_factory=_now)

    def as_dict(self):
        return {"web_ref_id": self.web_ref_id, "url": self.url, "title": self.title,
                "issuing_body": self.issuing_body, "year": self.year,
                "cited_by": self.cited_by, "first_indexed": self.first_indexed}


# INFRA-042: the STRUCTURED web-source fields per agent, the complete set in the empty-registry
# regime. Inline free-text URLs are deliberately out of scope (a separate convention-activated
# concern). This is the single source of truth for the field map (the OPT-1 gate imports it).
WEB_SOURCE_FIELDS = {
    "FACT_CHECKER": ("source_url",),
    "PRACTICE_AUDITOR": ("reference_url", "reference_source"),
}


def web_sources_in(agent, item):
    """Return [(field, value)] for each non-empty STRUCTURED web-source field on a finding."""
    out = []
    for fname in WEB_SOURCE_FIELDS.get(agent, ()):
        v = item.get(fname) if isinstance(item, dict) else None
        if isinstance(v, str) and v.strip():
            out.append((fname, v.strip()))
    return out


@dataclass
class ReferenceIndex:
    project_root: Path
    entries: list = field(default_factory=list)
    by_id: dict = field(default_factory=dict)
    # INFRA-042: WEB-REF store, co-persisted in the same per-run reference_index.json.
    web_entries: list = field(default_factory=list)
    web_by_id: dict = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _seq: int = 0
    _web_seq: int = 0
    # Explicit on-disk location. When None, falls back to the legacy
    # output/audit/reference_index.json. The pipeline passes the CURRENT run's
    # path (output/runs/<run>/audit/reference_index.json) so the index is
    # per-run and disposable (Part XXVII §A).
    index_path: Path | None = None

    @classmethod
    def open(cls, project_root: Path, *, index_path: Path | None = None) -> "ReferenceIndex":
        idx = cls(project_root=project_root, index_path=index_path)
        path = idx._resolved_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for e in data.get("entries", []):
                    entry = ReferenceEntry(
                        ref_id=e["ref_id"], input_type=e["input_type"],
                        document_id=e["document_id"], document_name=e["document_name"],
                        location=e.get("location", {}), text_excerpt=e.get("text_excerpt", ""),
                        cited_by=list(e.get("cited_by", [])),
                        first_indexed=e.get("first_indexed", _now()),
                    )
                    idx.entries.append(entry)
                    idx.by_id[entry.ref_id] = entry
                idx._seq = max((int(e.ref_id.split("-")[1]) for e in idx.entries
                                if e.ref_id.startswith("REF-")), default=0)
                for w in data.get("web_references", []):
                    we = WebReferenceEntry(
                        web_ref_id=w["web_ref_id"], url=w.get("url", ""), title=w.get("title", ""),
                        issuing_body=w.get("issuing_body", ""), year=w.get("year", ""),
                        cited_by=list(w.get("cited_by", [])),
                        first_indexed=w.get("first_indexed", _now()),
                    )
                    idx.web_entries.append(we)
                    idx.web_by_id[we.web_ref_id] = we
                # WEB-REF-NNNN -> split("-") = [WEB, REF, NNNN]; recover the high-water mark
                idx._web_seq = max((int(e.web_ref_id.split("-")[2]) for e in idx.web_entries
                                    if e.web_ref_id.startswith("WEB-REF-")), default=0)
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
        return idx

    @staticmethod
    def _path_for(project_root):
        return project_root / "output" / "audit" / "reference_index.json"

    def _resolved_path(self) -> Path:
        return self.index_path or self._path_for(self.project_root)

    def save(self) -> Path:
        with self._lock:
            path = self._resolved_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {"schema_version": "1.0.0", "generated_at": _now(),
                    "entries": [e.as_dict() for e in self.entries],
                    "web_references": [e.as_dict() for e in self.web_entries]}
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
            return path

    def _next_id(self):
        self._seq += 1
        return f"REF-{self._seq:04d}"

    def _next_web_id(self):
        self._web_seq += 1
        return f"WEB-REF-{self._web_seq:04d}"

    def add_web_reference(self, *, url, title="", issuing_body="", year="") -> WebReferenceEntry:
        """Mint a WEB-REF-NNNN entry for a search-discovered reference (INFRA-042)."""
        with self._lock:
            entry = WebReferenceEntry(
                web_ref_id=self._next_web_id(), url=url or "", title=title or "",
                issuing_body=issuing_body or "", year=year or "")
            self.web_entries.append(entry)
            self.web_by_id[entry.web_ref_id] = entry
            return entry

    def cite_web(self, web_ref_id, agent_name):
        with self._lock:
            entry = self.web_by_id.get(web_ref_id)
            if entry and agent_name not in entry.cited_by:
                entry.cited_by.append(agent_name)

    def add(self, *, input_type, document_id, document_name, location, text_excerpt) -> ReferenceEntry:
        with self._lock:
            entry = ReferenceEntry(
                ref_id=self._next_id(), input_type=input_type,
                document_id=document_id, document_name=document_name,
                location=location, text_excerpt=text_excerpt[:200],
            )
            self.entries.append(entry); self.by_id[entry.ref_id] = entry
            return entry

    def cite(self, ref_id, agent_name):
        with self._lock:
            entry = self.by_id.get(ref_id)
            if entry and agent_name not in entry.cited_by:
                entry.cited_by.append(agent_name)

    def find_by_document(self, document_id):
        return [e for e in self.entries if e.document_id == document_id]

    def index_document(self, *, input_type, document_id, document_name, text,
                       max_paragraphs=200, max_chars_per_excerpt=200) -> list:
        """Split text into paragraphs (and sentences within each paragraph) and add
        each paragraph as a reference entry."""
        out = []
        if not text:
            return out
        paras = [p.strip() for p in _PARA_RE.split(text) if p.strip()]
        page_estimate = 1
        running_chars = 0
        chars_per_page = 3000
        for p_idx, para in enumerate(paras[:max_paragraphs], start=1):
            sentences = [s.strip() for s in _SENT_RE.split(para) if s.strip()]
            location = {
                "page": page_estimate, "paragraph": p_idx,
                "sentence": 1 if sentences else 0,
                "char_start": running_chars,
                "char_end": running_chars + len(para),
            }
            entry = self.add(
                input_type=input_type, document_id=document_id,
                document_name=document_name, location=location,
                text_excerpt=para[:max_chars_per_excerpt],
            )
            out.append(entry)
            running_chars += len(para) + 2
            if running_chars > page_estimate * chars_per_page:
                page_estimate += 1
        return out
