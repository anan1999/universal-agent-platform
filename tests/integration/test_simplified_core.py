import json
import time
from pathlib import Path
from types import SimpleNamespace

from adaptive_agent.core.capabilities import Complexity
from adaptive_agent.core.execution_planner import ExecutionPlanner, ExecutionStrategy
from adaptive_agent.core.goal_analyzer import GoalAnalyzer
from adaptive_agent.core.goal_analyzer import GoalAnalysis
from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.core.tools import ToolRegistry
from adaptive_agent.intelligence.project import IntelligenceItem, ProjectIntelligenceStore
from adaptive_agent.project.adapter import initialize_project
from adaptive_agent.project.context_index import INDEX_MAX_BYTES, INDEX_TARGET_BYTES, ProjectContextIndex
from adaptive_agent.providers.mock import MockProvider
from adaptive_agent.skills.manifest import SkillManifest, SkillTrust
from adaptive_agent.skills.resolver import SkillResolver
from adaptive_agent.storage.database import Database
from scripts import context_cache_benchmark


def _fixture(root: Path) -> None:
    (root / "app").mkdir()
    (root / "frontend" / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname='expense-app'\ndependencies=['fastapi']\n", encoding="utf-8")
    (root / "package.json").write_text(
        '{"scripts":{"build":"vite build"},"dependencies":{"react":"latest"}}', encoding="utf-8")
    (root / "README.md").write_text("# Expense App\nFastAPI, React and SQLite.\n", encoding="utf-8")
    (root / "app" / "main.py").write_text(
        "from fastapi import FastAPI\nimport sqlite3\napp = FastAPI()\n", encoding="utf-8")
    (root / "frontend" / "src" / "App.jsx").write_text("export function App() {}\n", encoding="utf-8")
    (root / "tests" / "test_api.py").write_text("def test_api(): assert True\n", encoding="utf-8")


def _templates(root: Path) -> Path:
    templates = root / "templates"
    templates.mkdir()
    (templates / "capabilities.yaml").write_text("capabilities: {}\n", encoding="utf-8")
    return templates


def test_init_writes_compact_project_index_with_targeted_discovery(tmp_path):
    _fixture(tmp_path)
    initialize_project(tmp_path, _templates(tmp_path))
    path = tmp_path / ".agent" / "project-index.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert path.stat().st_size <= INDEX_TARGET_BYTES
    assert path.stat().st_size <= INDEX_MAX_BYTES
    assert value["architecture"] == {
        "backend": "FastAPI", "frontend": "React", "database": "SQLite"}
    assert value["important_paths"]["backend"] == "app/"
    assert value["important_paths"]["frontend"] == "frontend/"
    assert set(value["discovery"]["files_inspected"]) >= {"README.md", "pyproject.toml", "package.json"}


def test_index_updates_only_for_allowlisted_stable_changes(tmp_path):
    _fixture(tmp_path)
    store = ProjectContextIndex(tmp_path)
    store.initialize()
    before = store.path.read_text(encoding="utf-8")
    assert store.update_stable({"routine_files_changed": ["app/main.py"]}) is False
    assert store.path.read_text(encoding="utf-8") == before
    assert store.update_stable({"constraints": ["Expense dates use ISO-8601 strings"]}) is True
    assert "Expense dates use ISO-8601 strings" in store.load()["constraints"]


def test_file_cache_is_incremental_and_hash_invalidated(tmp_path):
    _fixture(tmp_path)
    store = ProjectContextIndex(tmp_path)
    store.initialize()
    assert store.cache.entries() == []
    entry = store.cache.remember("app/main.py")
    assert entry and entry["summary"].startswith("main.py:") and len(entry["summary"]) <= 320
    assert store.cache.valid("app/main.py")["hash"] == entry["hash"]
    (tmp_path / "app" / "main.py").write_text("def changed(): pass\n", encoding="utf-8")
    assert store.cache.valid("app/main.py") is None
    assert store.cache.entries() == []


def test_relevant_path_selection_does_not_preload_unrelated_areas(tmp_path):
    _fixture(tmp_path)
    context = ProjectContextIndex(tmp_path).select("Modify the backend monthly summary API")
    assert context.pre_task_ai_calls == 0
    assert "app/" in context.relevant_paths
    assert "frontend/" not in context.relevant_paths
    assert "tests/" not in context.relevant_paths


def test_minimal_skill_resolver_uses_real_procedure_and_skips_generic_label(tmp_path):
    generic = SkillManifest("python-expert", description="Python expert", capabilities=["python"],
                            trust=SkillTrust.TRUSTED)
    package = tmp_path / "api-validation"
    package.mkdir()
    (package / "SKILL.md").write_text("# Validate API\nRun the project contract.\n", encoding="utf-8")
    procedure = SkillManifest("api-validation", description="Project API validation workflow",
                              capabilities=["python"], trust=SkillTrust.PROJECT_LOCAL,
                              estimated_context_tokens=40, path=package)
    selected, rejected = SkillResolver([generic, procedure]).select(["python"], minimal=True)
    assert [item.manifest.id for item in selected] == ["api-validation"]
    assert selected[0].decision == "USE"
    assert next(item for item in rejected if item.manifest.id == "python-expert").decision == "SKIP"


def test_default_planner_is_single_agent_and_does_not_synthesize_skills():
    analysis = GoalAnalysis("Design and implement a novel workflow",
                            ["design", "coding", "novel_capability"],
                            complexity=Complexity.COMPLEX, read_only=False)
    plan = ExecutionPlanner(ToolRegistry.default(), SkillResolver([])).plan(analysis.goal, analysis)
    assert plan.strategy is ExecutionStrategy.SINGLE_AGENT_WITH_TOOLS
    assert plan.ai_agents == 1
    assert plan.expected_handoffs == 0
    assert plan.temporary_skills == []

    experimental = ExecutionPlanner(
        ToolRegistry.default(), SkillResolver([]), allow_skill_synthesis=True,
        allow_multi_agent=True, minimal_skills=False).plan(analysis.goal, analysis)
    assert experimental.strategy is ExecutionStrategy.MULTI_AGENT_DAG
    assert experimental.temporary_skills


def test_endpoint_follow_up_routes_to_coding_and_testing_capabilities():
    analysis = GoalAnalyzer().analyze(
        "Add a GET /reports/monthly/{month} endpoint and validate the work")
    assert {"coding", "testing"} <= set(analysis.capabilities)


def test_dashboard_follow_up_routes_to_implementation_instead_of_documentation(tmp_path):
    _fixture(tmp_path)
    initialize_project(tmp_path, _templates(tmp_path))
    goal = ("Add a dashboard month input that calls /reports/monthly/{month} and renders "
            "the returned total and by_category breakdown, with deterministic tests.")
    composition = Orchestrator(Database(tmp_path / "route.db"), MockProvider(delay=0),
                               active_profiles=["software-engineering"]).compose(
        "RUN-DASHBOARD", goal, str(tmp_path), "expense")

    assert {"coding", "testing"} <= set(composition.analysis.capabilities)
    assert composition.analysis.inferred is False
    assert [member.role_id for member in composition.team.members] == ["developer"]


def test_benchmark_follow_up_selects_developer_not_generic_analyst(tmp_path):
    _fixture(tmp_path)
    initialize_project(tmp_path, _templates(tmp_path))
    composition = Orchestrator(Database(tmp_path / "route.db"), MockProvider(delay=0)).compose(
        "RUN-ROUTE", context_cache_benchmark.GOAL, str(tmp_path), "expense")
    assert [member.role_id for member in composition.team.members] == ["developer"]


def test_fresh_orchestrator_uses_index_with_zero_pre_task_ai_calls(tmp_path):
    _fixture(tmp_path)
    initialize_project(tmp_path, _templates(tmp_path))
    first = Orchestrator(Database(tmp_path / "first.db"), MockProvider(delay=0))
    initial = first.compose("RUN-1", "Inspect the expense project", str(tmp_path), "expense")
    assert initial.project_intelligence["pre_task_ai_calls"] == 0
    assert len(initial.team.members) == 1
    index_before = (tmp_path / ".agent" / "project-index.json").read_text(encoding="utf-8")

    # A genuinely fresh process-equivalent object receives no prior chat or
    # provider state and still routes directly to the backend.
    fresh = Orchestrator(Database(tmp_path / "fresh.db"), MockProvider(delay=0))
    resumed = fresh.compose("RUN-2", "Modify the backend monthly summary API",
                            str(tmp_path), "expense")
    assert resumed.project_intelligence["pre_task_ai_calls"] == 0
    assert resumed.project_intelligence["relevant_paths"] == ["app/"]
    assert all(task.metadata["suggested_paths"] == ["app/"] for task in resumed.graph.tasks.values())
    assert all(task.metadata["allowed_scope"] == [] for task in resumed.graph.tasks.values())
    assert (tmp_path / ".agent" / "project-index.json").read_text(encoding="utf-8") == index_before


def test_existing_v231_intelligence_remains_readable_but_not_in_default_context(tmp_path):
    _fixture(tmp_path)
    initialize_project(tmp_path, _templates(tmp_path))
    legacy = ProjectIntelligenceStore(tmp_path)
    legacy.add(IntelligenceItem("old-fact", "knowledge", "Legacy fact",
                                evidence=["existing V2.3.1 state"]))
    assert legacy.items()[0].summary == "Legacy fact"
    composition = Orchestrator(Database(tmp_path / "db.sqlite"), MockProvider(delay=0)).compose(
        "RUN", "Modify the backend API", str(tmp_path), "expense")
    assert composition.project_intelligence["items"] == []


def test_index_status_reports_budget_and_cache(tmp_path):
    _fixture(tmp_path)
    status = ProjectContextIndex(tmp_path).status()
    assert status["within_target"] is True
    assert status["within_maximum"] is True
    assert status["cached_relevant_files"] == 0


def test_context_cache_benchmark_dry_run_is_one_pair_and_quota_free(tmp_path):
    args = SimpleNamespace(workspace=tmp_path / "pair", output=tmp_path / "dry.json")
    result = context_cache_benchmark.dry_run(args)
    assert result["ready"] is True
    assert result["provider_calls"] == 0
    assert result["pre_task_ai_calls"] == 0
    assert set(result["relevant_paths"]) >= {"app/", "frontend/"}
    assert result["same_uap_execution_path"] is True
    assert result["only_variable"] == "reusable_context_enabled"
    assert result["disabled"]["reusable_context_enabled"] is False
    assert result["enabled"]["reusable_context_enabled"] is True
    assert result["asset_creation"]["ai_invocations"] == 0
    assert context_cache_benchmark.acceptance(
        tmp_path / "pair" / "runs" / "large" / "disabled")["passed"] is False


def test_context_cache_scale_suite_reuses_prepared_fixture_and_is_quota_free(tmp_path):
    args = SimpleNamespace(workspace=tmp_path / "suite", output=tmp_path / "first.json", task="all")
    first = context_cache_benchmark.dry_run(args)
    args.output = tmp_path / "second.json"
    second = context_cache_benchmark.dry_run(args)
    assert [row["task_id"] for row in first["tasks"]] == ["small", "medium", "large"]
    assert [row["scale"] for row in first["tasks"]] == [1, 2, 3]
    assert all(row["ready"] for row in first["tasks"])
    assert first["provider_calls"] == second["provider_calls"] == 0
    assert first["prepared_fixture"]["reused"] is False
    assert second["prepared_fixture"]["reused"] is True
    assert len({row["source_hash"] for row in first["tasks"]}) == 1


def test_context_cache_keeps_shared_benchmark_task_constructor(tmp_path):
    built = context_cache_benchmark.task(tmp_path, "model-x", "low", "Small goal")
    assert built.title == "Small goal"
    assert built.metadata["working_directory"] == str(tmp_path)
    assert built.metadata["model"] == "model-x"


def test_small_acceptance_allows_semantically_equivalent_wire_keys(tmp_path):
    variants = [
        ("count", "total"),
        ("expense_count", "total_spending"),
    ]
    for index, (count_key, total_key) in enumerate(variants):
        project = tmp_path / f"variant-{index}"
        context_cache_benchmark.seed(project)
        source = project / "app" / "main.py"
        source.write_text(source.read_text(encoding="utf-8") + f'''\n\n@app.get("/reports/summary")
def report_summary():
    with connect() as database:
        row = database.execute("SELECT COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total FROM expenses").fetchone()
    return {{"{count_key}": row["count"], "{total_key}": row["total"]}}
''', encoding="utf-8")
        assert context_cache_benchmark.acceptance(project, "small")["passed"] is True
