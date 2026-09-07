from __future__ import annotations

from dataclasses import asdict, dataclass, field

from adaptive_agent.core.models import new_id
from adaptive_agent.storage.database import Database


@dataclass(slots=True)
class MailRequest:
    sender: str
    recipient: str
    task_id: str
    question: str
    files: list[str] = field(default_factory=list)
    max_response_words: int = 300
    id: str = field(default_factory=lambda: new_id("REQ"))


class Mailbox:
    def __init__(self, database: Database, run_id: str):
        self.database = database
        self.run_id = run_id

    def send(self, request: MailRequest) -> str:
        if request.sender == request.recipient:
            raise ValueError("agents cannot message themselves")
        if request.max_response_words > 500:
            raise ValueError("response budget exceeds protocol maximum")
        self.database.execute(
            "INSERT INTO messages(id,run_id,task_id,sender,recipient,status,data_json) VALUES(?,?,?,?,?,?,?)",
            (request.id, self.run_id, request.task_id, request.sender, request.recipient, "pending", self.database.json(asdict(request))),
        )
        return request.id

    def answer(self, request_id: str, finding: str, severity: str = "info", recommended_action: str = "") -> None:
        rows = self.database.query("SELECT data_json FROM messages WHERE id=?", (request_id,))
        if not rows:
            raise KeyError(request_id)
        payload = {"request_id": request_id, "status": "answered", "finding": finding, "severity": severity, "recommended_action": recommended_action}
        self.database.execute("UPDATE messages SET status='answered', data_json=? WHERE id=?", (self.database.json(payload), request_id))

