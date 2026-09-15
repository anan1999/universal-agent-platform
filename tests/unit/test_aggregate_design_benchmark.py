from scripts.aggregate_design_benchmark import aggregate, attribution, percent


def result(tokens, cached=0):
    return {"input_tokens": tokens - 5, "cached_input": cached, "output_tokens": 5,
            "provider_tool_calls": 1, "provider_messages": 1,
            "token_attribution": {"token_totals_exact": True, "windows": [
                {"kind": "after_file_change", "total_tokens": tokens}]}}


def test_aggregate_excludes_invalid_pairs_from_token_claim():
    source = {"environment": {"commit": "abc"}, "tracks": [{"domain": "ui-ux", "rounds": [
        {"round": 1, "goal": "one", "baseline": result(100), "uap": result(70),
         "quality": {"baseline": {"passed": True}, "uap": {"passed": True}},
         "comparison_valid": True},
        {"round": 2, "goal": "two", "baseline": result(100), "uap": result(10),
         "quality": {"baseline": {"passed": True}, "uap": {"passed": False}},
         "comparison_valid": False},
    ]}]}
    observed = aggregate([("ui-ux", source)])
    assert observed["summary"]["baseline_tokens"] == 100
    assert observed["summary"]["uap_tokens"] == 70
    assert observed["summary"]["quality_equivalent_all_rounds"] is False
    assert observed["summary"]["savings_claimable"] is False


def test_attribution_and_percent_are_deterministic():
    assert attribution(result(30))["tokens_by_kind"] == {"after_file_change": 30}
    assert percent(100, 70) == 30.0
