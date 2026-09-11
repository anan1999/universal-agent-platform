import json

from adaptive_agent.core.models import Receipt
from adaptive_agent.storage.database import Database
from adaptive_agent.tasks.receipt import ReceiptStore


def test_receipt_store_persists_only_compact_execution_outcome(tmp_path):
    database = Database(tmp_path / "state.db")
    store = ReceiptStore(database)
    receipt = Receipt(
        task_id="TASK-1",
        agent="executor",
        status="completed",
        summary="provider prose that must not be persisted",
        files=["app/main.py", "app/main.py"],
        findings=["long provider finding"],
        token_usage={"input": 100, "output": 25},
        provider="codex",
        model="example-model",
        learning_evidence=[{"type": "command", "summary": "pytest -q"}],
    )

    store.save(receipt)

    row = store.for_task("TASK-1")[0]
    payload = json.loads(row["data_json"])
    assert payload == {
        "task": "TASK-1",
        "status": "completed",
        "files": ["app/main.py"],
        "validation": "pass",
        "learning_evidence": [{"type": "command", "summary": "pytest -q"}],
        "error": None,
    }
    assert "provider prose" not in row["data_json"]
    assert "token_usage" not in payload
