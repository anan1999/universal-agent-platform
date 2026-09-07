"""Portable plugin packages.

A plugin is a directory containing `plugin.yaml` plus whatever the manifest
declares. This module defines the manifest contract and validates it. It
deliberately stops there: discovering a plugin never imports or runs its code.

Trust is the reason for that separation. Anything found outside the built-in
config directory arrives as `untrusted`, and an untrusted plugin is listed but
never loaded. Promoting one is an explicit user decision, because a plugin can
carry executable provider code and a tool allowlist — the same supply-chain
exposure as installing a package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

import yaml

MANIFEST_NAME = "plugin.yaml"
SCHEMA_VERSION = "1"


class PluginType(StrEnum):
    PROVIDER = "provider"
    PROFILE = "profile"
    SKILL = "skill"
    TOOL = "tool"
    INTEGRATION = "integration"

    @classmethod
    def parse(cls, value: str) -> "PluginType | None":
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return None


class Trust(StrEnum):
    BUILT_IN = "built_in"
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


#: Permissions a plugin may request. Anything else is rejected as unknown rather
#: than granted, so a typo cannot silently widen access.
PERMISSIONS: frozenset[str] = frozenset({
    "read_project",      # read files in the target project
    "write_project",     # modify files in the target project
    "run_commands",      # execute commands from the project allowlist
    "network",           # reach the network
    "read_credentials",  # read provider credentials from the environment
    "register_provider", # add an execution backend
})

#: Permissions that always need explicit user consent before the plugin loads.
DANGEROUS_PERMISSIONS: frozenset[str] = frozenset({
    "write_project", "run_commands", "read_credentials", "register_provider",
})


@dataclass(slots=True)
class PluginManifest:
    name: str = ""
    version: str = ""
    type: PluginType | None = None
    schema_version: str = SCHEMA_VERSION
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    #: Platform versions this plugin declares support for, e.g. ">=2.0".
    compatibility: str = ""
    #: Import path or relative file the loader would use, once trusted.
    entrypoint: str = ""
    permissions: list[str] = field(default_factory=list)
    author: str = ""
    homepage: str = ""
    trust: Trust = Trust.UNTRUSTED
    source: str = ""

    @property
    def dangerous(self) -> list[str]:
        return sorted(set(self.permissions) & DANGEROUS_PERMISSIONS)

    @property
    def loadable(self) -> bool:
        """Whether the platform may load this plugin without asking again."""
        return self.trust in (Trust.BUILT_IN, Trust.TRUSTED)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version,
                "type": self.type.value if self.type else None,
                "schema_version": self.schema_version, "description": self.description,
                "capabilities": list(self.capabilities), "compatibility": self.compatibility,
                "entrypoint": self.entrypoint, "permissions": list(self.permissions),
                "dangerous_permissions": self.dangerous, "author": self.author,
                "homepage": self.homepage, "trust": self.trust.value,
                "loadable": self.loadable, "source": self.source}


def parse_manifest(data: dict[str, Any], source: str = "",
                   trust: Trust = Trust.UNTRUSTED) -> tuple[PluginManifest, list[str]]:
    """Parse and validate a manifest. Returns the manifest and its errors.

    Never raises on bad input: a malformed third-party manifest should be
    reported, not allowed to break discovery of the plugins beside it.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return PluginManifest(source=source, trust=trust), ["manifest is not a mapping"]

    plugin_type = PluginType.parse(data.get("type", ""))
    if data.get("type") and plugin_type is None:
        errors.append(f"unknown plugin type {data.get('type')!r}; "
                      f"expected one of {', '.join(sorted(item.value for item in PluginType))}")

    manifest = PluginManifest(
        name=str(data.get("name", "") or ""),
        version=str(data.get("version", "") or ""),
        type=plugin_type,
        schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        description=str(data.get("description", "") or ""),
        capabilities=[str(item) for item in (data.get("capabilities") or [])],
        compatibility=str(data.get("compatibility", "") or ""),
        entrypoint=str(data.get("entrypoint", "") or ""),
        permissions=[str(item) for item in (data.get("permissions") or [])],
        author=str(data.get("author", "") or ""),
        homepage=str(data.get("homepage", "") or ""),
        trust=trust, source=source)

    for required in ("name", "version"):
        if not getattr(manifest, required):
            errors.append(f"missing required field {required!r}")
    if manifest.type is None and not data.get("type"):
        errors.append("missing required field 'type'")
    if manifest.schema_version != SCHEMA_VERSION:
        errors.append(f"unsupported schema_version {manifest.schema_version!r}; "
                      f"this build understands {SCHEMA_VERSION!r}")
    for permission in manifest.permissions:
        if permission not in PERMISSIONS:
            errors.append(f"unknown permission {permission!r}")
    if manifest.type is PluginType.PROVIDER and not manifest.entrypoint:
        errors.append("provider plugins must declare an entrypoint")
    return manifest, errors


def load_manifest(path: Path, trust: Trust = Trust.UNTRUSTED
                  ) -> tuple[PluginManifest, list[str]]:
    """Read a `plugin.yaml`. Reading a manifest never executes plugin code."""
    manifest_path = Path(path)
    if manifest_path.is_dir():
        manifest_path = manifest_path / MANIFEST_NAME
    if not manifest_path.exists():
        return PluginManifest(source=str(manifest_path), trust=trust), ["manifest not found"]
    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        return PluginManifest(source=str(manifest_path), trust=trust), [f"invalid YAML: {error}"]
    return parse_manifest(data, str(manifest_path), trust)


def discover(*directories: Path) -> list[dict[str, Any]]:
    """List installed plugins without loading any of them."""
    found: list[dict[str, Any]] = []
    for directory in directories:
        root = Path(directory)
        if not root.exists():
            continue
        for manifest_path in sorted(root.glob(f"*/{MANIFEST_NAME}")):
            trust = Trust.BUILT_IN if "config" in manifest_path.parts else Trust.UNTRUSTED
            manifest, errors = load_manifest(manifest_path, trust)
            found.append({**manifest.to_dict(), "errors": errors, "valid": not errors})
    return found


def blocked_reason(manifest: PluginManifest) -> str:
    """Why a plugin will not be loaded, or an empty string if it will be."""
    if manifest.loadable:
        return ""
    dangerous = manifest.dangerous
    if dangerous:
        return (f"untrusted plugin requesting {', '.join(dangerous)}; "
                f"approve it explicitly before it can load")
    return "untrusted plugin; approve it explicitly before it can load"


def validate_all(manifests: Iterable[PluginManifest]) -> dict[str, list[str]]:
    """Map plugin name to the reasons it is not loadable, for reporting."""
    return {manifest.name: [reason] for manifest in manifests
            if (reason := blocked_reason(manifest))}
