from adaptive_agent.core.models import Receipt
from adaptive_agent.storage.database import Database


class ReceiptStore:
    def __init__(self, database: Database):
        self.database = database

    def save(self, receipt: Receipt) -> None:
        self.database.execute(
            "INSERT INTO receipts(task_id,agent,status,data_json,created_at) VALUES(?,?,?,?,?)",
            (receipt.task_id, receipt.agent, receipt.status, self.database.json(receipt.to_dict()), receipt.created_at),
        )

    def for_task(self, task_id: str) -> list[dict]:
        return self.database.query("SELECT * FROM receipts WHERE task_id=? ORDER BY id", (task_id,))

