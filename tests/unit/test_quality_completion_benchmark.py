import asyncio

from scripts.quality_completion_benchmark import Ledger, MODEL, converge, cost


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
