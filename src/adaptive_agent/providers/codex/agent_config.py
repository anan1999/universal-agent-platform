from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ImportedCodexAgent:
    name: str
    description: str
    model: str | None
    reasoning: str | None
    source_path: str
    unknown_fields: dict[str, Any] = field(default_factory=dict)
    warning: str | None = None

    def registry_spec(self) -> dict[str, Any]:
        return {"type": "external", "description": self.description, "preferred_model": self.model,
                "reasoning": self.reasoning, "external_agent_config": {"path": self.source_path, "read_only": True},
                "unknown_fields": self.unknown_fields, "status": "enabled" if not self.warning else "warning"}


class CodexAgentConfigAdapter:
    KNOWN = {"name", "description", "model", "model_reasoning_effort", "developer_instructions"}

    def discover(self, codex_home: Path) -> list[ImportedCodexAgent]:
        agents_dir = codex_home / "agents"
        return [self.parse(path) for path in sorted(agents_dir.glob("*.toml"))] if agents_dir.is_dir() else []

    def parse(self, path: Path) -> ImportedCodexAgent:
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            return ImportedCodexAgent(str(data.get("name") or path.stem), str(data.get("description", "")),
                                      data.get("model"), data.get("model_reasoning_effort"), str(path.resolve()),
                                      {key: value for key, value in data.items() if key not in self.KNOWN})
        except (OSError, tomllib.TOMLDecodeError, TypeError) as error:
            return ImportedCodexAgent(path.stem, "", None, None, str(path.resolve()), warning=str(error))

