"""Base agent wrapper.

API key loading via .env_path, Claude/GPT/Qwen dispatch, contract enforcement,
bus posting with mandatory constitution_check, cost tracker hook.

The agent registry (config/agent_registry.json) is the SOLE source of each
agent's model: `spec["backend"]` selects the family (cross-family audit, LAW-III)
and `spec["model"]` selects the exact model id. The key layer (.env_path ->
config.py) provides API keys ONLY; it never sets or overrides a model.
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

# Shared resident local-model cache (qwen_local). A 4-bit 7B is several GB
# resident; loading a fresh copy per qwen_local call meant multiple agents on the
# SAME model_id tried to hold several copies and a later load failed (the
# redactor_unavailable that broke the old tier ladder). Key by model_id so the
# first qwen_local call loads once and every later wrapper with that model_id
# REUSES the resident instance. This changes only HOW the model loads, never WHAT
# it does (LAW-IV: still fully local).
_QWEN_MODELS: dict = {}                 # model_id -> (tokenizer, model)
_QWEN_LOAD_LOCK = threading.Lock()      # guards first-load so a concurrent first call cannot double-load


def _load_qwen(model_id):
    """Return the shared resident (tokenizer, model) for `model_id`, loading it at
    most once. Double-checked locking: the fast path returns the cached instance
    without the lock; the slow path loads under the lock and re-checks, so two
    concurrent first-callers cannot each load a copy. Deterministic and local —
    same from_pretrained arguments as before, only shared."""
    cached = _QWEN_MODELS.get(model_id)
    if cached is not None:
        return cached
    transformers = importlib.import_module("transformers")
    with _QWEN_LOAD_LOCK:
        cached = _QWEN_MODELS.get(model_id)        # re-check under the lock
        if cached is None:
            tok = transformers.AutoTokenizer.from_pretrained(model_id)
            mdl = transformers.AutoModelForCausalLM.from_pretrained(
                model_id, device_map="auto", load_in_4bit=True)
            cached = (tok, mdl)
            _QWEN_MODELS[model_id] = cached
    return cached

# Substrings (case-insensitive) that mark a rate-limit error from OpenAI.
_RATE_LIMIT_MARKERS = ("rate limit", "ratelimit", "429", "tokens per min", "tpm")


def _is_rate_limit_error(err: str) -> bool:
    if not err:
        return False
    e = err.lower()
    return any(m in e for m in _RATE_LIMIT_MARKERS)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


# External key-file resolution. The operator's config.py lives OUTSIDE the repo
# and is located at runtime in this fixed order — no absolute path or username is
# ever baked into a tracked file:
#   1. $SHIMMER_CONFIG_PATH  -- explicit override; may point at a config.py file
#      or at a directory containing one. Wins if set and the target exists.
#   2. ../api_keys/config.py -- sibling folder one level above the repo root.
#   3. .env_path             -- legacy repo-root pointer holding a relative path
#      to the config (kept as a fallback for pre-existing setups).
CONFIG_ENV_VAR = "SHIMMER_CONFIG_PATH"
CONFIG_DIRNAME = "api_keys"
CONFIG_FILENAME = "config.py"


def _as_config_file(p) -> Path:
    """Normalize a candidate to the config.py file: a candidate may point at the
    file directly or at a directory that contains it."""
    p = Path(p).expanduser()
    return p / CONFIG_FILENAME if p.is_dir() else p


def candidate_config_paths() -> "list[tuple[str, Path]]":
    """Ordered (source-label, path) config candidates. Pure resolution — does not
    check existence, so callers (e.g. the preflight tool) can report each source.
    No absolute path or username is hardcoded; everything is relative to the repo
    root or supplied by the operator's environment."""
    root = project_root()
    cands: "list[tuple[str, Path]]" = []
    env = os.environ.get(CONFIG_ENV_VAR)
    if env:
        cands.append((CONFIG_ENV_VAR, _as_config_file(env)))
    cands.append(("sibling ../" + CONFIG_DIRNAME + "/" + CONFIG_FILENAME,
                  root.parent / CONFIG_DIRNAME / CONFIG_FILENAME))
    env_path_file = root / ".env_path"
    if env_path_file.exists():
        rel = env_path_file.read_text(encoding="utf-8").strip()
        if rel:
            cands.append((".env_path pointer", (root / rel).resolve()))
    return cands


