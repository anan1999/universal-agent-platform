"""Goal analysis: turn a sentence into capabilities, complexity, and risk.

Deterministic and offline. Analysis must never consume AI quota, and it must
never reject a goal for being outside a known domain — an unrecognised goal
still produces a valid capability set via the general profile.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml

from adaptive_agent.core.capabilities import Complexity, Level, Requirement, Risk, normalize, signature
from adaptive_agent.profiles.registry import WorkProfileRegistry


@dataclass(slots=True)
class GoalAnalysis:
    goal: str
    capabilities: list[str] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    complexity: Complexity = Complexity.NORMAL
    risk: Risk = Risk.LOW
    read_only: bool = False
    profiles: list[str] = field(default_factory=list)
    unknown_profiles: list[str] = field(default_factory=list)
    artifact_types: list[str] = field(default_factory=list)
    approval_gates: list[str] = field(default_factory=list)
    #: Human-readable trace of why each conclusion was drawn.
    evidence: list[str] = field(default_factory=list)
    #: True when nothing in the lexicon matched and the general fallback was used.
    inferred: bool = False

    @property
    def capability_signature(self) -> str:
        return signature(self.capabilities)

    def to_dict(self) -> dict[str, Any]:
        return {"goal": self.goal, "capabilities": list(self.capabilities),
                "requirements": [item.to_dict() for item in self.requirements],
                "complexity": self.complexity.value, "risk": self.risk.value,
                "read_only": self.read_only, "profiles": list(self.profiles),
                "unknown_profiles": list(self.unknown_profiles),
                "artifact_types": list(self.artifact_types),
                "approval_gates": list(self.approval_gates),
                "capability_signature": self.capability_signature,
                "evidence": list(self.evidence), "inferred": self.inferred}


class GoalAnalyzer:
    def __init__(self, lexicon: dict[str, Any] | None = None,
                 profiles: WorkProfileRegistry | None = None):
        self.lexicon = lexicon if lexicon is not None else default_lexicon()
        self.profiles = profiles

    @classmethod
    def from_yaml(cls, path: Path, profiles: WorkProfileRegistry | None = None) -> "GoalAnalyzer":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(data, profiles)

    def analyze(self, goal: str, active_profiles: Sequence[str] = (),
                project_signals: Iterable[str] = ()) -> GoalAnalysis:
        text = " ".join(str(goal).lower().split())
        evidence: list[str] = []

        capabilities = self._capabilities(text, evidence)
        profiles, unknown = self._profiles(text, capabilities, active_profiles, project_signals, evidence)
        inferred = not capabilities

        if inferred and self.profiles is not None:
            declared, _ = self.profiles.resolve([str(item) for item in active_profiles])
            if declared:
                capabilities = sorted({capability for profile in declared
                                       for capability in profile.capabilities})
                evidence.append("No capability keyword matched; inherited capabilities from the "
                                "explicitly active profile(s): "
                                + ", ".join(profile.id for profile in declared) + ".")
            else:
                fallback = self.profiles.fallback()
                capabilities = list(fallback.capabilities)
                evidence.append("No capability keyword matched; inferred a generic capability set "
                                f"from the {fallback.id} profile so the goal is still planned.")

        risk = self._risk(text, evidence)
        complexity = self._complexity(text, capabilities, risk, evidence)
        read_only = self._read_only(text, evidence)
        gates = self._approval_gates(text, profiles, evidence)
        artifacts = self._artifacts(text, profiles, active_profiles)

        floor = {Complexity.TRIVIAL: Level.LOW, Complexity.SMALL: Level.LOW,
                 Complexity.NORMAL: Level.MEDIUM, Complexity.COMPLEX: Level.HIGH,
                 Complexity.CRITICAL: Level.VERY_HIGH}[complexity]
        requirements = [Requirement(name, floor, mandatory=False) for name in capabilities]

        return GoalAnalysis(goal=str(goal), capabilities=capabilities, requirements=requirements,
                            complexity=complexity, risk=risk, read_only=read_only,
                            profiles=profiles, unknown_profiles=unknown, artifact_types=artifacts,
                            approval_gates=gates, evidence=evidence, inferred=inferred)

    # -- individual signals ------------------------------------------------

    def _capabilities(self, text: str, evidence: list[str]) -> list[str]:
        found: dict[str, list[str]] = {}
        for capability, phrases in (self.lexicon.get("capabilities") or {}).items():
            hits = [phrase for phrase in phrases if _contains(text, phrase)]
            if hits:
                found[normalize(capability)] = hits
        if found:
            preview = ", ".join(f"{name} ({found[name][0]!r})" for name in sorted(found)[:5])
            evidence.append(f"Goal wording indicates: {preview}.")
        return sorted(found)

    def _profiles(self, text: str, capabilities: list[str], active: Sequence[str],
                  project_signals: Iterable[str], evidence: list[str]) -> tuple[list[str], list[str]]:
        declared = [str(item) for item in active]
        if self.profiles is None:
            return declared, []
        resolved, unknown = self.profiles.resolve(declared)
        if unknown:
            evidence.append(f"Unknown profile(s) {', '.join(unknown)} ignored; "
                            "the goal is planned from its capabilities instead.")
        selected = [profile.id for profile in resolved]

        suggested = self.profiles.suggest(project_signals, [text])
        for profile_id, why in suggested:
            if profile_id not in selected:
                selected.append(profile_id)
                evidence.append(f"Activated {profile_id} profile ({', '.join(why[:3])}).")
        for profile, overlap in self.profiles.match_capabilities(capabilities)[:2]:
            if profile.id not in selected and overlap >= 2:
                selected.append(profile.id)
                evidence.append(f"Activated {profile.id} profile ({overlap} matching capabilities).")
        return selected or [self.profiles.fallback().id], unknown

    def _risk(self, text: str, evidence: list[str]) -> Risk:
        table = self.lexicon.get("risk") or {}
        for level in ("high", "medium"):
            hit = next((phrase for phrase in table.get(level, []) if _contains(text, phrase)), None)
            if hit:
                evidence.append(f"Risk assessed {level} ({hit!r} in the goal).")
                return Risk.coerce(level)
        return Risk.LOW

    def _complexity(self, text: str, capabilities: list[str], risk: Risk,
                    evidence: list[str]) -> Complexity:
        table = self.lexicon.get("complexity") or {}
        chosen: Complexity | None = None
        reason = ""
        for level in ("trivial", "small", "complex", "critical"):
            hit = next((phrase for phrase in table.get(level, []) if _contains(text, phrase)), None)
            if not hit:
                continue
            candidate = Complexity.coerce(level)
            if chosen is None or candidate.rank > chosen.rank:
                chosen, reason = candidate, hit
        if chosen is not None:
            evidence.append(f"Complexity {chosen.value} ({reason!r} in the goal).")
        else:
            chosen = Complexity.SMALL if len(capabilities) <= 1 else Complexity.NORMAL
            evidence.append(f"Complexity {chosen.value} from {len(capabilities)} distinct capability area(s).")
        if risk is Risk.HIGH and chosen.rank < Complexity.COMPLEX.rank:
            evidence.append("Raised to complex because the goal carries high risk.")
            chosen = Complexity.COMPLEX
        return chosen

    def _read_only(self, text: str, evidence: list[str]) -> bool:
        hit = next((phrase for phrase in (self.lexicon.get("read_only") or []) if _contains(text, phrase)), None)
        if hit:
            evidence.append(f"Treated as read-only ({hit!r} in the goal); no workspace writes are planned.")
            return True
        return False

    def _approval_gates(self, text: str, profiles: Sequence[str], evidence: list[str]) -> list[str]:
        gates = []
        for gate, phrases in (self.lexicon.get("approval_signals") or {}).items():
            hit = next((phrase for phrase in phrases if _contains(text, phrase)), None)
            if hit:
                gates.append(gate)
                evidence.append(f"Requires the {gate} approval gate ({hit!r} in the goal).")
        return sorted(set(gates))

    def _artifacts(self, text: str, profiles: Sequence[str],
                   active_profiles: Sequence[str] = ()) -> list[str]:
        found = {kind for kind, phrases in (self.lexicon.get("artifacts") or {}).items()
                 if any(_contains(text, phrase) for phrase in phrases)}
        if not found and self.profiles is not None:
            declared, _ = self.profiles.resolve([str(item) for item in active_profiles])
            source_profiles = [profile.id for profile in declared] or list(profiles)
            for profile_id in source_profiles:
                profile = self.profiles.get(profile_id)
                if profile:
                    found.update(profile.artifact_types)
        return sorted(found) or ["unknown"]


def _contains(text: str, phrase: str) -> bool:
    phrase = str(phrase).lower().strip()
    if not phrase:
        return False
    if " " in phrase:
        return phrase in text
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def default_lexicon() -> dict[str, Any]:
    from adaptive_agent.runtime import RESOURCE_ROOT, platform_home

    merged: dict[str, Any] = {}
    for path in (RESOURCE_ROOT / "config" / "capability_lexicon.yaml",
                 platform_home() / "capability_lexicon.yaml"):
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for section, values in data.items():
            if isinstance(values, dict):
                merged.setdefault(section, {}).update(values)
            elif isinstance(values, list):
                merged.setdefault(section, []).extend(values)
    return merged
