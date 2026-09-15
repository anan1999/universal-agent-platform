from scripts import design_longitudinal_benchmark as benchmark


def row(domain: str, baseline: int, uap: int, valid: bool = True):
    return {"round": 1, "goal": "goal", "baseline_tokens": baseline,
            "uap_tokens": uap, "comparison_valid": valid,
            "baseline": {}, "uap": {},
            "quality": {"baseline": {"passed": True}, "uap": {"passed": True}}}


def test_summary_keeps_tracks_separate_and_pools_valid_pairs():
    tracks = [
        {"domain": "ui-ux", "rounds": [row("ui-ux", 100, 70)]},
        {"domain": "graphic-design", "rounds": [row("graphic-design", 80, 60)]},
        {"domain": "three-d-design", "rounds": [row("three-d-design", 90, 100, False)]},
    ]
    result = benchmark.summarize(tracks)
    assert result["baseline_tokens"] == 180
    assert result["uap_tokens"] == 130
    assert result["valid_rounds"] == 2
    assert result["quality_equivalent"] is False
    assert result["savings_claimable"] is False


def test_render_includes_problem_text_and_limitations():
    tracks = [{"domain": "ui-ux", "rounds": [row("ui-ux", 100, 70)]}]
    payload = {"tracks": tracks, "summary": benchmark.summarize(tracks)}
    text = benchmark.render(payload)
    assert "goal" in text
    assert "UI" not in text or "ui-ux" in text
    assert "aesthetic preference" in text


def test_only_one_completed_measured_quality_failure_is_repairable():
    current = row("ui-ux", 100, 70, False)
    current["baseline"] = {"status": "completed", "token_source": "measured",
                           "usage_complete": True}
    current["uap"] = {"status": "completed", "token_source": "measured",
                      "usage_complete": True}
    current["quality"]["baseline"]["passed"] = False
    assert benchmark.repairable_side(current) == "baseline"
    current["quality"]["uap"]["passed"] = False
    assert benchmark.repairable_side(current) is None


def test_canonical_is_selected_by_quality_and_never_tokens():
    current = row("ui-ux", 10, 1000, False)
    assert benchmark.canonical_side(current) == "baseline"
    current["quality"]["baseline"]["passed"] = False
    assert benchmark.canonical_side(current) == "uap"
    current["quality"]["uap"]["passed"] = False
    assert benchmark.canonical_side(current) is None


def test_only_zero_usage_provider_failures_are_execution_retryable():
    current = row("ui-ux", 0, 0, False)
    failed = {"status": "failed", "token_source": "unavailable",
              "input_tokens": 0, "output_tokens": 0}
    current["baseline"] = dict(failed)
    current["uap"] = dict(failed)
    assert benchmark.retryable_sides(current) == ["baseline", "uap"]
    current["baseline"]["input_tokens"] = 1
    assert benchmark.retryable_sides(current) == ["uap"]
