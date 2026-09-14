"""Conservative, project-local NORMAL/REDUCED adaptive budget policy v0."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any

from adaptive_agent.core.goal_analyzer import GoalAnalysis


POLICY_VERSION = "v0"
REDUCED_LIMIT = 6
MIN_COMPARABLE_PAIRS = 2
MAX_RECENT_PAIRS = 20
MIN_RELATIVE_IMPROVEMENT = 0.10
MAX_UNCACHED_REGRESSION = 0.20
EVIDENCE_TTL = 30 * 86400


@dataclass(frozen=True, slots=True)
class AdaptiveBudgetDecision:
    requested_mode: str
    selected_mode: str
    normal_limit: int | None
    effective_limit: int | None
    decision_source: str
    comparable_pairs: int
    reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    task_family: str
    artifact_type: str
    complexity: str
    provider: str | None
    resolved_model: str | None
    reasoning_setting: str | None
    enforcement: str
    policy_wall_ms: float
    policy_version: str = POLICY_VERSION

    @property
    def provider_tool_cap(self) -> int | None:
        return self.effective_limit if self.selected_mode == "reduced" else None

    @property
    def source(self) -> str:
        return self.decision_source

    @property
    def enabled(self) -> bool:
        return self.requested_mode in {"auto", "reduced"}

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["reasons"] = list(self.reasons)
        value["evidence_ids"] = list(self.evidence_ids)
        value["provider_tool_cap"] = self.provider_tool_cap
        return value


@dataclass(frozen=True, slots=True)
class BudgetObservation:
    run_id: str
    task_id: str
    experiment_pair_id: str | None
    task_family: str
    artifact_type: str
    complexity: str
    provider: str
    resolved_model: str
    reasoning_setting: str
    budget_mode: str
    effective_tool_call_limit: int | None
    observed_provider_tool_calls: int | None
    provider_status: str
    acceptance_status: str
    acceptance_contract_version: str | None
    input_tokens: int | None
    cached_input_tokens: int | None
    uncached_input_tokens: int | None
    output_tokens: int | None
    duration_seconds: float | None
    measurement_source: str
    is_synthetic: bool = False
    task_signature: str | None = None
    input_signature: str | None = None
    created_at: float | None = None


class AdaptiveToolBudgetStore:
    """One store for evidence, deterministic policy, inspection, and reset.

    Legacy tables remain for migration safety but never drive v0. Only
    independent, non-synthetic, measured NORMAL/REDUCED pairs can select REDUCED.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / ".agent/cache/adaptive-budgets.sqlite3"

    @staticmethod
    def task_family(analysis: GoalAnalysis) -> str:
        artifacts = {str(item).lower().replace("-", "_") for item in analysis.artifact_types}
        profiles = {str(item).lower() for item in analysis.profiles}
        capabilities = {str(item).lower() for item in analysis.capabilities}
        if any("3d" in item or "three_d" in item for item in artifacts):
            return "three_d"
        if any(item in artifacts for item in {"ui", "ux", "wireframe", "prototype", "interface"}):
            return "ui_ux"
        if any(item in artifacts for item in {"svg", "poster", "graphic", "brand", "visual_identity"}):
            return "graphic_design"
        if any("research" in item for item in profiles | capabilities | artifacts):
            return "research"
        if any(item in profiles | capabilities | artifacts for item in
               {"product", "product_management", "requirements", "product_requirements"}):
            return "product"
        if ("software-engineering" in profiles or any(item in capabilities for item in
                {"coding", "implementation", "debugging", "testing", "refactoring"})):
            return "software"
        return "unknown"

    @staticmethod
    def artifact_type(analysis: GoalAnalysis) -> str:
        known = sorted({str(item).lower().replace("-", "_") for item in analysis.artifact_types
                        if str(item).lower() != "unknown"})
        return known[0] if len(known) == 1 else "unknown"

    @staticmethod
    def family(analysis: GoalAnalysis) -> str:
        contract = {"task_family": AdaptiveToolBudgetStore.task_family(analysis),
                    "artifact_type": AdaptiveToolBudgetStore.artifact_type(analysis),
                    "complexity": analysis.complexity.value}
        serialized = json.dumps(contract, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()[:20]

    def fingerprint(self) -> str | None:
        # Project identity only: pair-level input_signature provides content
        # comparability. Budget decisions must not scan repository files.
        return hashlib.sha256(str(self.root).casefold().encode()).hexdigest()

    def _connect(self):
        if not self.path.resolve().is_relative_to(self.root):
            raise OSError("Adaptive budget path leaves project")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        db.execute(
            "CREATE TABLE IF NOT EXISTS adaptive_tool_budgets "
            "(family TEXT NOT NULL, fingerprint TEXT NOT NULL, accepted_runs INTEGER NOT NULL, "
            "last_verified REAL NOT NULL, PRIMARY KEY(family, fingerprint))")
        db.execute(
            "CREATE TABLE IF NOT EXISTS adaptive_budget_observations "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, family TEXT NOT NULL, fingerprint TEXT NOT NULL, "
            "effective_cap INTEGER, provider_tool_calls INTEGER NOT NULL, total_tokens INTEGER NOT NULL, "
            "uncached_tokens INTEGER NOT NULL, duration_seconds REAL NOT NULL, verified REAL NOT NULL)")
        db.execute(
            "CREATE TABLE IF NOT EXISTS adaptive_budget_runs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL, run_id TEXT NOT NULL, "
            "task_id TEXT NOT NULL, experiment_pair_id TEXT, task_family TEXT NOT NULL, "
            "artifact_type TEXT NOT NULL, complexity TEXT NOT NULL, provider TEXT NOT NULL, "
            "resolved_model TEXT NOT NULL, reasoning_setting TEXT NOT NULL, budget_mode TEXT NOT NULL, "
            "effective_tool_call_limit INTEGER, observed_provider_tool_calls INTEGER, "
            "provider_status TEXT NOT NULL, acceptance_status TEXT NOT NULL, "
            "acceptance_contract_version TEXT, input_tokens INTEGER, cached_input_tokens INTEGER, "
            "uncached_input_tokens INTEGER, output_tokens INTEGER, duration_seconds REAL, "
            "measurement_source TEXT NOT NULL, created_at REAL NOT NULL, is_synthetic INTEGER NOT NULL, "
            "task_signature TEXT, input_signature TEXT, UNIQUE(fingerprint,run_id,task_id), "
            "UNIQUE(fingerprint,experiment_pair_id,budget_mode))")
        return db

    @staticmethod
    def _nonnegative(value: int | float | None) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0

    def record_observation(self, item: BudgetObservation) -> bool:
        fingerprint = self.fingerprint()
        if fingerprint is None or not item.run_id or not item.task_id:
            return False
        created_at = item.created_at if self._nonnegative(item.created_at) else time.time()
        values = asdict(item)
        values["created_at"] = created_at
        values["is_synthetic"] = int(item.is_synthetic)
        columns = tuple(values)
        try:
            with closing(self._connect()) as db, db:
                cursor = db.execute(
                    f"INSERT OR IGNORE INTO adaptive_budget_runs(fingerprint,{','.join(columns)}) "
                    f"VALUES(?,{','.join('?' for _ in columns)})",
                    (fingerprint, *(values[name] for name in columns)))
                return cursor.rowcount == 1
        except (OSError, sqlite3.Error):
            return False

    def record(self, analysis: GoalAnalysis, accepted: bool,
               metrics: dict[str, Any] | None = None,
               effective_cap: int | None = None) -> bool:
        """Compatibility recorder for old callers; legacy rows never drive v0."""
        fingerprint = self.fingerprint()
        if fingerprint is None:
            return False
        family = self.family(analysis)
        try:
            with closing(self._connect()) as db, db:
                if not accepted:
                    db.execute("DELETE FROM adaptive_tool_budgets WHERE family=? AND fingerprint=?",
                               (family, fingerprint))
                    return True
                db.execute(
                    "INSERT INTO adaptive_tool_budgets VALUES (?, ?, 1, ?) "
                    "ON CONFLICT(family,fingerprint) DO UPDATE SET "
                    "accepted_runs=adaptive_tool_budgets.accepted_runs+1,last_verified=excluded.last_verified",
                    (family, fingerprint, time.time()))
                return True
        except (OSError, sqlite3.Error):
            return False

    def _matching_rows(self, task_family: str, artifact_type: str, complexity: str,
                       provider: str, model: str, reasoning: str) -> list[sqlite3.Row]:
        fingerprint = self.fingerprint()
        if fingerprint is None or not self.path.exists():
            return []
        with closing(self._connect()) as db:
            return db.execute(
                "SELECT * FROM adaptive_budget_runs WHERE fingerprint=? AND task_family=? "
                "AND artifact_type=? AND complexity=? AND provider=? AND resolved_model=? "
                "AND reasoning_setting=? AND created_at>=? AND created_at<=? "
                "ORDER BY created_at DESC,id DESC LIMIT ?",
                (fingerprint, task_family, artifact_type, complexity, provider, model, reasoning,
                 time.time() - EVIDENCE_TTL, time.time(), MAX_RECENT_PAIRS * 2 + 40)).fetchall()

    @staticmethod
    def _valid_pairs(rows: list[sqlite3.Row]) -> list[tuple[str, sqlite3.Row, sqlite3.Row]]:
        grouped: dict[str, dict[str, sqlite3.Row]] = {}
        for row in rows:
            pair = row["experiment_pair_id"]
            mode = row["budget_mode"]
            if (not pair or mode not in {"normal", "reduced"} or row["is_synthetic"]
                    or row["measurement_source"] != "measured"):
                continue
            grouped.setdefault(str(pair), {})[str(mode)] = row
        valid = []
        numeric = ("observed_provider_tool_calls", "input_tokens", "cached_input_tokens",
                   "uncached_input_tokens", "output_tokens", "duration_seconds")
        for pair, arms in grouped.items():
            if set(arms) != {"normal", "reduced"}:
                continue
            normal, reduced = arms["normal"], arms["reduced"]
            if (normal["provider_status"] != "completed" or reduced["provider_status"] != "completed"
                    or normal["acceptance_status"] != "pass" or reduced["acceptance_status"] != "pass"):
                continue
            if (not normal["acceptance_contract_version"]
                    or normal["acceptance_contract_version"] != reduced["acceptance_contract_version"]
                    or not normal["task_signature"]
                    or normal["task_signature"] != reduced["task_signature"]
                    or not normal["input_signature"]
                    or normal["input_signature"] != reduced["input_signature"]):
                continue
            if (normal["effective_tool_call_limit"] is None
                    or normal["effective_tool_call_limit"] <= REDUCED_LIMIT
                    or reduced["effective_tool_call_limit"] != REDUCED_LIMIT):
                continue
            if not all(AdaptiveToolBudgetStore._nonnegative(arm[name])
                       for arm in (normal, reduced) for name in numeric):
                continue
            valid.append((pair, normal, reduced))
        return valid[:MAX_RECENT_PAIRS]

    @staticmethod
    def _improvement(normal: float, reduced: float) -> float | None:
        return (normal - reduced) / normal if normal > 0 else None

    def decide(self, analysis: GoalAnalysis, *, requested_mode: str = "auto",
               provider: str | None = None, resolved_model: str | None = None,
               reasoning_setting: str | None = None, current_normal_limit: int | None = None,
               enforcement: str = "unsupported", explicit_cap: int | None = None
               ) -> AdaptiveBudgetDecision:
        started = time.perf_counter()
        mode = str(requested_mode or "auto").lower()
        normal_limit = explicit_cap if explicit_cap is not None else current_normal_limit
        task_family = self.task_family(analysis)
        artifact_type = self.artifact_type(analysis)
        complexity = analysis.complexity.value

        def result(selected: str, source: str, reasons: list[str], pairs=(), ids=(),
                   effective: int | None = None) -> AdaptiveBudgetDecision:
            return AdaptiveBudgetDecision(
                mode, selected, normal_limit, effective if effective is not None else normal_limit,
                source, len(pairs), tuple(reasons), tuple(ids), task_family, artifact_type,
                complexity, provider, resolved_model, reasoning_setting, enforcement,
                round((time.perf_counter() - started) * 1000, 3))

        if mode not in {"normal", "reduced", "auto"}:
            return result("normal", "fallback", ["invalid_requested_mode"])
        if mode == "normal":
            return result("normal", "user_override", ["normal_requested"])
        if normal_limit is not None and normal_limit <= REDUCED_LIMIT:
            selected = "reduced" if mode == "reduced" else "normal"
            return result(selected, "user_override" if mode == "reduced" else "policy",
                          ["normal_limit_already_six_or_less"], effective=normal_limit)
        if enforcement != "hard":
            return result("normal", "fallback" if mode == "auto" else "user_override",
                          ["provider_budget_soft_guidance" if enforcement == "soft_guidance"
                           else "provider_budget_unsupported"])
        if mode == "reduced":
            return result("reduced", "user_override", ["reduced_requested", "hard_limit_supported"],
                          effective=REDUCED_LIMIT)
        if task_family == "unknown" or artifact_type == "unknown":
            return result("normal", "policy", ["task_metadata_unknown"])
        if complexity not in {"trivial", "small", "normal"}:
            return result("normal", "policy", ["complexity_not_eligible"])
        if not provider or not resolved_model or not reasoning_setting:
            return result("normal", "policy", ["execution_settings_unknown"])
        if normal_limit is None:
            return result("normal", "policy", ["normal_limit_unknown"])
        try:
            rows = self._matching_rows(task_family, artifact_type, complexity,
                                       provider, resolved_model, reasoning_setting)
            pairs = self._valid_pairs(rows)
        except (OSError, sqlite3.Error, ValueError, TypeError):
            return result("normal", "fallback", ["policy_evidence_error"])
        failed_reduced = any(row["budget_mode"] == "reduced"
                             and row["acceptance_status"] == "fail"
                             and not row["is_synthetic"] for row in rows)
        if failed_reduced:
            return result("normal", "policy", ["recent_reduced_quality_failure"], pairs,
                          [item[0] for item in pairs])
        if len(pairs) < MIN_COMPARABLE_PAIRS:
            return result("normal", "policy", ["insufficient_comparable_history"], pairs,
                          [item[0] for item in pairs])
        normals = [normal for _, normal, _ in pairs]
        reduced = [item for _, _, item in pairs]
        normal_tools = median(item["observed_provider_tool_calls"] for item in normals)
        reduced_tools = median(item["observed_provider_tool_calls"] for item in reduced)
        if reduced_tools > normal_tools:
            return result("normal", "policy", ["tool_round_trips_not_improved"], pairs,
                          [item[0] for item in pairs])
        normal_uncached = median(item["uncached_input_tokens"] + item["output_tokens"] for item in normals)
        reduced_uncached = median(item["uncached_input_tokens"] + item["output_tokens"] for item in reduced)
        if normal_uncached <= 0:
            if reduced_uncached > 0:
                return result("normal", "policy", ["uncached_regression_guard_failed"], pairs,
                              [item[0] for item in pairs])
        elif (reduced_uncached - normal_uncached) / normal_uncached > MAX_UNCACHED_REGRESSION:
            return result("normal", "policy", ["uncached_regression_guard_failed"], pairs,
                          [item[0] for item in pairs])
        normal_total = median(item["input_tokens"] + item["output_tokens"] for item in normals)
        reduced_total = median(item["input_tokens"] + item["output_tokens"] for item in reduced)
        improvements = {
            "total_tokens": self._improvement(normal_total, reduced_total),
            "tool_round_trips": self._improvement(normal_tools, reduced_tools),
            "duration": self._improvement(
                median(item["duration_seconds"] for item in normals),
                median(item["duration_seconds"] for item in reduced)),
        }
        improved = [name for name, value in improvements.items()
                    if value is not None and value >= MIN_RELATIVE_IMPROVEMENT]
        if not improved:
            return result("normal", "policy", ["minimum_improvement_not_met"], pairs,
                          [item[0] for item in pairs])
        return result("reduced", "policy",
                      ["quality_checks_passed", f"{improved[0]}_improved",
                       "uncached_regression_guard_passed"],
                      pairs, [item[0] for item in pairs], effective=REDUCED_LIMIT)

    def status(self) -> list[dict[str, Any]]:
        fingerprint = self.fingerprint()
        if fingerprint is None or not self.path.exists():
            return []
        try:
            with closing(self._connect()) as db:
                rows = db.execute(
                    "SELECT task_family,artifact_type,complexity,provider,resolved_model,"
                    "reasoning_setting,COUNT(*) observations,COUNT(DISTINCT experiment_pair_id) pairs,"
                    "MAX(created_at) last_observed FROM adaptive_budget_runs WHERE fingerprint=? "
                    "GROUP BY task_family,artifact_type,complexity,provider,resolved_model,reasoning_setting "
                    "ORDER BY last_observed DESC LIMIT 64", (fingerprint,)).fetchall()
                return [dict(row) for row in rows]
        except (OSError, sqlite3.Error):
            return []

    def reset(self, analysis: GoalAnalysis | None = None) -> int:
        fingerprint = self.fingerprint()
        if fingerprint is None or not self.path.exists():
            return 0
        try:
            with closing(self._connect()) as db, db:
                if analysis is None:
                    cursor = db.execute("DELETE FROM adaptive_budget_runs WHERE fingerprint=?", (fingerprint,))
                    db.execute("DELETE FROM adaptive_tool_budgets WHERE fingerprint=?", (fingerprint,))
                else:
                    task_family, artifact = self.task_family(analysis), self.artifact_type(analysis)
                    cursor = db.execute(
                        "DELETE FROM adaptive_budget_runs WHERE fingerprint=? AND task_family=? AND artifact_type=?",
                        (fingerprint, task_family, artifact))
                    db.execute("DELETE FROM adaptive_tool_budgets WHERE fingerprint=? AND family=?",
                               (fingerprint, self.family(analysis)))
                return max(0, int(cursor.rowcount))
        except (OSError, sqlite3.Error):
            return 0
