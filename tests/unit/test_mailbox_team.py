from adaptive_agent.agents.registry import AgentRegistry
from adaptive_agent.core.team_manager import TeamManager
from adaptive_agent.messaging.mailbox import MailRequest, Mailbox
from adaptive_agent.storage.database import Database


def test_structured_mailbox(tmp_path):
    db = Database(tmp_path / "test.db")
    request_id = Mailbox(db, "RUN").send(MailRequest("developer", "reviewer", "TASK", "Check contract?"))
    Mailbox(db, "RUN").answer(request_id, "Contract is valid")
    assert db.query("SELECT status FROM messages WHERE id=?", (request_id,))[0]["status"] == "answered"


def test_temporary_specialist_and_promotion_candidate():
    registry = AgentRegistry()
    manager = TeamManager(registry)
    name, result = manager.ensure_capability("android_ota", "RUN")
    assert result == "temporary_specialist"
    assert not manager.record_success(name, "RUN")
    assert not manager.record_success(name, "RUN")
    assert manager.record_success(name, "RUN")
    assert registry.all()[name]["promotion_candidate"] is True
    registry.promote(name)
    assert registry.all()[name]["type"] == "permanent"

