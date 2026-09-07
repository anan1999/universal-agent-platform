from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10].upper()}"


class TaskKind(StrEnum):
    """How a task is carried out. Not every node in a DAG needs an AI agent."""

    AGENT = "agent"        # a reasoning agent executes it through a provider
    TOOL = "tool"          # a deterministic tool executes it, zero AI quota
    APPROVAL = "approval"  # a human must approve before the run continues
    ARTIFACT = "artifact"  # records a produced artifact, no execution


class TaskStatus(StrEnum):
    QUEUED = "queued"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class Task:
    id: str
    run_id: str
    title: str
    owner: str
    required_capabilities: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    priority: int = 50
    status: TaskStatus = TaskStatus.QUEUED
    model_class: str = "standard"
    reasoning: str = "medium"
    metadata: dict[str, Any] = field(default_factory=dict)
    kind: TaskKind = TaskKind.AGENT
    #: What this task is expected to produce. Domain-agnostic; see core.artifacts.
    artifact_type: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["kind"] = self.kind.value
        return data


@dataclass(slots=True)
class Receipt:
    task_id: str
    agent: str
    status: str
    summary: str
    files: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    token_usage: dict[str, int | bool | str] = field(default_factory=dict)
    confidence: str = "unknown"
    uncertainty_reason: str = ""
    needs_escalation: bool = False
    error_code: str | None = None
    provider: str | None = None
    model: str | None = None
    duration_seconds: float = 0.0
    retry_count: int = 0
    escalated: bool = False
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Event:
    event: str
    run_id: str | None = None
    agent: str | None = None
    task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: new_id("EVT"))
    timestamp: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
