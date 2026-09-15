from adaptive_agent.observability.benchmark_quality import assess_implementation_quality
from scripts.pocketflow_longitudinal_benchmark import source_snapshot


def test_independent_quality_scores_external_evidence_only():
    result = assess_implementation_quality(
        [{"name": "pytest", "passed": True},
         {"name": "monthly request", "passed": True}],
        ["frontend/src/main.jsx", "frontend/tests/monthly.test.js"],
        required_checks=["monthly request"], expected_prefixes=["frontend/"],
        require_test_change=True)

    assert result["score"] == 100
    assert result["passed"] is True
    assert result["provider_self_report_used"] is False


def test_independent_quality_rejects_missing_required_test_change():
    result = assess_implementation_quality(
        [{"name": "pytest", "passed": True}, {"name": "endpoint", "passed": True}],
        ["app/main.py"], required_checks=["endpoint"], expected_prefixes=["app/"],
        require_test_change=True)

    assert result["score"] == 85
    assert result["passed"] is False
    assert result["dimensions"]["test_evidence"]["passed"] is False


def test_independent_quality_exposes_scope_drift_without_hiding_correctness():
    result = assess_implementation_quality(
        [{"name": "pytest", "passed": True}, {"name": "endpoint", "passed": True}],
        ["app/main.py", "unrelated/notes.txt"],
        required_checks=["endpoint"], expected_prefixes=["app/"],
        require_test_change=False)

    assert result["score"] == 95
    assert result["passed"] is True
    assert result["unexpected_paths"] == ["unrelated/notes.txt"]


def test_product_snapshot_excludes_uap_instruction_marker(tmp_path):
    (tmp_path / "AGENTS.md").write_text("<!-- UAP:START -->", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('product')", encoding="utf-8")

    assert list(source_snapshot(tmp_path)) == ["main.py"]
