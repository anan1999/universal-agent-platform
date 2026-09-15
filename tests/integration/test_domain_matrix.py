"""Cross-domain orchestration.

The architectural claim being tested is that the core reasons in capabilities, so
a goal from a domain nobody anticipated still produces a valid plan. Everything
here plans or runs against the mock provider and consumes zero real AI quota.
"""

import pytest

from adaptive_agent.cli import _dry_run, _run_goal, _run_summary
from adaptive_agent.core.capabilities import Complexity, Risk
from adaptive_agent.runtime import database


@pytest.fixture
def project(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _agents(plan):
    return [task for task in plan["tasks"] if task["kind"] == "agent"]


def _kinds(plan):
    return {task["kind"] for task in plan["tasks"]}


# -- Scenario A: software engineering ---------------------------------------

def test_software_goal_uses_software_capabilities_and_a_deterministic_test(project):
    plan = _dry_run("Fix a Python bug in the configuration loader", "mock")
    assert "software-engineering" in plan["analysis"]["profiles"]
    assert "bug_fix" in plan["analysis"]["capabilities"]
    assert len(_agents(plan)) <= 3, "a bug fix does not need a large team"
    tools = [task for task in plan["tasks"] if task["kind"] == "tool"]
    assert any("test" in task["agent"] for task in tools), "software work should be verified"


# -- Scenario B: AI engineering ---------------------------------------------

def test_ai_goal_selects_a_performance_role_and_a_benchmark(project):
    plan = _dry_run("Benchmark INT8 model latency on the edge device", "mock")
    assert "ai-engineering" in plan["analysis"]["profiles"]
    assert "benchmarking" in plan["analysis"]["capabilities"]
    roles = {task["agent"] for task in _agents(plan)}
    assert any("analyst" in role or "engineer" in role for role in roles)
    assert any("benchmark" in task["agent"] for task in plan["tasks"] if task["kind"] == "tool")


def test_ai_goal_does_not_pull_qnn_into_the_core(project):
    """QNN is a skill, never a core concept."""
    plan = _dry_run("Quantize the QNN model to INT8 and measure accuracy", "mock")
    assert "ai-engineering" in plan["analysis"]["profiles"]
    assert "quantization" in plan["analysis"]["capabilities"]


# -- Scenario C: UI/UX -------------------------------------------------------

def test_uiux_goal_assumes_neither_pytest_nor_source_code(project):
    plan = _dry_run("Redesign the settings page for better usability", "mock")
    assert "uiux" in plan["analysis"]["profiles"]
    tool_ids = {task["agent"] for task in plan["tasks"] if task["kind"] == "tool"}
    assert "project_test" not in tool_ids, "design work must not imply a unit test run"
    assert not any(task["artifact_type"] == "source_code" for task in _agents(plan))


def test_uiux_goal_in_a_python_repo_does_not_run_the_test_suite(project):
    """A Python repo activates software-engineering; a design goal must not inherit pytest."""
    (project / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")
    plan = _dry_run("Redesign the settings page for better usability", "mock")
    assert "software-engineering" in plan["analysis"]["profiles"], "the repo is Python"
    tool_ids = {task["agent"] for task in plan["tasks"] if task["kind"] == "tool"}
    assert "project_test" not in tool_ids and "project_build" not in tool_ids
    assert any("did not draw on" in line for line in plan["team"]["rationale"]), \
        "skipping a profile's evaluation must be explained"


def test_accessibility_work_selects_a_reviewing_role(project):
    plan = _dry_run("Audit the checkout flow for accessibility and keyboard navigation", "mock")
    assert "accessibility" in plan["analysis"]["capabilities"]
    assert any("accessibility" in task["agent"] for task in _agents(plan))


@pytest.mark.parametrize(("goal", "profiles", "expected_role"), [
    ("Create the responsive medication-planner prototype described by the local requirements.",
     ["uiux"], "ui_designer"),
    ("Create the standalone vector event poster described by the local brief.",
     ["design"], "visual_designer"),
    ("Create the valid Wavefront 3D model described by the local brief.",
     ["design"], "visual_designer"),
])
def test_concrete_design_asset_selects_a_producing_role(project, goal, profiles, expected_role):
    plan = _dry_run(goal, "mock", profiles=profiles)
    agents = _agents(plan)
    assert agents[0]["agent"] == expected_role
    assert agents[0]["artifact_type"] == "design_asset"
    assert plan["analysis"]["read_only"] is False


def test_design_follow_up_inherits_active_profile_without_repeating_domain_words(project):
    plan = _dry_run(
        "Extend the kiosk with a distinct keypad group and preserve the existing bounds.",
        "mock", profiles=["design"])
    assert plan["analysis"]["inferred"] is True
    assert _agents(plan)[0]["agent"] == "visual_designer"
    assert any("explicitly active" in line for line in plan["analysis"]["evidence"])


def test_explicit_design_profile_wins_cross_profile_capability_tie(project):
    plan = _dry_run(
        "Extend the existing poster while preserving its hierarchy and original layers.",
        "mock", profiles=["design"])
    assert _agents(plan)[0]["agent"] == "visual_designer"


# -- Scenario D: product -----------------------------------------------------

def test_product_goal_produces_a_document_not_code(project):
    plan = _dry_run("Create feature requirements for a billing dashboard", "mock")
    assert "product" in plan["analysis"]["profiles"]
    assert "requirements" in plan["analysis"]["capabilities"]
    artifacts = {task["artifact_type"] for task in _agents(plan)}
    assert artifacts and "source_code" not in artifacts


# -- Scenario E: unknown domain ---------------------------------------------

def test_unknown_domain_composes_a_team_instead_of_failing(project):
    plan = _dry_run("Plan an interior lighting redesign for a small studio apartment", "mock")
    assert _agents(plan), "an unrecognized domain must still produce work"
    assert plan["team"]["members"], "an unrecognized domain must still produce a team"
    assert plan["mode"] == "universal"


def test_wholly_unknown_goal_falls_back_to_general_capabilities(project):
    plan = _dry_run("Choose the flower centerpieces for a wedding reception", "mock")
    assert plan["analysis"]["inferred"] is True, "no keyword should match this goal"
    assert plan["analysis"]["profiles"] == ["general"]
    assert plan["analysis"]["capabilities"], "fallback must still yield capabilities"
    assert _agents(plan)


def test_profile_detection_requires_whole_words(project):
    """Substring matching made "ci" fire on "de-ci-de"; detection steers the team."""
    plan = _dry_run("Decide what to cook for dinner on Saturday", "mock")
    assert "devops" not in plan["analysis"]["profiles"]


def test_unknown_domain_executes_end_to_end(project):
    run_id, status, _ = _run_goal("Plan an interior lighting redesign for a studio", "mock", delay=0)
    assert status == "completed"
    summary = _run_summary(database(), run_id)
    assert summary["team"], "the run must record why this team was chosen"


# -- Dynamic DAG depth -------------------------------------------------------

def test_trivial_work_gets_one_agent_and_no_evaluation(project):
    plan = _dry_run("Fix typo in the footer label", "mock")
    assert plan["analysis"]["complexity"] == Complexity.TRIVIAL.value
    assert len(_agents(plan)) == 1
    assert "tool" not in _kinds(plan), "trivial work does not justify an evaluation step"


def test_critical_work_adds_review_and_a_human_gate(project):
    plan = _dry_run("Deploy the service to the production cluster", "mock")
    assert plan["analysis"]["risk"] == Risk.HIGH.value
    assert "approval" in _kinds(plan), "a deployment must pass a human gate"
    assert any(task["agent"].endswith("reviewer") for task in _agents(plan))


def test_team_size_grows_with_complexity(project):
    trivial = len(_agents(_dry_run("Fix typo in the footer label", "mock")))
    critical = len(_agents(_dry_run("Deploy the service to the production cluster", "mock")))
    assert trivial < critical


# -- Read-only intent --------------------------------------------------------

def test_read_only_goal_selects_no_modifying_role_and_no_gate(project):
    plan = _dry_run("Locate the config loader. Do not modify anything.", "mock")
    assert plan["analysis"]["read_only"] is True
    assert "approval" not in _kinds(plan)
    assert not any(task["artifact_type"] == "source_code" for task in _agents(plan))


# -- Multi-profile projects --------------------------------------------------

def test_multiple_profiles_do_not_activate_every_role(project):
    """Profiles offer candidates; the goal decides which are used."""
    plan = _dry_run("Write the API reference documentation", "mock",
                    profiles=["software-engineering", "ai-engineering", "uiux",
                              "product", "technical-writing"])
    assert len(plan["analysis"]["profiles"]) >= 5
    assert len(_agents(plan)) <= 4, "five profiles must not mean five teams"
    assert plan["team"]["omitted"], "unused candidate roles must be explained"


def test_typo_with_four_active_profiles_still_uses_one_agent(project):
    plan = _dry_run("Fix a typo in API documentation.", "mock",
                    profiles=["product", "uiux", "software-engineering", "ai-engineering"])
    assert len(_agents(plan)) == 1
    assert len(plan["analysis"]["profiles"]) >= 4
    assert plan["team"]["omitted"], "profile roles are candidates, not an automatic fan-out"


# -- Routing is capability-first --------------------------------------------

def test_routing_is_explained_by_capability_not_by_role_name(project):
    plan = _dry_run("Redesign the settings page for better usability", "mock")
    for task in _agents(plan):
        assert task["model"], "every agent task must resolve to a model"
        assert task["reason"], "every routing decision must be explained"
        assert "always uses" not in task["reason"].lower()


def test_every_goal_records_why_the_team_was_chosen(project):
    for goal in ("Fix a Python bug in the loader",
                 "Redesign the settings page",
                 "Plan an interior lighting redesign"):
        plan = _dry_run(goal, "mock")
        assert plan["team"]["rationale"], f"no rationale recorded for {goal!r}"
        assert plan["team"]["capability_signature"]
