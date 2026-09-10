"""Versioned, machine-readable Skill packages.

A Skill is a reusable procedure and its supporting assets.  The manifest is
metadata-only so discovery never has to place instructions or references into
model context.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from adaptive_agent.core.capabilities import normalize


class SkillTrust(StrEnum):
    BUILT_IN = "built_in"
    TRUSTED = "trusted"
    PROJECT_LOCAL = "project_local"
    UNVERIFIED = "unverified"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


class SkillStatus(StrEnum):
    ACTIVE = "active"
    TEMPORARY = "temporary"
    EXPERIMENTAL = "experimental"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


@dataclass(slots=True)
class SkillManifest:
    id: str
    version: str = "0.0.0"
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    entrypoint: str = "SKILL.md"
    references: dict[str, str] = field(default_factory=dict)
    evaluation: list[str] = field(default_factory=list)
    security: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    trust: SkillTrust = SkillTrust.UNVERIFIED
    status: SkillStatus = SkillStatus.ACTIVE
    estimated_context_tokens: int | None = None
    portability: float | None = None
    path: Path | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.capabilities = [normalize(item) for item in self.capabilities]
        self.trust = self.trust if isinstance(self.trust, SkillTrust) else SkillTrust(self.trust)
        self.status = self.status if isinstance(self.status, SkillStatus) else SkillStatus(self.status)
        self.dependencies = list(dict.fromkeys(self.dependencies))

    @classmethod
    def from_file(cls, path: Path, default_trust: SkillTrust = SkillTrust.UNVERIFIED) -> "SkillManifest":
        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.setdefault("trust", default_trust.value)
        manifest = cls(**payload)
        manifest.path = path.parent.resolve()
        return manifest

    @classmethod
    def from_legacy(cls, identifier: str, spec: dict[str, Any]) -> "SkillManifest":
        scope = str(spec.get("scope", "global"))
        trust = SkillTrust.PROJECT_LOCAL if scope == "project" else SkillTrust.BUILT_IN
        return cls(identifier, str(spec.get("version", "0.0.0")),
                   str(spec.get("description", "")), list(spec.get("capabilities", [])),
                   tools=list(spec.get("tools", [])), evaluation=list(spec.get("evaluation", [])),
                   trust=trust, provenance={"source": "v2.1-compatibility"},
                   estimated_context_tokens=spec.get("estimated_context_tokens"))

    def to_dict(self, include_path: bool = True) -> dict[str, Any]:
        result = asdict(self)
        result["trust"] = self.trust.value
        result["status"] = self.status.value
        result["path"] = str(self.path) if include_path and self.path else None
        return result


@dataclass(slots=True)
class LoadedSkill:
    manifest: SkillManifest
    instructions: str
    references: dict[str, str] = field(default_factory=dict)

    @property
    def context_chars(self) -> int:
        return len(self.instructions) + sum(len(value) for value in self.references.values())

    @property
    def estimated_context_tokens(self) -> int:
        return max(1, (self.context_chars + 3) // 4)

    def to_context(self) -> str:
        sections = [f"SKILL {self.manifest.id}@{self.manifest.version}", self.instructions.strip()]
        sections.extend(f"REFERENCE {name}:\n{body.strip()}" for name, body in self.references.items())
        return "\n\n".join(item for item in sections if item)

