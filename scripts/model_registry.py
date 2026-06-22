"""Live model resolution + deprecated-model gate (INFRA-026).

The agent registry (config/agent_registry.json) is the SOLE source of each
agent's model id. At run start the pipeline resolves every agent's assigned
model against the provider's CURRENT model list (queried live) and refuses to
run if any assigned model has been retired.

Swaps are NEVER automatic. The operator must explicitly approve each
replacement; an unapproved deprecated model STOPS the run. If a graphical or
remote operator UI is ever built, this approval step MUST surface there too --
a dead model must never be swapped in without an explicit human decision,
regardless of interface (see enforce_current_models).
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path


# Tier-ordered current model ids per backend, strongest first. Used ONLY to
# propose a replacement when an assigned model is missing from the live list;
# never applied without operator approval.
_REPLACEMENT_LADDER = {
    "claude_api": ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"],
    "openai_api": ["gpt-4o", "gpt-4o-mini"],
    "qwen_local": ["Qwen/Qwen2.5-7B-Instruct"],
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def list_available_models(backend, keys):
    """Return a set of currently-available model ids for a backend, or None if
    the list cannot be obtained (missing key, SDK not installed, or a local
    backend with no remote catalog).

    None means 'cannot verify' -> the caller SKIPS the deprecation check for
    that backend (graceful degradation, never a silent swap)."""
    try:
        if backend == "claude_api":
            key = keys.get("ANTHROPIC_API_KEY")
            if not key:
                return None
            anthropic = importlib.import_module("anthropic")
            client = anthropic.Anthropic(api_key=key)
            # client.models.list() auto-paginates; .id is the model string.
            return {m.id for m in client.models.list()}
        if backend == "openai_api":
            key = keys.get("OPENAI_API_KEY")
            if not key:
                return None
            openai = importlib.import_module("openai")
            client = openai.OpenAI(api_key=key)
            return {m.id for m in client.models.list()}
        if backend == "qwen_local":
            # Local weights: no remote catalog to query, and positively
            # verifying availability would mean loading the model. Skip the
            # deprecation check for local backends (return None). Local model
            # retirement is an operator/deployment concern, not an API one.
            return None
    except Exception:
        # Network failure / auth error / SDK quirk: degrade to 'cannot verify'.
        return None
    return None


def _suggest_replacement(backend, available):
    for cand in _REPLACEMENT_LADDER.get(backend, []):
        if available is None or cand in available:
            return cand
    return None


def verify_models_current(registry, keys):
    """Compare every agent's assigned model against the live list for its
    backend.

    Returns (findings, skipped):
      findings: list of {agent, backend, dead_model, suggested_replacement}
                for assigned models NOT in the provider's current list.
      skipped:  list of {agent, backend, model} for backends whose live list
                could not be obtained (no key / local) -- reported, never swapped.
    """
    agents = registry.get("agents", registry)
    cache = {}
    findings = []
    skipped = []
    for name, spec in agents.items():
        backend = spec.get("backend")
        model = spec.get("model")
        if backend not in cache:
            cache[backend] = list_available_models(backend, keys)
        available = cache[backend]
        if available is None:
            skipped.append({"agent": name, "backend": backend, "model": model})
            continue
        if model not in available:
            findings.append({
                "agent": name, "backend": backend, "dead_model": model,
                "suggested_replacement": _suggest_replacement(backend, available),
            })
    return findings, skipped


def _record_approval(project_root, approvals):
    import durable_paths
    # Protected durable governance ledger (INFRA-030): survives reset; never auto-deleted.
    path = durable_paths.model_approvals_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8")).get("approvals", [])
        except json.JSONDecodeError:
            existing = []
    existing.extend(approvals)
    path.write_text(json.dumps({"approvals": existing}, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def enforce_current_models(project_root, registry, keys, *, interactive,
                           operator_handler=None, registry_path=None, now_iso=None):
    """Run the deprecated-model gate at pipeline start.

    Behaviour:
      - All assigned models current -> {"ok": True, "stopped": False, ...}.
      - A backend's live list is unavailable (no key / local) -> that backend
        is skipped with a note (graceful degradation, not a swap).
      - Any deprecated model -> the operator is shown which agent, which dead
        model, and a proposed current replacement, and must EXPLICITLY approve.
        On approval the swap is applied to the registry dict (and persisted to
        registry_path, if given) AND recorded to
        durable/governance/model_approvals.json. Unapproved deprecations STOP the run.

    Never auto-swaps. NOTE: if a UI is ever added, this approval MUST surface
    there too -- a dead model is never replaced without a human decision.
    """
    findings, skipped = verify_models_current(registry, keys)
    result = {"ok": not findings, "findings": findings, "skipped": skipped,
              "approved": [], "stopped": False}
    if not findings:
        return result

    agents = registry.get("agents", registry)
    approvals = []
    for f in findings:
        msg = (f"[model-gate] Agent {f['agent']} is assigned model "
               f"{f['dead_model']!r}, which is NOT in {f['backend']}'s current "
               f"model list (deprecated/retired). Proposed current replacement: "
               f"{f['suggested_replacement']!r}.")
        approved = False
        if interactive and operator_handler is not None:
            decision = operator_handler("MODEL_DEPRECATED", {
                "agent": f["agent"], "backend": f["backend"],
                "dead_model": f["dead_model"],
                "proposed_replacement": f["suggested_replacement"],
                "message": msg,
            })
            approved = str(decision).strip().lower() in {"yes", "y", "approve", "true"}
        if approved and f["suggested_replacement"]:
            agents[f["agent"]]["model"] = f["suggested_replacement"]
            approvals.append({"agent": f["agent"], "backend": f["backend"],
                              "from": f["dead_model"], "to": f["suggested_replacement"],
                              "approved_at": now_iso or _now()})
        else:
            # No approval (or non-interactive run) -> do not swap; STOP.
            result["stopped"] = True

    if approvals:
        _record_approval(project_root, approvals)
        if registry_path is not None:
            Path(registry_path).write_text(
                json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
        result["approved"] = approvals

    result["ok"] = not result["stopped"]
    return result
