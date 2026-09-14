"""Conservative, project-local evidence for adaptive provider tool limits."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from adaptive_agent.core.goal_analyzer import GoalAnalysis
from adaptive_agent.project.experience import OperationExperience


MIN_ACCEPTED_RUNS = 3
EVIDENCE_TTL = 30 * 86400
CAP_STEPS = ((9, 3), (6, 4), (3, 6))


@dataclass(frozen=True, slots=True)
class AdaptiveBudgetDecision:
    enabled: bool
    family: str
    accepted_runs: int
    provider_tool_cap: int | None
    source: str
    reason: str

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
        return connection

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
        except (OSError, sqlite3.Error):
            row = None
        accepted = int(row[0]) if row else 0
        cap = next((value for threshold, value in CAP_STEPS if accepted >= threshold), None)
        if cap is None:
            return AdaptiveBudgetDecision(
                True, family, accepted, None, "insufficient_history",
                f"Need {MIN_ACCEPTED_RUNS} comparable accepted runs; preserve the normal budget.",
            )
        return AdaptiveBudgetDecision(
            True, family, accepted, cap, "accepted_history",
            f"{accepted} consecutive comparable runs passed controller-owned deterministic checks.",
        )

    def record(self, analysis: GoalAnalysis, accepted: bool) -> bool:
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
                    return True
                db.execute(
                    "INSERT INTO adaptive_tool_budgets VALUES (?, ?, 1, ?) "
                    "ON CONFLICT(family, fingerprint) DO UPDATE SET "
                    "accepted_runs=adaptive_tool_budgets.accepted_runs+1, "
                    "last_verified=excluded.last_verified",
                    (family, fingerprint, time.time()),
                )
                return True
        except (OSError, sqlite3.Error):
            return False
