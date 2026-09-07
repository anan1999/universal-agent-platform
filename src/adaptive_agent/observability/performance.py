from adaptive_agent.core.capabilities import signature
from adaptive_agent.core.models import Receipt, Task
from adaptive_agent.storage.database import Database


class PerformanceTracker:
    """Execution history.

    Learning is keyed on the *capability signature*, not on the agent name.
    A capability signature transfers across agents, providers, and domains;
    "developer" does not.
    """

    def __init__(self, database: Database, minimum_samples: int = 5):
        self.database = database
        self.minimum_samples = minimum_samples

    def record(self, task: Task, receipt: Receipt) -> None:
        usage = receipt.token_usage
        metadata = task.metadata
        profiles = metadata.get("work_profiles") or []
        self.database.execute(
            "INSERT INTO agent_performance(agent_role,model,task_type,capability,success,duration,"
            "input_tokens,output_tokens,token_source,escalated,retry_count,provider,"
            "capability_signature,work_profile,complexity,evaluation_result) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (task.owner, receipt.model, metadata.get("task_type", "unknown"),
             task.required_capabilities[0] if task.required_capabilities else None,
             int(receipt.status == "completed"), receipt.duration_seconds, int(usage.get("input", 0)),
             int(usage.get("output", 0)), str(usage.get("source", "estimated")), int(receipt.escalated),
             receipt.retry_count, str(metadata.get("provider", "")),
             metadata.get("capability_signature") or signature(task.required_capabilities),
             ",".join(profiles) if isinstance(profiles, list) else str(profiles),
             str(metadata.get("complexity", "")), str(metadata.get("evaluation_result", ""))),
        )

    def metrics(self) -> list[dict]:
        rows = self.database.query(
            "SELECT agent_role,model,task_type,COUNT(*) task_count,AVG(success) success_rate,"
            "AVG(duration) average_duration,AVG(input_tokens+output_tokens) average_tokens,"
            "AVG(escalated) escalation_rate,(1-AVG(success)) failure_rate "
            "FROM agent_performance GROUP BY agent_role,model,task_type ORDER BY task_count DESC"
        )
        for row in rows:
            row["sufficient_history"] = row["task_count"] >= self.minimum_samples
        return rows

    def by_capability(self) -> list[dict]:
        """Portable history: what worked for this shape of work, regardless of role."""
        rows = self.database.query(
            "SELECT capability_signature,provider,model,work_profile,complexity,COUNT(*) task_count,"
            "AVG(success) success_rate,AVG(duration) average_duration,"
            "AVG(input_tokens+output_tokens) average_tokens,AVG(escalated) escalation_rate "
            "FROM agent_performance WHERE capability_signature != '' "
            "GROUP BY capability_signature,provider,model,work_profile,complexity "
            "ORDER BY task_count DESC"
        )
        for row in rows:
            row["sufficient_history"] = row["task_count"] >= self.minimum_samples
            # Below the threshold, history is shown for explainability only and
            # must not influence routing.
            row["influences_routing"] = row["sufficient_history"]
        return rows
