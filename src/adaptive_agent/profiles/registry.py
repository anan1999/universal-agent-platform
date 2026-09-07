"""Work Profiles: starter packs, not a closed taxonomy.

A profile *suggests* capabilities, roles, skills, tools, evaluation strategies,
and artifact expectations for a kind of work. It never mandates them, and an
unrecognised profile id degrades to `general` instead of failing the run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from adaptive_agent.core.capabilities import normalize


GENERAL = "general"


def _mentions(text: str, keyword: str) -> bool:
    """Whole-word keyword match.

    Substring matching turns short keywords into false positives: "ci" fires on
    "decide", "cd" on "record". Detection steers which roles get proposed, so a
    spurious match is not cosmetic.
    """
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword.lower())}(?![a-z0-9])", text) is not None


@dataclass(slots=True)
class ProfileRole:
    """A reasoning responsibility a profile can contribute to a team."""

    id: str
    name: str = ""
    responsibility: str = ""
    capabilities: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    #: Lower stages run first when the planner has no better ordering signal.
    stage: int = 50
    #: Optional roles are dropped first when shrinking to a minimum sufficient team.
    optional: bool = False
    #: Roles that evaluate other work rather than produce artifacts.
    evaluative: bool = False
    #: Roles that must not modify the workspace.
    read_only: bool = False
    profile: str = ""

    def __post_init__(self) -> None:
        self.name = self.name or self.id.replace("_", " ").title()
        self.capabilities = [normalize(item) for item in self.capabilities]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "responsibility": self.responsibility,
                "capabilities": list(self.capabilities), "skills": list(self.skills),
                "stage": self.stage, "optional": self.optional, "evaluative": self.evaluative,
                "read_only": self.read_only, "profile": self.profile}


@dataclass(slots=True)
class WorkProfile:
    id: str
    name: str = ""
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    roles: list[ProfileRole] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    evaluation: list[str] = field(default_factory=list)
    artifact_types: list[str] = field(default_factory=list)
    approval_gates: list[str] = field(default_factory=list)
    #: File markers and goal keywords that suggest this profile.
    detection: dict[str, list[str]] = field(default_factory=dict)
    #: Optional, explicitly opt-in provider/model hints. Never required.
    default_models: dict[str, str] = field(default_factory=dict)
    trust: str = "built_in"
    source: str = ""

    def __post_init__(self) -> None:
        self.name = self.name or self.id.replace("-", " ").title()
        self.capabilities = [normalize(item) for item in self.capabilities]

    def role(self, role_id: str) -> ProfileRole | None:
        return next((item for item in self.roles if item.id == role_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description,
                "capabilities": list(self.capabilities), "roles": [item.to_dict() for item in self.roles],
                "skills": list(self.skills), "tools": list(self.tools),
                "evaluation": list(self.evaluation), "artifact_types": list(self.artifact_types),
                "approval_gates": list(self.approval_gates), "detection": dict(self.detection),
                "default_models": dict(self.default_models), "trust": self.trust, "source": self.source}

    @classmethod
    def from_config(cls, data: dict[str, Any], source: str = "", trust: str = "built_in") -> "WorkProfile":
        spec = data.get("profile", data)
        identifier = str(spec.get("id") or Path(source).stem or "unnamed")
        roles = [ProfileRole(
            id=str(role.get("id")), name=str(role.get("name", "")),
            responsibility=str(role.get("responsibility", "")),
            capabilities=list(role.get("capabilities", [])), skills=list(role.get("skills", [])),
            stage=int(role.get("stage", 50)), optional=bool(role.get("optional", False)),
            evaluative=bool(role.get("evaluative", False)), read_only=bool(role.get("read_only", False)),
            profile=identifier,
        ) for role in spec.get("roles", []) if role.get("id")]
        return cls(
            id=identifier, name=str(spec.get("name", "")), description=str(spec.get("description", "")),
            capabilities=list(spec.get("capabilities", [])), roles=roles,
            skills=list(spec.get("skills", [])), tools=list(spec.get("tools", [])),
            evaluation=list(spec.get("evaluation", [])), artifact_types=list(spec.get("artifact_types", [])),
            approval_gates=list(spec.get("approval_gates", [])),
            detection={key: list(value) for key, value in (spec.get("detection") or {}).items()},
            default_models=dict(spec.get("default_models") or {}),
            trust=str(spec.get("trust", trust)), source=source,
        )


class WorkProfileRegistry:
    def __init__(self, profiles: Iterable[WorkProfile] = ()):
        self._profiles: dict[str, WorkProfile] = {profile.id: profile for profile in profiles}

    @classmethod
    def from_directories(cls, *directories: Path) -> "WorkProfileRegistry":
        registry = cls()
        for directory in directories:
            if not directory or not Path(directory).is_dir():
                continue
            trust = "built_in" if "config" in Path(directory).parts else "trusted"
            for path in sorted(Path(directory).glob("*.yaml")):
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                registry.add(WorkProfile.from_config(data, str(path), trust), replace=True)
        return registry

    def add(self, profile: WorkProfile, replace: bool = False) -> None:
        if profile.id in self._profiles and not replace:
            raise ValueError(f"profile already registered: {profile.id}")
        self._profiles[profile.id] = profile

    def __contains__(self, profile_id: object) -> bool:
        return profile_id in self._profiles

    def ids(self) -> list[str]:
        return sorted(self._profiles)

    def all(self) -> list[WorkProfile]:
        return [self._profiles[key] for key in self.ids()]

    def get(self, profile_id: str) -> WorkProfile | None:
        return self._profiles.get(profile_id)

    def resolve(self, profile_ids: Iterable[str]) -> tuple[list[WorkProfile], list[str]]:
        """Resolve ids to profiles. Unknown ids are reported, never fatal."""
        resolved, unknown = [], []
        for profile_id in profile_ids:
            profile = self._profiles.get(profile_id)
            if profile is None:
                unknown.append(profile_id)
            elif profile not in resolved:
                resolved.append(profile)
        if not resolved:
            fallback = self._profiles.get(GENERAL)
            if fallback is not None:
                resolved.append(fallback)
        return resolved, unknown

    def fallback(self) -> WorkProfile:
        return self._profiles.get(GENERAL) or WorkProfile(GENERAL, "General")

    def roles(self, profile_ids: Iterable[str]) -> list[ProfileRole]:
        profiles, _ = self.resolve(profile_ids)
        seen: dict[str, ProfileRole] = {}
        for profile in profiles:
            for role in profile.roles:
                seen.setdefault(role.id, role)
        return sorted(seen.values(), key=lambda item: (item.stage, item.id))

    def match_capabilities(self, capabilities: Iterable[str]) -> list[tuple[WorkProfile, int]]:
        """Profiles ranked by how many of the given capabilities they cover."""
        wanted = {normalize(item) for item in capabilities}
        scored = []
        for profile in self.all():
            covered = wanted & set(profile.capabilities)
            covered |= wanted & {item for role in profile.roles for item in role.capabilities}
            if covered:
                scored.append((profile, len(covered)))
        return sorted(scored, key=lambda item: (-item[1], item[0].id))

    def suggest(self, markers: Iterable[str], keywords: Iterable[str] = ()) -> list[tuple[str, list[str]]]:
        """Profiles suggested by project file markers and goal keywords."""
        marker_set = {str(item).lower() for item in markers}
        keyword_text = " ".join(str(item).lower() for item in keywords)
        suggestions = []
        for profile in self.all():
            evidence = sorted(marker_set & {item.lower() for item in profile.detection.get("files", [])})
            evidence += [word for word in profile.detection.get("keywords", [])
                         if _mentions(keyword_text, word)]
            if evidence:
                suggestions.append((profile.id, sorted(set(evidence))))
        return sorted(suggestions, key=lambda item: (-len(item[1]), item[0]))

    def to_dict(self) -> list[dict[str, Any]]:
        return [profile.to_dict() for profile in self.all()]


_DEFAULT: WorkProfileRegistry | None = None


def profile_registry(refresh: bool = False) -> WorkProfileRegistry:
    """Built-in profiles plus any installed in the user's platform home."""
    global _DEFAULT
    if _DEFAULT is None or refresh:
        from adaptive_agent.runtime import PACKAGE_ROOT, platform_home

        _DEFAULT = WorkProfileRegistry.from_directories(
            PACKAGE_ROOT / "config" / "profiles",
            platform_home() / "profiles",
        )
    return _DEFAULT
