"""Domain-agnostic capability vocabulary shared by the universal core.

Nothing in this module knows about software engineering, Codex, or any model
name. A capability is just a string; the platform reasons about *levels* of
support for capabilities and never about a closed taxonomy.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Iterable


class Support(StrEnum):
    """How a provider or model supports a capability."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    MODEL_DEPENDENT = "model_dependent"
    UNKNOWN = "unknown"

    @property
    def usable(self) -> bool:
        return self in {Support.SUPPORTED, Support.MODEL_DEPENDENT, Support.UNKNOWN}

    @property
    def confidence(self) -> float:
        return {Support.SUPPORTED: 1.0, Support.MODEL_DEPENDENT: 0.6,
                Support.UNKNOWN: 0.3, Support.UNSUPPORTED: 0.0}[self]


class Level(StrEnum):
    """Descriptive strength of a capability. Numeric scores are deliberately avoided."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"
    UNKNOWN = "unknown"

    @property
    def rank(self) -> int:
        return {Level.NONE: 0, Level.LOW: 1, Level.MEDIUM: 2,
                Level.HIGH: 3, Level.VERY_HIGH: 4, Level.UNKNOWN: 2}[self]

    @classmethod
    def coerce(cls, value: Any) -> "Level":
        if isinstance(value, Level):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.UNKNOWN


class Complexity(StrEnum):
    """Drives how deep a task DAG and how large a team may become."""

    TRIVIAL = "trivial"
    SMALL = "small"
    NORMAL = "normal"
    COMPLEX = "complex"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {Complexity.TRIVIAL: 0, Complexity.SMALL: 1, Complexity.NORMAL: 2,
                Complexity.COMPLEX: 3, Complexity.CRITICAL: 4}[self]

    @property
    def max_team_size(self) -> int:
        return {Complexity.TRIVIAL: 1, Complexity.SMALL: 2, Complexity.NORMAL: 3,
                Complexity.COMPLEX: 5, Complexity.CRITICAL: 7}[self]

    @classmethod
    def coerce(cls, value: Any) -> "Complexity":
        if isinstance(value, Complexity):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.NORMAL


class Risk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return {Risk.LOW: 0, Risk.MEDIUM: 1, Risk.HIGH: 2}[self]

    @classmethod
    def coerce(cls, value: Any) -> "Risk":
        if isinstance(value, Risk):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.LOW


_NORMALIZE = re.compile(r"[^a-z0-9]+")


def normalize(capability: str) -> str:
    """Capabilities are free-form strings; normalization keeps them comparable."""
    return _NORMALIZE.sub("_", str(capability).strip().lower()).strip("_")


def signature(capabilities: Iterable[str]) -> str:
    """A portable, order-independent key for performance history.

    History keyed on capabilities transfers across agents, providers, and
    domains; history keyed on agent names does not.
    """
    unique = sorted({normalize(item) for item in capabilities if normalize(item)})
    return "+".join(unique) if unique else "unspecified"


@dataclass(slots=True)
class Requirement:
    """A capability a task needs, and how strongly it needs it."""

    name: str
    level: Level = Level.UNKNOWN
    mandatory: bool = True
    reason: str = ""

    def __post_init__(self) -> None:
        self.name = normalize(self.name)
        self.level = Level.coerce(self.level)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "level": self.level.value,
                "mandatory": self.mandatory, "reason": self.reason}

    @classmethod
    def coerce(cls, value: Any) -> "Requirement":
        if isinstance(value, Requirement):
            return value
        if isinstance(value, dict):
            return cls(value.get("name", ""), Level.coerce(value.get("level", Level.UNKNOWN)),
                       bool(value.get("mandatory", True)), str(value.get("reason", "")))
        return cls(str(value))

    @classmethod
    def many(cls, values: Iterable[Any]) -> list["Requirement"]:
        seen: dict[str, Requirement] = {}
        for value in values:
            requirement = cls.coerce(value)
            if not requirement.name:
                continue
            existing = seen.get(requirement.name)
            if existing is None or requirement.level.rank > existing.level.rank:
                seen[requirement.name] = requirement
        return list(seen.values())


@dataclass(slots=True)
class CapabilityProfile:
    """A named bundle of capability levels, used by models and agents alike."""

    levels: dict[str, Level] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.levels = {normalize(name): Level.coerce(level) for name, level in self.levels.items()}

    def level(self, name: str) -> Level:
        return self.levels.get(normalize(name), Level.UNKNOWN)

    def covers(self, requirement: Requirement) -> bool:
        actual = self.level(requirement.name)
        if actual is Level.NONE:
            return False
        if requirement.level is Level.UNKNOWN or actual is Level.UNKNOWN:
            return True
        return actual.rank >= requirement.level.rank

    def gaps(self, requirements: Iterable[Requirement]) -> list[Requirement]:
        return [item for item in requirements if item.mandatory and not self.covers(item)]

    def coverage(self, requirements: Iterable[Requirement]) -> float:
        items = list(requirements)
        if not items:
            return 1.0
        return sum(1.0 for item in items if self.covers(item)) / len(items)

    def to_dict(self) -> dict[str, str]:
        return {name: level.value for name, level in sorted(self.levels.items())}


@dataclass(slots=True)
class Gap:
    """A capability nothing currently satisfies, plus how it may be closed."""

    capability: str
    reason: str
    resolvable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
