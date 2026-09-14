import json

import pytest

from adaptive_agent.bootstrap import consumption_mode
from adaptive_agent.cli import _dry_run, main
from adaptive_agent.core.capabilities import Risk
from adaptive_agent.core.consumption import ConsumptionMode, ExecutionBudget, consumption_policy
from adaptive_agent.core.execution_packet import ExecutionPacketBuilder


def test_balanced_preserves_v21_execution_budgets():
    policy = consumption_policy()
    assert policy.mode is ConsumptionMode.BALANCED
    assert policy.max_parallel_agents == 3
    assert policy.max_parallel_strong_agents == 1
    assert policy.max_escalations_per_task == 2
    assert policy.receipt_word_limit == 160
    assert policy.max_context_receipts == 4


def test_economy_is_sequential_and_keeps_high_risk_reasoning_safe():
    policy = consumption_policy("economy")
    assert policy.max_parallel_agents == 1
    assert policy.max_escalations_per_task == 1
    assert policy.team_limit(4, Risk.LOW) == 1
    assert policy.team_limit(4, Risk.HIGH) == 2
    assert policy.reasoning("medium", Risk.LOW) == "low"
    assert policy.reasoning("medium", Risk.HIGH) == "high"


def test_maximum_expands_budgets_without_changing_capability_contracts():
    policy = consumption_policy("maximum")
    assert policy.max_parallel_agents == 6
    assert policy.max_escalations_per_task == 3
    assert policy.reasoning("low", Risk.LOW) == "medium"
    assert policy.max_context_receipts == 6


def test_unknown_policy_is_rejected():
    with pytest.raises(ValueError, match="unknown consumption mode"):
        consumption_policy("unlimited")


def test_dry_run_exposes_policy_and_economy_caps_team(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    economy = _dry_run("Design and implement a production deployment workflow", "mock",
                       consumption="economy")
    balanced = _dry_run("Design and implement a production deployment workflow", "mock",
                        consumption="balanced")
    assert economy["consumption"]["mode"] == "economy"
    assert economy["team"]["consumption_mode"] == "economy"
    assert len(economy["team"]["members"]) <= len(balanced["team"]["members"])
    assert any("Consumption policy: economy" in line for line in economy["team"]["rationale"])


def test_cli_sets_and_reports_global_policy(capsys):
    assert main(["consumption", "economy", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "economy"
    assert consumption_mode() == "economy"
    assert main(["consumption", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["max_parallel_agents"] == 1


def test_project_policy_overrides_global_policy(monkeypatch, tmp_path):
    agent_dir = tmp_path / ".agent"
    agent_dir.mkdir()
    (agent_dir / "project.yaml").write_text(
        "consumption:\n  mode: economy\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    set_result = main(["consumption", "maximum", "--json"])
    assert set_result == 0
    plan = _dry_run("Analyze a research question", "mock")
    assert plan["consumption"]["mode"] == "economy"


def test_packet_builder_accepts_economy_context_budget():
    builder = ExecutionPacketBuilder(receipt_word_limit=80, max_receipts=2)
    assert builder.receipt_word_limit == 80
    assert builder.max_receipts == 2


def test_economy_keeps_human_gate_for_high_risk_work(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    plan = _dry_run("Deploy the service to the production cluster", "mock", consumption="economy")
    assert plan["analysis"]["risk"] == Risk.HIGH.value
    assert any(task["kind"] == "approval" for task in plan["tasks"])
    assert any(task["agent"].endswith("reviewer") for task in plan["tasks"]
               if task["kind"] == "agent")


def test_economy_keeps_deterministic_validation(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='tiny'\n", encoding="utf-8")
    plan = _dry_run("Fix a simple Python arithmetic bug and run the existing test.",
                    "mock", consumption="economy")
    assert any(task["kind"] == "tool" and "test" in task["agent"] for task in plan["tasks"])


def test_explicit_budget_is_validated_and_exposed_by_dry_run(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    budget = ExecutionBudget(max_provider_calls=1, max_provider_tool_calls=8,
                             max_provider_messages=5, max_tool_calls=4, max_total_tokens=3000,
                             max_output_tokens=500, max_retry_rounds=0,
                             max_wall_seconds=60, verification_reserve_percent=25)
    plan = _dry_run("Analyze a research question", "mock", execution_budget=budget)
    assert plan["execution_budget"]["enabled"] is True
    assert plan["execution_budget"]["max_provider_calls"] == 1
    assert plan["execution_budget"]["max_provider_tool_calls"] == 8
    assert plan["execution_budget"]["max_provider_messages"] == 5
    assert plan["execution_budget"]["verification_reserve_percent"] == 25
    with pytest.raises(ValueError, match="max_provider_calls"):
        ExecutionBudget(max_provider_calls=-1)
