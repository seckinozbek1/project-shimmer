"""Live cost tracker for Project Shimmer API calls.

PRICING (as of January 2026, conservative — verify before billing):
    Claude Sonnet 4 (claude-sonnet-4-*):  $3.00 / 1M input,  $15.00 / 1M output
    GPT-4o (gpt-4o*):                     $2.50 / 1M input,  $10.00 / 1M output
    Qwen local:                           zero cloud cost
"""

from __future__ import annotations

import json
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PRICING = {
    "claude": {"input_per_mtok": 3.00, "output_per_mtok": 15.00, "label": "Claude Sonnet 4 ($3/$15 per Mtok)"},
    "gpt":    {"input_per_mtok": 2.50, "output_per_mtok": 10.00, "label": "GPT-4o ($2.50/$10 per Mtok)"},
    "qwen":   {"input_per_mtok": 0.0,  "output_per_mtok": 0.0,   "label": "Qwen local (zero cloud cost)"},
}


def _now_iso(): return datetime.now(timezone.utc).isoformat()


def _model_family(s):
    s = (s or "").lower()
    if "claude" in s or s == "claude_api": return "claude"
    if "gpt" in s or "openai" in s: return "gpt"
    if "qwen" in s: return "qwen"
    return "other"


def _calc_cost(family, in_tok, out_tok, *, cache_read=0, cache_write=0, cached_in=0):
    """Cache-aware cost (INFRA-036). With no cache args this is the plain formula
    (backward-compatible with estimate_cost). Anthropic: input_tokens is the
    UNCACHED input; cache reads bill 0.1x, 5-min ephemeral writes 1.25x. OpenAI:
    prompt_tokens INCLUDES the cached prefix; cached portion bills 0.5x."""
    r = PRICING.get(family)
    if not r: return 0.0
    inr = r["input_per_mtok"] / 1e6; outr = r["output_per_mtok"] / 1e6
    if family == "claude":
        billed_in = (in_tok or 0) * 1.0 + (cache_read or 0) * 0.1 + (cache_write or 0) * 1.25
    elif family == "gpt":
        cached = min(cached_in or 0, in_tok or 0)
        billed_in = ((in_tok or 0) - cached) * 1.0 + cached * 0.5
    else:
        billed_in = (in_tok or 0)
    return round(billed_in * inr + (out_tok or 0) * outr, 6)


@dataclass
class CostEvent:
    timestamp: str
    agent: str
    backend: str
    model: str
    family: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    ok: bool
    error: str = ""
    # Prompt-cache usage (INFRA-036). Anthropic: cache_read/creation_input_tokens.
    # OpenAI: cached_input_tokens. Default 0 so a provider that returns no cache
    # fields logs zeros (a silent cache loss shows as the count dropping to 0).
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cached_input_tokens: int = 0

    def as_dict(self): return self.__dict__


