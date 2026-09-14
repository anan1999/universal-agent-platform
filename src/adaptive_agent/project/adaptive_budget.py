"""Conservative, project-local evidence for adaptive provider tool limits."""
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
from adaptive_agent.project.experience import OperationExperience


MIN_ACCEPTED_RUNS = 3
EVIDENCE_TTL = 30 * 86400
CAP_STEPS = ((3, 6), (6, 4), (9, 3))


@dataclass(frozen=True, slots=True)
class AdaptiveBudgetDecision:
    enabled: bool
    family: str
    accepted_runs: int
    provider_tool_cap: int | None
    source: str
    reason: str
    cost_samples: int = 0
    cost_gate: str = "insufficient_cost_evidence"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AdaptiveToolBudgetStore:
    """Learn only from controller-observed deterministic acceptance.

    The store never consumes provider prose, test output, or raw goals. Evidence
    is isolated by a bounded semantic task family and the current project
    environment fingerprint. A failed external check resets the consecutive
    evidence for that family.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / ".agent/cache/adaptive-budgets.sqlite3"

    @staticmethod
    def family(analysis: GoalAnalysis) -> str:
        contract = {
            "profiles": sorted(set(analysis.profiles)),
            "capabilities": sorted(set(analysis.capabilities)),
            "artifacts": sorted(set(analysis.artifact_types)),
            "complexity": analysis.complexity.value,
            "risk": analysis.risk.value,
            "read_only": analysis.read_only,
        }
        serialized = json.dumps(contract, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()[:20]

    def fingerprint(self) -> str | None:
        return OperationExperience(self.root).fingerprint()

    def _connect(self):
        if not self.path.resolve().is_relative_to(self.root):
            raise OSError("Adaptive budget path leaves project")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=2)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS adaptive_tool_budgets "
            "(family TEXT NOT NULL, fingerprint TEXT NOT NULL, accepted_runs INTEGER NOT NULL, "
            "last_verified REAL NOT NULL, PRIMARY KEY(family, fingerprint))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS adaptive_budget_observations "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, family TEXT NOT NULL, fingerprint TEXT NOT NULL, "
            "effective_cap INTEGER, provider_tool_calls INTEGER NOT NULL, total_tokens INTEGER NOT NULL, "
            "uncached_tokens INTEGER NOT NULL, duration_seconds REAL NOT NULL, verified REAL NOT NULL)"
        )
        return connection

    @staticmethod
    def _cost_improved(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> bool:
        return (
            median(item["total_tokens"] for item in after)
            <= median(item["total_tokens"] for item in before)
            and median(item["uncached_tokens"] for item in after)
            <= median(item["uncached_tokens"] for item in before)
        )

    def _observations(self, db, family: str, fingerprint: str) -> list[dict[str, Any]]:
        rows = db.execute(
            "SELECT effective_cap,provider_tool_calls,total_tokens,uncached_tokens,duration_seconds "
            "FROM adaptive_budget_observations WHERE family=? AND fingerprint=? "
            "AND verified>=? AND verified<=? ORDER BY id DESC LIMIT 12",
            (family, fingerprint, time.time() - EVIDENCE_TTL, time.time()),
        ).fetchall()
        return [dict(zip(("effective_cap", "provider_tool_calls", "total_tokens",
                         "uncached_tokens", "duration_seconds"), row))
                for row in reversed(rows)]

    @staticmethod
    def _eligible_cap(accepted: int, observations: list[dict[str, Any]]) -> tuple[int | None, str]:
        if accepted < MIN_ACCEPTED_RUNS:
            return None, "insufficient_quality_evidence"
        if len(observations) < 3:
            return None, "insufficient_cost_evidence"
        recent = observations[-3:]
        if max(item["provider_tool_calls"] for item in recent) > 6:
            return None, "observed_tools_exceed_cap_6"
        cap = 6
        gate = "cap_6_supported"
        if accepted >= 6 and len(observations) >= 6:
            before, after = observations[-6:-3], observations[-3:]
            if all(item["effective_cap"] == 4 for item in after):
                cap, gate = 4, "cap_4_previously_applied"
            elif (all(item["effective_cap"] == 6 for item in after)
                    and max(item["provider_tool_calls"] for item in after) <= 4
                    and AdaptiveToolBudgetStore._cost_improved(before, after)):
                cap, gate = 4, "cap_4_supported_by_cost"
        if accepted >= 9 and len(observations) >= 6 and cap == 4:
            before, after = observations[-6:-3], observations[-3:]
            if (all(item["effective_cap"] == 4 for item in after)
                    and max(item["provider_tool_calls"] for item in after) <= 3
                    and AdaptiveToolBudgetStore._cost_improved(before, after)):
                cap, gate = 3, "cap_3_supported_by_cost"
        return cap, gate

    def decide(self, analysis: GoalAnalysis, explicit_cap: int | None = None) -> AdaptiveBudgetDecision:
        family = self.family(analysis)
        if explicit_cap is not None:
            return AdaptiveBudgetDecision(
                True, family, 0, explicit_cap, "explicit",
                "The explicit provider tool-call limit takes precedence over learned evidence.",
            )
        fingerprint = self.fingerprint()
        if fingerprint is None or not self.path.exists():
            return AdaptiveBudgetDecision(
                True, family, 0, None, "insufficient_history",
                "No valid project fingerprint or accepted history; preserve the normal budget.",
            )
        try:
            with closing(self._connect()) as db:
                row = db.execute(
                    "SELECT accepted_runs FROM adaptive_tool_budgets "
                    "WHERE family=? AND fingerprint=? AND last_verified>=? AND last_verified<=?",
                    (family, fingerprint, time.time() - EVIDENCE_TTL, time.time()),
                ).fetchone()
                observations = self._observations(db, family, fingerprint)
        except (OSError, sqlite3.Error):
            row = None
            observations = []
        accepted = int(row[0]) if row else 0
        cap, cost_gate = self._eligible_cap(accepted, observations)
        if cap is None:
            return AdaptiveBudgetDecision(
                True, family, accepted, None, "insufficient_history",
                f"Need accepted quality and measurable cost evidence; preserve the normal budget.",
                len(observations), cost_gate,
            )
        return AdaptiveBudgetDecision(
            True, family, accepted, cap, "accepted_history",
            f"{accepted} consecutive comparable runs passed controller-owned deterministic checks.",
            len(observations), cost_gate,
        )

    def record(self, analysis: GoalAnalysis, accepted: bool,
               metrics: dict[str, Any] | None = None,
               effective_cap: int | None = None) -> bool:
        """Record one externally checked result; false is fail-closed and resets."""
        fingerprint = self.fingerprint()
        if fingerprint is None:
            return False
        family = self.family(analysis)
        try:
            with closing(self._connect()) as db, db:
                if not accepted:
                    db.execute(
                        "DELETE FROM adaptive_tool_budgets WHERE family=? AND fingerprint=?",
                        (family, fingerprint),
                    )
                    db.execute(
                        "DELETE FROM adaptive_budget_observations WHERE family=? AND fingerprint=?",
                        (family, fingerprint),
                    )
                    return True
                db.execute(
                    "INSERT INTO adaptive_tool_budgets VALUES (?, ?, 1, ?) "
                    "ON CONFLICT(family, fingerprint) DO UPDATE SET "
                    "accepted_runs=adaptive_tool_budgets.accepted_runs+1, "
                    "last_verified=excluded.last_verified",
                    (family, fingerprint, time.time()),
                )
                metrics = metrics or {}
                if (metrics.get("source") == "measured"
                        and all(isinstance(metrics.get(name), (int, float))
                                and metrics[name] >= 0 for name in (
                                    "provider_tool_calls", "total_tokens",
                                    "uncached_tokens", "duration_seconds"))):
                    db.execute(
                        "INSERT INTO adaptive_budget_observations"
                        "(family,fingerprint,effective_cap,provider_tool_calls,total_tokens,"
                        "uncached_tokens,duration_seconds,verified) VALUES(?,?,?,?,?,?,?,?)",
                        (family, fingerprint, effective_cap,
                         int(metrics["provider_tool_calls"]), int(metrics["total_tokens"]),
                         int(metrics["uncached_tokens"]), float(metrics["duration_seconds"]),
                         time.time()),
                    )
                return True
        except (OSError, sqlite3.Error):
            return False
