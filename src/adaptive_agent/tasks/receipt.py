from adaptive_agent.core.models import Receipt
from adaptive_agent.storage.database import Database


class ReceiptStore:
    def __init__(self, database: Database):
        self.database = database

    def save(self, receipt: Receipt) -> None:
        # Persist only the reusable outcome of an execution. Provider prose,
        # token accounting and routing diagnostics live in their dedicated
        # tables/in-memory result and do not belong in the project receipt.
        evidence = [item for item in receipt.learning_evidence if isinstance(item, dict)][:8]
        payload = {
            "task": receipt.task_id,
            "status": receipt.status,
            "files": list(dict.fromkeys(receipt.files))[:50],
            "validation": "pass" if receipt.status == "completed" else "fail",
            "learning_evidence": evidence,
            "error": receipt.error_code,
        }
        self.database.execute(
            "INSERT INTO receipts(task_id,agent,status,data_json,created_at) VALUES(?,?,?,?,?)",
            (receipt.task_id, receipt.agent, receipt.status, self.database.json(payload), receipt.created_at),
        )

    def for_task(self, task_id: str) -> list[dict]:
        return self.database.query("SELECT * FROM receipts WHERE task_id=? ORDER BY id", (task_id,))

