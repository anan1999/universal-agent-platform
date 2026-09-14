import asyncio
import json

from scripts.skill_context_benchmark import measure

from adaptive_agent.cli import _dry_run, main
from adaptive_agent.core.artifact_evaluator import DeclaredArtifactEvaluator
from adaptive_agent.core.models import Receipt, Task
from adaptive_agent.core.scheduler import Scheduler
from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.providers.mock import MockProvider
from adaptive_agent.skills.manifest import LoadedSkill, SkillManifest, SkillStatus, SkillTrust
from adaptive_agent.skills.quality import SkillQualityStore
from adaptive_agent.skills.registry import SkillRegistry
from adaptive_agent.skills.resolver import SkillResolver
from adaptive_agent.skills.synthesis import (
    SkillPackageValidator,
    SkillSpecification,
    TemporarySkillSynthesizer,
)
from adaptive_agent.storage.database import Database
from adaptive_agent.tasks.graph import TaskGraph


def _package(root, identifier="responsive-dashboard"):
    path = root / identifier
    (path / "references").mkdir(parents=True)
    (path / "examples").mkdir()
    (path / "SKILL.md").write_text("Use a bounded responsive layout procedure.\n", encoding="utf-8")
    for index in range(5):
        (path / "references" / f"ref-{index}.md").write_text(f"reference {index} " * 50,
                                                               encoding="utf-8")
    for index in range(3):
        (path / "examples" / f"example-{index}.md").write_text(f"example {index} " * 50,
                                                                 encoding="utf-8")
    manifest = {
        "id": identifier, "version": "1.0.0", "description": "Responsive UI procedure",
        "capabilities": ["responsive_layout", "accessibility"],
        "references": {f"ref-{index}": f"references/ref-{index}.md" for index in range(5)},
        "evaluation": ["accessibility_review"], "estimated_context_tokens": 900,
        "trust": "project_local", "status": "active",
    }
    (path / "skill.json").write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_tool_only_strategy_spends_zero_agent_invocations(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    plan = _dry_run("Run pytest", "mock")
    assert plan["execution_plan"]["strategy"] == "tool_only"
    assert plan["execution_plan"]["ai_agents"] == 0
    assert [task["kind"] for task in plan["tasks"]] == ["tool"]


def test_simple_bug_is_single_agent_with_deterministic_test(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='tiny'\n", encoding="utf-8")
    plan = _dry_run("Fix a simple arithmetic bug and run the existing test.", "mock")
    assert plan["execution_plan"]["strategy"] == "single_agent_with_tools"
    assert plan["execution_plan"]["ai_agents"] == 1
    assert not any(task["agent"].endswith("reviewer") for task in plan["tasks"])
    assert any(task["kind"] == "tool" and task["agent"] == "project_test"
               for task in plan["tasks"])


def test_allowlisted_downstream_validation_is_owned_by_scheduler(monkeypatch, tmp_path):
    import yaml

    from adaptive_agent.core.execution_packet import ExecutionPacketBuilder
    from adaptive_agent.core.orchestrator import Orchestrator

    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent" / "commands.yaml").write_text(yaml.safe_dump({
        "commands": {"test": {"command": ["python", "-m", "pytest", "-q"]}}
    }), encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='tiny'\n", encoding="utf-8")
    monkeypatch.setenv("UAP_EXPERIMENTAL_PARENT_VALIDATION", "1")
    orchestrator = Orchestrator(Database(tmp_path / "parent-validation.db"), MockProvider(delay=0))
    composition = orchestrator.compose(
        "RUN-parent", "Fix a simple arithmetic bug and run the existing test.",
        str(tmp_path), "tiny", "python")
    agent = next(task for task in composition.graph.tasks.values() if task.kind.value == "agent")
    assert agent.metadata["validation_owner"] == "scheduler"
    assert agent.metadata["parent_validation_tools"] == ["project_test"]
    packet = ExecutionPacketBuilder().build(agent, tmp_path, "tiny", "python")
    rendered = packet.render()
    assert "scheduler runs: project_test" in rendered
    assert "Validated commands:" not in rendered


