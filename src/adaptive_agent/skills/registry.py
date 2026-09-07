from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class SkillRegistry:
    def __init__(self, skills: dict[str, dict[str, Any]] | None = None):
        self._skills = skills or {}
        self.loaded: set[str] = set()

    @classmethod
    def from_yaml(cls, path: Path) -> "SkillRegistry":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(data.get("skills", {}))

    def register(self, name: str, spec: dict[str, Any]) -> None:
        if name in self._skills:
            raise ValueError(f"skill already exists: {name}")
        self._skills[name] = spec

    def load_for(self, required: list[str]) -> dict[str, dict[str, Any]]:
        missing = [name for name in required if name not in self._skills]
        if missing:
            raise KeyError(f"unknown skills: {', '.join(missing)}")
        self.loaded.update(required)
        return {name: self._skills[name] for name in required}

    def all(self) -> dict[str, dict[str, Any]]:
        return dict(self._skills)

