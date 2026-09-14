"""Reusable, quota-free infrastructure for deterministic benchmark workspaces."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


IGNORED_PARTS = {".agent", ".git", "__pycache__", ".pytest_cache", "node_modules",
                 "expenses.sqlite3"}
HARNESS_SCHEMA = 1


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.relative_to(root).parts):
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a checkpoint atomically so interruption cannot leave valid-looking JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


class PreparedFixture:
    """Cache an immutable fixture and materialize comparable clean arms from it."""

    def __init__(self, source: Path, workspace: Path):
        self.source = source.resolve()
        self.workspace = workspace.resolve()
        self.prepared = self.workspace / "prepared" / "base"
        self.manifest_path = self.workspace / "prepared" / "manifest.json"

    def prepare(self) -> dict[str, Any]:
        expected = tree_hash(self.source)
        manifest = self._manifest()
        reused = bool(
            manifest
            and manifest.get("schema_version") == HARNESS_SCHEMA
            and manifest.get("source_hash") == expected
            and self.prepared.is_dir()
            and tree_hash(self.prepared) == expected
        )
        if not reused:
            self._replace_tree(self.source, self.prepared)
            write_json(self.manifest_path, {
                "schema_version": HARNESS_SCHEMA,
                "source": str(self.source),
                "source_hash": expected,
            })
        return {"source_hash": expected, "prepared_path": "prepared/base", "reused": reused}

    def materialize(self, task_id: str, arm: str) -> Path:
        if not self.prepared.is_dir():
            raise RuntimeError("prepare() must be called before materialize()")
        if not task_id.replace("-", "").isalnum() or not arm.replace("-", "").isalnum():
            raise ValueError("task and arm names must be simple identifiers")
        destination = self.workspace / "runs" / task_id / arm
        self._replace_tree(self.prepared, destination)
        return destination

    def _manifest(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _replace_tree(self, source: Path, destination: Path) -> None:
        resolved = destination.resolve()
        if self.workspace not in resolved.parents:
            raise ValueError("benchmark destination escaped its workspace")
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns(*IGNORED_PARTS))


class Checkpoints:
    """Per-arm durable records used to resume without repeating successful AI calls."""

    def __init__(self, workspace: Path):
        self.root = workspace.resolve() / "checkpoints"

    def save(self, task_id: str, arm: str, signature: str, result: dict[str, Any]) -> Path:
        path = self.root / task_id / f"{arm}.json"
        write_json(path, {"schema_version": HARNESS_SCHEMA, "signature": signature,
                          "terminal": True, "result": result})
        return path

    def completed(self, task_id: str, arm: str, signature: str) -> dict[str, Any] | None:
        result = self.load(task_id, arm, signature)
        return result if result is not None and result.get("status") == "completed" else None

    def load(self, task_id: str, arm: str, signature: str) -> dict[str, Any] | None:
        """Load any matching terminal result for offline re-analysis."""
        path = self.root / task_id / f"{arm}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if (payload.get("schema_version") != HARNESS_SCHEMA
                or payload.get("signature") != signature
                or payload.get("terminal") is not True):
            return None
        result = payload.get("result")
        return result if isinstance(result, dict) else None


def experiment_signature(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