@dataclass
class CostTracker:
    log_dir: Path
    events_path: Path
    snapshot_path: Path
    print_live: bool = True
    stream: Any = None
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _events: list = field(default_factory=list)
    _by_family: dict = field(default_factory=dict)
    _by_agent: dict = field(default_factory=dict)
    _total_cost: float = 0.0
    _total_calls: int = 0
    _total_failures: int = 0

    @classmethod
    def open(cls, log_dir, *, print_live=True, stream=None):
        log_dir.mkdir(parents=True, exist_ok=True)
        return cls(log_dir=log_dir, events_path=log_dir / "cost_tracker.jsonl",
                   snapshot_path=log_dir / "cost_tracker.json", print_live=print_live, stream=stream)

    def record(self, *, agent, backend, model, input_tokens, output_tokens, ok, error="",
               cache_read_input_tokens=None, cache_creation_input_tokens=None,
               cached_input_tokens=None):
        family = _model_family(model or backend)
        in_tok = int(input_tokens or 0); out_tok = int(output_tokens or 0)
        cache_read = int(cache_read_input_tokens or 0)
        cache_write = int(cache_creation_input_tokens or 0)
        cached_in = int(cached_input_tokens or 0)
        cost = _calc_cost(family, in_tok, out_tok, cache_read=cache_read,
                          cache_write=cache_write, cached_in=cached_in) if ok else 0.0
        event = CostEvent(_now_iso(), agent, backend, model, family, in_tok, out_tok, cost, ok, error,
                          cache_read_input_tokens=cache_read,
                          cache_creation_input_tokens=cache_write,
                          cached_input_tokens=cached_in)
        with self._lock:
            self._events.append(event)
            self._total_calls += 1
            if not ok: self._total_failures += 1
            self._total_cost = round(self._total_cost + cost, 6)
            for store, key in ((self._by_family, family), (self._by_agent, agent)):
                state = store.setdefault(key, {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                               "cost_usd": 0.0, "failures": 0,
                                               "cache_read_input_tokens": 0,
                                               "cache_creation_input_tokens": 0,
                                               "cached_input_tokens": 0})
                state["calls"] += 1; state["input_tokens"] += in_tok; state["output_tokens"] += out_tok
                state["cost_usd"] = round(state["cost_usd"] + cost, 6)
                state["cache_read_input_tokens"] = state.get("cache_read_input_tokens", 0) + cache_read
                state["cache_creation_input_tokens"] = state.get("cache_creation_input_tokens", 0) + cache_write
                state["cached_input_tokens"] = state.get("cached_input_tokens", 0) + cached_in
                if not ok: state["failures"] += 1
            self._persist_event(event); self._persist_snapshot()
            if self.print_live: self._print_live(event)
        return event

    def get_live_state(self):
        with self._lock:
            return {
                "timestamp": _now_iso(),
                "total_cost_usd": round(self._total_cost, 6),
                "total_calls": self._total_calls,
                "total_failures": self._total_failures,
                "by_family": {k: dict(v) for k, v in self._by_family.items()},
                "by_agent": {k: dict(v) for k, v in self._by_agent.items()},
                "pricing": PRICING,
            }

    def finalize_line(self):
        if not self.print_live: return
        stream = self.stream or sys.stderr
        try: stream.write("\n"); stream.flush()
        except Exception: pass

    # Master-and-derived discipline (genesis Part XXVII §E / INFRA-033):
    # cost_tracker.jsonl is the append-only EVENT MASTER (one line per call — the
    # audit trail). cost_tracker.json is a DERIVED aggregate snapshot: a pure
    # function of those events (get_live_state() sums the same per-call data the
    # events record), rewritten after every record(). The two files serve
    # genuinely different purposes — immutable per-event audit log vs. fast-read
    # current totals — so both are kept; the .json is never an independent source,
    # only a recomputed view of the .jsonl events.
    def _persist_event(self, event):
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.as_dict(), ensure_ascii=False) + "\n")

    def _persist_snapshot(self):
        snap = self.get_live_state()
        tmp = self.snapshot_path.with_suffix(self.snapshot_path.suffix + ".tmp")
        tmp.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.snapshot_path)

    def _print_live(self, event):
        stream = self.stream or sys.stderr
        claude = self._by_family.get("claude", {}).get("cost_usd", 0.0)
        gpt = self._by_family.get("gpt", {}).get("cost_usd", 0.0)
        # Prompt-cache visibility (INFRA-036): cumulative Claude cache-read tokens
        # and GPT cached-prefix tokens. A drop to 0 over a run flags a silent miss.
        cr = self._by_family.get("claude", {}).get("cache_read_input_tokens", 0)
        gc = self._by_family.get("gpt", {}).get("cached_input_tokens", 0)
        cache_blurb = f" | cache: claude_read={cr} gpt_cached={gc}" if (cr or gc) else ""
        marker = "+" if event.ok else "x"
        line = (f"[COST] {event.agent:<18} {marker}${event.cost_usd:.4f} "
                f"| Claude: ${claude:.4f} | GPT: ${gpt:.4f} | TOTAL: ${self._total_cost:.4f}{cache_blurb} "
                f"({self._total_calls} calls{'; ' + str(self._total_failures) + ' err' if self._total_failures else ''})")
        try:
            stream.write("\r" + " " * 240 + "\r" + line[:240]); stream.flush()
        except Exception:
            pass


def estimate_cost(*, claude_calls, claude_in, claude_out, gpt_calls, gpt_in, gpt_out):
    return {
        "claude_cost_usd": round(_calc_cost("claude", claude_in * claude_calls, claude_out * claude_calls), 4),
        "gpt_cost_usd": round(_calc_cost("gpt", gpt_in * gpt_calls, gpt_out * gpt_calls), 4),
        "total_usd": round(_calc_cost("claude", claude_in * claude_calls, claude_out * claude_calls) +
                           _calc_cost("gpt", gpt_in * gpt_calls, gpt_out * gpt_calls), 4),
    }
