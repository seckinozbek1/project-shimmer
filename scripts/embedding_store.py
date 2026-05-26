"""Semantic retrieval layer (genesis Part XXI).

Builds a vector embedding store from input/context/ PDFs and provides
cosine-similarity retrieval for context assembly. The store is part of
the ontology snapshot and persists across runs via save/load.

Graceful degradation: if sentence-transformers is not installed, or if
the model fails to load, every function in this module returns a safe
fallback (0 passages built, None on load, [] on query) and the pipeline
silently uses Zipfian filtering instead.

Chunking: ~400-character passages — small enough to fit under the
all-MiniLM-L6-v2 256-token context window with margin, large enough to
carry one or two sentences of meaningful content per chunk.
"""

from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_TARGET_CHARS = 400
CHUNK_OVERLAP_CHARS = 80


def _try_import_st():
    try:
        import sentence_transformers
        return sentence_transformers
    except ImportError:
        return None


def _try_import_numpy():
    try:
        import numpy as np
        return np
    except ImportError:
        return None


def _read_pdf_pages(path: Path) -> list[tuple[int, str]]:
    """Return [(page_index_1_based, page_text), ...] or [] on failure."""
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        return [(i + 1, (page.extract_text() or "")) for i, page in enumerate(reader.pages)]
    except Exception:
        return []


