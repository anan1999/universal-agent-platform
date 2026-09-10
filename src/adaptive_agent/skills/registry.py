from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from adaptive_agent.skills.manifest import LoadedSkill, SkillManifest, SkillTrust


class SkillRegistry:
    def __init__(self, skills: dict[str, dict[str, Any]] | None = None):
        self._skills = skills or {}
        self._manifests = {name: SkillManifest.from_legacy(name, spec or {})
                           for name, spec in self._skills.items()}
        self.loaded: set[str] = set()

    @classmethod
    def from_yaml(cls, path: Path) -> "SkillRegistry":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(data.get("skills", {}))

    def register(self, name: str, spec: dict[str, Any]) -> None:
        if name in self._skills:
            raise ValueError(f"skill already exists: {name}")
        self._skills[name] = spec
        self._manifests[name] = SkillManifest.from_legacy(name, spec)

    def register_manifest(self, manifest: SkillManifest, replace: bool = False) -> None:
        if manifest.id in self._manifests and not replace:
            raise ValueError(f"skill already exists: {manifest.id}")
        self._manifests[manifest.id] = manifest
        self._skills[manifest.id] = {
            "description": manifest.description, "capabilities": manifest.capabilities,
            "scope": "project" if manifest.trust is SkillTrust.PROJECT_LOCAL else "global",
            "version": manifest.version, "lazy": True, "tools": manifest.tools,
            "evaluation": manifest.evaluation,
        }

    def discover_directory(self, path: Path, trust: SkillTrust = SkillTrust.UNVERIFIED) -> list[str]:
        found = []
        if not Path(path).exists():
            return found
        for manifest_path in sorted(Path(path).glob("*/skill.json")):
            manifest = SkillManifest.from_file(manifest_path, trust)
            self.register_manifest(manifest, replace=True)
            found.append(manifest.id)
        return found

    def load_for(self, required: list[str]) -> dict[str, dict[str, Any]]:
        missing = [name for name in required if name not in self._skills]
        if missing:
            raise KeyError(f"unknown skills: {', '.join(missing)}")
        self.loaded.update(required)
        return {name: self._skills[name] for name in required}

    def all(self) -> dict[str, dict[str, Any]]:
        return dict(self._skills)

    def manifests(self) -> list[SkillManifest]:
        """Metadata-only view used during discovery and ranking."""
        return [self._manifests[name] for name in sorted(self._manifests)]

    def manifest(self, name: str) -> SkillManifest:
        if name not in self._manifests:
            raise KeyError(f"unknown skill: {name}")
        return self._manifests[name]

    def load_selected(self, name: str, references: list[str] | None = None) -> LoadedSkill:
        """Progressively load instructions and only explicitly requested references."""
        manifest = self.manifest(name)
        self._validate_dependencies(name)
        requested = references or []
        if manifest.path is None:
            instructions = (f"# {manifest.id}\n\n{manifest.description}\n\n"
                            "Apply this reusable procedure only to its declared capabilities.")
            loaded_references: dict[str, str] = {}
        else:
            instructions = self._read_inside(manifest.path, manifest.entrypoint)
            loaded_references = {}
            for key in requested:
                if key not in manifest.references:
                    raise KeyError(f"skill {name} has no reference: {key}")
                loaded_references[key] = self._read_inside(manifest.path, manifest.references[key])
        self.loaded.add(name)
        return LoadedSkill(manifest, instructions, loaded_references)

    def validate(self, name: str) -> dict[str, Any]:
        manifest = self.manifest(name)
        errors, warnings = [], []
        if not manifest.id or not manifest.capabilities:
            errors.append("id and at least one capability are required")
        try:
            self._validate_dependencies(name)
        except ValueError as error:
            errors.append(str(error))
        executable = bool(manifest.tools or manifest.security.get("scripts") or
                          manifest.security.get("shell") or manifest.security.get("network"))
        if executable and manifest.trust in {SkillTrust.UNVERIFIED, SkillTrust.REVIEW_REQUIRED}:
            warnings.append("unverified executable content requires explicit approval")
        if manifest.path and not (manifest.path / manifest.entrypoint).is_file():
            errors.append(f"missing entrypoint: {manifest.entrypoint}")
        return {"skill": name, "version": manifest.version, "valid": not errors,
                "executable": executable, "approval_required": bool(warnings),
                "errors": errors, "warnings": warnings}

    def _validate_dependencies(self, root: str) -> None:
        visiting, visited = set(), set()

        def visit(name: str) -> None:
            if name in visiting:
                raise ValueError(f"skill dependency cycle detected at {name}")
            if name in visited:
                return
            visiting.add(name)
            for dependency in self.manifest(name).dependencies:
                if dependency not in self._manifests:
                    raise ValueError(f"missing skill dependency: {dependency}")
                visit(dependency)
            visiting.remove(name)
            visited.add(name)

        visit(root)

    @staticmethod
    def _read_inside(root: Path, relative: str) -> str:
        target = (root / relative).resolve()
        if root.resolve() not in target.parents:
            raise ValueError(f"skill asset escapes package: {relative}")
        return target.read_text(encoding="utf-8")

