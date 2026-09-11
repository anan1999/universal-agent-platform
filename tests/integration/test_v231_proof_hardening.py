import asyncio
import json

from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.intelligence.project import ProjectIntelligenceStore
from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.project.adapter import initialize_project
from adaptive_agent.providers.mock import MockProvider
from adaptive_agent.runtime import RESOURCE_ROOT
from adaptive_agent.storage.database import Database


class LearningMockProvider(MockProvider):
    """Emits only configured externalized evidence and captures real packets."""

    def __init__(self, evidence=None):
        super().__init__(delay=0)
        self.evidence = list(evidence or [])
        self.packets = []

    async def execute(self, task, progress=None, packet=None):
        self.packets.append(packet)
        receipt = await super().execute(task, progress, packet)
        receipt.learning_evidence = self.evidence
        self.evidence = []
        return receipt


def _run(project, database_path, goal, provider):
    db = Database(database_path)
    if not db.query("SELECT id FROM projects WHERE id='PRJ-PROOF'"):
        db.execute("INSERT INTO projects(id,path,name,type,config_json) VALUES(?,?,?,?,?)",
                   ("PRJ-PROOF", str(project), "proof-project", "python", "{}"))
    run_id = asyncio.run(Orchestrator(
        db, provider, EventBus(db), provider_name="mock",
        active_profiles=["software-engineering"], consumption_mode="economy",
    ).run_goal(goal, "PRJ-PROOF", str(project), project_name="proof-project",
               project_type="python", project_signals=["pyproject.toml"]))
    composition = json.loads(db.query(
        "SELECT composition_json FROM runs WHERE id=?", (run_id,))[0]["composition_json"])
    return run_id, composition


def test_three_fresh_orchestrators_learn_rediscover_and_validate_project_skill(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='proof-project'\n", encoding="utf-8")
    (project / "app.py").write_text("API_VERSION = 1\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_seed.py").write_text(
        "def test_seed():\n    assert True\n", encoding="utf-8")
    initialize_project(project, RESOURCE_ROOT / "templates", auto=True)
    database_path = tmp_path / "history.db"
    evidence = [
        {
            "id": "expense-api-contract",
            "type": "knowledge",
            "summary": "Expense API changes preserve the category response contract.",
            "capabilities": ["category", "api"],
            "related_paths": ["app.py"],
            "expected_reuse": 3,
            "validation": "validated",
            "evidence": ["Task 1 deterministic acceptance passed"],
        },
        {
            "id": "expense-api-workflow",
            "type": "procedure",
            "summary": "Expense API category contract update workflow.",
            "procedure_steps": [
                "Update the expense API response contract.",
                "Run the benchmark-owned acceptance suite.",
            ],
            "capabilities": ["category", "api", "testing"],
            "related_paths": ["app.py"],
            "expected_reuse": 3,
            "validation": "validated",
            "evidence": ["Task 1 deterministic acceptance passed"],
        },
    ]

    first_provider = LearningMockProvider(evidence)
    first_run, first_composition = _run(
        project, database_path, "Implement and test the expense category API contract", first_provider)
    first_items = ProjectIntelligenceStore(project).items()
    skill = next(item for item in first_items if item.id == "expense-api-workflow")
    assert skill.status == "temporary"
    assert (project / ".agent" / "skills" / "expense-api-workflow" / "skill.json").is_file()
    assert any(item.id == "expense-api-contract" for item in first_items)
    assert first_composition["project_intelligence"]["temperature"] == "cold"

    second_provider = LearningMockProvider()
    second_run, second_composition = _run(
        project, database_path, "Implement and test another expense category API change",
        second_provider)
    selected_second = second_composition["execution_plan"]["selected_skills"]
    assert any(item["skill"] == "expense-api-workflow" for item in selected_second)
    assert any(item["benefit_gate_result"] == "LOAD" for item in selected_second
               if item["skill"] == "expense-api-workflow")
    assert second_composition["project_intelligence"]["knowledge_selected"] >= 1
    assert second_composition["project_intelligence"]["skills_selected"] == 1
    assert any(packet and packet.project_skills and packet.skill_context
               for packet in second_provider.packets)

    third_provider = LearningMockProvider()
    third_run, third_composition = _run(
        project, database_path, "Test and extend the expense category API contract",
        third_provider)
    assert any(item["skill"] == "expense-api-workflow"
               for item in third_composition["execution_plan"]["selected_skills"])
    final_items = ProjectIntelligenceStore(project).items(include_inactive=True)
    final_skills = [item for item in final_items if item.id == "expense-api-workflow"]
    assert len(final_skills) == 1
    assert final_skills[0].validated_reuse_count >= 2
    assert final_skills[0].status == "promotion_candidate"

    data = json.loads((project / ".agent" / "intelligence.json").read_text(encoding="utf-8"))
    runs = {item["run_id"]: item for item in data["runs"]}
    assert runs[first_run]["learning_funnel"]["provider_learning_evidence_count"] == 2
    assert runs[first_run]["learning_funnel"]["accepted_by_kind"]["skill"] == 1
    assert runs[second_run]["validated_context_reuse"] >= 2
    assert runs[third_run]["validated_context_reuse"] >= 2
