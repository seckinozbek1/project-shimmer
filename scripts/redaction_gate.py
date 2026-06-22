"""Qwen-required startup gate for the always-on redaction phase (INFRA-035).

Redaction is the final pipeline phase (INFRA-034) and runs on the local Qwen
backend. Before any agent runs, the pipeline confirms that backend is
reachable/configured. If it is not, the run REFUSES to start — unless the
operator explicitly waives redaction for THIS run (per-run only, never a
persistent setting), which is logged to the governance ledger.

HONEST SCOPE — what is verified pre-run vs at first call:
  Verified NOW (cheap, no model load, no paid call): torch + transformers are
    importable, and a qwen_local model id is configured in the agent registry.
    GPU presence is probed with torch.cuda.is_available().
  Verified AT FIRST REDACTION CALL (not here): the actual model load/download
    (transformers.AutoModelForCausalLM.from_pretrained) and GPU placement. A local
    load can still fail at first use even when this pre-run check passes; the
    redaction phase degrades safely in that case (REDACTION_SKIPPED, INFRA-034).

GPU is a SOFT reminder only: if Qwen is configured but no GPU is detected, the
caller prints a "redaction will be slow on CPU" warning. That is never recorded
and never blocks.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


def qwen_backend_status(project_root) -> dict:
    """Cheap pre-run probe of the local Qwen redaction backend. No model load,
    no network, no paid call. Returns a status dict (see module docstring for the
    verified-now vs verified-at-first-call split)."""
    # Model id from the registry (also confirms qwen_local agents exist).
    model_id = None
    try:
        reg = json.loads((Path(project_root) / "config" / "agent_registry.json")
                         .read_text(encoding="utf-8"))
        for spec in reg.get("agents", {}).values():
            if spec.get("backend") == "qwen_local":
                model_id = spec.get("model")
                break
    except Exception:
        pass

    have_torch = importlib.util.find_spec("torch") is not None
    have_tf = importlib.util.find_spec("transformers") is not None
    missing_libs = [n for n, ok in (("torch", have_torch), ("transformers", have_tf)) if not ok]
    configured = have_torch and have_tf and bool(model_id)

    gpu = False
    if have_torch:
        try:
            torch = importlib.import_module("torch")
            gpu = bool(torch.cuda.is_available())
        except Exception:
            gpu = False

    if configured:
        detail = f"torch+transformers importable; qwen_local model {model_id!r} configured"
    else:
        bits = []
        if missing_libs:
            bits.append("missing libraries: " + ", ".join(missing_libs))
        if not model_id:
            bits.append("no qwen_local model id in agent_registry.json")
        detail = "; ".join(bits) or "Qwen backend not configured"

    return {
        "configured": configured,
        "gpu": gpu,
        "model_id": model_id,
        "missing_libs": missing_libs,
        "detail": detail,
        "verified_now": "torch+transformers importable + qwen_local model id configured",
        "verified_at_first_call": "actual model load/download and GPU placement",
    }


def record_redaction_waiver(project_root, run_id, *, reason, now_iso=None) -> Path:
    """Append a per-run redaction-waiver record to the governance ledger
    (durable/governance/redaction_waivers.jsonl — survives reset, never deleted).
    Records that the operator consciously waived redaction for THIS run only."""
    import durable_paths
    path = durable_paths.redaction_waivers_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": now_iso or datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "event": "REDACTION_WAIVED",
        "reason": reason,
        "scope": "this run only",
        "note": "operator declared this run non-sensitive and accepted running with no redaction",
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path
