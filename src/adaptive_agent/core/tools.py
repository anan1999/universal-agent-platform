"""Deterministic tools.

Not every task needs an AI agent. A tool is a deterministic capability with a
declared risk level, and it can only run a command the project has explicitly
allowlisted in `.agent/commands.yaml`. Arbitrary shell execution is never
reachable from a tool definition, the API, or the browser.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

import yaml

from adaptive_agent.core.capabilities import normalize


class ToolRisk(StrEnum):
    SAFE = "safe"              # read-only, no side effects
    LOW = "low"                # writes only inside the workspace
    MODERATE = "moderate"      # slow, or touches shared local state
    DESTRUCTIVE = "destructive"  # requires explicit human approval, always

    @property
    def needs_approval(self) -> bool:
        return self is ToolRisk.DESTRUCTIVE


class ToolExecution(StrEnum):
    #: Runs a command that the project allowlisted by name in .agent/commands.yaml.
    PROJECT_COMMAND = "project_command"
    #: Runs a fixed, argument-free inspection command shipped with the platform.
    BUILTIN_COMMAND = "builtin_command"
    #: Pure in-process computation.
    INTERNAL = "internal"
    #: Requires a human to do something outside the platform.
    MANUAL = "manual"


@dataclass(slots=True)
class ToolSpec:
    id: str
    name: str = ""
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
    risk: ToolRisk = ToolRisk.SAFE
    execution: ToolExecution = ToolExecution.INTERNAL
    #: For BUILTIN_COMMAND: the exact argv. For PROJECT_COMMAND: the allowlist key.
    command: list[str] | str | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    requires_repository: bool = False
    timeout: float = 600.0
    trust: str = "built_in"

    def __post_init__(self) -> None:
        self.name = self.name or self.id.replace("_", " ").title()
        self.capabilities = [normalize(item) for item in self.capabilities]
        self.risk = ToolRisk(self.risk) if not isinstance(self.risk, ToolRisk) else self.risk
        self.execution = (ToolExecution(self.execution)
                          if not isinstance(self.execution, ToolExecution) else self.execution)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description,
                "capabilities": list(self.capabilities), "risk": self.risk.value,
                "execution": self.execution.value, "command": self.command,
                "input_schema": dict(self.input_schema), "output_schema": dict(self.output_schema),
                "requires_repository": self.requires_repository, "timeout": self.timeout,
                "trust": self.trust}


@dataclass(slots=True)
class ToolResult:
    tool: str
    status: str
    summary: str
    output: str = ""
    findings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    exit_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "status": self.status, "summary": self.summary,
                "output": self.output, "findings": list(self.findings),
                "duration_seconds": self.duration_seconds, "exit_code": self.exit_code}


BUILT_IN_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec("git_status", description="Report uncommitted changes in the workspace.",
             capabilities=["version_control", "workspace_inspection"], risk=ToolRisk.SAFE,
             execution=ToolExecution.BUILTIN_COMMAND, command=["git", "status", "--porcelain"],
             requires_repository=True),
    ToolSpec("git_diff", description="Report the current diff, name-only.",
             capabilities=["version_control", "workspace_inspection"], risk=ToolRisk.SAFE,
             execution=ToolExecution.BUILTIN_COMMAND, command=["git", "diff", "--name-only"],
             requires_repository=True),
    ToolSpec("project_test", description="Run the project's own allowlisted test command.",
             capabilities=["testing", "test", "evaluation"], risk=ToolRisk.LOW,
             execution=ToolExecution.PROJECT_COMMAND, command="test"),
    ToolSpec("project_build", description="Run the project's own allowlisted build command.",
             capabilities=["build"], risk=ToolRisk.LOW,
             execution=ToolExecution.PROJECT_COMMAND, command="build"),
    ToolSpec("benchmark_run", description="Run the project's own allowlisted benchmark command.",
             capabilities=["benchmarking", "latency_analysis"], risk=ToolRisk.MODERATE,
             execution=ToolExecution.PROJECT_COMMAND, command="benchmark"),
    ToolSpec("goal_coverage", description="Check the produced receipts against the stated goal.",
             capabilities=["evaluation", "goal_analysis"], risk=ToolRisk.SAFE,
             execution=ToolExecution.INTERNAL),
)


class ToolRegistry:
    def __init__(self, tools: Iterable[ToolSpec] = ()):
        self._tools: dict[str, ToolSpec] = {tool.id: tool for tool in tools}

    @classmethod
    def default(cls, extra: Path | None = None) -> "ToolRegistry":
        registry = cls(BUILT_IN_TOOLS)
        if extra and Path(extra).exists():
            data = yaml.safe_load(Path(extra).read_text(encoding="utf-8")) or {}
            for identifier, spec in (data.get("tools") or {}).items():
                registry.register(ToolSpec(id=identifier, trust="trusted", **(spec or {})), replace=True)
        return registry

    def register(self, tool: ToolSpec, replace: bool = False) -> None:
        if tool.id in self._tools and not replace:
            raise ValueError(f"tool already registered: {tool.id}")
        self._tools[tool.id] = tool

    def get(self, tool_id: str) -> ToolSpec | None:
        return self._tools.get(tool_id)

    def all(self) -> list[ToolSpec]:
        return [self._tools[key] for key in sorted(self._tools)]

    def search(self, capabilities: Iterable[str]) -> list[ToolSpec]:
        wanted = {normalize(item) for item in capabilities}
        return [tool for tool in self.all() if wanted & set(tool.capabilities)]

    def to_dict(self) -> list[dict[str, Any]]:
        return [tool.to_dict() for tool in self.all()]


class ToolExecutor:
    """Runs tools. Refuses anything outside the allowlist or without approval."""

    def __init__(self, registry: ToolRegistry, workspace: Path,
                 approvals: Iterable[str] = (), output_limit: int = 4000):
        self.registry = registry
        self.workspace = Path(workspace)
        self.approvals = {str(item) for item in approvals}
        self.output_limit = output_limit

    def allowlisted(self, name: str) -> dict[str, Any] | None:
        path = self.workspace / ".agent" / "commands.yaml"
        if not path.exists():
            return None
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return (data.get("commands") or {}).get(name)

    def run(self, tool: ToolSpec | str) -> ToolResult:
        spec = self.registry.get(tool) if isinstance(tool, str) else tool
        if spec is None:
            return ToolResult(str(tool), "failed", f"Unknown tool: {tool}")
        started = time.monotonic()
        if spec.risk.needs_approval and spec.id not in self.approvals:
            return ToolResult(spec.id, "blocked",
                              f"{spec.name} is destructive and requires explicit human approval.")
        if spec.execution is ToolExecution.MANUAL:
            return ToolResult(spec.id, "blocked", f"{spec.name} must be performed by a human.")
        if spec.execution is ToolExecution.INTERNAL:
            return ToolResult(spec.id, "completed", f"{spec.name} evaluated in-process.",
                              duration_seconds=time.monotonic() - started)
        if spec.requires_repository and not (self.workspace / ".git").exists():
            return ToolResult(spec.id, "skipped", f"{spec.name} needs a Git repository; none here.",
                              duration_seconds=time.monotonic() - started)

        if spec.execution is ToolExecution.PROJECT_COMMAND:
            entry = self.allowlisted(str(spec.command))
            if not entry:
                return ToolResult(spec.id, "skipped",
                                  f"No '{spec.command}' command is allowlisted in .agent/commands.yaml.",
                                  duration_seconds=time.monotonic() - started)
            argv = entry["command"] if isinstance(entry["command"], list) else shlex.split(str(entry["command"]))
            timeout = float(entry.get("timeout", spec.timeout))
        else:
            argv = list(spec.command or [])
            timeout = spec.timeout
        if not argv:
            return ToolResult(spec.id, "failed", f"{spec.name} has no command to run.")
        return self._spawn(spec, argv, timeout, started)

    def _spawn(self, spec: ToolSpec, argv: list[str], timeout: float, started: float) -> ToolResult:
        try:
            completed = subprocess.run(argv, cwd=str(self.workspace), capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=timeout, check=False)
        except FileNotFoundError:
            return ToolResult(spec.id, "skipped", f"{argv[0]} is not installed.",
                              duration_seconds=time.monotonic() - started)
        except subprocess.TimeoutExpired:
            return ToolResult(spec.id, "failed", f"{spec.name} exceeded {timeout:g}s.",
                              duration_seconds=time.monotonic() - started)
        except OSError as error:
            return ToolResult(spec.id, "failed", str(error), duration_seconds=time.monotonic() - started)
        output = ((completed.stdout or "") + (completed.stderr or "")).strip()
        if len(output) > self.output_limit:
            output = output[: self.output_limit] + "\n…[truncated]"
        status = "completed" if completed.returncode == 0 else "failed"
        summary = (f"{spec.name} succeeded." if status == "completed"
                   else f"{spec.name} exited {completed.returncode}.")
        return ToolResult(spec.id, status, summary, output,
                          duration_seconds=time.monotonic() - started, exit_code=completed.returncode)