def resolve_config_path() -> "Path | None":
    """Return the first existing config candidate, or None if the operator has set
    none up. Resilient by design: a keyless environment is a supported state (the
    pipeline gates handle absent keys — model-gate skip, redaction waiver)."""
    for _src, p in candidate_config_paths():
        try:
            if p.exists():
                return p
        except OSError:
            continue
    return None


def load_api_keys() -> dict[str, str]:
    target = resolve_config_path()
    if target is None:
        return {}
    spec = importlib.util.spec_from_file_location("_shimmer_keys", target)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_shimmer_keys"] = mod
    spec.loader.exec_module(mod)
    out = {}
    # KEYS ONLY. The external key file (located via .env_path -> an
    # operator-managed config.py outside the repo) may define anything, but this
    # reader copies out ONLY the allowlisted API-key names below. Every other
    # variable in that file is ignored -- in particular any `model` / `MODEL`
    # (or otherwise model-related) assignment is deliberately NOT read and can
    # never influence which model an agent runs. Model selection is owned
    # exclusively by config/agent_registry.json (spec.model). Do NOT add a model
    # name to this allowlist.
    _KEY_NAMES = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "BRAVE_API_KEY")
    for k in _KEY_NAMES:
        if hasattr(mod, k):
            out[k] = getattr(mod, k)
    return out


def _now(): return datetime.now(timezone.utc).isoformat()


def _match_balanced(text, start):
    """Return the index of the close delimiter matching the JSON opener at
    text[start], or None if unbalanced. Braces/brackets inside JSON string
    literals are ignored (string state + backslash escapes are tracked)."""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == '"': in_str = False
            continue
        if c == '"': in_str = True
        elif c in "{[": depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return i
    return None


def _iter_balanced_json(text):
    """Yield each top-level balanced {...} / [...] span in document order. Nested
    structures inside a span are part of that span, not yielded separately. Used to
    recover JSON from output that wraps it in prose or emits several fragments."""
    i, n = 0, len(text)
    while i < n:
        if text[i] in "{[":
            end = _match_balanced(text, i)
            if end is not None:
                yield text[i:end + 1]
                i = end + 1
                continue
        i += 1


# ---------------------------------------------------------------------------
# Canonical inter-agent envelope (INFRA-037).
#
# Every agent output payload is ONE wrapper, carried as body.payload inside the
# existing message-bus transport envelope (the transport envelope is unchanged):
#
#     {"agent": str, "doc_id": str, "items": [ <flat item>, ... ]}
#
# items is ALWAYS a list (singleton -> one element; empty result -> []). No bare
# list, no bare dict, ever. Each item is STRICTLY FLAT (interp #1): every value is
# a scalar OR an array of scalars -- no nested objects, no arrays of objects.
# Structure is expressed as MORE ITEMS, not nesting.
#
# Per-item core fields:
#   model-owned (the model must supply): ref, kind, confidence, and verdict
#     (verdict is OPTIONAL: present when the agent judges, absent when it only
#     extracts).
#   runtime-owned (stamped/derived here, interp #2 -- the model is never required
#     to produce these correctly): item_id, revision, ts.
#   ref is the singular PRIMARY anchor consumers filter on; ref_ids is the flat
#     array carrying all citations (interp #3).
CORE_ITEM_REQUIRED = ("ref", "kind", "confidence")  # model-owned; verdict optional


def _is_scalar(v) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def _is_flat_item(item) -> bool:
    """Interp #1: an item is one level -- every value is a scalar or an array of
    scalars. A nested object, or an array containing an object, is NOT flat."""
    if not isinstance(item, dict):
        return False
    for v in item.values():
        if _is_scalar(v):
            continue
        if isinstance(v, list) and all(_is_scalar(e) for e in v):
            continue
        return False
    return True


def is_envelope(payload) -> bool:
    """True iff payload is the canonical wrapper shape (agent:str, doc_id:str,
    items:list). Does not validate per-item content."""
    return (isinstance(payload, dict)
            and isinstance(payload.get("agent"), str)
            and isinstance(payload.get("doc_id"), str)
            and isinstance(payload.get("items"), list))


