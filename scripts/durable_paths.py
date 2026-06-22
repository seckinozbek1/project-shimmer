"""Protected durable-asset paths (genesis Part XXVII §B / INFRA-030).

The protected class lives OUTSIDE any auto-cleaned/output tree, under a single
top-level `durable/` directory, so protection is STRUCTURAL (by location), not
just a name-check. No per-run cleanup, and no reset wipe path, iterates durable/.

Internal layout encodes reset semantics by location:
  durable/cache/      domain-learning caches (embedding store, verification tier-2) -> RESETTABLE
  durable/global/     cross-project caches (verification tier-3)                     -> SURVIVES reset
  durable/learnings/  discovered learnings (institutions/citations/speech-acts/...)  -> RESETTABLE
  durable/reference/  learned reference assets (linguistic identity, situational)    -> RESETTABLE
  durable/governance/ operator-approval + amendment-guard ledgers                    -> SURVIVES reset (never deleted)

This module is the single source of truth for these paths. Every writer and
reader imports from here.
"""

from __future__ import annotations

from pathlib import Path

DURABLE_DIRNAME = "durable"

CACHE = "cache"
GLOBAL = "global"
LEARNINGS = "learnings"
REFERENCE = "reference"
GOVERNANCE = "governance"

# Subdirs reset is allowed to strip (after snapshot-first backup) vs. never.
RESETTABLE_SUBDIRS = (CACHE, LEARNINGS, REFERENCE)
PRESERVED_SUBDIRS = (GLOBAL, GOVERNANCE)
ALL_SUBDIRS = (CACHE, GLOBAL, LEARNINGS, REFERENCE, GOVERNANCE)


def durable_root(project_root) -> Path:
    return Path(project_root) / DURABLE_DIRNAME


def _sub(project_root, name) -> Path:
    return durable_root(project_root) / name


def cache_dir(pr): return _sub(pr, CACHE)
def global_dir(pr): return _sub(pr, GLOBAL)
def learnings_dir(pr): return _sub(pr, LEARNINGS)
def reference_dir(pr): return _sub(pr, REFERENCE)
def governance_dir(pr): return _sub(pr, GOVERNANCE)


# --- cache (resettable) ---
def embedding_store_path(pr): return cache_dir(pr) / "embedding_store.pkl"
def verification_cache_path(pr): return cache_dir(pr) / "verification_cache.json"        # tier-2 project

# --- global (survives reset) ---
def verification_cache_global_path(pr): return global_dir(pr) / "verification_cache_global.json"  # tier-3

# --- learnings (resettable) ---
def institution_registry_path(pr): return learnings_dir(pr) / "institution_registry.json"
def citation_convention_path(pr): return learnings_dir(pr) / "citation_convention.json"
def speech_acts_taxonomy_path(pr): return learnings_dir(pr) / "speech_acts_taxonomy.json"
def search_strategy_learnings_path(pr): return learnings_dir(pr) / "search_strategy_learnings.json"
def discovered_apis_path(pr): return learnings_dir(pr) / "discovered_apis.json"
def document_dates_path(pr): return learnings_dir(pr) / "document_dates.json"

# --- reference (resettable) ---
def linguistic_identity_path(pr): return reference_dir(pr) / "LINGUISTIC_IDENTITY.md"
def situational_awareness_path(pr): return reference_dir(pr) / "situational_awareness.md"

# --- governance (survives reset; never deleted) ---
def model_approvals_path(pr): return governance_dir(pr) / "model_approvals.json"
def constitution_guard_log_path(pr): return governance_dir(pr) / "constitution_guard_log.jsonl"
def redaction_waivers_path(pr): return governance_dir(pr) / "redaction_waivers.jsonl"


def ensure_dirs(project_root) -> None:
    """Create all durable subdirs (idempotent). Used at boot / first write."""
    for name in ALL_SUBDIRS:
        _sub(project_root, name).mkdir(parents=True, exist_ok=True)


def is_protected(path, project_root) -> bool:
    """True if `path` lives anywhere under durable/. Cleanup/reset code uses this
    to refuse, by location, to touch the protected class."""
    try:
        Path(path).resolve().relative_to(durable_root(project_root).resolve())
        return True
    except (ValueError, OSError):
        return False
