import json
import sqlite3
import time
from pathlib import Path

from adaptive_agent.cli import _adaptive_budget_mode, _budget_analysis, main, parser
from adaptive_agent.core.capabilities import Complexity
from adaptive_agent.core.goal_analyzer import GoalAnalysis
from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.project.adaptive_budget import (
    AdaptiveToolBudgetStore,
    BudgetObservation,
)
from adaptive_agent.providers.codex.provider import CodexEventBudget, CodexProvider
from adaptive_agent.providers.mock import MockProvider
from adaptive_agent.storage.database import Database


FAMILIES = {
    "software": (["coding"], ["source_code"], ["software-engineering"]),
    "research": (["research"], ["research_report"], ["research"]),
    "product": (["product"], ["product_requirements"], ["product-management"]),
    "ui_ux": (["design"], ["prototype"], ["design"]),
    "graphic_design": (["design"], ["poster"], ["design"]),
    "three_d": (["design"], ["3d_model"], ["design"]),
}

DOMAIN_ARTIFACT_SCENARIOS = (
    ("software", "source_code"),
    ("software", "test_result"),
    ("research", "research_report"),
    ("research", "research_summary"),
    ("product", "product_requirements"),
    ("product", "roadmap"),
    ("ui_ux", "prototype"),
    ("ui_ux", "wireframe"),
    ("graphic_design", "poster"),
    ("graphic_design", "brand"),
    ("three_d", "3d_model"),
    ("three_d", "3d_scene"),
)


def analysis(family="software", complexity=Complexity.NORMAL):
    capabilities, artifacts, profiles = FAMILIES[family]
    return GoalAnalysis(
        f"{family} task", capabilities=list(capabilities), artifact_types=list(artifacts),
        profiles=list(profiles), complexity=complexity)


def scenario_analysis(family, artifact):
    capabilities, _, profiles = FAMILIES[family]
    return GoalAnalysis(
        f"{family} {artifact} task", capabilities=list(capabilities),
        artifact_types=[artifact], profiles=list(profiles), complexity=Complexity.NORMAL)


def initialized(root: Path) -> AdaptiveToolBudgetStore:
    (root / ".agent").mkdir()
    (root / ".agent/commands.yaml").write_text("commands: {}\n", encoding="utf-8")
    (root / "project.txt").write_text("stable input\n", encoding="utf-8")
    return AdaptiveToolBudgetStore(root)


def observation(current, pair, mode, *, run=None, provider="codex", model="model-a",
                reasoning="low", accepted="pass", tools=None, input_tokens=None,
                cached=200, output=100, seconds=None, measured="measured", synthetic=False,
                task_signature=None, input_signature=None):
    normal = mode == "normal"
    return BudgetObservation(
        run_id=run or f"run-{pair}-{mode}", task_id=f"task-{pair}-{mode}",
        experiment_pair_id=pair,
        task_family=AdaptiveToolBudgetStore.task_family(current),
        artifact_type=AdaptiveToolBudgetStore.artifact_type(current),
        complexity=current.complexity.value, provider=provider, resolved_model=model,
        reasoning_setting=reasoning, budget_mode=mode,
        effective_tool_call_limit=8 if normal else 6,
        observed_provider_tool_calls=(5 if normal else 4) if tools is None else tools,
        provider_status="completed", acceptance_status=accepted,
        acceptance_contract_version="contract-v1",
        input_tokens=(900 if normal else 750) if input_tokens is None else input_tokens,
        cached_input_tokens=cached,
        uncached_input_tokens=((900 if normal else 750) if input_tokens is None else input_tokens) - cached,
        output_tokens=output, duration_seconds=(10 if normal else 8) if seconds is None else seconds,
        measurement_source=measured, is_synthetic=synthetic,
        task_signature=task_signature or f"sig-{pair}",
        input_signature=input_signature or f"input-{pair}", created_at=time.time())


def add_pair(store, current, number, **changes):
    pair = f"pair-{number}"
    for mode in ("normal", "reduced"):
        values = dict(changes.get(mode, {}))
        assert store.record_observation(observation(current, pair, mode, **values))