def _chunk_page(text: str, *, target: int = CHUNK_TARGET_CHARS,
                overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    """Split text into ~target-char chunks with small overlap. Whitespace-
    aware: prefer sentence/paragraph boundaries when one is within range."""
    if not text:
        return []
    text = " ".join(text.split())  # collapse whitespace
    if len(text) <= target:
        return [text]
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + target)
        if end < n:
            # nudge end to the next sentence boundary or space within a small window
            for boundary in (". ", "? ", "! ", ".\n", "\n"):
                idx = text.find(boundary, end - 60, end + 60)
                if idx != -1:
                    end = idx + len(boundary)
                    break
            else:
                space = text.rfind(" ", end - 40, end)
                if space != -1:
                    end = space
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def build_store(
    context_dir: Path,
    store_path: Path,
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    reference_index: Any = None,
) -> int:
    """Build an embedding store from every PDF in context_dir, OR load an
    existing one if the corpus hasn't changed.

    Staleness rule: if a pickle exists at `store_path`, compare the set of
    PDF filenames in context_dir against the set of doc_names recorded in
    the store's passages. If they match, the existing store is reused and
    we return its passage count without rebuilding. If they differ — any
    add or remove — the store is rebuilt from scratch.

    If `reference_index` is provided, each passage is also registered
    with the index via `reference_index.add(...)` so REF-* identifiers
    are shared between the Zipfian and semantic retrieval paths. If not
    provided, the store mints local ref_ids and the caller is responsible
    for any cross-walk it needs.

    Returns the number of passages in the active store (loaded or built).
    Returns 0 on graceful degradation (missing library, model load failure,
    no PDFs found).
    """
    # Staleness check: load existing pickle if present, compare to corpus.
    if store_path.exists():
        existing = load_store(store_path)
        stale, _added, _removed = is_store_stale(existing, context_dir)
        if not stale and existing is not None:
            n_docs = len(_store_doc_names(existing))
            print(f"[embedding] Store loaded ({n_docs} docs, up to date)",
                  file=sys.stderr, flush=True)
            return len(existing.get("passages") or [])
        n_ctx = len(_context_dir_pdf_names(context_dir))
        n_store = len(_store_doc_names(existing)) if existing else 0
        print(
            f"[embedding] Store stale ({n_ctx} docs in context, "
            f"{n_store} in store), rebuilding",
            file=sys.stderr, flush=True,
        )

    st = _try_import_st()
    np = _try_import_numpy()
    if st is None or np is None:
        print("[embedding_store] sentence-transformers or numpy missing; "
              "skipping store build (Zipfian fallback active)", file=sys.stderr)
        return 0
    if not context_dir.exists():
        print(f"[embedding_store] context dir not found: {context_dir}", file=sys.stderr)
        return 0
    pdfs = sorted(p for p in context_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    if not pdfs:
        return 0

    print(f"[embedding_store] building from {len(pdfs)} PDFs in {context_dir}",
          file=sys.stderr, flush=True)
    try:
        model = st.SentenceTransformer(model_name)
    except Exception as e:
        print(f"[embedding_store] model load failed ({type(e).__name__}: {e}); "
              "Zipfian fallback active", file=sys.stderr)
        return 0

    passages: list[dict] = []
    for pdf in pdfs:
        pages = _read_pdf_pages(pdf)
        if not pages:
            continue
        for page_no, page_text in pages:
            for chunk in _chunk_page(page_text):
                passage: dict[str, Any] = {
                    "doc_name": pdf.name,
                    "doc_id": pdf.stem,
                    "page": page_no,
                    "text": chunk,
                }
                if reference_index is not None:
                    entry = reference_index.add(
                        input_type="context",
                        document_id=pdf.stem,
                        document_name=pdf.name,
                        location={"page": page_no, "paragraph": 0,
                                  "sentence": 0,
                                  "char_start": 0, "char_end": len(chunk)},
                        text_excerpt=chunk[:200],
                    )
                    passage["ref_id"] = entry.ref_id
                else:
                    passage["ref_id"] = f"REF-EMB-{len(passages) + 1:05d}"
                passages.append(passage)

    if not passages:
        return 0
    texts = [p["text"] for p in passages]
    t0 = time.monotonic()
    try:
        emb = model.encode(texts, batch_size=32, show_progress_bar=False,
                           convert_to_numpy=True, normalize_embeddings=True)
    except Exception as e:
        print(f"[embedding_store] encode failed ({type(e).__name__}: {e}); "
              "Zipfian fallback active", file=sys.stderr)
        return 0
    print(f"[embedding_store] embedded {len(passages)} passages in "
          f"{time.monotonic() - t0:.1f}s", file=sys.stderr, flush=True)

    store = {
        "model_name": model_name,
        "passages": passages,
        "embeddings": emb.astype(np.float32),
    }
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with store_path.open("wb") as fh:
        pickle.dump(store, fh, protocol=pickle.HIGHEST_PROTOCOL)
    if reference_index is not None:
        reference_index.save()
    return len(passages)


def load_store(store_path: Path) -> dict | None:
    """Load the pickle. Returns None if the file doesn't exist or fails to load."""
    if not store_path.exists():
        return None
    try:
        with store_path.open("rb") as fh:
            return pickle.load(fh)
    except Exception as e:
        print(f"[embedding_store] load failed ({type(e).__name__}: {e})", file=sys.stderr)
        return None


def _context_dir_pdf_names(context_dir: Path) -> set[str]:
    if not context_dir.exists():
        return set()
    return {p.name for p in context_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ".pdf"}


def _store_doc_names(store: dict) -> set[str]:
    return {p.get("doc_name") for p in (store.get("passages") or [])
            if p.get("doc_name")}


def is_store_stale(store: dict | None, context_dir: Path) -> tuple[bool, set[str], set[str]]:
    """Return (stale, added, removed). `stale` is True if the set of PDF
    filenames in context_dir differs from the set of doc_names recorded in
    the store's passages. The added/removed sets help the caller log a
    one-line diagnostic before rebuilding."""
    if store is None:
        return (True, _context_dir_pdf_names(context_dir), set())
    current = _context_dir_pdf_names(context_dir)
    stored = _store_doc_names(store)
    return (current != stored, current - stored, stored - current)


def query_store(store: dict, query_text: str, n: int = 20) -> list[dict]:
    """Return the top-n passages by cosine similarity. Each result is the
    passage dict with `similarity` (float in [-1, 1]) added.

    Returns [] on any failure (missing library, empty store, bad query).
    """
    if not store or not query_text:
        return []
    st = _try_import_st()
    np = _try_import_numpy()
    if st is None or np is None:
        return []
    passages = store.get("passages") or []
    emb = store.get("embeddings")
    if not passages or emb is None or len(emb) == 0:
        return []
    try:
        model = st.SentenceTransformer(store.get("model_name") or DEFAULT_MODEL_NAME)
        q = model.encode([query_text], convert_to_numpy=True,
                         normalize_embeddings=True)[0]
    except Exception as e:
        print(f"[embedding_store] query encode failed ({type(e).__name__}: {e})",
              file=sys.stderr)
        return []
    # Both query and passage embeddings are L2-normalized, so dot product = cosine sim.
    sims = emb @ q
    top_idx = np.argsort(-sims)[: max(0, n)]
    out = []
    for idx in top_idx:
        i = int(idx)
        rec = dict(passages[i])
        rec["similarity"] = float(sims[i])
        out.append(rec)
    return out


def store_path_for(project_root: Path) -> Path:
    return project_root / "output" / "audit" / "embedding_store.pkl"


def get_or_build(project_root: Path, *, reference_index: Any = None) -> dict | None:
    """Boot-time convenience wrapper around build_store. The staleness
    decision (load existing pickle vs. rebuild) lives inside build_store
    itself, so this function simply triggers the build/load and returns
    the resulting store dict (or None on graceful degradation)."""
    path = store_path_for(project_root)
    context_dir = project_root / "input" / "context"
    n = build_store(context_dir, path, reference_index=reference_index)
    if n == 0:
        return None
    return load_store(path)
