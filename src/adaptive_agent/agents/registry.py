from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


class AgentRegistry:
    def __init__(self, agents: dict[str, dict[str, Any]] | None = None):
        self._agents = agents or {}

    @classmethod
    def from_yaml(cls, path: Path) -> "AgentRegistry":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(data.get("agents", {}))

    def register(self, name: str, spec: dict[str, Any]) -> None:
        if name in self._agents:
            raise ValueError(f"agent already exists: {name}")
        self._agents[name] = {**spec, "status": spec.get("status", "enabled")}

    def update(self, name: str, **changes: Any) -> None:
        self._require(name).update(changes)

    def enable(self, name: str) -> None:
        self._require(name)["status"] = "enabled"

    def disable(self, name: str) -> None:
        self._require(name)["status"] = "disabled"

    def deprecate(self, name: str) -> None:
        self._require(name)["status"] = "deprecated"

    def promote(self, name: str) -> None:
        agent = self._require(name)
        if agent.get("successful_uses", 0) < 3:
            raise ValueError("promotion requires at least 3 successful uses")
        agent["type"] = "permanent"
        agent["promotion_candidate"] = False

    def search(self, capabilities: list[str]) -> list[tuple[str, dict[str, Any]]]:
        needed = set(capabilities)
        matches = []
        for name, spec in self._agents.items():
            if spec.get("status", "enabled") == "enabled" and needed <= set(spec.get("capabilities", [])):
                matches.append((name, deepcopy(spec)))
        return matches

    def all(self) -> dict[str, dict[str, Any]]:
        return deepcopy(self._agents)

    def _require(self, name: str) -> dict[str, Any]:
        if name not in self._agents:
            raise KeyError(name)
        return self._agents[name]