def decide(store, current=None, **overrides):
    values = {"requested_mode": "auto", "provider": "codex", "resolved_model": "model-a",
              "reasoning_setting": "low", "current_normal_limit": 8, "enforcement": "hard"}
    values.update(overrides)
    return store.decide(current or analysis(), **values)


def test_feature_is_opt_in_and_legacy_flag_maps_to_auto(tmp_path):
    normal = parser().parse_args(["run", "Build an API", "--dry-run"])
    auto = parser().parse_args(["run", "Build an API", "--dry-run", "--budget", "auto"])
    legacy = parser().parse_args([
        "run", "Build an API", "--dry-run", "--adaptive-provider-tool-budget"])
    assert _adaptive_budget_mode(normal) is None
    assert _adaptive_budget_mode(auto) == "auto"
    assert _adaptive_budget_mode(legacy) == "auto"
    orchestrator = Orchestrator(Database(tmp_path / "db.sqlite"), MockProvider(delay=0))
    assert orchestrator.adaptive_tool_budget is False


def test_auto_without_history_or_with_one_pair_stays_normal(tmp_path):
    store = initialized(tmp_path)
    assert decide(store).selected_mode == "normal"
    add_pair(store, analysis(), 1)
    decision = decide(store)
    assert decision.selected_mode == "normal"
    assert decision.comparable_pairs == 1
    assert decision.reasons == ("insufficient_comparable_history",)


def test_two_comparable_quality_pairs_select_reduced(tmp_path):
    store = initialized(tmp_path)
    for number in (1, 2):
        add_pair(store, analysis(), number)
    decision = decide(store)
    assert decision.selected_mode == "reduced"
    assert decision.effective_limit == 6
    assert decision.evidence_ids == ("pair-2", "pair-1")
    assert "quality_checks_passed" in decision.reasons


def test_total_tokens_down_but_uncached_up_35_percent_stays_normal(tmp_path):
    store = initialized(tmp_path)
    for number in (1, 2):
        add_pair(store, analysis(), number,
                 normal={"input_tokens": 1000, "cached": 400, "output": 100},
                 reduced={"input_tokens": 900, "cached": 55, "output": 100})
    decision = decide(store)
    assert decision.selected_mode == "normal"
    assert decision.reasons == ("uncached_regression_guard_failed",)


def test_recent_reduced_quality_failure_forces_normal(tmp_path):
    store = initialized(tmp_path)
    for number in (1, 2):
        add_pair(store, analysis(), number)
    assert store.record_observation(observation(
        analysis(), "pair-failed", "reduced", accepted="fail"))
    decision = decide(store)
    assert decision.selected_mode == "normal"
    assert decision.reasons[0] == "recent_reduced_quality_failure"


def test_complex_or_unknown_task_metadata_stays_normal(tmp_path):
    store = initialized(tmp_path)
    assert decide(store, analysis(complexity=Complexity.COMPLEX)).reasons == (
        "complexity_not_eligible",)
    unknown = GoalAnalysis("unknown", artifact_types=["unknown"])
    assert decide(store, unknown).reasons == ("task_metadata_unknown",)


def test_provider_model_reasoning_are_isolated(tmp_path):
    store = initialized(tmp_path)
    for number in (1, 2):
        add_pair(store, analysis(), number)
    assert decide(store, provider="other").comparable_pairs == 0
    assert decide(store, resolved_model="model-b").comparable_pairs == 0
    assert decide(store, reasoning_setting="high").comparable_pairs == 0


def test_unknown_settings_usage_or_acceptance_do_not_form_pairs(tmp_path):
    store = initialized(tmp_path)
    for number in (1, 2):
        pair = f"bad-{number}"
        store.record_observation(observation(analysis(), pair, "normal"))
        store.record_observation(observation(
            analysis(), pair, "reduced", accepted="not_run", measured="unavailable",
            input_tokens=None, tools=None))
    assert decide(store).comparable_pairs == 0
    assert decide(store, resolved_model=None).reasons == ("execution_settings_unknown",)


