"""Conservative Skill quality history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from adaptive_agent.storage.database import Database


@dataclass(slots=True)
class SkillQualityRecord:
    skill_id: str
    version: str
    runs: int
    successes: int
    failures: int
    artifact_quality: float | None
    average_invocations: float | None
    measured_tokens: int | None
    estimated_context_tokens: int | None
    last_validated: str | None
    promotion_candidate: bool

    @property
    def reliability(self) -> float | None:
        return self.successes / self.runs * 100 if self.runs >= 3 else None

    @property
    def history_status(self) -> str:
        return "SUFFICIENT" if self.runs >= 3 else "INSUFFICIENT_HISTORY"

    def to_dict(self) -> dict[str, Any]:
        return {"skill_id": self.skill_id, "version": self.version, "runs": self.runs,
                "successes": self.successes, "failures": self.failures,
                "reliability": self.reliability, "artifact_quality": self.artifact_quality,
                "average_invocations": self.average_invocations,
                "measured_tokens": self.measured_tokens,
                "estimated_context_tokens": self.estimated_context_tokens,
                "last_validated": self.last_validated,
                "promotion_candidate": self.promotion_candidate,
                "history_status": self.history_status}


class SkillQualityStore:
    def __init__(self, database: Database):
        self.database = database

    def record(self, skill_id: str, version: str, run_id: str, task_id: str,
               success: bool, artifact_quality: float | None, invocations: int,
               tokens: int | None, token_source: str, context_tokens: int | None,
               provider: str = "", model: str = "", safety_failure: bool = False) -> None:
        self.database.execute(
            "INSERT INTO skill_runs(skill_id,version,run_id,task_id,success,artifact_quality,"
            "invocations,tokens,token_source,context_tokens,provider,model,safety_failure) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (skill_id, version, run_id, task_id, int(success), artifact_quality, invocations,
             tokens, token_source, context_tokens, provider, model, int(safety_failure)),
        )

    def get(self, skill_id: str, version: str | None = None) -> SkillQualityRecord:
        where = "skill_id=?" + (" AND version=?" if version else "")
        params = (skill_id, version) if version else (skill_id,)
        rows = self.database.query(
            f"SELECT skill_id,version,COUNT(*) runs,SUM(success) successes,"
            f"SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) failures,AVG(artifact_quality) artifact_quality,"
            f"AVG(invocations) average_invocations,"
            f"SUM(CASE WHEN token_source='measured' THEN tokens ELSE 0 END) measured_tokens,"
            f"AVG(context_tokens) estimated_context_tokens,MAX(created_at) last_validated,"
            f"SUM(safety_failure) safety_failures FROM skill_runs WHERE {where} GROUP BY skill_id,version "
            f"ORDER BY version DESC LIMIT 1", params)
        if not rows:
            return SkillQualityRecord(skill_id, version or "unknown", 0, 0, 0, None, None,
                                      None, None, None, False)
        row = rows[0]
        candidate = row["runs"] >= 3 and row["successes"] >= 3 and row["safety_failures"] == 0
        return SkillQualityRecord(row["skill_id"], row["version"], row["runs"], row["successes"],
                                  row["failures"], row["artifact_quality"], row["average_invocations"],
                                  row["measured_tokens"] if row["measured_tokens"] else None,
                                  row["estimated_context_tokens"], row["last_validated"], candidate)
