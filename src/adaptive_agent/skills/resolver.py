"""Deterministic, explainable Skill discovery and selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol

from adaptive_agent.core.capabilities import normalize
from adaptive_agent.skills.manifest import SkillManifest, SkillStatus, SkillTrust


EQUIVALENTS = {
    "wcag_compliance": {"accessibility", "wcag", "accessible_web_interface"},
    "responsive_ui": {"responsive_layout", "adaptive_layout", "frontend_implementation"},
    "responsive_design": {"responsive_layout", "adaptive_layout"},
    "repository_write": {"write_access", "repository_access"},
    "test": {"testing", "unit_testing"},
    "w8a8_validation": {"quantization", "inference", "tensor_contract"},
}


class SkillDiscoverySource(Protocol):
    id: str

    def manifests(self) -> Iterable[SkillManifest]: ...


class DirectorySkillSource:
    def __init__(self, path: Path, source_id: str = "local",
                 trust: SkillTrust = SkillTrust.UNVERIFIED):
        self.path, self.id, self.trust = Path(path), source_id, trust

    def manifests(self) -> Iterable[SkillManifest]:
        if not self.path.exists():
            return []
        found = []
        for manifest_path in sorted(self.path.glob("*/skill.json")):
            try:
                manifest = SkillManifest.from_file(manifest_path, self.trust)
            except (ValueError, TypeError, OSError):
                continue
            manifest.provenance.setdefault("discovery_source", self.id)
            found.append(manifest)
        return found


@dataclass(slots=True)
class SkillCandidate:
    manifest: SkillManifest
    score: float
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    context_cost_source: str = "estimated"
    decision: str = "SKIP"

    def to_dict(self) -> dict:
        return {"skill": self.manifest.id, "version": self.manifest.version,
                "score": round(self.score, 3), "matched": self.matched, "missing": self.missing,
                "reasons": self.reasons, "trust": self.manifest.trust.value,
                "status": self.manifest.status.value,
                "estimated_context_tokens": self.manifest.estimated_context_tokens,
                "context_cost_source": self.context_cost_source, "decision": self.decision}


class SkillResolver:
    """Ranks metadata without loading Skill instructions or reference files."""

    def __init__(self, manifests: Iterable[SkillManifest] = (), quality: dict[str, dict] | None = None):
        self._manifests = list(manifests)
        self.quality = quality or {}

    def discover(self, *sources: SkillDiscoverySource) -> None:
        known = {(item.id, item.version) for item in self._manifests}
        for source in sources:
            for manifest in source.manifests():
                if (manifest.id, manifest.version) not in known:
                    self._manifests.append(manifest)
                    known.add((manifest.id, manifest.version))

    def candidates(self, required: Iterable[str], minimize_cost: bool = False,
                   provider_capabilities: Iterable[str] = ()) -> list[SkillCandidate]:
        wanted = {normalize(item) for item in required if normalize(item)}
        available = {normalize(item) for item in provider_capabilities}
        ranked = [self._score(item, wanted, minimize_cost, available) for item in self._manifests
                  if item.status not in {SkillStatus.DEPRECATED, SkillStatus.RETIRED}
                  and item.trust is not SkillTrust.BLOCKED]
        return sorted((item for item in ranked if item.matched),
                      key=lambda item: (-item.score, item.manifest.id, item.manifest.version))

    def select(self, required: Iterable[str], minimize_cost: bool = False,
               provider_capabilities: Iterable[str] = (),
               minimal: bool = False) -> tuple[list[SkillCandidate], list[SkillCandidate]]:
        wanted = {normalize(item) for item in required if normalize(item)}
        ranked = self.candidates(wanted, minimize_cost, provider_capabilities)
        selected, covered = [], set()
        for candidate in ranked:
            if minimal and not self._reusable_procedure(candidate.manifest):
                candidate.reasons.append(
                    "SKIP: generic capability metadata is not a reusable project procedure")
                continue
            new = set(candidate.matched) - covered
            if not new:
                continue
            candidate.decision = "USE"
            candidate.reasons.append("USE: clearly matched a non-trivial reusable procedure")
            selected.append(candidate)
            covered.update(new)
            if covered >= wanted:
                break
        rejected = [item for item in ranked if item not in selected]
        return selected, rejected

    @staticmethod
    def _reusable_procedure(manifest: SkillManifest) -> bool:
        """A loadable Skill must contain an actual bounded procedure.

        Legacy catalog labels such as ``Python expert`` stay discoverable but
        are not placed in every task's context.  Project/package Skills with a
        real SKILL.md remain eligible through the same resolver.
        """
        if manifest.estimated_context_tokens is not None and manifest.estimated_context_tokens > 4_000:
            return False
        if manifest.path and (manifest.path / manifest.entrypoint).is_file():
            return True
        return bool(manifest.provenance.get("reusable_procedure"))

    def equivalent(self, capability: str, offered: str) -> bool:
        capability, offered = normalize(capability), normalize(offered)
        if capability == offered:
            return True
        cap_set = {capability, *EQUIVALENTS.get(capability, set())}
        offered_set = {offered, *EQUIVALENTS.get(offered, set())}
        if cap_set & offered_set:
            return True
        left, right = set(capability.split("_")), set(offered.split("_"))
        if len(left) < 2 or len(right) < 2:
            return False
        return len(left & right) / max(len(left), len(right)) >= 0.5

    def _score(self, manifest: SkillManifest, wanted: set[str], minimize_cost: bool,
               provider_capabilities: set[str]) -> SkillCandidate:
        matched = sorted(cap for cap in wanted
                         if any(self.equivalent(cap, offered) for offered in manifest.capabilities))
        missing = sorted(wanted - set(matched))
        match_score = len(matched) / max(1, len(wanted)) * 70
        record = self.quality.get(f"{manifest.id}@{manifest.version}", {})
        runs = int(record.get("runs", 0) or 0)
        reliability = float(record.get("reliability", 0) or 0) if runs >= 3 else 0
        artifact_quality = float(record.get("artifact_quality", 0) or 0) if runs >= 3 else 0
        portability = manifest.portability if manifest.portability is not None else 0.5
        cost = manifest.estimated_context_tokens
        cost_penalty = (min(cost or 0, 100_000) / 10_000) * (4 if minimize_cost else 1)
        trust_adjustment = {SkillTrust.BUILT_IN: 8, SkillTrust.TRUSTED: 7,
                            SkillTrust.PROJECT_LOCAL: 5, SkillTrust.UNVERIFIED: -8,
                            SkillTrust.REVIEW_REQUIRED: -15}.get(manifest.trust, -100)
        dependency_penalty = 2 * len(manifest.dependencies)
        provider_penalty = 0
        required_provider = set(manifest.security.get("provider_capabilities", []))
        if required_provider and available and not required_provider <= provider_capabilities:
            provider_penalty = 25
        score = (match_score + reliability * 0.08 + artifact_quality * 0.06
                 + portability * 5 + trust_adjustment - cost_penalty - dependency_penalty - provider_penalty)
        reasons = [f"matched {len(matched)}/{len(wanted)} required capabilities",
                   f"trust={manifest.trust.value}",
                   f"context cost={cost if cost is not None else 'unknown'} (estimated)",
                   (f"quality history={runs} runs" if runs >= 3 else "quality=INSUFFICIENT_HISTORY")]
        if provider_penalty:
            reasons.append("provider lacks a Skill-declared capability")
        return SkillCandidate(manifest, score, matched, missing, reasons)
