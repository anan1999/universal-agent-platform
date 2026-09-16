import asyncio

from scripts.quality_completion_benchmark import Ledger, MODEL, converge, cost, defects


def test_quality_completion_benchmark_is_pinned_to_sol():
    assert MODEL == "gpt-5.6-sol"


def test_failed_named_checks_become_repair_feedback():
    assert defects({"passed": False, "checks": [
        {"name": "pytest", "passed": True},
        {"name": "react dashboard", "passed": False},
    ]}) == ["react dashboard"]


def test_failed_check_diagnostic_becomes_repair_feedback():
    assert defects({"passed": False, "checks": [
        {"name": "api contract", "passed": False,
         "detail": "AssertionError: expected 201, received 422"},
    ]}) == ["api contract: AssertionError: expected 201, received 422"]


def receipt(tokens=10):
    return {"status": "completed", "model": MODEL, "input_tokens": tokens,
            "output_tokens": 0, "token_source": "measured", "usage_complete": True}


def test_repairs_continue_beyond_three_turns_and_keep_all_costs(tmp_path):
    ledger = Ledger(tmp_path / "attempts.db")
    prompts = []

    async def invoke(prompt):
        prompts.append(prompt)
        return receipt()

    result = asyncio.run(converge(
        ledger, "ui-ux", 1, "baseline", "Build the artifact", invoke,
        lambda: {"passed": len(prompts) == 5, "errors": ["keyboard navigation broken"]},
        token_ceiling=100, seconds_ceiling=30))
    assert result["outcome"] == "contract_passed"
    assert result["observed_tokens"] == 50
    assert result["attempts"] == 5
    assert "keyboard navigation broken" in prompts[1]
    assert cost(ledger.rows("ui-ux", 1, "baseline"))["observed_tokens"] == 50


def test_check_failure_is_injected_into_next_prompt(tmp_path):
    ledger = Ledger(tmp_path / "attempts.db")
    prompts = []

    async def invoke(prompt):
        prompts.append(prompt)
        return receipt()

    result = asyncio.run(converge(
        ledger, "programming", 2, "uap", "Build dashboard", invoke,
        lambda: {"passed": len(prompts) == 2, "checks": [
            {"name": "react dashboard", "passed": len(prompts) == 2},
        ]}, token_ceiling=100, seconds_ceiling=30))
    assert result["outcome"] == "contract_passed"
    assert "react dashboard" in prompts[1]


def test_budget_exhaustion_keeps_failed_cost_and_marks_unfinished(tmp_path):
    ledger = Ledger(tmp_path / "attempts.db")

    async def invoke(prompt):
        return receipt(60)

    result = asyncio.run(converge(
        ledger, "ui-ux", 1, "uap", "Build", invoke,
        lambda: {"passed": False, "errors": ["missing artifact"]},
        token_ceiling=100, seconds_ceiling=30))
    assert result["outcome"] == "budget_exhausted_unfinished"
    assert result["observed_tokens"] == 120  # single call can exceed remaining ceiling


def test_unknown_usage_is_not_retried_as_zero_cost(tmp_path):
    ledger = Ledger(tmp_path / "attempts.db")
    calls = []

    async def invoke(prompt):
        calls.append(prompt)
        raise TimeoutError()

    result = asyncio.run(converge(
        ledger, "ui-ux", 1, "uap", "Build", invoke,
        lambda: {"passed": False}, token_ceiling=100, seconds_ceiling=30))
    assert len(calls) == 1
    assert result["outcome"] == "measurement_incomplete"
    assert not result["measurement_complete"]


def test_wrong_model_cannot_be_a_success(tmp_path):
    ledger = Ledger(tmp_path / "attempts.db")

    async def invoke(prompt):
        return {**receipt(), "model": "unexpected-model"}

    result = asyncio.run(converge(
        ledger, "ui-ux", 1, "baseline", "Build", invoke,
        lambda: {"passed": True}, token_ceiling=100, seconds_ceiling=30))
    assert result["outcome"] == "model_mismatch"
