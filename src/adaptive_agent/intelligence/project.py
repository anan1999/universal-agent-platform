from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable


INDEX_SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat()


class IntelligenceKind(StrEnum):
    KNOWLEDGE = "knowledge"
    DECISION = "decision"
    SKILL = "skill"
    AGENT = "agent"
    COMMAND = "command"
    EVALUATION = "evaluation"
    ARTIFACT = "artifact"
    KNOWN_ISSUE = "known_issue"
    TASK_HISTORY = "task_history"
    RECEIPT = "receipt"


class IntelligenceStatus(StrEnum):
    CURRENT = "current"
    NEEDS_REVALIDATION = "needs_revalidation"
    SUPERSEDED = "superseded"
    INACTIVE = "inactive"
    NEEDS_REVIEW = "needs_review"


class RunTemperature(StrEnum):
    COLD = "cold"
    WARM = "warm"
    REVALIDATION = "revalidation"


@dataclass(slots=True)
class IntelligenceItem:
    id: str
    kind: str
    summary: str
    detail_path: str | None = None
    capabilities: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    related_paths: list[str] = field(default_factory=list)
    source_hashes: dict[str, str] = field(default_factory=dict)
    source_commit: str | None = None
    status: str = IntelligenceStatus.CURRENT.value
    confidence: str = "medium"
    evidence: list[str] = field(default_factory=list)
    validation: str = "evidence_backed"
    expected_reuse: int = 1
    reuse_count: int = 0
    created_at: str = field(default_factory=_now)
    verified_at: str = field(default_factory=_now)
    verified_commit: str | None = None
    first_created_task: str | None = None
    supersedes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "IntelligenceItem":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value[key] for key in allowed if key in value})


