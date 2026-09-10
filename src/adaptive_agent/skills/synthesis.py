"""Specification-first temporary Skill synthesis and static safety validation."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from adaptive_agent.core.capabilities import normalize
from adaptive_agent.skills.manifest import SkillManifest, SkillStatus, SkillTrust


UNSAFE_PATTERNS = {
    "destructive delete": re.compile(r"\b(rm\s+-rf|Remove-Item\s+.*-Recurse|rmdir\s+/s)\b", re.I),
    "blind remote execution": re.compile(r"\b(curl|wget)\b.*\|\s*(bash|sh|powershell)", re.I),
    "secret access": re.compile(r"\b(API_KEY|TOKEN|PASSWORD|SECRET)\b", re.I),
}


@dataclass(slots=True)
class SkillSpecification:
    id: str
    capability: str
    description: str
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    procedure: list[str] = field(default_factory=list)
    evaluation: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    creation_reason: str = "missing reusable capability"

    def validate(self) -> list[str]:
        errors = []
        if not self.id or not normalize(self.capability):
            errors.append("id and capability are required")
        if not self.procedure:
            errors.append("bounded procedure is required")
        if not self.outputs:
            errors.append("outputs contract is required")
        if not self.evaluation:
            errors.append("evaluation strategy is required")
        return errors


@dataclass(slots=True)
class SkillValidation:
    valid: bool
    trust: SkillTrust
    findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"valid": self.valid, "trust": self.trust.value, "findings": self.findings}


class SkillPackageValidator:
    def validate_text(self, manifest: SkillManifest, instructions: str) -> SkillValidation:
        findings = []
        for label, pattern in UNSAFE_PATTERNS.items():
            if pattern.search(instructions):
                findings.append(label)
        executable = bool(manifest.tools or manifest.security.get("scripts") or
                          manifest.security.get("shell") or manifest.security.get("network"))
        if findings:
            return SkillValidation(False, SkillTrust.BLOCKED, findings)
        if executable and manifest.trust not in {SkillTrust.BUILT_IN, SkillTrust.TRUSTED}:
            return SkillValidation(True, SkillTrust.REVIEW_REQUIRED,
                                   ["executable content requires explicit human approval"])
        return SkillValidation(True, manifest.trust, [])


class TemporarySkillSynthesizer:
    """Create a reviewable package from a validated specification, never executable by default."""

    def synthesize(self, specification: SkillSpecification, destination: Path) -> SkillManifest:
        errors = specification.validate()
        if errors:
            raise ValueError("; ".join(errors))
        path = Path(destination) / specification.id
        if path.exists():
            raise ValueError(f"skill already exists: {specification.id}")
        path.mkdir(parents=True)
        instructions = "\n".join([
            f"# {specification.id}", "", specification.description, "", "## Procedure", "",
            *[f"{index}. {step}" for index, step in enumerate(specification.procedure, 1)],
            "", "## Evaluation", "", *[f"- {item}" for item in specification.evaluation],
        ])
        manifest = self.propose(specification)
        manifest.path = path.resolve()
        (path / "SKILL.md").write_text(instructions + "\n", encoding="utf-8")
        (path / "skill.json").write_text(
            json.dumps(manifest.to_dict(include_path=False), indent=2) + "\n", encoding="utf-8")
        return manifest

    def propose(self, specification: SkillSpecification) -> SkillManifest:
        errors = specification.validate()
        if errors:
            raise ValueError("; ".join(errors))
        return SkillManifest(
            specification.id, "0.1.0", specification.description,
            [specification.capability], specification.inputs, specification.outputs,
            tools=specification.tools, evaluation=specification.evaluation,
            security={"generated": True, "scripts": False, "network": False,
                      "filesystem_writes": False},
            provenance={"origin": "synthesized", "creation_reason": specification.creation_reason,
                        "specification": asdict(specification)},
            trust=SkillTrust.REVIEW_REQUIRED, status=SkillStatus.TEMPORARY,
        )