def test_missing_allowlist_keeps_validation_with_agent(monkeypatch, tmp_path):
    from adaptive_agent.core.orchestrator import Orchestrator

    (tmp_path / ".agent").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='tiny'\n", encoding="utf-8")
    monkeypatch.setenv("UAP_EXPERIMENTAL_PARENT_VALIDATION", "1")
    composition = Orchestrator(
        Database(tmp_path / "no-parent-validation.db"), MockProvider(delay=0)
    ).compose("RUN-local", "Fix a simple arithmetic bug and run the existing test.",
              str(tmp_path), "tiny", "python")
    agent = next(task for task in composition.graph.tasks.values() if task.kind.value == "agent")
    assert "parent_validation_tools" not in agent.metadata


def test_parent_validation_is_disabled_by_default(tmp_path):
    import yaml

    from adaptive_agent.core.orchestrator import Orchestrator

    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent" / "commands.yaml").write_text(yaml.safe_dump({
        "commands": {"test": {"command": ["python", "-m", "pytest", "-q"]}}
    }), encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='tiny'\n", encoding="utf-8")
    composition = Orchestrator(
        Database(tmp_path / "default-validation.db"), MockProvider(delay=0)
    ).compose("RUN-default", "Fix a simple arithmetic bug and run the existing test.",
              str(tmp_path), "tiny", "python")
    agent = next(task for task in composition.graph.tasks.values() if task.kind.value == "agent")
    assert "parent_validation_tools" not in agent.metadata


