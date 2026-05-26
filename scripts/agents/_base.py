"""Shared helpers for per-agent wrappers."""

from __future__ import annotations

from dataclasses import dataclass

from agent_wrapper import AgentWrapper


@dataclass
class NamedAgent(AgentWrapper):
    CLASS_NAME: str = ""

    def __init__(self, constitution, bus, registry, contracts, keys=None, cost_tracker=None):
        super().__init__(name=self.CLASS_NAME, constitution=constitution, bus=bus,
                         registry=registry, contracts=contracts, keys=keys or {},
                         cost_tracker=cost_tracker)