def make_envelope(agent, doc_id, items) -> dict:
    """Build/normalize the canonical wrapper, stamping the RUNTIME-owned per-item
    fields (interp #2): ts (UTC now) and revision (default 1) when absent, and a
    derived item_id when the model omitted one. Model-owned fields are untouched.
    Re-emitting the same logical item with a higher `revision` is how a producer
    supersedes a prior value (see current_items)."""
    norm = []
    for idx, it in enumerate(items or []):
        if not isinstance(it, dict):
            norm.append(it)  # left as-is; validation will flag it
            continue
        item = dict(it)
        if not item.get("ts"):
            item["ts"] = _now()
        if not isinstance(item.get("revision"), int) or isinstance(item.get("revision"), bool):
            item["revision"] = 1
        if not item.get("item_id"):
            item["item_id"] = f"{agent}:{item.get('kind')}:{item.get('ref')}:{idx}"
        norm.append(item)
    return {"agent": agent, "doc_id": doc_id, "items": norm}


def current_items(items):
    """VERSION GUARDRAIL (INFRA-037): reduce items to the current revision per
    item_id -- highest `revision`, tie-break latest `ts`. Items without an item_id
    are kept as-is (they cannot collide). This is the single helper every consumer
    uses so a superseded value is never read."""
    best = {}
    passthrough = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        key = it.get("item_id")
        if key is None:
            passthrough.append(it)
            continue
        cur = best.get(key)
        cand_rank = (it.get("revision", 1), it.get("ts", ""))
        if cur is None or cand_rank > (cur.get("revision", 1), cur.get("ts", "")):
            best[key] = it
    return list(best.values()) + passthrough


