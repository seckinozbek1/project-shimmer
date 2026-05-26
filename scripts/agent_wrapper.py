"""Base agent wrapper.

API key loading via .env_path, Claude/GPT/Qwen dispatch, contract enforcement,
bus posting with mandatory constitution_check, cost tracker hook.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bus_reader import assemble_context
from constitution import CheckResult, Constitution
from cost_tracker import CostTracker
from message_bus import MessageBus


# Throttle concurrent GPT calls — at most 2 in flight at once. The 30K
# TPM cap on gpt-4o is best avoided by serializing more aggressively than
# the asyncio task graph would otherwise.
_GPT_SEMAPHORE = threading.Semaphore(2)

# Substrings (case-insensitive) that mark a rate-limit error from OpenAI.
_RATE_LIMIT_MARKERS = ("rate limit", "ratelimit", "429", "tokens per min", "tpm")


def _is_rate_limit_error(err: str) -> bool:
    if not err:
        return False
    e = err.lower()
    return any(m in e for m in _RATE_LIMIT_MARKERS)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_api_keys() -> dict[str, str]:
    root = project_root()
    env_path_file = root / ".env_path"
    if not env_path_file.exists():
        return {}
    rel = env_path_file.read_text(encoding="utf-8").strip()
    target = (root / rel).resolve()
    if not target.exists():
        raise FileNotFoundError(f".env_path points to {target}, which does not exist")
    spec = importlib.util.spec_from_file_location("_shimmer_keys", target)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_shimmer_keys"] = mod
    spec.loader.exec_module(mod)
    out = {}
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "BRAVE_API_KEY", "MODEL"):
        if hasattr(mod, k):
            out[k] = getattr(mod, k)
    return out


def _now(): return datetime.now(timezone.utc).isoformat()


@dataclass
class CallResult:
    backend: str
    model: str
    raw_text: str
    parsed: Any = None
    usage: dict = field(default_factory=dict)
    ok: bool = True
    error: str = ""


@dataclass
class AgentWrapper:
    name: str
    constitution: Constitution
    bus: MessageBus
    registry: dict
    contracts: dict
    keys: dict = field(default_factory=dict)
    cost_tracker: CostTracker | None = None

    def __post_init__(self):
        if self.name not in self.registry:
            raise ValueError(f"agent {self.name!r} not in registry")
        self.spec = self.registry[self.name]
        self.backend = self.spec["backend"]
        self.contract = self.contracts.get(self.name, {})
        if not self.keys:
            self.keys = load_api_keys()

    def _record_cost(self, r):
        if self.cost_tracker is None: return
        self.cost_tracker.record(
            agent=self.name, backend=r.backend, model=r.model,
            input_tokens=(r.usage or {}).get("input_tokens"),
            output_tokens=(r.usage or {}).get("output_tokens"),
            ok=r.ok, error=r.error,
        )

    def check_constitution(self, situation): return self.constitution.check(situation)

    def call_claude(self, prompt, *, max_tokens=4096):
        key = self.keys.get("ANTHROPIC_API_KEY")
        if not key:
            r = CallResult("claude_api", "?", "", ok=False, error="ANTHROPIC_API_KEY not loaded")
            self._record_cost(r); return r
        try:
            anthropic = importlib.import_module("anthropic")
        except ImportError as e:
            r = CallResult("claude_api", "?", "", ok=False, error=f"anthropic not installed: {e}")
            self._record_cost(r); return r
        model = self.keys.get("MODEL") or "claude-sonnet-4-20250514"
        if not model.startswith("claude"): model = "claude-sonnet-4-20250514"
        try:
            client = anthropic.Anthropic(api_key=key)
            resp = client.messages.create(model=model, max_tokens=max_tokens,
                                          messages=[{"role": "user", "content": prompt}])
        except Exception as e:
            r = CallResult("claude_api", model, "", ok=False, error=f"{type(e).__name__}: {e}")
            self._record_cost(r); return r
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        r = CallResult("claude_api", model, text, usage={
            "input_tokens": getattr(resp.usage, "input_tokens", None),
            "output_tokens": getattr(resp.usage, "output_tokens", None),
        })
        self._record_cost(r); return r

    def call_gpt(self, prompt, *, max_tokens=4096):
        with _GPT_SEMAPHORE:
            return self._call_gpt_locked(prompt, max_tokens=max_tokens)

    def _call_gpt_locked(self, prompt, *, max_tokens=4096):
        key = self.keys.get("OPENAI_API_KEY")
        if not key:
            r = CallResult("openai_api", "?", "", ok=False, error="OPENAI_API_KEY not loaded")
            self._record_cost(r); return r
        try:
            openai = importlib.import_module("openai")
        except ImportError as e:
            r = CallResult("openai_api", "?", "", ok=False, error=f"openai not installed: {e}")
            self._record_cost(r); return r
        model = "gpt-4o"

        def _attempt():
            try:
                client = openai.OpenAI(api_key=key)
                resp = client.chat.completions.create(
                    model=model, max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
            except Exception as e:
                return None, f"{type(e).__name__}: {e}"
            return resp, ""

        resp, err = _attempt()
        if resp is None and _is_rate_limit_error(err):
            print(
                f"[RATE_LIMIT] {self.name} hit GPT rate limit, waiting 60s before retry",
                file=sys.stderr, flush=True,
            )
            time.sleep(60)
            resp, err = _attempt()
        if resp is None:
            r = CallResult("openai_api", model, "", ok=False, error=err)
            self._record_cost(r); return r
        text = resp.choices[0].message.content or ""
        r = CallResult("openai_api", model, text, usage={
            "input_tokens": getattr(resp.usage, "prompt_tokens", None),
            "output_tokens": getattr(resp.usage, "completion_tokens", None),
        })
        self._record_cost(r); return r

    def call_qwen(self, prompt, *, max_new_tokens=1024):
        try:
            torch = importlib.import_module("torch")
            transformers = importlib.import_module("transformers")
        except ImportError as e:
            r = CallResult("qwen_local", "qwen2.5-7b", "", ok=False, error=f"torch/transformers missing: {e}")
            self._record_cost(r); return r
        model_id = os.environ.get("SHIMMER_QWEN_MODEL", "Qwen/Qwen2.5-7B-Instruct")
        try:
            tok = transformers.AutoTokenizer.from_pretrained(model_id)
            mdl = transformers.AutoModelForCausalLM.from_pretrained(model_id, device_map="auto", load_in_4bit=True)
        except Exception as e:
            r = CallResult("qwen_local", model_id, "", ok=False, error=f"qwen load failed: {e}")
            self._record_cost(r); return r
        inputs = tok(prompt, return_tensors="pt").to(mdl.device)
        with torch.no_grad():
            out = mdl.generate(**inputs, max_new_tokens=max_new_tokens)
        text = tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        r = CallResult("qwen_local", model_id, text, usage={
            "input_tokens": int(inputs["input_ids"].shape[1]),
            "output_tokens": out.shape[-1] - int(inputs["input_ids"].shape[1]),
        })
        self._record_cost(r); return r

    def dispatch(self, prompt, **kwargs):
        if self.backend == "claude_api": return self.call_claude(prompt, **kwargs)
        if self.backend == "openai_api": return self.call_gpt(prompt, **kwargs)
        if self.backend == "qwen_local": return self.call_qwen(prompt, **kwargs)
        return CallResult(self.backend, "?", "", ok=False, error=f"unknown backend {self.backend!r}")

    def parse_contract_output(self, raw):
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"): text = text[4:].strip()
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            arr_start, arr_end = text.find("["), text.rfind("]")
            cand = None
            if arr_start >= 0 and arr_end > arr_start and (start < 0 or arr_start < start):
                cand = text[arr_start:arr_end + 1]
            elif start >= 0 and end > start:
                cand = text[start:end + 1]
            if cand:
                try: obj = json.loads(cand)
                except json.JSONDecodeError as e: return None, [f"json parse failure: {e}"]
            else:
                return None, ["no JSON object found in output"]
        missing = []
        required = self.contract.get("required", [])
        if isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, dict):
                    for rkey in required:
                        if rkey not in item:
                            missing.append(f"[{i}].{rkey}")
        elif isinstance(obj, dict):
            for rkey in required:
                if rkey not in obj:
                    missing.append(rkey)
        # AMENDMENT_DRAFTER: each amendment object inside .amendments must
        # carry the location / convention_ref / original_text / action /
        # severity / comment fields. A missing or None value here is a
        # contract violation and bubbles up to a CHALLENGE on the bus.
        if self.name == "AMENDMENT_DRAFTER" and isinstance(obj, dict):
            amendments = obj.get("amendments")
            if isinstance(amendments, list):
                nested_required = ("location", "convention_ref", "original_text",
                                   "action", "severity", "comment")
                for i, a in enumerate(amendments):
                    if not isinstance(a, dict):
                        missing.append(f"amendments[{i}].(not an object)")
                        continue
                    for field_name in nested_required:
                        if field_name not in a or a.get(field_name) in (None, ""):
                            missing.append(f"amendments[{i}].{field_name}")
        return obj, missing

    def post_to_bus(self, *, recipient, channel, msg_type, body, constitution_check, sender_role="agent"):
        return self.bus.post({
            "timestamp": _now(), "sender": self.name, "sender_role": sender_role,
            "recipient": recipient, "channel": channel, "type": msg_type, "body": body,
            "constitution_check": constitution_check,
        })

    def _persist_contract_violation_raw_text(self, raw_text: str, missing: list) -> Path | None:
        """Write the full raw_text of a contract-violating response to disk so
        the operator can recover what the model actually produced. The bus
        message stores only an excerpt; this file holds the complete output.

        Path: output/audit/contract_violations/{agent}_{timestamp}.txt
        Returns the path on success, or None if persistence failed (never
        raises — recovery is best-effort and must not interrupt the pipeline).
        """
        if not raw_text:
            return None
        try:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            out_dir = project_root() / "output" / "audit" / "contract_violations"
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"{self.name}_{ts}.txt"
            header = (
                f"# Contract violation raw output\n"
                f"# agent: {self.name}\n"
                f"# timestamp: {datetime.now(timezone.utc).isoformat()}\n"
                f"# missing_fields: {missing}\n"
                f"# raw_text_bytes: {len(raw_text.encode('utf-8'))}\n"
                f"# ---\n"
            )
            path.write_text(header + raw_text, encoding="utf-8")
            return path
        except Exception:
            return None

    def build_constitution_check(self, *, laws_consulted, result, resolution=""):
        return {"laws_consulted": laws_consulted, "result": result, "resolution": resolution}

    def prompt_template(self, context_text, work):
        does = "\n".join(f"- {d}" for d in self.spec.get("does", []))
        does_not = "\n".join(f"- {d}" for d in self.spec.get("does_not", []))
        cf = self.contract.get("fields", {}); required = self.contract.get("required", [])
        directives = self.contract.get("directives") or []
        work_str = work if isinstance(work, str) else json.dumps(work, ensure_ascii=False, indent=2)
        directives_block = ""
        if directives:
            directives_block = "## Directives (from contract)\n" + "\n".join(
                f"- {d}" for d in directives
            ) + "\n\n"
        return (f"You are {self.name}, a Project Shimmer agent.\n\n"
                f"## You DO\n{does}\n\n"
                f"## You DO NOT (LAW-II)\n{does_not}\n\n"
                f"{directives_block}"
                f"## Context\n{context_text}\n\n"
                f"## Output contract (return JSON only)\n"
                f"Fields: {cf}\nRequired keys: {required}\n"
                f"If multiple findings (per claim/per paragraph/per amendment), return a JSON array of objects.\n"
                f"Otherwise return a single JSON object. No markdown fences.\n\n"
                f"## Work payload\n{work_str}\n")

    def run_task(self, *, work_payload, run_objectives="", channel="main",
                 recipient="ORCHESTRATOR", recent_bus_limit=30, max_tokens=4096,
                 relevant_precedent_ids=None, convention_registry=None,
                 reference_index_excerpt=None):
        situation = {"agent": self.name, "action": "execute_task",
                     "tags": ["task_execution", self.spec.get("category", "")]}
        check = self.check_constitution(situation)
        pkg = assemble_context(
            backend=self.backend, constitution=self.constitution, bus=self.bus,
            work_payload=work_payload, run_objectives=run_objectives,
            relevant_precedent_ids=relevant_precedent_ids, channel=channel,
            recent_bus_limit=recent_bus_limit,
            convention_registry=convention_registry,
            reference_index_excerpt=reference_index_excerpt,
        )
        prompt = self.prompt_template(pkg.as_text(), work_payload)
        # Per-agent token ceiling override from contract (e.g., ARCHIVIST=4096
        # to fit the corpus-level structural inventory). The contract's
        # max_output_tokens wins over the caller-supplied max_tokens because
        # agents with structural output requirements (inventories, large
        # lists) know better than callers what they need.
        contract_max = self.contract.get("max_output_tokens")
        if isinstance(contract_max, int) and contract_max > 0:
            max_tokens = max(max_tokens, contract_max)
        if self.backend == "qwen_local":
            result = self.dispatch(prompt, max_new_tokens=min(max_tokens, 1024))
        else:
            result = self.dispatch(prompt, max_tokens=max_tokens)
        if not result.ok:
            self.post_to_bus(recipient=recipient, channel=channel, msg_type="YIELD",
                             body={"event": "BACKEND_ERROR", "backend": result.backend, "model": result.model,
                                   "error": result.error},
                             constitution_check=self.build_constitution_check(
                                 laws_consulted=["LAW-V"], result="RESOLVED",
                                 resolution="agent yielded on backend error"))
            return {"ok": False, "agent": self.name, "backend": result.backend, "model": result.model,
                    "parsed": None, "raw_text": "", "contract_missing": [], "error": result.error}
        parsed, missing = self.parse_contract_output(result.raw_text)
        if parsed is None or missing:
            # Persist the full raw_text to disk so post-mortem analysis can
            # recover what the model actually produced. The bus message keeps
            # only a 400-char excerpt for readability; the full text lives at
            # output/audit/contract_violations/{agent}_{timestamp}.txt.
            raw_text_path = self._persist_contract_violation_raw_text(
                result.raw_text, missing
            )
            self.post_to_bus(
                recipient=recipient, channel=channel, msg_type="CHALLENGE",
                body={
                    "event": "CONTRACT_VIOLATION",
                    "backend": result.backend, "model": result.model,
                    "missing_fields": missing,
                    "raw_excerpt": result.raw_text[:400],
                    "raw_text_path": str(raw_text_path) if raw_text_path else None,
                    "raw_text_bytes": len(result.raw_text.encode("utf-8")) if result.raw_text else 0,
                },
                constitution_check=self.build_constitution_check(
                    laws_consulted=["LAW-II"], result="RESOLVED",
                    resolution="agent output did not match contract"
                ),
            )
            return {"ok": False, "agent": self.name, "backend": result.backend, "model": result.model,
                    "parsed": parsed, "raw_text": result.raw_text, "contract_missing": missing,
                    "error": "contract_violation"}
        self.post_to_bus(recipient=recipient, channel=channel, msg_type="INFORM",
                         body={"event": "AGENT_OUTPUT", "backend": result.backend, "model": result.model,
                               "payload": parsed},
                         constitution_check=self.build_constitution_check(
                             laws_consulted=["LAW-V"],
                             result=check.layer or ("RESOLVED" if check.resolved else "RESOLVED"),
                             resolution=(f"governed by {check.rule_id}" if check.resolved
                                         else "no governing rule yet; novel action recorded")))
        return {"ok": True, "agent": self.name, "backend": result.backend, "model": result.model,
                "parsed": parsed, "raw_text": result.raw_text, "contract_missing": [], "error": None}