def test_synthetic_mock_history_never_drives_auto(tmp_path):
    store = initialized(tmp_path)
    for number in (1, 2):
        add_pair(store, analysis(), number,
                 normal={"synthetic": True}, reduced={"synthetic": True})
    assert decide(store).comparable_pairs == 0


def test_duplicate_pair_and_completion_replay_are_idempotent(tmp_path):
    store = initialized(tmp_path)
    item = observation(analysis(), "pair-1", "normal")
    assert store.record_observation(item)
    assert not store.record_observation(item)
    replay = observation(analysis(), "pair-1", "normal", run="different-run")
    assert not store.record_observation(replay)
    rows = store.status()
    assert rows[0]["observations"] == 1
    assert rows[0]["pairs"] == 1


def test_explicit_modes_and_smaller_user_limit_are_preserved(tmp_path):
    store = initialized(tmp_path)
    normal = decide(store, requested_mode="normal")
    assert normal.selected_mode == "normal" and normal.decision_source == "user_override"
    reduced = decide(store, requested_mode="reduced")
    assert reduced.selected_mode == "reduced" and reduced.effective_limit == 6
    capped = decide(store, requested_mode="reduced", current_normal_limit=4)
    assert capped.effective_limit == 4
    assert capped.reasons == ("normal_limit_already_six_or_less",)
    already_six = decide(store, current_normal_limit=6)
    assert already_six.selected_mode == "normal"


def test_policy_exception_and_unsupported_enforcement_fail_to_normal(tmp_path, monkeypatch):
    store = initialized(tmp_path)
    monkeypatch.setattr(store, "_matching_rows", lambda *args: (_ for _ in ()).throw(sqlite3.Error()))
    assert decide(store).reasons == ("policy_evidence_error",)
    assert decide(store, enforcement="unsupported").reasons == ("provider_budget_unsupported",)
    assert decide(store, enforcement="soft_guidance").reasons == (
        "provider_budget_soft_guidance",)
    assert MockProvider.provider_tool_budget_enforcement == "unsupported"
    assert CodexProvider.provider_tool_budget_enforcement == "hard"


def test_codex_hard_monitor_stops_before_seventh_tool():
    monitor = CodexEventBudget(max_tool_calls=6)
    for number in range(6):
        assert monitor.observe(json.dumps({"type": "item.started", "item": {
            "type": "command_execution", "id": number}}).encode()) is None
        assert monitor.observe(json.dumps({"type": "item.completed", "item": {
            "type": "command_execution", "id": number}}).encode()) is None
    reason = monitor.observe(json.dumps({"type": "item.started", "item": {
        "type": "command_execution", "id": 7}}).encode())
    assert reason == "provider tool-call budget exhausted at 6"