def decode_items(payload, *, current=True):
    """THE canonical decoder. Given an agent's body.payload (the wrapper), return
    its items -- by default reduced to the current revision per item_id. A payload
    that is not the canonical wrapper returns [] (callers treat an absent/invalid
    wrapper as 'no items', then flag absence per the READ-WHEN-PRESENT rule). This
    is the ONE reader; no agent path bypasses it."""
    if not is_envelope(payload):
        return []
    items = [it for it in payload["items"] if isinstance(it, dict)]
    return current_items(items) if current else items


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
    # Per-run context (run_context.RunContext). Threaded from the orchestrator so
    # every agent writes its run-scoped artifacts (contract-violation dumps) into
    # the CURRENT run's folder, never a shared global output/ path (Part XXVII §A).
    run_context: Any = None
    # LAW-IV outbound masking (INFRA-041 P2, chokepoint 1). An INJECTED callable
    # (built by sensitivity_layer.make_outbound_prompt_masker; pipeline owns the import,
    # so the boundary "only orchestration imports sensitivity_layer" holds and this module
    # imports nothing from the privacy home). Called just before dispatch to mask the
    # outbound prompt for NETWORK backends under sensitive mode; None => no masking (the
    # default, so non-sensitive runs and unmodified callers are byte-for-byte unchanged).
    outbound_masker: Any = None

    def __post_init__(self):
        if self.name not in self.registry:
            raise ValueError(f"agent {self.name!r} not in registry")
        self.spec = self.registry[self.name]
        self.backend = self.spec["backend"]
        # Registry is the sole source of the agent's model id (no key-layer
        # override, no hardcoded default).
        self.model = self.spec.get("model")
        self.contract = self.contracts.get(self.name, {})
        if not self.keys:
            self.keys = load_api_keys()

    def _record_cost(self, r):
        if self.cost_tracker is None: return
        u = r.usage or {}
        self.cost_tracker.record(
            agent=self.name, backend=r.backend, model=r.model,
            input_tokens=u.get("input_tokens"),
            output_tokens=u.get("output_tokens"),
            # Prompt-cache usage (INFRA-036). Anthropic: cache_read/creation;
            # OpenAI: cached_input_tokens. Absent -> 0 (handled in record()).
            cache_read_input_tokens=u.get("cache_read_input_tokens"),
            cache_creation_input_tokens=u.get("cache_creation_input_tokens"),
            cached_input_tokens=u.get("cached_input_tokens"),
            ok=r.ok, error=r.error,
        )

    def check_constitution(self, situation): return self.constitution.check(situation)

    def call_claude(self, stable_prefix, dynamic_suffix="", *, max_tokens=4096):
        key = self.keys.get("ANTHROPIC_API_KEY")
        if not key:
            r = CallResult("claude_api", "?", "", ok=False, error="ANTHROPIC_API_KEY not loaded")
            self._record_cost(r); return r
        try:
            anthropic = importlib.import_module("anthropic")
        except ImportError as e:
            r = CallResult("claude_api", "?", "", ok=False, error=f"anthropic not installed: {e}")
            self._record_cost(r); return r
        model = self.model
        if not model:
            # No silent substitution: a missing/invalid model is surfaced, not
            # quietly replaced. The registry is the sole source of truth.
            r = CallResult("claude_api", "?", "", ok=False,
                           error=f"no model configured for agent {self.name!r} in agent_registry.json")
            self._record_cost(r); return r
        # Prompt caching (INFRA-036), EXPLICIT for Anthropic: mark the END of the
        # stable prefix with cache_control so it is written once and read at 0.1x
        # on subsequent calls. The prefix must be an EXACT match across calls;
        # build_prompt guarantees no dynamic content precedes the breakpoint.
        # Default TTL is ephemeral (5 minutes), which fits this workload: a run
        # fires many agent calls back-to-back within minutes, so the 5-min window
        # (1.25x write) covers reuse without paying the 2x one-hour write premium.
        if stable_prefix:
            content = [{"type": "text", "text": stable_prefix,
                        "cache_control": {"type": "ephemeral"}}]
            if dynamic_suffix:
                content.append({"type": "text", "text": dynamic_suffix})
        else:
            content = [{"type": "text", "text": dynamic_suffix}]
        try:
            client = anthropic.Anthropic(api_key=key)
            resp = client.messages.create(model=model, max_tokens=max_tokens,
                                          messages=[{"role": "user", "content": content}])
        except Exception as e:
            r = CallResult("claude_api", model, "", ok=False, error=f"{type(e).__name__}: {e}")
            self._record_cost(r); return r
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        # Cache fields (absent on older models / SDKs -> 0, never crash).
        r = CallResult("claude_api", model, text, usage={
            "input_tokens": getattr(resp.usage, "input_tokens", None),
            "output_tokens": getattr(resp.usage, "output_tokens", None),
            "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        })
        self._record_cost(r); return r

    def call_gpt(self, stable_prefix, dynamic_suffix="", *, max_tokens=4096):
        with _GPT_SEMAPHORE:
            return self._call_gpt_locked(stable_prefix, dynamic_suffix, max_tokens=max_tokens)

    def _call_gpt_locked(self, stable_prefix, dynamic_suffix="", *, max_tokens=4096):
        # Prompt caching (INFRA-036), AUTOMATIC for OpenAI: no cache_control. We
        # only STRUCTURE the prompt stable-prefix-first (identical discipline as
        # Claude) so OpenAI's automatic prefix cache actually catches, then verify
        # it via the logged cached_tokens field below.
        prompt = stable_prefix + ("\n\n" + dynamic_suffix if (stable_prefix and dynamic_suffix)
                                  else dynamic_suffix)
        key = self.keys.get("OPENAI_API_KEY")
        if not key:
            r = CallResult("openai_api", "?", "", ok=False, error="OPENAI_API_KEY not loaded")
            self._record_cost(r); return r
        try:
            openai = importlib.import_module("openai")
        except ImportError as e:
            r = CallResult("openai_api", "?", "", ok=False, error=f"openai not installed: {e}")
            self._record_cost(r); return r
        model = self.model
        if not model:
            r = CallResult("openai_api", "?", "", ok=False,
                           error=f"no model configured for agent {self.name!r} in agent_registry.json")
            self._record_cost(r); return r

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
        # OpenAI reports the auto-cached prefix in usage.prompt_tokens_details
        # .cached_tokens (object OR dict, depending on SDK). Absent -> 0, never
        # crash. Logging it makes a silent provider-side cache loss visible (the
        # cached count drops to zero in the cost log) instead of hidden.
        cached = 0
        details = getattr(resp.usage, "prompt_tokens_details", None)
        if isinstance(details, dict):
            cached = details.get("cached_tokens") or 0
        elif details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0
        r = CallResult("openai_api", model, text, usage={
            "input_tokens": getattr(resp.usage, "prompt_tokens", None),
            "output_tokens": getattr(resp.usage, "completion_tokens", None),
            "cached_input_tokens": cached,
        })
        self._record_cost(r); return r

    def call_qwen(self, prompt, *, max_new_tokens=1024):
        try:
            torch = importlib.import_module("torch")
            transformers = importlib.import_module("transformers")
        except ImportError as e:
            r = CallResult("qwen_local", "qwen2.5-7b", "", ok=False, error=f"torch/transformers missing: {e}")
            self._record_cost(r); return r
        model_id = self.model
        if not model_id:
            r = CallResult("qwen_local", "?", "", ok=False,
                           error=f"no model configured for agent {self.name!r} in agent_registry.json")
            self._record_cost(r); return r
        try:
            # Shared resident instance (loaded once per model_id) — the single
            # REDACTOR (qwen_local) reuses ONE 7B; any other qwen_local agent on
            # the same model_id reuses it too (see _load_qwen).
            tok, mdl = _load_qwen(model_id)
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

    def dispatch(self, stable_prefix, dynamic_suffix="", **kwargs):
        """Route a cache-structured (stable_prefix, dynamic_suffix) prompt to the
        backend. Claude marks the stable prefix as an explicit cache breakpoint;
        GPT concatenates stable-first for OpenAI's automatic prefix cache; Qwen
        (local, no caching) receives the plain concatenation."""
        if self.backend == "claude_api": return self.call_claude(stable_prefix, dynamic_suffix, **kwargs)
        if self.backend == "openai_api": return self.call_gpt(stable_prefix, dynamic_suffix, **kwargs)
        if self.backend == "qwen_local":
            full = stable_prefix + ("\n\n" + dynamic_suffix if dynamic_suffix else "")
            return self.call_qwen(full, **kwargs)
        return CallResult(self.backend, "?", "", ok=False, error=f"unknown backend {self.backend!r}")

    def _contract_missing(self, obj):
        """Validate obj against the CANONICAL ENVELOPE (INFRA-037). Returns the
        list of problems; an empty list means the wrapper is valid (an empty
        `items` list IS valid -- a 'nothing to report' result). A bare list or
        bare dict is rejected: it is not the wrapper.

        Checks: the wrapper shape ({agent:str, doc_id:str, items:list}); per item,
        flatness (interp #1), the model-owned core fields (ref/kind/confidence;
        verdict optional, runtime stamps item_id/revision/ts), and this agent's
        contract `required` (agent-specific per-item fields)."""
        if not is_envelope(obj):
            return ["not a canonical envelope {agent:str, doc_id:str, items:list}"]
        missing = []
        required = self.contract.get("required", [])  # agent-specific per-item fields
        for i, item in enumerate(obj["items"]):
            if not isinstance(item, dict):
                missing.append(f"items[{i}].(not an object)")
                continue
            if not _is_flat_item(item):
                missing.append(f"items[{i}].(not flat: nested object or array-of-objects)")
            for rkey in CORE_ITEM_REQUIRED:
                if rkey not in item or item.get(rkey) in (None, ""):
                    missing.append(f"items[{i}].{rkey}")
            for rkey in required:
                if rkey not in item or item.get(rkey) in (None, ""):
                    missing.append(f"items[{i}].{rkey}")
        return missing

    def _finalize_envelope(self, obj):
        """Validate obj as the wrapper and (when it is one) stamp the runtime-owned
        item fields. Returns (wrapper-or-obj, missing)."""
        missing = self._contract_missing(obj)
        if is_envelope(obj):
            return make_envelope(obj["agent"], obj["doc_id"], obj["items"]), missing
        return obj, missing

    def parse_contract_output(self, raw):
        """Parse the model response into the CANONICAL ENVELOPE (INFRA-037).

        (1) STRICT fast path: whole-response json.loads. A clean wrapper is
            accepted (and stamped); a clean bare list/dict is REJECTED (it is not
            the wrapper) and reported as a contract violation.
        (2) TOLERANT recovery (only if strict json fails): scan balanced JSON
            candidates and recover the FIRST that is a valid wrapper -- recovery
            recovers INTO the wrapper, it never fabricates one from a bare list. If
            a candidate parses but is not a valid wrapper, it is returned as a
            best-effort with its problems (so the violation is reported, not
            masked). If nothing parses, return (None, [parse failure])."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"): text = text[4:].strip()
        # (1) strict fast path
        try:
            obj = json.loads(text)
            return self._finalize_envelope(obj)
        except json.JSONDecodeError:
            pass
        # (2) tolerant recovery: first balanced candidate that is a valid wrapper
        first_parsed = None
        last_error = None
        found_candidate = False
        for cand in _iter_balanced_json(text):
            found_candidate = True
            try:
                obj = json.loads(cand)
            except json.JSONDecodeError as e:
                last_error = e
                continue
            env, missing = self._finalize_envelope(obj)
            if not missing:
                return env, []  # first candidate that is a valid wrapper
            if first_parsed is None:
                first_parsed = (env, missing)  # best-effort fallback (reports the violation)
        if first_parsed is not None:
            return first_parsed
        if found_candidate and last_error is not None:
            return None, [f"json parse failure: {last_error}"]
        return None, ["no JSON object found in output"]

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

        Path: <run_dir>/audit/contract_violations/{agent}_{timestamp}.txt — the
        CURRENT run's folder (run-awareness threaded in from the orchestrator).
        If no run context was supplied (e.g. an isolated unit construction), it
        falls back to output/audit/contract_violations/ so nothing is lost.
        Returns the path on success, or None if persistence failed (never
        raises — recovery is best-effort and must not interrupt the pipeline).
        """
        if not raw_text:
            return None
        try:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            if self.run_context is not None:
                out_dir = self.run_context.contract_violations_dir()
            else:
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

    def _output_contract_text(self) -> str:
        """The CANONICAL ENVELOPE output instruction (INFRA-037), shared by
        prompt_template and _stable_agent_block so the two never drift. Instructs
        the wrapper with a 'nothing to report' example and a one-item example."""
        cf = self.contract.get("fields", {}); required = self.contract.get("required", [])
        return (
            "## Output contract — return ONE JSON object (the canonical envelope), no markdown fences:\n"
            f'{{"agent": "{self.name}", "doc_id": "<document id>", "items": [ ... ]}}\n'
            "`items` is ALWAYS a list. Each item is FLAT: one level, values are scalars or arrays of "
            "scalars only — NO nested objects and NO arrays of objects (express structure as MORE items, "
            "e.g. one item per finding/element/redaction).\n"
            "Per item, supply the core fields: ref (the REF-*/segment id this item is about), kind, "
            "confidence (CONFIDENT|UNCERTAIN), verdict (only when you judge), ref_ids (flat array of all "
            "REF-* you cite; a search-discovered web reference is cited as a WEB-REF-* id, INFRA-042). "
            "Plus this agent's fields: "
            f"{cf}; required per item: {required}. "
            "(item_id, revision, ts are stamped by the runtime — you may omit them.)\n"
            f'Nothing to report -> {{"agent": "{self.name}", "doc_id": "<id>", "items": []}}\n'
            f"One item -> {self._worked_item_example()}\n"
        )

    def _worked_item_example(self) -> str:
        """A per-agent worked one-item example. REDACTOR gets a REDACTION-shaped
        example (kind='redaction') so the generic 'finding' example never seeds it
        (that bleed caused valid redactions to be tagged kind='finding' and dropped)."""
        if self.name == "REDACTOR":
            return ('{"agent": "REDACTOR", "doc_id": "<id>", "items": ['
                    '{"ref": "REF-0006", "kind": "redaction", "confidence": "CONFIDENT", '
                    '"span": "<exact text to redact, verbatim>", "category": "<the matched rule\'s category>", '
                    '"replacement": "[REDACTED]", "method": "REDACT", '
                    '"rule_id": "<id of the rule that matched, e.g. CONV-006 or RED-DFLT-001>", '
                    '"ref_ids": ["REF-0006"]}]}')
        if self.name.startswith("EDITOR"):
            return ('{"agent": "' + self.name + '", "doc_id": "<id>", "items": ['
                    '{"ref": "REF-0003", "kind": "editorial_observation", "confidence": "CONFIDENT", '
                    '"verdict": "concern", '
                    '"rationale": "<prose: e.g. amendment 2 restates convention CONV-004 without adding analysis; '
                    'consider merging it with amendment 1 or cutting it for necessity>", '
                    '"ref_ids": ["REF-0003"]}]}')
        return ('{"agent": "' + self.name + '", "doc_id": "<id>", "items": ['
                '{"ref": "REF-0001", "kind": "finding", "confidence": "CONFIDENT", "ref_ids": ["REF-0001"]}]}')

    def prompt_template(self, context_text, work):
        does = "\n".join(f"- {d}" for d in self.spec.get("does", []))
        does_not = "\n".join(f"- {d}" for d in self.spec.get("does_not", []))
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
                f"{self._output_contract_text()}\n"
                f"## Work payload\n{work_str}\n")

    def _stable_agent_block(self) -> str:
        """The per-agent STABLE prompt block: identity + DO/DO-NOT + directives +
        output contract. Identical across this agent's calls within a run; carries
        no per-call/dynamic content. Same text as the corresponding parts of
        prompt_template (only relocated to the front for caching)."""
        does = "\n".join(f"- {d}" for d in self.spec.get("does", []))
        does_not = "\n".join(f"- {d}" for d in self.spec.get("does_not", []))
        directives = self.contract.get("directives") or []
        directives_block = ""
        if directives:
            directives_block = "## Directives (from contract)\n" + "\n".join(
                f"- {d}" for d in directives
            ) + "\n\n"
        return (f"You are {self.name}, a Project Shimmer agent.\n\n"
                f"## You DO\n{does}\n\n"
                f"## You DO NOT (LAW-II)\n{does_not}\n\n"
                f"{directives_block}"
                f"{self._output_contract_text()}")

    def build_prompt(self, pkg, work):
        """Cache-structured prompt as (stable_prefix, dynamic_suffix), INFRA-036.

        stable_prefix = agent stable block + constitution + conventions — the
        largest identical-across-calls block, with NO dynamic content. It is the
        explicit cache breakpoint on the Claude path and the auto-cached prefix on
        the GPT path. dynamic_suffix = per-call context (objectives, precedents,
        retrieved passages, recent bus) + the work payload.

        Same information as prompt_template(pkg.as_text(), work), only reordered
        stable-first (constitution/conventions and the output contract move ahead
        of the per-call sections)."""
        work_str = work if isinstance(work, str) else json.dumps(work, ensure_ascii=False, indent=2)
        stable = self._stable_agent_block()
        st = pkg.stable_text()
        if st:
            stable = stable + "\n## Context\n" + st
        dyn = pkg.dynamic_text()
        dynamic = (dyn + "\n\n" if dyn else "") + f"## Work payload\n{work_str}\n"
        return stable, dynamic

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
        # Cache-structured prompt (INFRA-036): stable prefix first, dynamic suffix
        # last, so Claude (explicit cache_control) and GPT (automatic prefix cache)
        # both reuse the stable prefix across calls.
        stable_prefix, dynamic_suffix = self.build_prompt(pkg, work_payload)
        # LAW-IV outbound masking (INFRA-041 P2, chokepoint 1): mask the assembled prompt
        # UPSTREAM of dispatch, for NETWORK backends under sensitive mode (qwen_local is
        # exempt: local hardware is the sanctioned sensitive handler). The injected masker
        # owns the network/exempt/may_handle_sensitive decision; when none is injected (the
        # default, and every non-sensitive run) this is a no-op and the prompt is unchanged.
        if self.outbound_masker is not None:
            stable_prefix, dynamic_suffix = self.outbound_masker(
                stable_prefix, dynamic_suffix, backend=self.backend, agent=self.name)
        # Per-agent token ceiling override from contract (e.g., ARCHIVIST=4096
        # to fit the corpus-level structural inventory). The contract's
        # max_output_tokens wins over the caller-supplied max_tokens because
        # agents with structural output requirements (inventories, large
        # lists) know better than callers what they need.
        contract_max = self.contract.get("max_output_tokens")
        if isinstance(contract_max, int) and contract_max > 0:
            max_tokens = max(max_tokens, contract_max)
        if self.backend == "qwen_local":
            result = self.dispatch(stable_prefix, dynamic_suffix, max_new_tokens=min(max_tokens, 1024))
        else:
            result = self.dispatch(stable_prefix, dynamic_suffix, max_tokens=max_tokens)
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
            # <run_dir>/audit/contract_violations/{agent}_{timestamp}.txt.
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
                    "raw_text_path": str(raw_text_path) if raw_text_path else None,
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
