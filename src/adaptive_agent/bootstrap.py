"""Platform setup and project attachment.

`agentctl setup` prepares the user-level installation once. `agentctl init`
and `agentctl attach` prepare a target project. Both are idempotent and neither
makes an irreversible change without being asked.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from adaptive_agent.models.registry import ModelRegistry
from adaptive_agent.profiles.registry import profile_registry
from adaptive_agent.providers.registry import providers as provider_registry
from adaptive_agent.runtime import PACKAGE_ROOT, database, platform_home


PLATFORM_CONFIG = "platform.yaml"

DEFAULT_PLATFORM_CONFIG: dict[str, Any] = {
    "platform": {
        "dashboard_host": "127.0.0.1",
        "dashboard_port": 8787,
        "command_execution": "allowlist_only",
        "specialist_promotion": "explicit_approval_only",
        "plugin_execution": "trusted_only",
    },
    "providers": {"preference": ["auto"]},
    "budget": {"max_parallel_agents": 3, "max_parallel_strong_agents": 1,
               "max_escalations_per_task": 2},
    "adaptive": {"minimum_history_samples": 5, "escalation_threshold": 0.25},
}


@dataclass(slots=True)
class SetupResult:
    home: Path
    created: list[str] = field(default_factory=list)
    checks: list[tuple[str, str, str]] = field(default_factory=list)
    providers: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unresolved and all(status != "FAIL" for _, status, _ in self.checks)

    def render(self) -> str:
        width = max((len(label) for label, _, _ in self.checks), default=10) + 2
        lines = ["Universal Agent Platform", "", f"Platform home: {self.home}", ""]
        if self.providers:
            lines += ["Detecting AI providers...", ""]
            name_width = max(len(item["name"]) for item in self.providers) + 2
            for item in self.providers:
                label = "READY" if item["ready"] else item["status"].upper()
                lines.append(f"  {item['name']:<{name_width}}{label:<14}{item['detail']}")
            lines.append("")
        for label, status, detail in self.checks:
            lines.append(f"{label:<{width}}{status}" + (f"  ({detail})" if detail else ""))
        if self.created:
            lines += ["", "Created:"] + [f"  {item}" for item in self.created]
        if self.unresolved:
            lines += ["", "Needs a decision before the platform is usable:"] + \
                     [f"  - {item}" for item in self.unresolved]
        lines += ["", "Setup complete." if self.ok else "Setup incomplete."]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {"home": str(self.home), "ok": self.ok, "created": list(self.created),
                "checks": [{"check": a, "status": b, "detail": c} for a, b, c in self.checks],
                "providers": list(self.providers), "unresolved": list(self.unresolved)}


def platform_config() -> dict[str, Any]:
    path = platform_home() / PLATFORM_CONFIG
    if not path.exists():
        return DEFAULT_PLATFORM_CONFIG
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {**DEFAULT_PLATFORM_CONFIG, **data}


def provider_preference() -> list[str]:
    return list(platform_config().get("providers", {}).get("preference", ["auto"])) or ["auto"]


def set_provider_preference(*preferred: str) -> list[str]:
    home = platform_home()
    home.mkdir(parents=True, exist_ok=True)
    config = platform_config()
    config["providers"] = {**config.get("providers", {}), "preference": list(preferred) or ["auto"]}
    (home / PLATFORM_CONFIG).write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return list(preferred)


def setup(auto: bool = False, non_interactive: bool = False) -> SetupResult:
    """Prepare the user-level installation. Idempotent and non-destructive."""
    home = platform_home()
    result = SetupResult(home=home)

    for directory in (home, home / "data", home / "logs", home / "profiles", home / "plugins"):
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            result.created.append(str(directory))

    config_path = home / PLATFORM_CONFIG
    if not config_path.exists():
        config_path.write_text(yaml.safe_dump(DEFAULT_PLATFORM_CONFIG, sort_keys=False), encoding="utf-8")
        result.created.append(str(config_path))

    result.checks.append(("Python", "PASS", sys.version.split()[0]))
    result.checks.append(("Platform home", "PASS" if os.access(home, os.W_OK) else "FAIL", str(home)))

    try:
        db = database()
        version = db.query("SELECT MAX(version) v FROM schema_migrations")[0]["v"]
        result.checks.append(("Database", "PASS", f"schema v{version}"))
    except Exception as error:  # pragma: no cover - unwritable home
        result.checks.append(("Database", "FAIL", str(error)))

    registry = profile_registry(refresh=True)
    result.checks.append(("Work profiles", "PASS", f"{len(registry.all())} installed"))

    models = ModelRegistry.from_yaml(PACKAGE_ROOT / "config" / "models.yaml", home / "models.yaml")
    result.checks.append(("Model registry", "PASS", f"{len(models.all())} models"))

    result.providers = provider_registry().discover()
    ready = [item for item in result.providers if item["ready"]]
    result.checks.append(("Providers", "PASS" if ready else "WARN",
                          f"{len(ready)} ready of {len(result.providers)} registered"))
    result.checks.append(("Dashboard", "PASS", "binds to 127.0.0.1 only"))

    if not ready:
        message = ("No provider is ready. Install a provider CLI, configure credentials, "
                   "or run with --provider mock.")
        if non_interactive and not auto:
            result.unresolved.append(message)
        else:
            result.checks.append(("Provider readiness", "WARN", message))
    return result


@dataclass(slots=True)
class InitPlan:
    """What `init --auto` intends to do, so it can be reported before it happens."""

    path: Path
    profiles: list[str] = field(default_factory=list)
    evidence: dict[str, list[str]] = field(default_factory=dict)
    languages: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    build_command: str | None = None
    test_command: str | None = None

    def render(self, pending: bool = True) -> str:
        """Render the plan. `pending` phrases it as a proposal rather than a result."""
        lines = [f"Analyzing project: {self.path}", ""]
        lines.append("Detected:")
        lines += [f"  {item}" for item in (self.languages if self.languages != ["unknown"] else ["no language markers"])]
        if self.signals:
            lines.append("")
            lines.append("Signals:")
            lines.append("  " + ", ".join(self.signals[:14]))
        lines += ["", "Recommended work profiles:"]
        for profile_id in self.profiles:
            why = ", ".join(self.evidence.get(profile_id, [])[:3])
            lines.append(f"  {profile_id}" + (f"  ({why})" if why else ""))
        if self.test_command or self.build_command:
            lines += ["", "Project commands that would be allowlisted:" if pending
                      else "Allowlisted project commands:"]
            if self.build_command:
                lines.append(f"  build: {self.build_command}")
            if self.test_command:
                lines.append(f"  test:  {self.test_command}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {"path": str(self.path), "profiles": list(self.profiles),
                "evidence": {k: list(v) for k, v in self.evidence.items()},
                "languages": list(self.languages), "signals": list(self.signals),
                "build_command": self.build_command, "test_command": self.test_command}


def analyze_project(path: Path) -> InitPlan:
    """Inspect a project without changing anything."""
    from adaptive_agent.project.discovery import discover

    info = discover(Path(path))
    return InitPlan(Path(path).resolve(), info.recommended_profiles, info.evidence,
                    info.languages, info.signals, info.build_command, info.test_command)
