"""Domain-agnostic artifacts.

Files in Git worktrees are only one artifact form. A design spec, a benchmark
table, and a research report are all first-class outputs here, and an
artifact does not need a path at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from adaptive_agent.core.models import new_id, now_iso


class ArtifactType(StrEnum):
    SOURCE_CODE = "source_code"
    TEST_RESULT = "test_result"
    REPORT = "report"
    MARKDOWN = "markdown"
    IMAGE = "image"
    DESIGN_SPEC = "design_spec"
    DATASET = "dataset"
    BENCHMARK = "benchmark"
    PRESENTATION = "presentation"
    SPREADSHEET = "spreadsheet"
    PLAN = "plan"
    RESEARCH_NOTES = "research_notes"
    CONFIGURATION = "configuration"
    #: An isolated working area, e.g. a Git worktree. One strategy, not the model.
    WORKSPACE = "workspace"
    CUSTOM = "custom"
    UNKNOWN = "unknown"

    @classmethod
    def coerce(cls, value: Any) -> "ArtifactType":
        """Unknown kinds become CUSTOM rather than raising, so plugins can invent types."""
        if isinstance(value, ArtifactType):
            return value
        text = str(value or "").strip().lower()
        if not text:
            return cls.UNKNOWN
        try:
            return cls(text)
        except ValueError:
            return cls.WORKSPACE if text in _WORKSPACE_ALIASES else cls.CUSTOM


#: Common aliases emitted by worktree integrations.
_WORKSPACE_ALIASES = {"git_worktree", "worktree", "workdir"}


@dataclass(slots=True)
class Artifact:
    run_id: str
    type: ArtifactType = ArtifactType.UNKNOWN
    name: str = ""
    #: Filesystem path, URL, or logical address. Optional by design.
    location: str | None = None
    #: Small results can live inline instead of on disk.
    content: str | None = None
    task_id: str | None = None
    #: Raw kind string used by integrations and plugins.
    kind: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: new_id("ART"))
    created_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        self.type = ArtifactType.coerce(self.type)
        self.kind = self.kind or self.type.value
        self.name = self.name or self.location or self.type.value

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "run_id": self.run_id, "task_id": self.task_id,
                "type": self.type.value, "kind": self.kind, "name": self.name,
                "location": self.location, "content": self.content,
                "metadata": dict(self.metadata), "created_at": self.created_at}


class ArtifactStore:
    """Persistence for domain-agnostic artifacts."""

    def __init__(self, database):
        self.database = database

    def save(self, artifact: Artifact) -> Artifact:
        metadata = {**artifact.metadata, "name": artifact.name,
                    "created_at": artifact.created_at}
        if artifact.content is not None:
            metadata["content"] = artifact.content
        self.database.execute(
            "INSERT OR REPLACE INTO artifacts(id,run_id,task_id,path,kind,artifact_type,metadata_json) "
            "VALUES(?,?,?,?,?,?,?)",
            (artifact.id, artifact.run_id, artifact.task_id, artifact.location or "",
             artifact.kind, artifact.type.value, self.database.json(metadata)))
        return artifact

    def for_run(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.database.query(
            "SELECT id,run_id,task_id,path,kind,artifact_type,metadata_json FROM artifacts WHERE run_id=?",
            (run_id,))
        results = []
        for row in rows:
            metadata = self.database.loads(row.pop("metadata_json"))
            artifact_type = ArtifactType.coerce(row.get("artifact_type") or row["kind"])
            results.append({**row, "type": artifact_type.value,
                            "name": metadata.get("name") or row["path"] or artifact_type.value,
                            "location": row["path"] or None, "metadata": metadata})
        return results
