"""Semantic retrieval layer (genesis Part XXI).

Builds a vector embedding store from every supported document in input/context/
(the shared text_extract format family: .pdf/.docx/.html/.htm/.txt/.md/.rst/
.log/.json) and provides cosine-similarity retrieval for context assembly. The
store is part of the snapshot and persists across runs via save/load.

Graceful degradation: if sentence-transformers is not installed, or if
the model fails to load, every function in this module returns a safe
fallback (0 passages built, None on load, [] on query) and the pipeline
silently uses Zipfian filtering instead.

Chunking: ~400-character passages — small enough to fit under the
all-MiniLM-L6-v2 256-token context window with margin, large enough to
carry one or two sentences of meaningful content per chunk.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import sys
import time
from pathlib import Path
from typing import Any

import language_detect
import text_extract


# English-centric model: fast and strong on English, and the historical default
# (keeps English behavior and any pre-existing English store unchanged).
DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
# Multilingual default for any positively-detected non-English language. This is
# the canonical sentence-transformers multilingual MiniLM (50+ languages incl.
# Arabic/Hebrew, 384-dim). Downloaded by sentence-transformers at runtime; if it
# is unavailable, _resolve_model() degrades to the English default with a warning.
MULTILINGUAL_DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# Language (ISO 639-1) -> embedding model. Extensible: add a language-specialized
# model here when clearly better than the multilingual default.
LANG_MODEL_REGISTRY = {
    "en": DEFAULT_MODEL_NAME,
}
CHUNK_TARGET_CHARS = 400
CHUNK_OVERLAP_CHARS = 80

# Loaded SentenceTransformer instances, keyed by model id (avoid reloading).
_MODEL_CACHE: dict = {}


def model_for_language(lang: str) -> str:
    """Map a document's dominant language to its embedding model. English and
    unknown ('und' / unset — e.g. when langdetect is absent) keep the fast
    English default so detection-off never triggers a surprise model download;
    only a positively-detected non-English language switches to multilingual."""
    code = (lang or "").lower()
    if code in ("", "und"):
        return DEFAULT_MODEL_NAME
    return LANG_MODEL_REGISTRY.get(code, MULTILINGUAL_DEFAULT_MODEL)


def _registry_signature() -> str:
    """Stable hash of the language->model policy. Recorded in the store so a
    change to the registry (different models) forces a rebuild — staleness
    accounts for the model used, not just the document set."""
    payload = json.dumps(
        {"registry": LANG_MODEL_REGISTRY, "default": MULTILINGUAL_DEFAULT_MODEL,
         "english": DEFAULT_MODEL_NAME, "v": 2},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _load_model(st, name):
    """Load (and cache) a SentenceTransformer by id. Returns None on failure."""
    if name in _MODEL_CACHE:
        return _MODEL_CACHE[name]
    try:
        model = st.SentenceTransformer(name)
    except Exception as e:
        print(f"[embedding_store] WARN: model {name!r} unavailable "
              f"({type(e).__name__}: {e})", file=sys.stderr, flush=True)
        model = None
    _MODEL_CACHE[name] = model
    return model


def _resolve_model(st, name):
    """Return (actual_name, model), degrading gracefully: requested model ->
    multilingual default -> English default. (actual_name, None) only if none
    load. Never silently mislabels: the returned name is what actually embedded."""
    tried = []
    for candidate in (name, MULTILINGUAL_DEFAULT_MODEL, DEFAULT_MODEL_NAME):
        if candidate in tried:
            continue
        tried.append(candidate)
        model = _load_model(st, candidate)
        if model is not None:
            if candidate != name:
                print(f"[embedding_store] WARN: falling back from {name!r} to "
                      f"{candidate!r}", file=sys.stderr, flush=True)
            return candidate, model
    return None, None


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
    """Build an embedding store from every supported document in context_dir
    (the shared text_extract format family), OR load an existing one if the
    corpus hasn't changed.

    Staleness rule: if a pickle exists at `store_path`, compare the set of
    supported document filenames in context_dir against the set of doc_names
    recorded in the store's passages. If they match, the existing store is reused and
    we return its passage count without rebuilding. If they differ — any
    add or remove — the store is rebuilt from scratch.

    If `reference_index` is provided, each passage is also registered
    with the index via `reference_index.add(...)` so REF-* identifiers
    are shared between the Zipfian and semantic retrieval paths. If not
    provided, the store mints local ref_ids and the caller is responsible
    for any cross-walk it needs.

    Returns the number of passages in the active store (loaded or built).
    Returns 0 on graceful degradation (missing library, model load failure,
    no supported documents found).
    """
    # Staleness check: load existing pickle if present, compare to corpus.
    if store_path.exists():
        existing = load_store(store_path)
        stale, _added, _removed = is_store_stale(existing, context_dir)
        if not stale and existing is not None:
            n_docs = len(_store_doc_names(existing))
            print(f"[embedding] Store loaded ({n_docs} docs, up to date)",
                  file=sys.stderr, flush=True)
            return _store_passage_count(existing)
        n_ctx = len(_context_dir_doc_names(context_dir))
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
    docs = sorted(p for p in context_dir.iterdir()
                  if p.is_file() and text_extract.is_supported(p))
    if not docs:
        return 0

    print(f"[embedding_store] building from {len(docs)} documents in {context_dir}",
          file=sys.stderr, flush=True)

    # Per document: detect the dominant language, choose its embedding model, and
    # group passages by the model that will embed them. CORRECTNESS: passages
    # embedded by different models are NOT numerically comparable, so each model
    # gets its own sub-store and a query is only ever scored within one model's
    # sub-store (see query_store). The caller-supplied `model_name` is no longer
    # used to pick the model (per-document language drives selection now).
    groups: dict[str, list[dict]] = {}
    doc_models: dict[str, str] = {}
    passage_seq = 0
    for doc in docs:
        pages = text_extract.extract_pages(doc)
        if not pages:
            continue
        full_text = "\n".join(t for _, t in pages)
        lang = language_detect.detect_language(full_text)
        actual, _model = _resolve_model(st, model_for_language(lang))
        if actual is None:
            print("[embedding_store] no embedding model available; "
                  "Zipfian fallback active", file=sys.stderr)
            return 0
        doc_models[doc.name] = actual
        for page_no, page_text in pages:
            for chunk in _chunk_page(page_text):
                passage_seq += 1
                passage: dict[str, Any] = {
                    "doc_name": doc.name,
                    "doc_id": doc.stem,
                    "page": page_no,
                    "text": chunk,
                    "lang": lang,
                    "model_name": actual,
                }
                if reference_index is not None:
                    entry = reference_index.add(
                        input_type="context",
                        document_id=doc.stem,
                        document_name=doc.name,
                        location={"page": page_no, "paragraph": 0,
                                  "sentence": 0,
                                  "char_start": 0, "char_end": len(chunk)},
                        text_excerpt=chunk[:200],
                    )
                    passage["ref_id"] = entry.ref_id
                else:
                    passage["ref_id"] = f"REF-EMB-{passage_seq:05d}"
                groups.setdefault(actual, []).append(passage)

    if not groups:
        return 0

    # Encode each model's group with that model; store per-model sub-stores.
    models_block: dict[str, dict] = {}
    total = 0
    for mname, plist in groups.items():
        model = _load_model(st, mname)
        if model is None:
            print(f"[embedding_store] WARN: model {mname!r} unavailable at encode "
                  f"time; skipping {len(plist)} passages", file=sys.stderr)
            continue
        texts = [p["text"] for p in plist]
        t0 = time.monotonic()
        try:
            emb = model.encode(texts, batch_size=32, show_progress_bar=False,
                               convert_to_numpy=True, normalize_embeddings=True)
        except Exception as e:
            print(f"[embedding_store] encode failed for {mname!r} "
                  f"({type(e).__name__}: {e}); skipping", file=sys.stderr)
            continue
        models_block[mname] = {"passages": plist, "embeddings": emb.astype(np.float32)}
        total += len(plist)
        print(f"[embedding_store] embedded {len(plist)} passages with {mname!r} in "
              f"{time.monotonic() - t0:.1f}s", file=sys.stderr, flush=True)

    if not models_block:
        return 0

    store = {
        "schema": 2,
        "models": models_block,
        "doc_models": doc_models,
        "registry_signature": _registry_signature(),
    }
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with store_path.open("wb") as fh:
        pickle.dump(store, fh, protocol=pickle.HIGHEST_PROTOCOL)
    if reference_index is not None:
        reference_index.save()
    return total


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


def _context_dir_doc_names(context_dir: Path) -> set[str]:
    if not context_dir.exists():
        return set()
    return {p.name for p in context_dir.iterdir()
            if p.is_file() and text_extract.is_supported(p)}


def _store_passages(store: dict):
    """Yield every passage across all model sub-stores (schema 2), or the flat
    passage list (legacy schema 1)."""
    models = store.get("models")
    if models is not None:
        for block in models.values():
            yield from (block.get("passages") or [])
    else:
        yield from (store.get("passages") or [])


def _store_passage_count(store: dict) -> int:
    return sum(1 for _ in _store_passages(store))


def _store_doc_names(store: dict) -> set[str]:
    return {p.get("doc_name") for p in _store_passages(store) if p.get("doc_name")}


def is_store_stale(store: dict | None, context_dir: Path) -> tuple[bool, set[str], set[str]]:
    """Return (stale, added, removed). `stale` is True if any of: the store is
    missing; it predates the per-language schema (schema != 2); the
    language->model registry changed (registry_signature mismatch — so the
    model used is part of the staleness decision, not just the document set); or
    the set of supported document filenames in context_dir differs from the
    doc_names recorded in the store."""
    if store is None:
        return (True, _context_dir_doc_names(context_dir), set())
    if store.get("schema") != 2:
        return (True, _context_dir_doc_names(context_dir), set())
    if store.get("registry_signature") != _registry_signature():
        return (True, _context_dir_doc_names(context_dir), set())
    current = _context_dir_doc_names(context_dir)
    stored = _store_doc_names(store)
    return (current != stored, current - stored, stored - current)


def query_store(store: dict, query_text: str, n: int = 20) -> list[dict]:
    """Return the top-n passages by cosine similarity across every model
    sub-store. Each result is the passage dict with `similarity` (float in
    [-1, 1]) added.

    CORRECTNESS: a query is embedded SEPARATELY by each sub-store's model and
    scored only against that sub-store's passages, so every similarity is a
    same-model cosine (the embedding math is always valid — passages and the
    query they are compared to were produced by the same model). Results from
    all sub-stores are then merged and the global top-n returned.

    Returns [] on any failure (missing library, empty store, bad query).
    """
    if not store or not query_text:
        return []
    st = _try_import_st()
    np = _try_import_numpy()
    if st is None or np is None:
        return []
    model_blocks = store.get("models")
    if model_blocks is None and store.get("passages") is not None:
        # Legacy schema-1 store: a single flat model.
        model_blocks = {
            (store.get("model_name") or DEFAULT_MODEL_NAME): {
                "passages": store.get("passages") or [],
                "embeddings": store.get("embeddings"),
            }
        }
    if not model_blocks:
        return []
    scored: list[dict] = []
    for mname, block in model_blocks.items():
        passages = block.get("passages") or []
        emb = block.get("embeddings")
        if not passages or emb is None or len(emb) == 0:
            continue
        model = _load_model(st, mname)
        if model is None:
            continue
        try:
            q = model.encode([query_text], convert_to_numpy=True,
                             normalize_embeddings=True)[0]
        except Exception as e:
            print(f"[embedding_store] query encode failed for {mname!r} "
                  f"({type(e).__name__}: {e})", file=sys.stderr)
            continue
        # Same-model: both query and passages were embedded by `mname`, both
        # L2-normalized, so dot product = cosine similarity.
        sims = emb @ q
        for i in range(len(passages)):
            rec = dict(passages[i])
            rec["similarity"] = float(sims[i])
            scored.append(rec)
    scored.sort(key=lambda r: r["similarity"], reverse=True)
    return scored[: max(0, n)]


def store_path_for(project_root: Path) -> Path:
    import durable_paths
    # Protected durable cache (INFRA-030): outside the auto-cleaned output tree.
    return durable_paths.embedding_store_path(project_root)


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
