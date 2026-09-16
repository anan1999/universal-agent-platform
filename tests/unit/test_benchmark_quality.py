from adaptive_agent.observability.benchmark_quality import assess_implementation_quality
import inspect

from scripts.pocketflow_longitudinal_benchmark import evaluate, frontend_source_files, run_api_probe, source_snapshot


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


def test_react_dashboard_can_be_server_served_from_app_static(tmp_path):
    source = tmp_path / "app" / "static" / "app.js"
    source.parent.mkdir(parents=True)
    source.write_text("ReactDOM.createRoot(root).render(React.createElement('main'));", encoding="utf-8")
    unrelated = tmp_path / "scripts" / "helper.js"
    unrelated.parent.mkdir()
    unrelated.write_text("console.log('not a dashboard')", encoding="utf-8")

    assert frontend_source_files(tmp_path) == [source]


def test_external_api_probe_accepts_both_supported_date_field_names():
    source = inspect.getsource(evaluate)
    assert "('date', 'expense_date', 'spent_on')" in source
    assert source.count("expense create schema accepts neither date nor expense_date") == 2


def test_api_probe_discovers_non_app_package_factory(tmp_path):
    package = tmp_path / "expense_app"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "main.py").write_text(
        "import sqlite3\n"
        "from fastapi import FastAPI\n"
        "def create_app(database_path):\n"
        "    app = FastAPI()\n"
        "    app.state.connection = sqlite3.connect(database_path)\n"
        "    @app.get('/health')\n"
        "    def health(): return {'database': bool(database_path)}\n"
        "    return app\n", encoding="utf-8")

    result = run_api_probe(tmp_path, "assert client.get('/health').json() == {'database': True}")
    assert result.returncode == 0, result.stderr
