import asyncio
import json
from pathlib import Path

import yaml

from adaptive_agent.core.artifact_evaluator import DeclaredArtifactEvaluator
from adaptive_agent.core.consumption import ExecutionBudget
from adaptive_agent.core.execution_packet import ExecutionPacketBuilder
from adaptive_agent.core.models import Receipt, Task, TaskKind
from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.intelligence.project import ProjectIntelligenceStore
from adaptive_agent.project.adapter import initialize_project
from adaptive_agent.project.context_index import ProjectContextIndex
from adaptive_agent.providers.mock import MockProvider
from adaptive_agent.runtime import RESOURCE_ROOT
from adaptive_agent.skills.registry import SkillRegistry
from adaptive_agent.storage.database import Database


def initialized_project(root: Path, *, software: bool = True) -> Path:
    project = root / "project"
    project.mkdir()
    (project / "README.md").write_text(
        "# Project\nA Python API.\n" if software else "# Brand launch\nDesign project.\n",
        encoding="utf-8")
    if software:
        (project / "api").mkdir()
        (project / "api" / "routes.py").write_text("ROUTES = []\n", encoding="utf-8")
        (project / "src" / "utils").mkdir(parents=True)
        (project / "src" / "utils" / "dates.py").write_text(
            "def iso_date(value): return value.isoformat()\n", encoding="utf-8")
        (project / "private").mkdir()
        (project / "private" / "secret.txt").write_text("not authorized\n", encoding="utf-8")
        (project / "pyproject.toml").write_text("[project]\nname='reuse-fixture'\n", encoding="utf-8")
    initialize_project(project, RESOURCE_ROOT / "templates", auto=True)
    return project


def first_agent(composition):
    return next(task for task in composition.graph.tasks.values() if task.kind is TaskKind.AGENT)


class PacketProvider(MockProvider):
    id = "codex"

    def __init__(self, learning_evidence=None):
        super().__init__(delay=0)
        self.packets = []
        self.learning_evidence = learning_evidence or []

    async def execute(self, task, progress=None, packet=None):
        self.packets.append(packet)
        return Receipt(
            task.id, task.owner, "completed", "Produced requested work.",
            token_usage={"input": 10, "output": 5, "cached": 0, "source": "measured",
                         "estimated": False, "invocation_count": 1,
                         "provider_tool_calls": 0, "provider_messages": 1},
            provider=self.id, model=task.metadata.get("model"),
            learning_evidence=list(self.learning_evidence))


class HardBudgetMock(MockProvider):
    provider_tool_budget_enforcement = "hard"


def test_suggested_paths_are_navigation_not_permission(tmp_path):
    project = initialized_project(tmp_path)
    config_path = project / ".agent" / "project.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["constraints"]["allowed_files"] = ["api/", "src/"]
    config["constraints"]["denied_files"] = ["private/"]
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    index = ProjectContextIndex(project)
    value = index.load()
    value["important_paths"] = {"backend": "api/"}
    index._write(value)

    composition = Orchestrator(Database(tmp_path / "scope.db"), MockProvider(delay=0)).compose(
        "RUN-SCOPE", "Modify the API and reuse the date utility", str(project), "fixture", "python")
    task = first_agent(composition)
    packet = ExecutionPacketBuilder().build(task, project, "fixture", "python")

    assert packet.suggested_paths == ["api/"]
    assert packet.allowed_scope == ["api/", "src/"]
    assert packet.denied_scope == ["private/"]
    assert "src/utils/dates.py" not in packet.suggested_paths
    assert "Navigation suggestions do not restrict exploration" in packet.render()
    assert "private/" in packet.render()


def test_index_decision_and_constraint_reach_packet_once(tmp_path):
    project = initialized_project(tmp_path)
    index = ProjectContextIndex(project)
    assert index.update_stable({
        "constraints": ["Dates use ISO-8601."],
        "decisions": ["Public API errors use problem details."],
    })
    composition = Orchestrator(Database(tmp_path / "packet.db"), MockProvider(delay=0)).compose(
        "RUN-PACKET", "Modify API date validation", str(project), "fixture", "python")
    packet = ExecutionPacketBuilder().build(first_agent(composition), project, "fixture", "python")
    rendered = packet.render()

    assert packet.relevant_constraints == ["Dates use ISO-8601."]
    assert packet.active_decisions == ["Public API errors use problem details."]
    assert rendered.count("Dates use ISO-8601.") == 1
    assert rendered.count("Public API errors use problem details.") == 1
    assert any("project-index.json" in source for source in packet.source_references)


def test_missing_or_corrupt_index_falls_back_to_targeted_exploration(tmp_path):
    project = initialized_project(tmp_path)
    index = ProjectContextIndex(project)
    index.path.write_text("{broken", encoding="utf-8")
    selection = index.select("Modify the API")

    assert selection.discovery_performed is True
    assert selection.reuse_hits == 0
    assert selection.reuse_miss_reason == "CACHE_INVALID"
    assert selection.targeted_exploration_allowed is True
    assert "project_index" in " ".join(selection.stale_or_unavailable_items)