@dataclass(slots=True)
class ContextSelection:
    temperature: str
    reason: str
    items: list[dict[str, Any]] = field(default_factory=list)
    stale_items: list[str] = field(default_factory=list)
    reuse_hits: int = 0
    rediscovery_count: int = 0
    context_chars: int = 0
    estimated_tokens: int = 0
    loaded_detail_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectIntelligenceStore:
    """Git-friendly metadata index with progressively loaded detail files.

    The store deliberately rejects transcript-like kinds and empty evidence. It
    is safe to use without SQLite and never scans outside the project root.
    """

    def __init__(self, project_root: Path):
        self.root = Path(project_root).resolve()
        self.agent_dir = self.root / ".agent"
        self.path = self.agent_dir / "intelligence.json"

    def initialize(self) -> None:
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        (self.agent_dir / "knowledge").mkdir(exist_ok=True)
        if not self.path.exists():
            self._write({"schema_version": INDEX_SCHEMA_VERSION, "items": [], "runs": []})

    def _read(self) -> dict[str, Any]:
        self.initialize()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        return {"schema_version": INDEX_SCHEMA_VERSION,
                "items": list(value.get("items", [])), "runs": list(value.get("runs", []))}

    def _write(self, value: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(".json.tmp")
        content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        temporary.write_text(content, encoding="utf-8")
        for attempt in range(4):
            try:
                temporary.replace(self.path)
                return
            except PermissionError:
                if attempt < 3:
                    time.sleep(0.02 * (attempt + 1))
        # Some Windows indexers briefly hold the destination open. Preserve
        # availability after bounded retries; the next write is atomic again.
        self.path.write_text(content, encoding="utf-8")
        temporary.unlink(missing_ok=True)

    def items(self, include_inactive: bool = False) -> list[IntelligenceItem]:
        result = [IntelligenceItem.from_dict(item) for item in self._read()["items"]]
        if include_inactive:
            return result
        return [item for item in result if item.status not in {
            IntelligenceStatus.SUPERSEDED.value, IntelligenceStatus.INACTIVE.value}]

    def add(self, item: IntelligenceItem, detail: str | None = None) -> IntelligenceItem:
        if item.kind not in {kind.value for kind in IntelligenceKind}:
            raise ValueError(f"unsupported intelligence kind: {item.kind}")
        if not item.summary.strip() or not item.evidence:
            raise ValueError("project intelligence requires a summary and explicit evidence")
        if item.kind in {IntelligenceKind.SKILL.value, IntelligenceKind.AGENT.value}:
            if item.expected_reuse < 2 or item.validation not in {"validated", "measured"}:
                raise ValueError("reusable skills and agents require validation and expected reuse >= 2")
        item.related_paths = sorted(set(item.related_paths))
        item.source_hashes = item.source_hashes or self.hash_paths(item.related_paths)
        item.source_commit = item.source_commit or self.commit()
        item.verified_commit = item.verified_commit or item.source_commit
        data = self._read()
        existing = [IntelligenceItem.from_dict(value) for value in data["items"]]
        for old in existing:
            if old.id == item.id and old.status != IntelligenceStatus.SUPERSEDED.value:
                if old.summary == item.summary and old.source_hashes == item.source_hashes:
                    return old
                old.status = IntelligenceStatus.SUPERSEDED.value
                item.supersedes = old.id
        if detail is not None:
            relative = item.detail_path or f".agent/knowledge/{item.kind}-{item.id}.md"
            detail_path = self._safe(relative)
            detail_path.parent.mkdir(parents=True, exist_ok=True)
            detail_path.write_text(detail.rstrip() + "\n", encoding="utf-8")
            item.detail_path = detail_path.relative_to(self.root).as_posix()
        data["items"] = [value.to_dict() for value in existing] + [item.to_dict()]
        self._write(data)
        return item

    def invalidate_changed(self) -> list[str]:
        data = self._read()
        changed: list[str] = []
        result: list[dict[str, Any]] = []
        for raw in data["items"]:
            item = IntelligenceItem.from_dict(raw)
            if item.status == IntelligenceStatus.CURRENT.value and item.source_hashes:
                current = self.hash_paths(item.source_hashes.keys())
                if current != item.source_hashes:
                    item.status = IntelligenceStatus.NEEDS_REVALIDATION.value
                    changed.append(item.id)
            elif item.status == IntelligenceStatus.NEEDS_REVALIDATION.value:
                changed.append(item.id)
            result.append(item.to_dict())
        data["items"] = result
        self._write(data)
        return sorted(set(changed))

    def revalidate(self, item_id: str, evidence: Iterable[str] = ()) -> IntelligenceItem:
        data = self._read()
        found: IntelligenceItem | None = None
        values: list[dict[str, Any]] = []
        for raw in data["items"]:
            item = IntelligenceItem.from_dict(raw)
            if item.id == item_id and item.status != IntelligenceStatus.SUPERSEDED.value:
                item.source_hashes = self.hash_paths(item.related_paths)
                item.status = IntelligenceStatus.CURRENT.value
                item.verified_at = _now()
                item.verified_commit = self.commit()
                item.evidence.extend(value for value in evidence if value not in item.evidence)
                found = item
            values.append(item.to_dict())
        if found is None:
            raise KeyError(item_id)
        data["items"] = values
        self._write(data)
        return found

    def select(self, goal: str, capabilities: Iterable[str] = (), max_items: int = 8,
               max_chars: int = 6000, record_reuse: bool = False) -> ContextSelection:
        stale = self.invalidate_changed()
        active = [item for item in self.items() if item.status == IntelligenceStatus.CURRENT.value]
        if not active:
            temperature = RunTemperature.REVALIDATION.value if stale else RunTemperature.COLD.value
            reason = "related project intelligence changed and must be revalidated" if stale else "no reusable project intelligence exists"
            return ContextSelection(temperature, reason, stale_items=stale,
                                    rediscovery_count=1 if not stale else 0)
        wanted = self._terms(goal) | {str(value).lower() for value in capabilities}
        scored: list[tuple[int, IntelligenceItem]] = []
        for item in active:
            haystack = self._terms(" ".join([item.summary, *item.capabilities, *item.tags]))
            score = len(wanted & haystack) * 10 + min(item.reuse_count, 5)
            if item.kind == IntelligenceKind.KNOWLEDGE.value:
                score += 1
            if item.kind in {IntelligenceKind.DECISION.value, IntelligenceKind.KNOWN_ISSUE.value}:
                score += 2
            if score:
                scored.append((score, item))
        selected = [item for _, item in sorted(scored, key=lambda value: (-value[0], value[1].id))[:max_items]]
        loaded: list[dict[str, Any]] = []
        chars = 0
        paths: list[str] = []
        for item in selected:
            value = item.to_dict()
            detail = ""
            if item.detail_path:
                target = self._safe(item.detail_path)
                if target.exists():
                    detail = target.read_text(encoding="utf-8")
                    detail = detail[:max(0, max_chars - chars - len(item.summary))]
                    if detail:
                        value["detail"] = detail
                        paths.append(item.detail_path)
            size = len(item.summary) + len(detail)
            if chars + size > max_chars:
                break
            chars += size
            loaded.append(value)
        if record_reuse and selected:
            ids = {item["id"] for item in loaded}
            data = self._read()
            for raw in data["items"]:
                if raw.get("id") in ids and raw.get("status") == IntelligenceStatus.CURRENT.value:
                    raw["reuse_count"] = int(raw.get("reuse_count", 0)) + 1
            self._write(data)
        temperature = RunTemperature.REVALIDATION.value if stale else RunTemperature.WARM.value
        reason = ("some related intelligence requires revalidation; current items were reused" if stale
                  else "relevant verified project intelligence was reused")
        return ContextSelection(temperature, reason, loaded, stale, len(loaded), 0,
                                chars, (chars + 3) // 4, paths)

    def record_run(self, run_id: str, selection: ContextSelection) -> None:
        data = self._read()
        data["runs"] = [item for item in data["runs"] if item.get("run_id") != run_id]
        data["runs"].append({"run_id": run_id, "created_at": _now(), **selection.to_dict()})
        data["runs"] = data["runs"][-100:]
        self._write(data)

    def status(self) -> dict[str, Any]:
        data = self._read()
        items = [IntelligenceItem.from_dict(value) for value in data["items"]]
        current = [item for item in items if item.status == IntelligenceStatus.CURRENT.value]
        counts = {kind.value: sum(item.kind == kind.value and item.status == IntelligenceStatus.CURRENT.value
                                  for item in items) for kind in IntelligenceKind}
        runs = data["runs"]
        reuse = sum(int(item.get("reuse_hits", 0)) for item in runs)
        maturity = self._maturity(len(current), len(runs), reuse)
        return {"schema_version": INDEX_SCHEMA_VERSION, "level": maturity,
                "level_name": ("unknown", "discovered", "learned", "optimized")[maturity],
                "items": len(items), "current": len(current), "counts": counts,
                "runs": len(runs), "reuse_hits": reuse,
                "knowledge_created": counts[IntelligenceKind.KNOWLEDGE.value],
                "skill_reuse_hits": sum(item.reuse_count for item in items
                                        if item.kind == IntelligenceKind.SKILL.value),
                "agent_reuse_hits": sum(item.reuse_count for item in items
                                        if item.kind == IntelligenceKind.AGENT.value),
                "rediscovery_count": sum(int(item.get("rediscovery_count", 0)) for item in runs),
                "context_chars": sum(int(item.get("context_chars", 0)) for item in runs),
                "estimated_context_tokens": sum(int(item.get("estimated_tokens", 0)) for item in runs),
                "cold_runs": sum(item.get("temperature") == RunTemperature.COLD.value for item in runs),
                "warm_runs": sum(item.get("temperature") == RunTemperature.WARM.value for item in runs),
                "revalidation_runs": sum(item.get("temperature") == RunTemperature.REVALIDATION.value for item in runs)}

    def maintenance(self) -> dict[str, list[str]]:
        """Return recommendations only; maintenance never deletes project evidence."""
        items = self.items(include_inactive=True)
        return {
            "archive": [item.id for item in items if item.status == IntelligenceStatus.SUPERSEDED.value],
            "revalidate": [item.id for item in items
                           if item.status == IntelligenceStatus.NEEDS_REVALIDATION.value],
            "review": [item.id for item in items if item.status == IntelligenceStatus.NEEDS_REVIEW.value],
            "prune_candidates": [item.id for item in items
                                 if item.status == IntelligenceStatus.INACTIVE.value and item.reuse_count == 0],
        }

    def learn_discovery(self, info: Any, run_id: str | None = None) -> list[IntelligenceItem]:
        """Persist only deterministic project discovery evidence after a cold run."""
        related = [value for value in getattr(info, "signals", [])
                   if (self.root / value).is_file()]
        evidence = [f"project discovery: {value}" for value in getattr(info, "signals", [])]
        if not evidence:
            return []
        summary = (f"{info.name} is a {info.type} project using "
                   f"{', '.join(info.languages)}; detected signals: {', '.join(info.signals)}.")
        learned = [self.add(IntelligenceItem(
            id="project-discovery", kind=IntelligenceKind.KNOWLEDGE.value,
            summary=summary, capabilities=["project_context"],
            tags=[info.type, *info.languages, *info.recommended_profiles],
            related_paths=related, evidence=evidence, confidence="high",
            first_created_task=run_id),
            detail=("# Project discovery\n\n" + summary + "\n\n"
                    + "This record comes from deterministic file-marker discovery."))]
        for name, command in (("build", info.build_command), ("test", info.test_command)):
            if not command:
                continue
            learned.append(self.add(IntelligenceItem(
                id=f"command-{name}", kind=IntelligenceKind.COMMAND.value,
                summary=f"Approved discovered {name} command: {command}",
                capabilities=[name, "command_execution"], tags=[name],
                related_paths=related, evidence=[f"deterministic discovery selected: {command}"],
                confidence="high", first_created_task=run_id)))
        return learned

    def record_compact_receipt(self, run_id: str, status: str, goal: str,
                               task_count: int) -> IntelligenceItem:
        """Record bounded lifecycle history, never provider prose or chain-of-thought."""
        words = " ".join(goal.split()[:24])
        return self.add(IntelligenceItem(
            id=f"run-{run_id.lower()}", kind=IntelligenceKind.RECEIPT.value,
            summary=f"Run {run_id} {status} with {task_count} tasks: {words}",
            capabilities=["task_history"], tags=[status],
            evidence=[f"sqlite run record: {run_id}"], confidence="high",
            validation="measured", first_created_task=run_id))

    def distill_run(self, run_id: str, status: str, goal: str, task_count: int,
                    reported_files: Iterable[str] = (), evaluation_passed: bool | None = None
                    ) -> list[IntelligenceItem]:
        """Distill structured receipts only; free-form provider reasoning is ignored."""
        learned = [self.record_compact_receipt(run_id, status, goal, task_count)]
        learned.append(self.add(IntelligenceItem(
            id=f"task-{run_id.lower()}", kind=IntelligenceKind.TASK_HISTORY.value,
            summary=f"{status.title()} project task: {' '.join(goal.split()[:24])}",
            capabilities=["task_history"], tags=[status],
            evidence=[f"sqlite run status: {run_id}={status}"], confidence="high",
            validation="measured", first_created_task=run_id)))
        valid_files: list[str] = []
        for value in reported_files:
            candidate = Path(value)
            try:
                target = candidate.resolve() if candidate.is_absolute() else self._safe(value)
            except (OSError, ValueError):
                continue
            if target.is_file() and (target == self.root or self.root in target.parents):
                valid_files.append(target.relative_to(self.root).as_posix())
        if valid_files:
            signature = hashlib.sha256("\n".join(sorted(valid_files)).encode()).hexdigest()[:12]
            learned.append(self.add(IntelligenceItem(
                id=f"artifacts-{signature}", kind=IntelligenceKind.ARTIFACT.value,
                summary=f"Run {run_id} produced: {', '.join(sorted(valid_files)[:12])}",
                capabilities=["artifact_reuse"], tags=["produced", status],
                related_paths=valid_files, evidence=[f"structured provider receipt: {run_id}"],
                confidence="high" if status == "completed" else "medium",
                validation="measured", first_created_task=run_id)))
        if evaluation_passed is not None:
            learned.append(self.add(IntelligenceItem(
                id=f"evaluation-{run_id.lower()}", kind=IntelligenceKind.EVALUATION.value,
                summary=f"Deterministic artifact evaluation for {run_id}: "
                        f"{'passed' if evaluation_passed else 'failed'}.",
                capabilities=["evaluation"], tags=["passed" if evaluation_passed else "failed"],
                evidence=[f"artifact_evaluations table: {run_id}"], confidence="high",
                validation="measured", first_created_task=run_id)))
        return learned

    @staticmethod
    def amortization(cold_cost: int, warm_costs: Iterable[int]) -> dict[str, Any]:
        warm = list(warm_costs)
        baseline = cold_cost * (len(warm) + 1)
        actual = cold_cost + sum(warm)
        savings = baseline - actual
        average = actual / (len(warm) + 1) if warm else float(cold_cost)
        return {"runs": len(warm) + 1, "cold_cost": cold_cost, "warm_costs": warm,
                "baseline_cost": baseline, "actual_cost": actual, "savings": savings,
                "average_cost": average, "break_even_run": 2 if warm and warm[0] < cold_cost else None}

    def hash_paths(self, paths: Iterable[str]) -> dict[str, str]:
        values: dict[str, str] = {}
        for relative in sorted(set(str(value).replace("\\", "/") for value in paths)):
            target = self._safe(relative)
            if target.is_file():
                values[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
            else:
                values[relative] = "missing"
        return values

    def commit(self) -> str | None:
        try:
            result = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"],
                                    capture_output=True, text=True, check=False)
        except OSError:
            return None
        return (result.stdout.strip() or None) if result.returncode == 0 else None

    def _safe(self, relative: str) -> Path:
        target = (self.root / relative).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"intelligence path escapes project: {relative}")
        return target

    @staticmethod
    def _terms(value: str) -> set[str]:
        return {item for item in re.findall(r"[a-z0-9_+-]{3,}", value.lower())}

    @staticmethod
    def _maturity(current_items: int, runs: int, reuse_hits: int) -> int:
        if current_items == 0:
            return 0
        if runs < 2 or reuse_hits == 0:
            return 1
        if runs < 5 or reuse_hits < 5:
            return 2
        return 3
