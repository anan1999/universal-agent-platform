import json
import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.pocketflow_longitudinal_benchmark as benchmark


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "benchmark-fixtures" / "pocketflow" / "acceptance" / "contract.py"


def test_benchmark_owned_backend_contract_is_external_and_executable(tmp_path):
    project = tmp_path / "candidate"
    project.mkdir()
    (project / "app.py").write_text(
        """from datetime import date
import sqlite3
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

DB = Path(__file__).with_name('expenses.sqlite3')
app = FastAPI()

class ExpenseIn(BaseModel):
    amount: float
    category: str
    description: str
    date: date

def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY, amount REAL, category TEXT, description TEXT, date TEXT)')
    return db

@app.post('/expenses')
def create(value: ExpenseIn):
    with connect() as db:
        cur = db.execute('INSERT INTO expenses(amount,category,description,date) VALUES(?,?,?,?)',
                         (value.amount,value.category,value.description,value.date.isoformat()))
        row = db.execute('SELECT * FROM expenses WHERE id=?',(cur.lastrowid,)).fetchone()
    return dict(row)

@app.get('/expenses')
def list_expenses(category: str | None = None, month: str | None = None):
    query, values = 'SELECT * FROM expenses WHERE 1=1', []
    if category:
        query += ' AND category=?'; values.append(category)
    if month:
        query += ' AND substr(date,1,7)=?'; values.append(month)
    with connect() as db:
        return [dict(row) for row in db.execute(query, values)]

@app.get('/expenses/{expense_id}')
def get_expense(expense_id: int):
    with connect() as db:
        row = db.execute('SELECT * FROM expenses WHERE id=?',(expense_id,)).fetchone()
    if not row: raise HTTPException(404)
    return dict(row)

@app.put('/expenses/{expense_id}')
def update(expense_id: int, value: ExpenseIn):
    with connect() as db:
        db.execute('UPDATE expenses SET amount=?,category=?,description=?,date=? WHERE id=?',
                   (value.amount,value.category,value.description,value.date.isoformat(),expense_id))
        row = db.execute('SELECT * FROM expenses WHERE id=?',(expense_id,)).fetchone()
    return dict(row)

@app.delete('/expenses/{expense_id}', status_code=204)
def delete(expense_id: int):
    with connect() as db: db.execute('DELETE FROM expenses WHERE id=?',(expense_id,))
""", encoding="utf-8")
    result = subprocess.run([sys.executable, str(CONTRACT), "--project", str(project),
                             "--task", "1"], cwd=ROOT, capture_output=True,
                            text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["contract"] == "pocketflow-v1"
    assert payload["passed"] is True
    assert payload["checks"][0]["name"] == "external_backend_crud_persistence"


def test_benchmark_script_separates_hypotheses_and_never_uses_generated_tests_as_quality_gate():
    script = (ROOT / "scripts" / "pocketflow_longitudinal_benchmark.py").read_text(encoding="utf-8")
    assert 'EXECUTION_EFFICIENCY = "execution-efficiency"' in script
    assert 'LONGITUDINAL_LEARNING = "longitudinal-learning"' in script
    assert '"quality_source": "benchmark_owned_external_acceptance"' in script
    assert '"self_tests":' in script
    assert 'baseline_checkpoints = workspace / "checkpoints" / "baseline"' in script
    assert 'uap_checkpoints = workspace / "checkpoints" / "uap"' in script
    assert '"independent longitudinal baseline and UAP lines"' in script


def test_uap_checkpoint_copies_and_restores_agent_intelligence(tmp_path):
    source, checkpoint, restored = tmp_path / "source", tmp_path / "checkpoint", tmp_path / "restored"
    (source / ".agent").mkdir(parents=True)
    (source / ".agent" / "intelligence.json").write_text('{"runs":[1]}', encoding="utf-8")
    (source / "app.py").write_text("VERSION=1", encoding="utf-8")
    benchmark.reset_source(source, checkpoint, include_agent=True)
    benchmark.reset_source(checkpoint, restored, include_agent=True)
    assert (restored / ".agent" / "intelligence.json").read_text(encoding="utf-8") == '{"runs":[1]}'
    assert (restored / "app.py").read_text(encoding="utf-8") == "VERSION=1"


def test_offline_longitudinal_harness_preserves_two_independent_source_lines(tmp_path, monkeypatch):
    class FakeProvider:
        execution_mode = SimpleNamespace(value="agentic_local")

        def probe(self):
            return SimpleNamespace(ready=True, detail="offline fake")

        def capabilities(self):
            return SimpleNamespace(supports=lambda *args, **kwargs: True)

    class FakeRegistry:
        def __contains__(self, provider_id):
            return provider_id == "fake"

        def get(self, provider_id):
            return SimpleNamespace(implemented=True)

        def create(self, provider_id, **kwargs):
            return FakeProvider()

    sequence = {"baseline": 0, "uap": 0}

    async def fake_baseline(provider, root, goal, model, reasoning):
        sequence["baseline"] += 1
        (root / "baseline-line.txt").write_text(str(sequence["baseline"]), encoding="utf-8")
        return _fake_result("fake", "same-model", ["baseline-line.txt"])

    async def fake_uap(provider, root, goal, db, provider_id):
        sequence["uap"] += 1
        (root / "uap-line.txt").write_text(str(sequence["uap"]), encoding="utf-8")
        return {**_fake_result("fake", "same-model", ["uap-line.txt"]),
                "temperature": "cold" if sequence["uap"] == 1 else "warm",
                "reuse_hits": max(0, sequence["uap"] - 1), "rediscovery": 0,
                "learning_funnel": {},
                "reuse_funnel": {"validated_context_reuse": max(0, sequence["uap"] - 1)},
                "stale_intelligence": []}

    monkeypatch.setattr(benchmark, "providers", lambda: FakeRegistry())
    monkeypatch.setattr(benchmark, "baseline_run", fake_baseline)
    monkeypatch.setattr(benchmark, "uap_run", fake_uap)
    monkeypatch.setattr(benchmark, "evaluate", lambda root, task: {
        "passed": True, "harness_error": None, "checks": [],
        "quality_source": "benchmark_owned_external_acceptance"})
    args = SimpleNamespace(
        provider="fake", timeout=10, workspace=tmp_path / "workspace",
        output=tmp_path / "result.json", report=tmp_path / "report.md",
        resume=False, mode="longitudinal-learning", model="same-model",
        reasoning="low", canonical_source="baseline")
    result = asyncio.run(benchmark.execute(args))
    tasks = result["tasks"]
    assert len(tasks) == 5
    assert tasks[1]["source_lineage"]["baseline"]["starting_hash"] == (
        tasks[0]["source_lineage"]["baseline"]["ending_hash"])
    assert tasks[1]["source_lineage"]["uap"]["starting_hash"] == (
        tasks[0]["source_lineage"]["uap"]["ending_hash"])
    assert tasks[0]["source_lineage"]["baseline"]["ending_hash"] != (
        tasks[0]["source_lineage"]["uap"]["ending_hash"])
    assert result["environment"]["source_policy"] == (
        "independent longitudinal baseline and UAP lines")


def test_resume_restores_source_after_failed_baseline_modified_files(tmp_path, monkeypatch):
    class FakeProvider:
        execution_mode = SimpleNamespace(value="agentic_local")

        def probe(self):
            return SimpleNamespace(ready=True, detail="offline fake")

        def capabilities(self):
            return SimpleNamespace(supports=lambda *args, **kwargs: True)

    class FakeRegistry:
        def __contains__(self, provider_id):
            return provider_id == "fake"

        def get(self, provider_id):
            return SimpleNamespace(implemented=True)

        def create(self, provider_id, **kwargs):
            return FakeProvider()

    attempt = {"failed": False, "verified_restore": False}

    async def fake_baseline(provider, root, goal, model, reasoning):
        partial = root / "partial-from-timeout.txt"
        if not attempt["failed"]:
            partial.write_text("unmeasured provider work", encoding="utf-8")
            attempt["failed"] = True
            return {**_fake_result("fake", "same-model", []), "status": "failed",
                    "error": "CODEX_TIMEOUT"}
        assert not partial.exists()
        attempt["verified_restore"] = True
        (root / "baseline-line.txt").write_text(goal, encoding="utf-8")
        return _fake_result("fake", "same-model", ["baseline-line.txt"])

    async def fake_uap(provider, root, goal, db, provider_id):
        (root / "uap-line.txt").write_text(goal, encoding="utf-8")
        return {**_fake_result("fake", "same-model", ["uap-line.txt"]),
                "temperature": "cold", "reuse_hits": 0, "rediscovery": 0,
                "learning_funnel": {}, "reuse_funnel": {"validated_context_reuse": 0},
                "stale_intelligence": []}

    monkeypatch.setattr(benchmark, "providers", lambda: FakeRegistry())
    monkeypatch.setattr(benchmark, "baseline_run", fake_baseline)
    monkeypatch.setattr(benchmark, "uap_run", fake_uap)
    monkeypatch.setattr(benchmark, "evaluate", lambda root, task: {
        "passed": True, "harness_error": None, "checks": [],
        "quality_source": "benchmark_owned_external_acceptance"})
    args = SimpleNamespace(
        provider="fake", timeout=10, workspace=tmp_path / "workspace",
        output=tmp_path / "result.json", report=tmp_path / "report.md",
        resume=False, mode="longitudinal-learning", model="same-model",
        reasoning="low", canonical_source="baseline")
    with pytest.raises(SystemExit, match="CODEX_TIMEOUT"):
        asyncio.run(benchmark.execute(args))

    args.resume = True
    result = asyncio.run(benchmark.execute(args))
    assert attempt["verified_restore"] is True
    assert len(result["tasks"]) == 5


def test_invalid_quality_writes_complete_json_and_report(tmp_path, monkeypatch):
    provider = SimpleNamespace(
        execution_mode=SimpleNamespace(value="agentic_local"),
        probe=lambda: SimpleNamespace(ready=True, detail="offline fake"),
        capabilities=lambda: SimpleNamespace(supports=lambda *args, **kwargs: True),
    )

    class FakeRegistry:
        def __contains__(self, provider_id):
            return provider_id == "fake"

        def get(self, provider_id):
            return SimpleNamespace(implemented=True)

        def create(self, provider_id, **kwargs):
            return provider

    async def fake_baseline(provider, root, goal, model, reasoning):
        return _fake_result("fake", "same-model", ["app.py"])

    async def fake_uap(provider, root, goal, db, provider_id):
        return {**_fake_result("fake", "same-model", ["app.py"]),
                "temperature": "cold", "reuse_hits": 0, "rediscovery": 0,
                "learning_funnel": {}, "reuse_funnel": {"validated_context_reuse": 0},
                "stale_intelligence": []}

    monkeypatch.setattr(benchmark, "providers", lambda: FakeRegistry())
    monkeypatch.setattr(benchmark, "baseline_run", fake_baseline)
    monkeypatch.setattr(benchmark, "uap_run", fake_uap)
    monkeypatch.setattr(benchmark, "evaluate", lambda root, task: {
        "passed": False, "harness_error": None,
        "checks": [{"name": "external_contract", "passed": False, "detail": "wrong field"}],
        "quality_source": "benchmark_owned_external_acceptance"})
    args = SimpleNamespace(
        provider="fake", timeout=10, workspace=tmp_path / "workspace",
        output=tmp_path / "result.json", report=tmp_path / "report.md",
        resume=False, mode="longitudinal-learning", model="same-model",
        reasoning="low", canonical_source="baseline")

    with pytest.raises(SystemExit, match="INVALID_QUALITY"):
        asyncio.run(benchmark.execute(args))
    payload = json.loads(args.output.read_text(encoding="utf-8"))
    assert payload["tasks"][0]["result_state"] == "INVALID_QUALITY"
    assert payload["cumulative"]["paired_measurement_claimable"] is False
    report = args.report.read_text(encoding="utf-8")
    assert "External acceptance failures" in report
    assert "baseline/external_contract: wrong field" in report


def _fake_result(provider, model, files):
    return {"status": "completed", "provider": provider, "model": model,
            "input_tokens": 10, "cached_input": 2, "non_cached_input": 8,
            "output_tokens": 1, "token_source": "measured", "ai_invocations": 1,
            "handoffs": 0, "deterministic_tool_calls": 0,
            "files_explored": {"value": None, "source": "unavailable"},
            "duration_seconds": 0.01, "retries": 0, "files_modified": files,
            "error": None}


def test_benchmark_result_states_are_not_collapsed():
    good = _fake_result("fake", "model", ["app.py"])
    quality = {"passed": True, "harness_error": None}
    assert benchmark.result_state(good, good, quality, quality) == "VALID"
    assert benchmark.result_state(good, good, quality,
                                  {"passed": False, "harness_error": None}) == "INVALID_QUALITY"
    assert benchmark.result_state(good, good, quality,
                                  {"passed": False, "harness_error": "bad suite"}) == "INVALID_HARNESS"
    quota = {**good, "status": "failed", "error": "quota limit reached"}
    assert benchmark.result_state(quota, good, quality, quality) == "QUOTA_LIMIT"
    mismatched = {**good, "model": "other"}
    assert benchmark.result_state(good, mismatched, quality, quality) == "NOT_COMPARABLE"