def test_provider_completion_without_acceptance_is_unverified(tmp_path, monkeypatch):
    monkeypatch.setenv("UAP_EXPERIMENTAL_HEAVY_LEARNING", "1")
    project = initialized_project(tmp_path, software=False)
    provider = PacketProvider()
    asyncio.run(Orchestrator(Database(tmp_path / "unverified.db"), provider).run_goal(
        "Review the API architecture", working_directory=str(project),
        project_name="fixture", project_type="python"))
    run = ProjectIntelligenceStore(project)._read()["runs"][-1]

    assert run["success"] is True
    assert run["evaluation_passed"] is None
    assert run["validated_reuse"] is False


def test_required_sections_are_checked_in_actual_artifact(tmp_path):
    (tmp_path / "brief.md").write_text("# Brief\nNo target section here.\n", encoding="utf-8")
    task = Task("T", "R", "Create brief", "designer", metadata={
        "required_artifacts": ["brief.md"], "required_sections": ["Audience"]})
    receipt = Receipt("T", "designer", "completed", "Audience section completed.")
    quality = DeclaredArtifactEvaluator().evaluate(task, receipt, tmp_path)

    assert quality.passed is False
    assert "missing required section in artifacts: Audience" in quality.failures


def test_budget_is_run_local_on_reused_orchestrator(tmp_path):
    project = initialized_project(tmp_path)
    configured = ExecutionBudget(max_provider_tool_calls=8)
    orchestrator = Orchestrator(
        Database(tmp_path / "budget.db"), HardBudgetMock(delay=0),
        execution_budget=configured, adaptive_budget_mode="reduced")
    reduced = orchestrator.compose("RUN-A", "Modify the API", str(project), "fixture", "python")
    orchestrator.adaptive_budget_mode = "normal"
    normal = orchestrator.compose("RUN-B", "Modify the API", str(project), "fixture", "python")

    assert reduced.execution_budget["max_provider_tool_calls"] == 6
    assert normal.execution_budget["max_provider_tool_calls"] == 8
    assert orchestrator.execution_budget is configured
    assert orchestrator.execution_budget.max_provider_tool_calls == 8


def test_structured_receipt_reaches_fresh_session_provider_packet(tmp_path):
    project = initialized_project(tmp_path, software=False)
    (project / "brand-policy.md").write_text("Use cobalt blue for primary actions.\n", encoding="utf-8")
    evidence = [{
        "type": "decision", "summary": "Primary actions use cobalt blue.",
        "evidence": ["brand-policy.md:1"], "related_paths": ["brand-policy.md"],
        "capabilities": ["brand_design"], "tags": ["brand"], "expected_reuse": 3,
        "validation": "validated", "detail": "", "rationale": "Approved brand policy.",
        "alternatives": [], "procedure_steps": [], "inputs": [], "outputs": [],
        "evaluation": [],
    }]
    first_provider = PacketProvider(evidence)
    asyncio.run(Orchestrator(Database(tmp_path / "first.db"), first_provider).run_goal(
        "Create a launch layout", working_directory=str(project),
        project_name="brand", project_type="design"))

    second_provider = PacketProvider()
    asyncio.run(Orchestrator(Database(tmp_path / "second.db"), second_provider).run_goal(
        "Refine the launch call to action", working_directory=str(project),
        project_name="brand", project_type="design"))
    rendered = "\n".join(packet.render() for packet in second_provider.packets)

    assert "Primary actions use cobalt blue." in rendered
    assert rendered.count("Primary actions use cobalt blue.") == 1
    assert "brand-policy.md" in rendered


def test_repeated_procedure_reuses_one_project_skill_package(tmp_path):
    project = initialized_project(tmp_path)
    store = ProjectIntelligenceStore(project)
    candidate = {
        "id": "release-check", "kind": "procedure",
        "summary": "Validate a release with the approved checklist.",
        "procedure": "Run the allowlisted checks and inspect their results.",
        "capabilities": ["release_validation"], "tags": ["release"],
        "related_paths": ["README.md"], "evidence": ["README.md:1"],
        "validation": "evidence_backed", "expected_reuse": 3,
    }
    assert len(store.learn_candidates([candidate], run_id="RUN-1")) == 1
    assert len(store.learn_candidates([candidate], run_id="RUN-2")) == 1
    assert len([item for item in store.items() if item.kind == "skill"]) == 1

    registry = SkillRegistry()
    registry.discover_directory(project / ".agent" / "skills")
    loaded = registry.load_selected("release-check")
    assert loaded.manifest.id == "release-check"


def test_nonsoftware_fixture_reuses_brand_rules_without_coding_defaults(tmp_path):
    project = initialized_project(tmp_path, software=False)
    ProjectContextIndex(project).update_stable({
        "constraints": ["Use the approved cobalt and ivory palette."],
        "decisions": ["Deliver the concept as a one-page design brief."],
    })
    composition = Orchestrator(Database(tmp_path / "design.db"), MockProvider(delay=0)).compose(
        "RUN-DESIGN", "Create a brand identity direction and one-page design brief",
        str(project), "brand", "design")
    packet = ExecutionPacketBuilder().build(first_agent(composition), project, "brand", "design")
    rendered = packet.render()

    assert "approved cobalt and ivory palette" in rendered
    assert "one-page design brief" in rendered
    assert "coding" not in composition.analysis.capabilities
    assert "pytest" not in rendered.lower()
