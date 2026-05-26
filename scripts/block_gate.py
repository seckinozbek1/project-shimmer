"""BLOCK gate for mid-execution interrupt handling (genesis Part XI Phase 3)."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now(): return datetime.now(timezone.utc).isoformat()


@dataclass
class BlockHandle:
    id: str
    raised_by: str
    channel: str
    agent: str | None
    reason: str
    raised_at: str
    released: bool = False
    release_reason: str = ""
    released_at: str | None = None
    _event: threading.Event = field(default_factory=threading.Event)
    _async_events: list = field(default_factory=list)
    _async_lock: threading.RLock = field(default_factory=threading.RLock)

    def release(self, reason):
        if self.released: return
        self.released = True; self.release_reason = reason; self.released_at = _now()
        self._event.set()
        with self._async_lock:
            for ev in self._async_events:
                _set_async_safe(ev)

    def wait(self, timeout=None): return self._event.wait(timeout=timeout)

    async def wait_async(self, timeout=None):
        if self.released: return True
        ev = asyncio.Event()
        with self._async_lock:
            if self.released: return True
            self._async_events.append(ev)
        try:
            if timeout is None: await ev.wait()
            else: await asyncio.wait_for(ev.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def as_dict(self):
        return {"id": self.id, "raised_by": self.raised_by, "channel": self.channel, "agent": self.agent,
                "reason": self.reason, "raised_at": self.raised_at, "released": self.released,
                "release_reason": self.release_reason, "released_at": self.released_at}


def _set_async_safe(ev):
    try: loop = ev._loop
    except AttributeError: loop = None
    if loop is None or loop.is_closed():
        ev.set(); return
    try: loop.call_soon_threadsafe(ev.set)
    except RuntimeError: ev.set()


@dataclass
class BlockGate:
    blocks: dict = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _seq: int = 0

    def raise_block(self, *, raised_by, channel, reason, agent=None):
        with self._lock:
            self._seq += 1; bid = f"BLK-{self._seq:04d}"
            h = BlockHandle(id=bid, raised_by=raised_by, channel=channel, agent=agent, reason=reason, raised_at=_now())
            self.blocks[bid] = h
            return h

    def release(self, block_id, reason):
        with self._lock:
            h = self.blocks.get(block_id)
            if h is None or h.released: return h
            h.release(reason); return h

    def active(self, channel=None, agent=None):
        with self._lock:
            out = []
            for h in self.blocks.values():
                if h.released: continue
                if channel and h.channel not in (channel, "BROADCAST"): continue
                if agent and h.agent is not None and h.agent != agent: continue
                out.append(h)
            return out

    def is_blocked(self, channel, agent=None): return bool(self.active(channel=channel, agent=agent))

    def wait_clear(self, channel, *, agent=None, timeout=None):
        import time
        deadline = (time.monotonic() + timeout) if timeout is not None else None
        while True:
            handles = self.active(channel=channel, agent=agent)
            if not handles: return True
            remaining = max(0.0, deadline - time.monotonic()) if deadline is not None else None
            if remaining == 0.0: return False
            handles[0].wait(timeout=remaining)
            if deadline is not None and time.monotonic() >= deadline:
                return not self.active(channel=channel, agent=agent)

    async def wait_clear_async(self, channel, *, agent=None, timeout=None):
        deadline = None
        if timeout is not None:
            loop = asyncio.get_running_loop(); deadline = loop.time() + timeout
        while True:
            handles = self.active(channel=channel, agent=agent)
            if not handles: return True
            remaining = None
            if deadline is not None:
                loop = asyncio.get_running_loop()
                remaining = max(0.0, deadline - loop.time())
                if remaining == 0.0: return False
            await handles[0].wait_async(timeout=remaining)
            if deadline is not None:
                loop = asyncio.get_running_loop()
                if loop.time() >= deadline:
                    return not self.active(channel=channel, agent=agent)
