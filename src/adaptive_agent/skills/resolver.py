"""Deterministic, explainable Skill discovery and selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol

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
    capability_match: float = 0.0
    project_relevance: int = 0
    historical_reuse: int = 0
    benefit_gate_result: str = "NOT_APPLICABLE"
    selection_reason: str = ""

    def to_dict(self) -> dict:
        return {"skill": self.manifest.id, "version": self.manifest.version,
                "score": round(self.score, 3), "matched": self.matched, "missing": self.missing,
                "reasons": self.reasons, "trust": self.manifest.trust.value,
                "status": self.manifest.status.value,
                "estimated_context_tokens": self.manifest.estimated_context_tokens,
                "context_cost_source": self.context_cost_source,
                "capability_match": round(self.capability_match, 3),
                "project_relevance": self.project_relevance,
                "historical_reuse": self.historical_reuse,
                "benefit_gate_result": self.benefit_gate_result,
                "final_score": round(self.score, 3),
                "selection_reason": self.selection_reason or "; ".join(self.reasons)}


class SkillResolver:
    """Ranks metadata without loading Skill instructions or reference files."""

    def __init__(self, manifests: Iterable[SkillManifest] = (), quality: dict[str, dict] | None = None,
                 project_metadata: dict[str, dict[str, Any]] | None = None):
        self._manifests = list(manifests)
        self.quality = quality or {}
        self.project_metadata = project_metadata or {}

    def discover(self, *sources: SkillDiscoverySource) -> None:
        known = {(item.id, item.version) for item in self._manifests}
        for source in sources:
            for manifest in source.manifests():
                if (manifest.id, manifest.version) not in known:
                    self._manifests.append(manifest)
                    known.add((manifest.id, manifest.version))

    def candidates(self, required: Iterable[str], minimize_cost: bool = False,
                   provider_capabilities: Iterable[str] = (), goal: str = "") -> list[SkillCandidate]:
        wanted = {normalize(item) for item in required if normalize(item)}
        available = {normalize(item) for item in provider_capabilities}
        ranked = [self._score(item, wanted, minimize_cost, available, goal) for item in self._manifests
                  if item.status not in {SkillStatus.DEPRECATED, SkillStatus.RETIRED}
                  and item.trust is not SkillTrust.BLOCKED]
        return sorted((item for item in ranked if item.matched or item.project_relevance),
                      key=lambda item: (-item.score, item.manifest.id, item.manifest.version))

    def select(self, required: Iterable[str], minimize_cost: bool = False,
               provider_capabilities: Iterable[str] = (), goal: str = "") -> tuple[list[SkillCandidate], list[SkillCandidate]]:
        wanted = {normalize(item) for item in required if normalize(item)}
        ranked = self.candidates(wanted, minimize_cost, provider_capabilities, goal)
        selected, covered = [], set()
        for candidate in ranked:
            if candidate.benefit_gate_result not in {"NOT_APPLICABLE", "LOAD"}:
                continue
            new = set(candidate.matched) - covered
            if not new and not candidate.project_relevance:
                continue
            selected.append(candidate)
            candidate.selection_reason = (
                "selected by the unified resolver: capability/project relevance passed the benefit gate")
            covered.update(new)
            if covered >= wanted:
                break
        rejected = [item for item in ranked if item not in selected]
        return selected, rejected

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
               provider_capabilities: set[str], goal: str = "") -> SkillCandidate:
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
        metadata = self.project_metadata.get(manifest.id, {})
        project_relevance = int(metadata.get("project_relevance", 0) or 0)
        historical_reuse = int(metadata.get("validated_context_reuse", 0) or 0)
        benefit_gate = str(metadata.get("benefit_gate", "NOT_APPLICABLE"))
        gate_penalty = 100 if benefit_gate == "SKIP" else 20 if benefit_gate == "LOAD_METADATA_ONLY" else 0
        score = (match_score + reliability * 0.08 + artifact_quality * 0.06
                 + portability * 5 + trust_adjustment - cost_penalty - dependency_penalty - provider_penalty)
        score += min(project_relevance, 5) * 12 + min(historical_reuse, 5) * 3 - gate_penalty
        reasons = [f"matched {len(matched)}/{len(wanted)} required capabilities",
                   f"trust={manifest.trust.value}",
                   f"context cost={cost if cost is not None else 'unknown'} (estimated)",
                   (f"quality history={runs} runs" if runs >= 3 else "quality=INSUFFICIENT_HISTORY")]
        if metadata:
            reasons.extend([f"project relevance={project_relevance}",
                            f"historical validated context reuse={historical_reuse}",
                            f"benefit gate={benefit_gate}"])
        if provider_penalty:
            reasons.append("provider lacks a Skill-declared capability")
        return SkillCandidate(manifest, score, matched, missing, reasons,
                              capability_match=(len(matched) / max(1, len(wanted))),
                              project_relevance=project_relevance,
                              historical_reuse=historical_reuse,
                              benefit_gate_result=benefit_gate)