def test_budget_explain_is_zero_provider_calls_and_matches_policy(tmp_path, monkeypatch, capsys):
    store = initialized(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("adaptive_agent.cli.database", lambda: (_ for _ in ()).throw(
        AssertionError("budget explain must not initialize platform DB")))
    assert main(["budget", "explain", "Build a FastAPI endpoint", "--mode", "auto",
                 "--provider", "codex", "--model", "model-a", "--reasoning", "low",
                 "--normal-limit", "8", "--enforcement", "hard", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    direct = store.decide(_budget_analysis("Build a FastAPI endpoint", tmp_path),
                          requested_mode="auto", provider="codex", resolved_model="model-a",
                          reasoning_setting="low", current_normal_limit=8, enforcement="hard")
    assert payload["decision"]["selected_mode"] == direct.selected_mode
    assert payload["decision"]["reasons"] == list(direct.reasons)
    assert payload["provider_calls"] == 0


def test_multidomain_evidence_never_pools_across_families(tmp_path):
    store = initialized(tmp_path)
    for family in FAMILIES:
        current = analysis(family)
        add_pair(store, current, f"{family}-1")
        assert decide(store, current).selected_mode == "normal"
        add_pair(store, current, f"{family}-2")
        assert decide(store, current).selected_mode == "reduced"
    assert len(store.status()) == len(FAMILIES)


def test_twelve_domain_artifact_scenarios_are_independently_eligible(tmp_path):
    store = initialized(tmp_path)
    for index, (family, artifact) in enumerate(DOMAIN_ARTIFACT_SCENARIOS):
        current = scenario_analysis(family, artifact)
        add_pair(store, current, f"scenario-{index}-1")
        assert decide(store, current).selected_mode == "normal"
        add_pair(store, current, f"scenario-{index}-2")
        decision = decide(store, current)
        assert decision.selected_mode == "reduced"
        assert decision.task_family == family
        assert decision.artifact_type == artifact
    assert len(store.status()) == len(DOMAIN_ARTIFACT_SCENARIOS)


def test_multiround_conversation_learns_then_fails_closed(tmp_path):
    store = initialized(tmp_path)
    current = analysis("ui_ux")
    timeline = [decide(store, current).selected_mode]
    add_pair(store, current, 1)
    timeline.append(decide(store, current).selected_mode)
    add_pair(store, current, 2)
    timeline.append(decide(store, current).selected_mode)
    store.record_observation(observation(
        current, "round-3", "reduced", accepted="fail", run="run-round-3"))
    timeline.append(decide(store, current).selected_mode)
    assert timeline == ["normal", "normal", "reduced", "normal"]


def test_twelve_round_conversation_preserves_context_boundaries(tmp_path):
    store = initialized(tmp_path)
    ui = scenario_analysis("ui_ux", "prototype")
    graphic = scenario_analysis("graphic_design", "poster")
    timeline = []

    timeline.append(decide(store, ui).selected_mode)  # 1: cold start
    add_pair(store, ui, "ui-1")
    timeline.append(decide(store, ui).selected_mode)  # 2: one pair
    store.record_observation(observation(
        ui, "ui-unpaired", "reduced", run="ui-unpaired-run"))
    timeline.append(decide(store, ui).selected_mode)  # 3: unpaired evidence ignored
    add_pair(store, ui, "ui-2")
    timeline.append(decide(store, ui).selected_mode)  # 4: learned reduction
    timeline.append(decide(store, ui, provider="other").selected_mode)  # 5
    timeline.append(decide(store, ui, resolved_model="model-b").selected_mode)  # 6
    timeline.append(decide(store, ui, reasoning_setting="high").selected_mode)  # 7
    timeline.append(decide(store, ui, requested_mode="normal").selected_mode)  # 8
    timeline.append(decide(store, ui, requested_mode="reduced").selected_mode)  # 9
    timeline.append(decide(store, ui, enforcement="soft_guidance").selected_mode)  # 10
    store.record_observation(observation(
        ui, "ui-failed", "reduced", accepted="fail", run="ui-failed-run"))
    timeline.append(decide(store, ui).selected_mode)  # 11: failure closes learned path
    timeline.append(decide(store, graphic).selected_mode)  # 12: design domains stay isolated

    assert timeline == [
        "normal", "normal", "normal", "reduced", "normal", "normal",
        "normal", "normal", "reduced", "normal", "normal", "normal",
    ]


def test_policy_project_identity_does_not_scan_repository(tmp_path, monkeypatch):
    store = initialized(tmp_path)
    monkeypatch.setattr(Path, "iterdir", lambda *_: (_ for _ in ()).throw(
        AssertionError("policy identity must not scan repository contents")))
    assert store.fingerprint()
    assert decide(store).selected_mode == "normal"


def test_incomplete_values_zero_denominator_and_policy_latency_are_safe(tmp_path):
    store = initialized(tmp_path)
    for number in (1, 2):
        add_pair(store, analysis(), number,
                 normal={"input_tokens": 0, "cached": 0, "output": 0, "tools": 0, "seconds": 0},
                 reduced={"input_tokens": 1, "cached": 0, "output": 0, "tools": 0, "seconds": 0})
    decision = decide(store)
    assert decision.selected_mode == "normal"
    assert decision.policy_wall_ms >= 0


def test_status_and_targeted_reset_are_project_local(tmp_path):
    store = initialized(tmp_path)
    for number in (1, 2):
        add_pair(store, analysis("research"), number)
    assert store.status()[0]["pairs"] == 2
    assert store.reset(analysis("research")) == 4
    assert store.status() == []
