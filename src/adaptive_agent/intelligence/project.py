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
HISTORICAL_KINDS = {"receipt", "task_history"}
REUSABLE_KINDS = {"knowledge", "decision", "command", "evaluation", "skill", "agent", "known_issue"}


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
    TEMPORARY = "temporary"
    VALIDATED = "validated"
    PROMOTION_CANDIDATE = "promotion_candidate"
    NEEDS_REVALIDATION = "needs_revalidation"
    SUPERSEDED = "superseded"
    INACTIVE = "inactive"
    NEEDS_REVIEW = "needs_review"


class RunTemperature(StrEnum):
    COLD = "cold"
    WARM = "warm"
    REVALIDATION = "revalidation"


class PersistenceDecision(StrEnum):
    DO_NOT_PERSIST = "do_not_persist"
    RECEIPT_ONLY = "receipt_only"
    TEMPORARY = "temporary"
    CURRENT = "current"
    NEEDS_REVIEW = "needs_review"


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
    why_persisted: str | None = None
    persistence_decision: str | None = None
    creation_cost: int = 0
    selected_count: int = 0
    validated_reuse_count: int = 0
    failures: int = 0
    repairs: int = 0
    last_used: str | None = None
    occurrence_count: int = 0
    evidence_count: int = 0
    last_seen_task: str | None = None

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
    selected_only_count: int = 0
    reuse_miss_reason: str | None = None
    typed_reuse_hits: dict[str, int] = field(default_factory=dict)
    stale_count: int = 0
    historical_items: list[dict[str, Any]] = field(default_factory=list)
    skipped_items: list[dict[str, Any]] = field(default_factory=list)
    stale_reasons: list[dict[str, Any]] = field(default_factory=list)
    intelligence_candidates_considered: int = 0
    intelligence_selected: int = 0
    knowledge_selected: int = 0
    skills_selected: int = 0
    decisions_selected: int = 0
    commands_selected: int = 0
    reuse_candidate_found: bool = False
    rediscovery_avoidance: str = "UNAVAILABLE"

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
        if item.kind == IntelligenceKind.SKILL.value and self._is_generic_procedure(item.summary, detail):
            raise ValueError("generic procedures are not project-specific reusable intelligence")
        if item.persistence_decision is None:
            item.persistence_decision = (None if item.kind in {"skill", "agent"}
                                         else PersistenceDecision.CURRENT.value)
        item.why_persisted = item.why_persisted or "explicit evidence-backed project value"
        if item.kind in {IntelligenceKind.SKILL.value, IntelligenceKind.AGENT.value}:
            candidate_role = item.kind == IntelligenceKind.AGENT.value and item.persistence_decision == PersistenceDecision.NEEDS_REVIEW.value
            candidate_skill = item.kind == IntelligenceKind.SKILL.value and item.persistence_decision == PersistenceDecision.TEMPORARY.value
            if (not candidate_role and not candidate_skill and item.expected_reuse < 2) or (not candidate_role and not candidate_skill and item.validation not in {"validated", "measured"}):
                raise ValueError("reusable skills and agents require validation and expected reuse >= 2")
        item.related_paths = sorted(set(item.related_paths))
        item.source_hashes = item.source_hashes or self.hash_paths(item.related_paths)
        item.source_commit = item.source_commit or self.commit()
        item.verified_commit = item.verified_commit or item.source_commit
        data = self._read()
        existing = [IntelligenceItem.from_dict(value) for value in data["items"]]
        for old in existing:
            if (old.kind == item.kind and old.status != IntelligenceStatus.SUPERSEDED.value
                    and old.summary.strip().lower() == item.summary.strip().lower()
                    and item.kind in {IntelligenceKind.SKILL.value, IntelligenceKind.AGENT.value}):
                if item.kind == IntelligenceKind.AGENT.value:
                    old.evidence = list(dict.fromkeys([*old.evidence, *item.evidence]))
                    old.related_paths = sorted(set([*old.related_paths, *item.related_paths]))
                    old.capabilities = sorted(set([*old.capabilities, *item.capabilities]))
                    old.occurrence_count = max(1, old.occurrence_count) + 1
                    old.evidence_count = len(old.evidence)
                    old.last_seen_task = item.first_created_task
                    if old.occurrence_count >= 2 and old.status == IntelligenceStatus.NEEDS_REVIEW.value:
                        old.status = IntelligenceStatus.TEMPORARY.value
                        old.persistence_decision = PersistenceDecision.TEMPORARY.value
                    data["items"] = [value.to_dict() if value.id != old.id else old.to_dict() for value in existing]
                    self._write(data)
                return old
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
        if item.kind == IntelligenceKind.SKILL.value:
            self._materialize_skill(item, detail or item.summary)
        data["items"] = [value.to_dict() for value in existing] + [item.to_dict()]
        self._write(data)
        return item

    def _invalidate_changed(self) -> tuple[list[str], list[dict[str, Any]]]:
        data = self._read()
        changed: list[str] = []
        reasons: list[dict[str, Any]] = []
        result: list[dict[str, Any]] = []
        for raw in data["items"]:
            item = IntelligenceItem.from_dict(raw)
            if item.status in {IntelligenceStatus.CURRENT.value, IntelligenceStatus.TEMPORARY.value,
                                IntelligenceStatus.VALIDATED.value, IntelligenceStatus.PROMOTION_CANDIDATE.value} and item.source_hashes:
                current = self.hash_paths(item.source_hashes.keys())
                if current != item.source_hashes:
                    item.status = IntelligenceStatus.NEEDS_REVALIDATION.value
                    if item.kind == IntelligenceKind.SKILL.value:
                        self._mark_skill_stale(item)
                    changed.append(item.id)
                    changed_paths = sorted(path for path in item.source_hashes
                                           if current.get(path) != item.source_hashes.get(path))
                    reasons.append({"id": item.id, "reason": "source_hash_changed",
                                    "changed_paths": changed_paths,
                                    "previous_hashes": {path: item.source_hashes.get(path)
                                                        for path in changed_paths},
                                    "current_hashes": {path: current.get(path)
                                                       for path in changed_paths}})
            elif item.status == IntelligenceStatus.NEEDS_REVALIDATION.value:
                changed.append(item.id)
                reasons.append({"id": item.id, "reason": "already_marked_stale",
                                "changed_paths": sorted(item.related_paths)})
            result.append(item.to_dict())
        data["items"] = result
        self._write(data)
        return sorted(set(changed)), reasons

    def invalidate_changed(self) -> list[str]:
        """Compatibility API returning stale item ids only."""
        return self._invalidate_changed()[0]

    def _mark_skill_stale(self, item: IntelligenceItem) -> None:
        skill_id = re.sub(r"[^a-z0-9_-]+", "-", item.id.lower()).strip("-") or "project-skill"
        manifest_path = self.agent_dir / "skills" / skill_id / "skill.json"
        if not manifest_path.exists():
            return
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            value["status"] = "deprecated"
            value.setdefault("provenance", {})["intelligence_status"] = IntelligenceStatus.NEEDS_REVALIDATION.value
            manifest_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except (OSError, ValueError):
            return

    def _sync_skill_manifest_status(self, item_id: str, status: str) -> None:
        skill_id = re.sub(r"[^a-z0-9_-]+", "-", item_id.lower()).strip("-") or "project-skill"
        manifest_path = self.agent_dir / "skills" / skill_id / "skill.json"
        if not manifest_path.exists():
            return
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            value["status"] = "temporary" if status in {"validated", "promotion_candidate"} else status
            value.setdefault("provenance", {})["intelligence_status"] = status
            manifest_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except (OSError, ValueError):
            return

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
        if found.kind == IntelligenceKind.SKILL.value:
            self._sync_skill_manifest_status(found.id, found.status)
        return found

    def select(self, goal: str, capabilities: Iterable[str] = (), max_items: int = 8,
               max_chars: int = 6000, record_reuse: bool = False) -> ContextSelection:
        stale, stale_reasons = self._invalidate_changed()
        active = [item for item in self.items() if item.status in {IntelligenceStatus.CURRENT.value,
                                                                    IntelligenceStatus.TEMPORARY.value,
                                                                    IntelligenceStatus.VALIDATED.value,
                                                                    IntelligenceStatus.PROMOTION_CANDIDATE.value}]
        historical = [item for item in active if item.kind in HISTORICAL_KINDS]
        if not active:
            temperature = RunTemperature.REVALIDATION.value if stale else RunTemperature.COLD.value
            reason = "related project intelligence changed and must be revalidated" if stale else "no reusable project intelligence exists"
            return ContextSelection(temperature, reason, stale_items=stale,
                                    rediscovery_count=1 if not stale else 0,
                                    reuse_miss_reason="STALE" if stale else "NOT_FOUND",
                                    stale_count=len(stale), stale_reasons=stale_reasons)
        wanted = self._terms(goal) | {str(value).lower() for value in capabilities}
        scored: list[tuple[int, IntelligenceItem]] = []
        skipped: list[dict[str, Any]] = []
        for item in active:
            if item.kind in HISTORICAL_KINDS:
                continue
            if item.kind == IntelligenceKind.SKILL.value:
                skipped.append({"id": item.id,
                                "reason": "selection delegated to the unified SkillResolver"})
                continue
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
        typed = {kind.value: 0 for kind in IntelligenceKind}
        if record_reuse and selected:
            ids = {item["id"] for item in loaded}
            data = self._read()
            for raw in data["items"]:
                if raw.get("id") in ids and raw.get("status") in {IntelligenceStatus.CURRENT.value,
                                                                      IntelligenceStatus.TEMPORARY.value,
                                                                      IntelligenceStatus.VALIDATED.value,
                                                                      IntelligenceStatus.PROMOTION_CANDIDATE.value}:
                    raw["reuse_count"] = int(raw.get("reuse_count", 0)) + 1
                    raw["selected_count"] = int(raw.get("selected_count", 0)) + 1
                    raw["last_used"] = _now()
                    typed[raw.get("kind", "unknown")] = typed.get(raw.get("kind", "unknown"), 0) + 1
            self._write(data)
        temperature = (RunTemperature.REVALIDATION.value if stale else
                       RunTemperature.WARM.value if loaded else RunTemperature.COLD.value)
        reason = ("some related intelligence requires revalidation; current items were reused" if stale and loaded
                  else "related project intelligence changed and must be revalidated" if stale
                  else "relevant verified project intelligence was reused" if loaded
                  else "no relevant reusable project intelligence was selected")
        selected_kinds = {kind: sum(item.get("kind") == kind for item in loaded)
                          for kind in REUSABLE_KINDS}
        considered = sum(item.kind not in HISTORICAL_KINDS for item in active)
        return ContextSelection(temperature, reason, loaded, stale, len(loaded),
                                0 if loaded or stale else 1,
                                chars, (chars + 3) // 4, paths,
                                selected_only_count=len(loaded) if not record_reuse else 0,
                                reuse_miss_reason=None if loaded else "STALE" if stale else "NOT_RELEVANT",
                                typed_reuse_hits=typed, stale_count=len(stale),
                                historical_items=[item.to_dict() for item in historical],
                                skipped_items=skipped, stale_reasons=stale_reasons,
                                intelligence_candidates_considered=considered,
                                intelligence_selected=len(loaded),
                                knowledge_selected=selected_kinds.get("knowledge", 0),
                                skills_selected=selected_kinds.get("skill", 0),
                                decisions_selected=selected_kinds.get("decision", 0),
                                commands_selected=selected_kinds.get("command", 0),
                                reuse_candidate_found=bool(loaded))

    def skill_metadata(self, goal: str, task_complexity: str = "normal") -> dict[str, dict[str, Any]]:
        """Expose project evidence as ranking metadata; selection stays in SkillResolver."""
        wanted = self._terms(goal)
        result: dict[str, dict[str, Any]] = {}
        for item in self.items():
            if item.kind != IntelligenceKind.SKILL.value:
                continue
            terms = self._terms(" ".join([item.summary, *item.tags, *item.capabilities]))
            skill_id = re.sub(r"[^a-z0-9_-]+", "-", item.id.lower()).strip("-") or "project-skill"
            result[skill_id] = {
                "project_relevance": len(wanted & terms),
                "validation": item.validation,
                "status": item.status,
                "selected_count": item.selected_count,
                "validated_context_reuse": item.validated_reuse_count,
                "last_used": item.last_used,
                "benefit_gate": self.skill_benefit_gate(
                    item, goal=goal, task_complexity=task_complexity),
            }
        return result

    def attach_selected_skills(self, selection: ContextSelection, skill_ids: Iterable[str],
                               *, record_reuse: bool = False) -> ContextSelection:
        """Attach only SkillResolver-selected project Skills to reusable context telemetry."""
        wanted = set(skill_ids)
        selected = [item for item in self.items() if item.kind == IntelligenceKind.SKILL.value
                    and (re.sub(r"[^a-z0-9_-]+", "-", item.id.lower()).strip("-")
                         or "project-skill") in wanted]
        existing = {item.get("id") for item in selection.items}
        added = [item for item in selected if item.id not in existing]
        if record_reuse and added:
            ids = {item.id for item in added}
            data = self._read()
            for raw in data["items"]:
                if raw.get("id") in ids:
                    raw["reuse_count"] = int(raw.get("reuse_count", 0)) + 1
                    raw["selected_count"] = int(raw.get("selected_count", 0)) + 1
                    raw["last_used"] = _now()
                    selection.typed_reuse_hits["skill"] = (
                        selection.typed_reuse_hits.get("skill", 0) + 1)
            self._write(data)
        selection.items.extend(item.to_dict() for item in added)
        added_chars = sum(len(item.summary) for item in added)
        selection.context_chars += added_chars
        selection.estimated_tokens = (selection.context_chars + 3) // 4
        selection.reuse_hits = len(selection.items)
        selection.intelligence_selected = len(selection.items)
        selection.skills_selected += len(added)
        selection.reuse_candidate_found = bool(selection.items)
        if added and selection.temperature == RunTemperature.COLD.value:
            selection.temperature = RunTemperature.WARM.value
            selection.reason = "relevant verified project intelligence was reused"
            selection.rediscovery_count = 0
            selection.reuse_miss_reason = None
        return selection

    def record_run(self, run_id: str, selection: ContextSelection, *, success: bool = True,
                   evaluation_passed: bool | None = True, learning_investment: dict[str, Any] | None = None) -> None:
        data = self._read()
        reusable_selected = sum(item.get("kind") in REUSABLE_KINDS for item in selection.items)
        validated_context = reusable_selected if success and evaluation_passed else 0
        data["runs"] = [item for item in data["runs"] if item.get("run_id") != run_id]
        data["runs"].append({"run_id": run_id, "created_at": _now(), "success": bool(success),
                              "evaluation_passed": evaluation_passed,
                              "validated_reuse": bool(validated_context),
                              "validated_context_reuse": validated_context,
                              "successful_selected_items": (len(selection.items)
                                                            if success and evaluation_passed else 0),
                              "learning_investment": learning_investment or {"ai_invocations": 0},
                              **selection.to_dict()})
        data["runs"] = data["runs"][-100:]
        if success and evaluation_passed and selection.items:
            selected_ids = {item.get("id") for item in selection.items}
            for raw in data["items"]:
                if raw.get("id") in selected_ids and raw.get("kind") in REUSABLE_KINDS:
                    raw["validated_reuse_count"] = int(raw.get("validated_reuse_count", 0)) + 1
                    if raw.get("kind") == IntelligenceKind.SKILL.value:
                        count = raw["validated_reuse_count"]
                        raw["status"] = (IntelligenceStatus.PROMOTION_CANDIDATE.value if count >= 2
                                          else IntelligenceStatus.VALIDATED.value)
                        self._sync_skill_manifest_status(raw.get("id", ""), raw["status"])
        self._write(data)

    def status(self) -> dict[str, Any]:
        data = self._read()
        items = [IntelligenceItem.from_dict(value) for value in data["items"]]
        current = [item for item in items if item.status in {IntelligenceStatus.CURRENT.value,
                                                              IntelligenceStatus.TEMPORARY.value,
                                                              IntelligenceStatus.VALIDATED.value,
                                                              IntelligenceStatus.PROMOTION_CANDIDATE.value}]
        counts = {kind.value: sum(item.kind == kind.value and item.status in {IntelligenceStatus.CURRENT.value,
                                                                                IntelligenceStatus.TEMPORARY.value,
                                                                                IntelligenceStatus.VALIDATED.value,
                                                                                IntelligenceStatus.PROMOTION_CANDIDATE.value}
                                  for item in items) for kind in IntelligenceKind}
        historical_counts = {kind: sum(item.kind == kind for item in items) for kind in HISTORICAL_KINDS}
        runs = data["runs"]
        reusable = [item for item in current if item.kind in REUSABLE_KINDS]
        typed_selected = {kind: sum(int(item.get("typed_reuse_hits", {}).get(kind, 0)) for item in runs)
                          for kind in REUSABLE_KINDS}
        typed = {kind: sum(int(item.get("typed_reuse_hits", {}).get(kind, 0)) for item in runs
                           if item.get("success") is True and item.get("evaluation_passed") is True)
                 for kind in REUSABLE_KINDS}
        validated = sum(typed.values())
        reuse = sum(int(item.get("reuse_hits", 0)) for item in runs)
        successful_warm = sum(1 for item in runs if item.get("temperature") == "warm"
                              and item.get("success") is True and item.get("evaluation_passed") is True)
        maturity = self._maturity(len(reusable), successful_warm, validated)
        return {"schema_version": INDEX_SCHEMA_VERSION, "level": maturity,
                "level_name": ("unknown", "discovered", "learned", "optimized")[maturity],
                "items": len(items), "current": len(current), "counts": counts,
                "runs": len(runs), "reuse_hits": reuse,
                "reusable_intelligence_hits": sum(typed.values()),
                "validated_reusable_hits": sum(typed.values()) if validated else 0,
                "historical": historical_counts,
                "typed_reuse_hits": typed,
                "selected_only": sum(int(item.get("selected_only_count", 0)) for item in runs),
                "selected_reuse_hits": sum(typed_selected.values()),
                "validated_reuse": validated,
                "validated_context_reuse": validated,
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
                "revalidation_runs": sum(item.get("temperature") == RunTemperature.REVALIDATION.value for item in runs),
                "learning_yield": {
                    "tasks_run": len(runs),
                    "tasks_with_learning_evidence": sum(
                        bool(item.get("learning_funnel", {}).get("provider_learning_evidence_count"))
                        for item in runs),
                    "evidence_emitted": sum(int(item.get("learning_funnel", {}).get(
                        "provider_learning_evidence_count", 0)) for item in runs),
                    "candidates_created": sum(int(item.get("learning_funnel", {}).get(
                        "distiller_candidate_count", 0)) for item in runs),
                    "durable_items_created": sum(int(item.get("learning_funnel", {}).get(
                        "persistence_accepted_count", 0)) for item in runs),
                    "durable_items_reused": reuse,
                    "durable_items_validated": validated,
                }}

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

    def learn_candidates_with_report(self, candidates: Iterable[dict[str, Any]],
                                     run_id: str | None = None,
                                     quality_passed: bool = True) -> "PersistenceResult":
        """Persist structured evidence and expose every acceptance/rejection decision."""
        candidate_rows = list(candidates)
        if not quality_passed:
            rejected = [{"reason": "weak_validation", "kind": str(item.get("kind", "unknown")),
                         "summary": str(item.get("summary", ""))} for item in candidate_rows]
            reasons = {reason: sum(item.get("reason") == reason for item in rejected)
                       for reason in ("generic", "missing_evidence", "duplicate",
                                      "expected_reuse_too_low", "weak_validation", "stale",
                                      "unsupported", "other")}
            return PersistenceResult([], rejected, {kind: 0 for kind in REUSABLE_KINDS},
                                     reasons, [])
        learned: list[IntelligenceItem] = []
        rejected: list[dict[str, Any]] = []
        existing = self.items(include_inactive=True)
        for candidate in candidate_rows:
            kind = str(candidate.get("kind", "")).lower()
            if kind not in REUSABLE_KINDS | {"skill_candidate", "agent_role_candidate", "task_local", "receipt_only", "procedure", "evaluation_rule"}:
                rejected.append({"reason": "unsupported", "kind": kind or "unknown",
                                 "summary": str(candidate.get("summary", ""))})
                continue
            if kind in {"task_local", "receipt_only"}:
                rejected.append({"reason": "expected_reuse_too_low", "kind": kind,
                                 "summary": str(candidate.get("summary", ""))})
                continue
            normalized = ("skill" if kind in {"skill_candidate", "procedure"} else
                          "agent" if kind == "agent_role_candidate" else
                          "evaluation" if kind == "evaluation_rule" else kind)
            evidence = list(candidate.get("evidence") or [])
            summary = str(candidate.get("summary") or candidate.get("decision") or candidate.get("procedure") or "").strip()
            if not summary or not evidence:
                rejected.append({"reason": "missing_evidence", "kind": normalized,
                                 "summary": summary})
                continue
            expected = int(candidate.get("expected_reuse", 1))
            validation = str(candidate.get("validation", "evidence_backed"))
            if normalized == "skill" and expected < 2:
                rejected.append({"reason": "expected_reuse_too_low", "kind": normalized,
                                 "summary": summary})
                continue
            if normalized == "agent" and expected < 1:
                rejected.append({"reason": "expected_reuse_too_low", "kind": normalized,
                                 "summary": summary})
                continue
            if any(item.kind == normalized and item.status != IntelligenceStatus.SUPERSEDED.value
                   and item.summary.strip().lower() == summary.lower() for item in existing):
                rejected.append({"reason": "duplicate", "kind": normalized, "summary": summary})
                continue
            is_role_candidate = normalized == "agent" and not bool(candidate.get("validated_reuse"))
            item = IntelligenceItem(id=str(candidate.get("id") or hashlib.sha1(summary.encode()).hexdigest()[:12]),
                                    kind=normalized, summary=summary, capabilities=list(candidate.get("capabilities") or []),
                                    tags=list(candidate.get("tags") or []), related_paths=list(candidate.get("related_paths") or []),
                                    evidence=evidence, validation=validation, expected_reuse=expected,
                                    first_created_task=run_id, last_seen_task=run_id, occurrence_count=1,
                                    evidence_count=len(evidence), why_persisted=str(candidate.get("why_persisted") or "structured execution evidence"),
                                    persistence_decision=(PersistenceDecision.NEEDS_REVIEW.value if is_role_candidate else
                                                          PersistenceDecision.TEMPORARY.value if normalized == "skill" else
                                                          PersistenceDecision.CURRENT.value),
                                    status=(IntelligenceStatus.NEEDS_REVIEW.value if is_role_candidate else
                                            IntelligenceStatus.TEMPORARY.value if normalized == "skill" else
                                            IntelligenceStatus.CURRENT.value))
            try:
                persisted = self.add(item, detail=candidate.get("detail") or candidate.get("procedure"))
            except ValueError as error:
                reason = ("generic" if "generic" in str(error).lower() else
                          "weak_validation" if "validation" in str(error).lower() else "other")
                rejected.append({"reason": reason, "kind": normalized, "summary": summary,
                                 "detail": str(error)})
                continue
            learned.append(persisted)
            existing.append(persisted)
        accepted_by_kind = {kind: sum(item.kind == kind for item in learned)
                            for kind in REUSABLE_KINDS}
        rejected_by_reason = {reason: sum(item.get("reason") == reason for item in rejected)
                              for reason in ("generic", "missing_evidence", "duplicate",
                                             "expected_reuse_too_low", "weak_validation", "stale",
                                             "unsupported", "other")}
        materialized = [f".agent/skills/{item.id}" for item in learned
                        if item.kind == IntelligenceKind.SKILL.value]
        return PersistenceResult(learned, rejected, accepted_by_kind,
                                 rejected_by_reason, materialized)

    def learn_candidates(self, candidates: Iterable[dict[str, Any]],
                         run_id: str | None = None) -> list[IntelligenceItem]:
        """Compatibility wrapper returning accepted durable items only."""
        return self.learn_candidates_with_report(candidates, run_id).accepted

    def record_learning_funnel(self, run_id: str, provider_evidence: Iterable[dict[str, Any]],
                               distillation: "DistillationResult",
                               persistence: "PersistenceResult") -> dict[str, Any]:
        """Persist compact externalized evidence and the complete learning funnel."""
        allowed = {"id", "type", "kind", "summary", "procedure", "procedure_steps",
                   "capabilities", "expected_reuse", "evidence", "related_paths",
                   "validation", "rationale", "decision", "choice", "tags"}
        safe_evidence = [{key: value for key, value in item.items() if key in allowed}
                         for item in provider_evidence if isinstance(item, dict)]
        funnel = {
            "provider_learning_evidence_count": len(safe_evidence),
            "provider_learning_evidence_types": sorted({str(item.get("type", item.get("kind", "unknown")))
                                                        for item in safe_evidence}),
            "provider_learning_evidence": safe_evidence,
            "distiller_input_count": distillation.input_count,
            "distiller_candidate_count": len(distillation.candidates),
            "distiller_rejected_count": len(distillation.rejected),
            "distiller_rejected_by_reason": distillation.rejected_by_reason,
            "persistence_accepted_count": len(persistence.accepted),
            "persistence_rejected_count": len(persistence.rejected),
            "accepted_by_kind": persistence.accepted_by_kind,
            "rejected_by_reason": persistence.rejected_by_reason,
            "materialized": persistence.materialized,
        }
        data = self._read()
        for record in data["runs"]:
            if record.get("run_id") == run_id:
                record["learning_funnel"] = funnel
        self._write(data)
        return funnel

    def _materialize_skill(self, item: IntelligenceItem, detail: str) -> None:
        """Write the existing V2.2 project-local Skill package format."""
        skill_id = re.sub(r"[^a-z0-9_-]+", "-", item.id.lower()).strip("-") or "project-skill"
        directory = self.agent_dir / "skills" / skill_id
        directory.mkdir(parents=True, exist_ok=True)
        capabilities = item.capabilities or ["project-specific-procedure"]
        procedure_text = detail.strip()
        manifest = {
            "id": skill_id, "version": "0.1.0", "description": item.summary,
            "capabilities": capabilities, "entrypoint": "SKILL.md", "trust": "review_required",
            "status": "temporary", "evaluation": [item.validation],
            "provenance": {"source": "project_intelligence", "creation_task": item.first_created_task,
                           "evidence": item.evidence, "related_paths": item.related_paths},
            "estimated_context_tokens": max(1, (len(procedure_text) + len(item.summary) + 3) // 4),
        }
        (directory / "skill.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (directory / "SKILL.md").write_text(
            f"# {skill_id}\n\n## Purpose\n{item.summary}\n\n## When to use\n"
            f"Use when the task matches: {', '.join(capabilities)}.\n\n"
            f"## Procedure\n{detail}\n\n## Validation\n{item.validation}\n\n"
            "## Boundaries\nThis temporary Skill is project-local and review-required.\n", encoding="utf-8")

    def explain(self) -> dict[str, Any]:
        runs = self._read()["runs"]
        return {"items": [{**item.to_dict(),
                            "validated_context_reuse_count": item.validated_reuse_count,
                            "reusable": item.kind in REUSABLE_KINDS,
                            "payback_status": self.skill_payback(item.id)}
                           for item in self.items(include_inactive=True)],
                "learning_funnels": [{"run_id": item.get("run_id"),
                                      **item.get("learning_funnel", {})}
                                     for item in runs if item.get("learning_funnel")],
                "maintenance": self.maintenance(), "status": self.status()}

    def skill_payback(self, item_id: str) -> str:
        item = next((value for value in self.items(include_inactive=True) if value.id == item_id), None)
        if not item or item.kind != "skill":
            return "NOT_APPLICABLE"
        if any("benchmark" in value.lower() and "comparable" in value.lower() for value in item.evidence):
            return "PAYBACK_MEASURED"
        if item.validated_reuse_count >= 2:
            return "REPEATED_VALIDATED_CONTEXT_REUSE"
        if item.validated_reuse_count:
            return "VALIDATED_CONTEXT_REUSE"
        if item.selected_count:
            return "SELECTED"
        return "NOT_REUSED"

    def skill_benefit_gate(self, item: IntelligenceItem, *, goal: str = "",
                           task_complexity: str = "normal") -> str:
        """Explainable marginal-value gate used before loading project Skills."""
        if item.kind != IntelligenceKind.SKILL.value:
            return "SKIP"
        if self._is_generic_procedure(item.summary, None):
            return "SKIP"
        match = len(self._terms(goal) & self._terms(" ".join([item.summary, *item.tags, *item.capabilities])))
        if item.status not in {IntelligenceStatus.CURRENT.value, IntelligenceStatus.TEMPORARY.value,
                               IntelligenceStatus.VALIDATED.value,
                               IntelligenceStatus.PROMOTION_CANDIDATE.value}:
            return "SKIP"
        if item.validated_reuse_count or (match and task_complexity in {
                "normal", "complex", "critical", "high"}):
            return "LOAD"
        return "LOAD_METADATA_ONLY"

    @staticmethod
    def amortization(cold_cost: int | None = None, warm_costs: Iterable[int | None] = (), *,
                     baseline_costs: Iterable[int | None] | None = None,
                     uap_costs: Iterable[int | None] | None = None,
                     baseline_quality: Iterable[bool] | None = None,
                     uap_quality: Iterable[bool] | None = None) -> dict[str, Any]:
        if baseline_costs is not None or uap_costs is not None:
            baseline = list(baseline_costs or [])
            actual = list(uap_costs or [])
            bq = list(baseline_quality or [True] * len(baseline))
            uq = list(uap_quality or [True] * len(actual))
            cumulative_b = cumulative_u = 0
            cumulative_baselines: list[int] = []
            cumulative_uaps: list[int] = []
            break_even = None
            comparisons = []
            for index, (b, u) in enumerate(zip(baseline, actual), 1):
                valid = bool(b is not None and u is not None and index <= len(bq) and index <= len(uq)
                             and bq[index-1] and uq[index-1])
                comparisons.append({"task": index, "valid": valid, "status": "VALID" if valid else "INVALID_QUALITY_OR_UNAVAILABLE"})
                if valid:
                    cumulative_b += int(b); cumulative_u += int(u)
                    cumulative_baselines.append(cumulative_b)
                    cumulative_uaps.append(cumulative_u)
                    if break_even is None and cumulative_u <= cumulative_b and all(c["valid"] for c in comparisons):
                        break_even = index
                else:
                    break_even = "NOT_CLAIMABLE"
                    break
            return {"baseline_costs": baseline, "uap_costs": actual, "cumulative_baseline": cumulative_b,
                    "cumulative_uap": cumulative_u, "cumulative_baselines": cumulative_baselines,
                    "cumulative_uaps": cumulative_uaps, "comparisons": comparisons,
                    "break_even_task": break_even, "break_even_run": break_even,
                    "comparison_valid": all(c["valid"] for c in comparisons) if comparisons else False,
                    "savings_claimable": break_even != "NOT_CLAIMABLE"}
        assert cold_cost is not None
        warm = list(warm_costs)
        baseline = cold_cost * (len(warm) + 1)
        actual = cold_cost + sum(warm)
        savings = baseline - actual
        average = actual / (len(warm) + 1) if warm else float(cold_cost)
        return {"runs": len(warm) + 1, "cold_cost": cold_cost, "warm_costs": warm,
                "baseline_cost": baseline, "actual_cost": actual, "savings": savings,
                "average_cost": average, "break_even_run": 2 if warm and warm[0] < cold_cost else None,
                "status": "ILLUSTRATIVE_ONLY", "savings_claimable": False}

    @staticmethod
    def illustrative_amortization_estimate(cold_cost: int, warm_costs: Iterable[int]) -> dict[str, Any]:
        """Deprecated non-authoritative estimate retained only for compatibility."""
        return ProjectIntelligenceStore.amortization(cold_cost, warm_costs)

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
        values = {item for item in re.findall(r"[a-z0-9_+-]{3,}", value.lower())}
        aliases = {
            "categories": "category", "expenses": "expense", "monthly": "month",
            "months": "month", "reports": "report", "tests": "test",
        }
        return values | {aliases[item] for item in values if item in aliases}

    @staticmethod
    def _maturity(current_items: int, runs: int, reuse_hits: int) -> int:
        if current_items == 0:
            return 0
        if runs < 2 or reuse_hits == 0:
            return 1
        if runs < 5 or reuse_hits < 5:
            return 2
        return 3

    @staticmethod
    def _is_generic_procedure(summary: str, detail: str | None) -> bool:
        text = f"{summary} {detail or ''}".lower()
        return any(value in text for value in ("debug python by reading errors", "coding best practices", "react expert", "senior developer"))


class IntelligenceDistiller:
    """Pure, inspectable structured-evidence distiller; no provider call is made."""

    def distill(self, *, run_id: str, status: str, goal: str, task_count: int,
                structured_evidence: Iterable[dict[str, Any]] = (), reported_files: Iterable[str] = (),
                evaluation_passed: bool | None = None) -> "DistillationResult":
        mapping = {"knowledge": "knowledge", "decision": "decision", "command": "command",
                   "project_fact": "knowledge", "validated_project_fact": "knowledge",
                   "evaluation_rule": "evaluation", "known_issue": "known_issue",
                   "procedure": "skill_candidate", "skill": "skill_candidate",
                   "agent_role": "agent_role_candidate", "agent": "agent_role_candidate"}
        evidence_rows = list(structured_evidence)
        candidates: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for raw in evidence_rows:
            if not isinstance(raw, dict):
                rejected.append({"reason": "unsupported", "type": "non_object"})
                continue
            source_type = str(raw.get("type", raw.get("kind", ""))).lower()
            kind = mapping.get(source_type)
            summary = str(raw.get("summary", "")).strip()
            evidence = raw.get("evidence")
            if not kind:
                rejected.append({"reason": "unsupported", "type": source_type or "unknown",
                                 "summary": summary})
                continue
            if not summary or not isinstance(evidence, list) or not evidence:
                rejected.append({"reason": "missing_evidence", "type": source_type,
                                 "summary": summary})
                continue
            if kind == "decision" and not (raw.get("rationale") or raw.get("decision") or raw.get("choice")):
                rejected.append({"reason": "weak_validation", "type": source_type,
                                 "summary": summary})
                continue
            if kind == "skill_candidate":
                procedure = raw.get("procedure") or raw.get("procedure_steps") or raw.get("detail")
                if not procedure:
                    rejected.append({"reason": "missing_evidence", "type": source_type,
                                     "summary": summary})
                    continue
                if self._generic(summary):
                    rejected.append({"reason": "generic", "type": source_type,
                                     "summary": summary})
                    continue
                procedure_text = ("\n".join(f"{index}. {step}" for index, step in enumerate(procedure, 1))
                                  if isinstance(procedure, list) else str(procedure))
                raw = {**raw, "detail": procedure_text,
                       "expected_reuse": max(2, int(raw.get("expected_reuse", 1)))}
            if kind == "agent_role_candidate" and self._generic_agent(summary):
                rejected.append({"reason": "generic", "type": source_type,
                                 "summary": summary})
                continue
            key = (kind, summary.lower())
            if key in seen:
                rejected.append({"reason": "duplicate", "type": source_type,
                                 "summary": summary})
                continue
            seen.add(key)
            candidates.append({**raw, "kind": kind, "summary": summary, "evidence": evidence})
        return DistillationResult(run_id=run_id, status=status, goal=goal, task_count=task_count,
                                  candidates=candidates, reported_files=list(reported_files),
                                  evaluation_passed=evaluation_passed, ai_invocations=0,
                                  input_count=len(evidence_rows), rejected=rejected)

    @staticmethod
    def _generic(summary: str) -> bool:
        value = summary.lower()
        return any(marker in value for marker in ("debug python", "coding best practices", "react expert", "generic debugging"))

    @staticmethod
    def _generic_agent(summary: str) -> bool:
        value = summary.lower()
        return any(marker in value for marker in ("react agent", "python agent", "senior developer", "tester agent"))


@dataclass(slots=True)
class DistillationResult:
    run_id: str
    status: str
    goal: str
    task_count: int
    candidates: list[dict[str, Any]] = field(default_factory=list)
    reported_files: list[str] = field(default_factory=list)
    evaluation_passed: bool | None = None
    ai_invocations: int = 0
    input_count: int = 0
    rejected: list[dict[str, Any]] = field(default_factory=list)

    @property
    def rejected_by_reason(self) -> dict[str, int]:
        return {reason: sum(item.get("reason") == reason for item in self.rejected)
                for reason in ("generic", "missing_evidence", "duplicate",
                               "expected_reuse_too_low", "weak_validation", "stale",
                               "unsupported", "other")}


@dataclass(slots=True)
class PersistenceResult:
    accepted: list[IntelligenceItem] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    accepted_by_kind: dict[str, int] = field(default_factory=dict)
    rejected_by_reason: dict[str, int] = field(default_factory=dict)
    materialized: list[str] = field(default_factory=list)