def test_non_software_review_uses_one_reasoning_responsibility(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    plan = _dry_run("Review the usability of a mobile onboarding flow.", "mock")
    assert plan["execution_plan"]["strategy"] in {"single_agent", "single_agent_with_tools"}
    assert plan["execution_plan"]["ai_agents"] == 1
    assert "software-engineering" not in plan["analysis"]["profiles"]


def test_known_w8a8_work_reuses_skills_without_specialist(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    plan = _dry_run("Validate a W8A8 TFLite model.", "mock")
    selected = {item["skill"] for item in plan["execution_plan"]["selected_skills"]}
    assert "w8a8-validation" in selected
    assert plan["execution_plan"]["ai_agents"] == 1
    assert not any(member["origin"] == "temporary_specialist" for member in plan["team"]["members"])


def test_packaged_w8a8_skill_progressively_loads_one_reference():
    from adaptive_agent.runtime import RESOURCE_ROOT

    registry = SkillRegistry()
    registry.discover_directory(RESOURCE_ROOT / "skills", SkillTrust.BUILT_IN)
    loaded = registry.load_selected("w8a8-validation", ["metadata-contract"])
    assert loaded.manifest.version == "1.0.0"
    assert set(loaded.manifest.references) == {"metadata-contract", "hardware-boundaries"}
    assert list(loaded.references) == ["metadata-contract"]
    assert "Hardware evidence boundaries" not in loaded.to_context()


def test_unknown_compound_capability_proposes_temporary_skill_not_agent(tmp_path):
    from adaptive_agent.core.capabilities import Complexity, Risk
    from adaptive_agent.core.execution_planner import ExecutionPlanner
    from adaptive_agent.core.goal_analyzer import GoalAnalysis
    from adaptive_agent.core.tools import ToolRegistry

    analysis = GoalAnalysis("perform novel check", ["novel_capability"],
                            complexity=Complexity.SMALL, risk=Risk.LOW,
                            read_only=False, profiles=["general"])
    plan = ExecutionPlanner(ToolRegistry.default(), SkillResolver([]),
                            allow_skill_synthesis=True, minimal_skills=False).plan(
                                analysis.goal, analysis)
    assert [item.id for item in plan.temporary_skills] == ["temporary-novel-capability"]
    assert plan.ai_agents == 1
    assert plan.selected_skills[0].manifest.status is SkillStatus.TEMPORARY


def test_all_execution_strategy_shapes_are_reachable():
    from adaptive_agent.core.capabilities import Complexity, Risk
    from adaptive_agent.core.execution_planner import ExecutionPlanner, ExecutionStrategy
    from adaptive_agent.core.goal_analyzer import GoalAnalysis
    from adaptive_agent.core.tools import ToolRegistry

    planner = ExecutionPlanner(ToolRegistry.default(), SkillResolver([]),
                               allow_multi_agent=True, minimal_skills=False)
    artifact = GoalAnalysis("Record artifact report.md", ["documentation"],
                            complexity=Complexity.TRIVIAL, read_only=True)
    approval = GoalAnalysis("Approve production deployment", ["deployment"],
                            complexity=Complexity.COMPLEX, risk=Risk.HIGH, read_only=True,
                            approval_gates=["deployment"])
    parallel = GoalAnalysis("research and compare", ["research", "comparison", "review"],
                            complexity=Complexity.COMPLEX, read_only=True)
    dag = GoalAnalysis("design and implement", ["design", "coding"],
                       complexity=Complexity.COMPLEX, read_only=False)
    assert planner.plan(artifact.goal, artifact).strategy is ExecutionStrategy.ARTIFACT_ONLY
    assert planner.plan(approval.goal, approval).strategy is ExecutionStrategy.HUMAN_APPROVAL
    assert planner.plan(parallel.goal, parallel).strategy is ExecutionStrategy.MULTI_AGENT_PARALLEL
    assert planner.plan(dag.goal, dag).strategy is ExecutionStrategy.MULTI_AGENT_DAG


def test_skill_resolver_matches_equivalent_capability_and_explains_cost():
    compact = SkillManifest("adaptive-layout", "1.0.0", "compact", ["responsive_layout"],
                            trust=SkillTrust.TRUSTED, estimated_context_tokens=12000)
    huge = SkillManifest("responsive-suite", "1.0.0", "huge", ["responsive_design"],
                         trust=SkillTrust.TRUSTED, estimated_context_tokens=80000)
    candidates = SkillResolver([huge, compact]).candidates(["responsive_design"], minimize_cost=True)
    assert candidates[0].manifest.id == "adaptive-layout"
    assert candidates[0].matched == ["responsive_design"]
    assert any("context cost" in reason for reason in candidates[0].reasons)


def test_progressive_loading_excludes_unrequested_references(tmp_path):
    path = _package(tmp_path)
    registry = SkillRegistry()
    registry.discover_directory(tmp_path, SkillTrust.PROJECT_LOCAL)
    metadata_chars = len(json.dumps(registry.manifest("responsive-dashboard").to_dict()))
    loaded = registry.load_selected("responsive-dashboard", ["ref-2"])
    all_chars = sum(item.stat().st_size for item in path.rglob("*.md"))
    assert list(loaded.references) == ["ref-2"]
    assert "reference 2" in loaded.to_context()
    assert "reference 1" not in loaded.to_context()
    assert loaded.context_chars < all_chars
    assert metadata_chars < all_chars


def test_offline_context_benchmark_is_reproducible(tmp_path):
    result = measure(tmp_path)
    assert result == {
        "eager_chars": 20101,
        "progressive_chars": 3174,
        "saved_chars": 16927,
        "reduction_percent": 84.21,
        "eager_estimated_tokens": 5026,
        "progressive_estimated_tokens": 794,
        "ai_invocations": 0,
    }


def test_skill_dependency_cycle_is_rejected():
    registry = SkillRegistry()
    registry.register_manifest(SkillManifest("a", capabilities=["a"], dependencies=["b"]))
    registry.register_manifest(SkillManifest("b", capabilities=["b"], dependencies=["a"]))
    result = registry.validate("a")
    assert result["valid"] is False
    assert "cycle" in result["errors"][0]


def test_temporary_skill_is_specification_first_and_not_trusted(tmp_path):
    specification = SkillSpecification(
        "qnn-w8a8-validation", "qnn_w8a8_validation", "Validate quantized model contracts.",
        inputs={"model": "path"}, outputs={"report": "markdown"},
        procedure=["Inspect tensor dtypes.", "Run bounded runtime validation."],
        evaluation=["tensor_dtype", "runtime_execution"])
    manifest = TemporarySkillSynthesizer().synthesize(specification, tmp_path)
    assert manifest.status is SkillStatus.TEMPORARY
    assert manifest.trust is SkillTrust.REVIEW_REQUIRED
    assert SkillPackageValidator().validate_text(
        manifest, (manifest.path / "SKILL.md").read_text(encoding="utf-8")).valid


def test_unsafe_generated_skill_is_blocked():
    manifest = SkillManifest("unsafe", capabilities=["cleanup"],
                             trust=SkillTrust.UNVERIFIED, security={"scripts": True})
    result = SkillPackageValidator().validate_text(manifest, "Run rm -rf / to clean everything")
    assert result.valid is False
    assert result.trust is SkillTrust.BLOCKED


def test_three_validated_uses_only_create_promotion_candidate(tmp_path):
    db = Database(tmp_path / "quality.db")
    store = SkillQualityStore(db)
    for index in range(3):
        store.record("temporary-skill", "0.1.0", f"RUN-{index}", f"TASK-{index}",
                     True, 1.0, 1, 10, "measured", 25, "mock", "mock-small")
    quality = store.get("temporary-skill", "0.1.0")
    assert quality.promotion_candidate is True
    assert quality.reliability == 100
    assert quality.history_status == "SUFFICIENT"


def test_third_qualified_scheduler_use_emits_promotion_candidate(tmp_path):
    db = Database(tmp_path / "promotion-event.db")
    bus = EventBus(db)
    scheduler = Scheduler(db, bus, MockProvider(delay=0))
    task = Task("TASK", "RUN", "work", "worker", metadata={"provider": "mock"})
    skill = LoadedSkill(SkillManifest(
        "temporary-skill", "0.1.0", capabilities=["analysis"],
        trust=SkillTrust.REVIEW_REQUIRED, status=SkillStatus.TEMPORARY), "procedure")
    for _ in range(3):
        scheduler._record_skill_quality(
            task,
            Receipt("TASK", "worker", "completed", "done", provider="mock", model="mock-small",
                    token_usage={"input": 5, "output": 5, "source": "measured",
                                 "invocation_count": 1}),
            [skill],
        )
    events = db.query("SELECT event,metadata_json FROM events WHERE event='skill_promotion_candidate'")
    assert len(events) == 1
    assert json.loads(events[0]["metadata_json"])["version"] == "0.1.0"


def test_artifact_failure_overrides_agent_done_status(tmp_path):
    db = Database(tmp_path / "artifact.db")
    task = Task("TASK", "RUN", "produce required artifact", "builder",
                metadata={"required_artifacts": ["result.txt"],
                          "working_directory": str(tmp_path), "provider": "mock"})
    db.execute("INSERT INTO runs(id,goal,status) VALUES('RUN','goal','running')")
    db.execute("INSERT INTO tasks(id,run_id,title,owner,status,priority,data_json) VALUES(?,?,?,?,?,?,?)",
               (task.id, task.run_id, task.title, task.owner, task.status.value, task.priority,
                db.json(task.to_dict())))
    success = asyncio.run(Scheduler(db, EventBus(db), MockProvider(delay=0),
                                    max_escalations=0).run(TaskGraph([task])))
    assert success is False
    evaluation = db.query("SELECT passed,quality_json FROM artifact_evaluations")[0]
    assert evaluation["passed"] == 0
    assert "missing artifact" in evaluation["quality_json"]


def test_declared_artifact_evaluator_accepts_real_evidence(tmp_path):
    (tmp_path / "report.md").write_text("# Findings\n", encoding="utf-8")
    task = Task("T", "R", "report", "writer",
                metadata={"required_artifacts": ["report.md"], "required_sections": ["Findings"]})
    result = DeclaredArtifactEvaluator().evaluate(
        task, Receipt("T", "writer", "completed", "Findings are documented."), tmp_path)
    assert result.passed is True
    assert result.deterministic_validation is True


def test_skill_intelligence_cli_is_available(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["skill", "validate", "w8a8-validation"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert main(["skill", "candidates", "w8a8 validation"]) == 0
    candidates = json.loads(capsys.readouterr().out)
    assert candidates[0]["skill"] == "w8a8-validation"
