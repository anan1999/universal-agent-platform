"""Small, deterministic project routing index for fresh AI sessions.

The index is deliberately a map, not a knowledge base.  Creation inspects a
bounded set of high-value files and top-level directories.  File summaries are
cached only after a file was useful to a completed task.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import yaml


INDEX_SCHEMA_VERSION = 1
INDEX_TARGET_BYTES = 4 * 1024
INDEX_MAX_BYTES = 8 * 1024
CONTEXT_BUDGETS = {
    "project_index_tokens": 2_000,
    "project_references_tokens": 6_000,
    "skill_tokens": 4_000,
    "receipt_tokens": 1_000,
}

HIGH_VALUE_FILES = (
    "README.md", "pyproject.toml", "requirements.txt", "package.json",
    "tsconfig.json", "go.mod", "Cargo.toml", "pom.xml", "CMakeLists.txt",
    "Dockerfile", "docker-compose.yml", "pytest.ini", "tox.ini",
    "main.py", "app/main.py", "src/main.py", "frontend/package.json",
)
IGNORED_DIRECTORIES = {
    ".git", ".agent", ".venv", "venv", "node_modules", "build", "dist",
    "coverage", ".pytest_cache", "__pycache__",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _terms(value: str) -> set[str]:
    return {item for item in re.findall(r"[a-z0-9_./-]+", value.lower()) if len(item) > 1}


@dataclass(slots=True)
class ProjectContext:
    project_index: dict[str, Any]
    relevant_paths: list[str] = field(default_factory=list)
    cached_files: list[dict[str, Any]] = field(default_factory=list)
    discovery_performed: bool = False
    context_chars: int = 0
    estimated_tokens: int = 0
    pre_task_ai_calls: int = 0
    budgets: dict[str, int] = field(default_factory=lambda: dict(CONTEXT_BUDGETS))
    suggested_paths: list[str] = field(default_factory=list)
    relevant_project_facts: list[str] = field(default_factory=list)
    relevant_constraints: list[str] = field(default_factory=list)
    relevant_decisions: list[str] = field(default_factory=list)
    selected_skills: list[str] = field(default_factory=list)
    source_references: list[str] = field(default_factory=list)
    stale_or_unavailable_items: list[str] = field(default_factory=list)
    reuse_miss_reason: str | None = None
    targeted_exploration_allowed: bool = True

    @property
    def reuse_hits(self) -> int:
        return len(self.cached_files)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["suggested_paths"] = list(self.suggested_paths or self.relevant_paths)
        # Compatibility keys keep older API/receipt readers functional without
        # activating the legacy intelligence lifecycle.
        value.update({"temperature": "warm" if self.project_index else "cold",
                      "reason": "compact project index selected reusable navigation assets",
                      "items": [], "stale_items": [], "reuse_hits": len(self.cached_files),
                      "rediscovery_count": int(self.discovery_performed),
                      "loaded_detail_paths": [], "selected_only_count": len(self.cached_files),
                      "reuse_miss_reason": self.reuse_miss_reason,
                      "typed_reuse_hits": {},
                      "stale_count": len(self.stale_or_unavailable_items),
                      "historical_items": [], "skipped_items": []})
        return value


class FileSummaryCache:
    """Hash-invalidated summaries for files proven useful by actual work."""

    def __init__(self, project_root: Path):
        self.root = Path(project_root).resolve()
        self.path = self.root / ".agent" / "cache" / "files.json"

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "files": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"schema_version": 1, "files": {}}
        return {"schema_version": 1, "files": dict(value.get("files", {}))}

    def _write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def remember(self, relative_path: str, summary: str | None = None,
                 important_symbols: Iterable[str] = ()) -> dict[str, Any] | None:
        relative = relative_path.replace("\\", "/").lstrip("./")
        target = (self.root / relative).resolve()
        try:
            target.relative_to(self.root)
        except ValueError:
            return None
        if not target.is_file() or target.stat().st_size > 1_000_000:
            return None
        symbols = list(dict.fromkeys(str(item) for item in important_symbols if str(item)))
        if summary is None:
            summary, detected = self._deterministic_summary(target)
            symbols = list(dict.fromkeys([*symbols, *detected]))
        entry = {"path": relative, "hash": _hash(target), "summary": summary[:320],
                 "important_symbols": symbols[:24], "last_verified": _now()}
        data = self._read()
        data["files"][relative] = entry
        self._write(data)
        return entry

    def valid(self, relative_path: str) -> dict[str, Any] | None:
        relative = relative_path.replace("\\", "/").lstrip("./")
        data = self._read()
        entry = data["files"].get(relative)
        if not entry:
            return None
        target = (self.root / relative).resolve()
        if not target.is_relative_to(self.root) or not target.is_file() or entry.get("hash") != _hash(target):
            data["files"].pop(relative, None)
            self._write(data)
            return None
        return entry

    def entries(self) -> list[dict[str, Any]]:
        result = []
        for relative in list(self._read()["files"]):
            entry = self.valid(relative)
            if entry:
                result.append(entry)
        return result

    @staticmethod
    def _deterministic_summary(path: Path) -> tuple[str, list[str]]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:24_000]
        except OSError:
            return f"Useful project file: {path.name}", []
        symbols = re.findall(
            r"(?m)^\s*(?:async\s+def|def|class|function|export\s+(?:function|class|const))\s+([A-Za-z_$][\w$]*)",
            text,
        )
        first = next((line.strip("# /\t") for line in text.splitlines() if line.strip()), path.name)
        return f"{path.name}: {first[:220]}", symbols


class ProjectContextIndex:
    """Canonical compact index plus relevant-path selection."""

    def __init__(self, project_root: Path):
        self.root = Path(project_root).resolve()
        self.path = self.root / ".agent" / "project-index.json"
        self.cache = FileSummaryCache(self.root)
        self._last_load_issue: str | None = None

    def initialize(self) -> dict[str, Any]:
        if self.path.exists():
            return self.load()
        self._last_load_issue = "project_index_missing"
        value = self._discover()
        self._write(value)
        return value

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self.initialize()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._last_load_issue = "project_index_invalid"
            value = self._discover()
            self._write(value)
        return value

    def select(self, goal: str) -> ProjectContext:
        self._last_load_issue = None
        discovery = not self.path.exists()
        index = self.initialize()
        discovery = discovery or self._last_load_issue is not None
        relevant = self.relevant_paths(goal, index)
        cached_before = set(self.cache._read()["files"])
        cached = []
        relevant_terms = _terms(" ".join(relevant)) | _terms(goal)
        valid_cache_entries = self.cache.entries()
        for entry in valid_cache_entries:
            if _terms(str(entry.get("path", "")) + " " + str(entry.get("summary", ""))) & relevant_terms:
                cached.append(entry)
        stale_cache = sorted(cached_before - {str(item.get("path")) for item in valid_cache_entries})
        serialized = json.dumps(index, ensure_ascii=False, separators=(",", ":"))
        cache_text = json.dumps(cached, ensure_ascii=False, separators=(",", ":"))
        context_chars = len(serialized) + len(cache_text) + sum(map(len, relevant))
        project = index.get("project", {}) if isinstance(index.get("project"), dict) else {}
        architecture = index.get("architecture", {}) if isinstance(index.get("architecture"), dict) else {}
        facts = ([str(project.get("summary"))] if project.get("summary") else [])
        facts.extend(f"{key}: {value}" for key, value in architecture.items())
        facts.extend(f"{item.get('path')}: {item.get('summary')}" for item in cached)
        constraints = [str(item) for item in index.get("constraints", []) if str(item).strip()]
        decisions = [str(item) for item in index.get("decisions", []) if str(item).strip()]
        skills = [str(item) for item in index.get("skills", []) if str(item).strip()]
        sources = [".agent/project-index.json"]
        sources.extend(str(item) for item in index.get("sources", []) if str(item).strip())
        sources.extend(str(item.get("path")) for item in cached if item.get("path"))
        unavailable = ([self._last_load_issue] if self._last_load_issue else [])
        unavailable.extend(f"cached_file_changed:{path}" for path in stale_cache)
        miss = ("CACHE_INVALID" if self._last_load_issue == "project_index_invalid"
                else "NOT_FOUND" if discovery and not cached else None)
        return ProjectContext(
            project_index=index, relevant_paths=relevant, cached_files=cached,
            discovery_performed=discovery, context_chars=context_chars,
            estimated_tokens=max(1, (context_chars + 3) // 4), pre_task_ai_calls=0,
            suggested_paths=relevant, relevant_project_facts=list(dict.fromkeys(facts)),
            relevant_constraints=list(dict.fromkeys(constraints)),
            relevant_decisions=list(dict.fromkeys(decisions)), selected_skills=skills,
            source_references=list(dict.fromkeys(sources)),
            stale_or_unavailable_items=unavailable, reuse_miss_reason=miss,
            targeted_exploration_allowed=True)

    def relevant_paths(self, goal: str, index: dict[str, Any] | None = None) -> list[str]:
        index = index or self.load()
        text = goal.lower()
        area_terms = {
            "backend": ("api", "backend", "endpoint", "server", "fastapi", "database", "sqlite", "schema"),
            "frontend": ("frontend", "dashboard", "react", "ui", "component", "page", "css"),
            "tests": ("test", "pytest", "validation", "regression", "acceptance", "quality"),
            "docs": ("readme", "documentation", "docs", "guide"),
        }
        important = dict(index.get("important_paths", {}))
        chosen = [path for area, path in important.items()
                  if any(term in text for term in area_terms.get(area, (area,)))]
        for entry in self.cache.entries():
            if _terms(goal) & _terms(str(entry.get("summary", "")) + " " + str(entry.get("path", ""))):
                chosen.append(str(entry["path"]))
        if not chosen:
            chosen.extend(list(important.values())[:3])
        return list(dict.fromkeys(chosen))[:12]

    def update_stable(self, changes: dict[str, Any]) -> bool:
        """Apply allowlisted stable changes; routine code changes become no-op."""
        data = self.load()
        before = json.dumps(data, sort_keys=True, ensure_ascii=False)
        for section in ("architecture", "important_paths", "commands"):
            values = changes.get(section)
            if isinstance(values, dict):
                data.setdefault(section, {}).update({str(k): str(v) for k, v in values.items() if v})
        for section in ("constraints", "decisions", "skills", "sources"):
            values = changes.get(section)
            if isinstance(values, list):
                current = data.setdefault(section, [])
                current.extend(str(item) for item in values if str(item).strip())
                data[section] = list(dict.fromkeys(current))[-20:]
        if json.dumps(data, sort_keys=True, ensure_ascii=False) == before:
            return False
        data["last_verified_commit"] = self._commit()
        self._write(data)
        return True

    def remember_useful_files(self, paths: Iterable[str]) -> int:
        count = 0
        for path in dict.fromkeys(str(item) for item in paths):
            count += int(self.cache.remember(path) is not None)
        return count

    def status(self) -> dict[str, Any]:
        index = self.initialize()
        size = self.path.stat().st_size
        return {"path": ".agent/project-index.json", "size_bytes": size,
                "within_target": size <= INDEX_TARGET_BYTES,
                "within_maximum": size <= INDEX_MAX_BYTES,
                "cached_relevant_files": len(self.cache.entries()),
                "architecture": index.get("architecture", {}),
                "important_paths": index.get("important_paths", {}),
                "last_verified_commit": index.get("last_verified_commit")}

    def _discover(self) -> dict[str, Any]:
        files = [name for name in HIGH_VALUE_FILES if (self.root / name).is_file()]
        directories = sorted(item.name for item in self.root.iterdir()
                             if item.is_dir() and item.name not in IGNORED_DIRECTORIES)[:80]
        samples = "\n".join(self._sample(name) for name in files)
        lowered = samples.lower()
        architecture: dict[str, str] = {}
        if "fastapi" in lowered:
            architecture["backend"] = "FastAPI"
        elif any(name in directories for name in ("app", "backend", "api")):
            architecture["backend"] = "present"
        if '"react"' in lowered or "from react" in lowered:
            architecture["frontend"] = "React"
        elif any(name in directories for name in ("frontend", "web", "ui")):
            architecture["frontend"] = "present"
        if "sqlite" in lowered:
            architecture["database"] = "SQLite"
        important: dict[str, str] = {}
        for area, candidates in {
            "backend": ("app", "backend", "api", "src"),
            "frontend": ("frontend", "web", "ui"),
            "tests": ("tests", "test"),
            "docs": ("docs",),
        }.items():
            selected = next((name for name in candidates if name in directories), None)
            if selected:
                important[area] = f"{selected}/"
        if "README.md" in files:
            important.setdefault("docs", "README.md")
        commands = self._commands()
        project_yaml = self.root / ".agent" / "project.yaml"
        constraints: list[str] = []
        if project_yaml.exists():
            try:
                configured = yaml.safe_load(project_yaml.read_text(encoding="utf-8")) or {}
                constraints = [str(item) for item in
                               (configured.get("constraints", {}).get("stable", []) or [])][:20]
            except (OSError, ValueError):
                pass
        skill_root = self.root / ".agent" / "skills"
        skills = sorted(item.name for item in skill_root.iterdir() if item.is_dir()) if skill_root.exists() else []
        return {"schema_version": INDEX_SCHEMA_VERSION,
                "project": {"name": self.root.name,
                            "summary": self._summary(architecture)},
                "architecture": architecture, "important_paths": important,
                "commands": commands, "constraints": constraints,
                "decisions": [], "skills": skills[:20], "sources": [],
                "discovery": {"files_inspected": files, "top_level_directories": directories},
                "last_verified_commit": self._commit()}

    def _commands(self) -> dict[str, str]:
        path = self.root / ".agent" / "commands.yaml"
        if path.exists():
            try:
                values = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("commands", {})
                return {str(name): str(spec.get("command")) for name, spec in values.items()
                        if isinstance(spec, dict) and spec.get("command")}
            except (OSError, ValueError):
                pass
        commands: dict[str, str] = {}
        if (self.root / "pyproject.toml").exists() or (self.root / "pytest.ini").exists():
            commands["test"] = "pytest -q"
        if (self.root / "package.json").exists():
            commands["frontend_build"] = "npm run build"
        return commands

    def _sample(self, relative: str) -> str:
        try:
            return (self.root / relative).read_text(encoding="utf-8", errors="replace")[:8_000]
        except OSError:
            return ""

    @staticmethod
    def _summary(architecture: dict[str, str]) -> str:
        if not architecture:
            return "Project with a compact deterministic context index."
        return "Project using " + ", ".join(architecture.values()) + "."

    def _write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
        if len(content.encode("utf-8")) > INDEX_MAX_BYTES:
            value["discovery"] = {"files_inspected": value.get("discovery", {}).get("files_inspected", [])}
            content = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
        if len(content.encode("utf-8")) > INDEX_MAX_BYTES:
            raise ValueError("project index exceeds the 8 KiB soft maximum; move detail to references")
        self.path.write_text(content, encoding="utf-8")

    def _commit(self) -> str | None:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root,
                                capture_output=True, text=True, check=False)
        return result.stdout.strip() or None
