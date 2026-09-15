import json
import asyncio
from types import SimpleNamespace

import pytest

from scripts.benchmark_harness import (
    Checkpoints, PreparedFixture, changed_files, experiment_signature, tree_hash,
)
from scripts import context_cache_benchmark as benchmark


def test_prepared_fixture_is_reused_until_source_changes(tmp_path):
    source = tmp_path / "fixture"
    source.mkdir()
    (source / "app.py").write_text("VERSION = 1\n", encoding="utf-8")
    prepared = PreparedFixture(source, tmp_path / "bench")

    first = prepared.prepare()
    second = prepared.prepare()
    assert first["reused"] is False
    assert second["reused"] is True
    assert tree_hash(prepared.prepared) == tree_hash(source)

    (source / "app.py").write_text("VERSION = 2\n", encoding="utf-8")
    third = prepared.prepare()
    assert third["reused"] is False
    assert tree_hash(prepared.prepared) == tree_hash(source)


def test_materialized_arms_start_identical_and_are_isolated(tmp_path):
    source = tmp_path / "fixture"
    source.mkdir()
    (source / "app.py").write_text("original\n", encoding="utf-8")
    prepared = PreparedFixture(source, tmp_path / "bench")
    prepared.prepare()
    disabled = prepared.materialize("small", "disabled")
    enabled = prepared.materialize("small", "enabled")
    assert tree_hash(disabled) == tree_hash(enabled)
    (disabled / "app.py").write_text("changed\n", encoding="utf-8")
    assert (enabled / "app.py").read_text(encoding="utf-8") == "original\n"


def test_prepared_fixture_excludes_runtime_cache_even_when_source_contains_it(tmp_path):
    source = tmp_path / "fixture"
    cache = source / "app" / "__pycache__"
    cache.mkdir(parents=True)
    (source / "app" / "main.py").write_text("value = 1\n", encoding="utf-8")
    (cache / "main.pyc").write_bytes(b"runtime-only")
    prepared = PreparedFixture(source, tmp_path / "bench")
    prepared.prepare()
    assert (prepared.prepared / "app" / "main.py").is_file()
    assert not (prepared.prepared / "app" / "__pycache__").exists()


def test_changed_files_ignores_runtime_artifacts_and_detects_content(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "same.py").write_text("same\n", encoding="utf-8")
    (after / "same.py").write_text("same\n", encoding="utf-8")
    (before / "changed.py").write_text("old\n", encoding="utf-8")
    (after / "changed.py").write_text("new\n", encoding="utf-8")
    (after / "added.py").write_text("added\n", encoding="utf-8")
    (after / "__pycache__").mkdir()
    (after / "__pycache__" / "same.pyc").write_bytes(b"runtime")
    assert changed_files(before, after) == ["added.py", "changed.py"]


def test_checkpoint_only_resumes_matching_completed_arm(tmp_path):
    checkpoints = Checkpoints(tmp_path)
    signature = experiment_signature({"task": "small", "model": "test"})
    checkpoints.save("small", "enabled", signature, {"status": "completed", "tokens": 10})
    assert checkpoints.completed("small", "enabled", signature)["tokens"] == 10
    assert checkpoints.completed("small", "enabled", "different") is None
    checkpoints.save("small", "disabled", signature, {"status": "failed"})
    assert checkpoints.completed("small", "disabled", signature) is None
    assert checkpoints.load("small", "disabled", signature)["status"] == "failed"


def test_atomic_checkpoint_leaves_no_temporary_file(tmp_path):
    checkpoints = Checkpoints(tmp_path)
    checkpoints.save("large", "disabled", "sig", {"status": "completed"})
    path = tmp_path / "checkpoints" / "large" / "disabled.json"
    assert json.loads(path.read_text(encoding="utf-8"))["terminal"] is True
    assert not path.with_suffix(".json.tmp").exists()


def test_early_completion_is_part_of_experiment_signature():
    common = dict(provider="codex", model="model", reasoning="low", timeout=30)
    disabled = SimpleNamespace(**common, early_completion=False)
    enabled = SimpleNamespace(**common, early_completion=True)
    spec = benchmark.TASKS["small"]
    assert benchmark._signature(disabled, spec, "hash", "disabled") != benchmark._signature(
        enabled, spec, "hash", "disabled")


def test_round_plan_alternates_arm_order_and_call_ceiling_precedes_provider(monkeypatch):
    args = SimpleNamespace(task="small", rounds=3, max_provider_calls=6)
    plan = benchmark.round_plan(args)
    assert [row[2] for row in plan] == ["small-r1", "small-r2", "small-r3"]
    assert [row[3] for row in plan] == [
        ("disabled", "enabled"), ("enabled", "disabled"), ("disabled", "enabled")]
    assert benchmark.enforce_call_ceiling(args) == 6
    args.max_provider_calls = 5
    monkeypatch.setattr(benchmark, "providers", lambda: (_ for _ in ()).throw(AssertionError()))
    with pytest.raises(SystemExit, match="requires 6 provider calls"):
        asyncio.run(benchmark.execute(args))


def test_receipt_metrics_separates_artifact_and_provider_completion():
    receipt = SimpleNamespace(
        status="completed", provider="codex", model="model", files=[], error_code=None,
        uncertainty_reason="", completion={"artifact": "completed", "provider": "stopped"},
        token_usage={"input": 0, "output": 0, "cached": 0, "source": "unavailable",
                     "invocation_count": 1, "provider_tool_calls": 2},
    )
    metrics = benchmark.receipt_metrics(receipt, 2.5)
    assert metrics["completion"] == {"artifact": "completed", "provider": "stopped"}
    assert metrics["provider_protocol_status"] == "stopped"
    assert metrics["usage_complete"] is False


def test_pair_aggregation_separates_time_observation_from_token_proof():
    def arm(seconds, tools):
        return {"duration_seconds": seconds, "provider_tool_calls": tools,
                "provider_protocol_status": "stopped", "error": None}
    pairs = [
        {"equal_quality": True, "baseline": arm(60, 3), "uap": arm(54, 3),
         "decision_evidence": {"measured_complete_tokens": False}},
        {"equal_quality": True, "baseline": arm(40, 2), "uap": arm(36, 2),
         "decision_evidence": {"measured_complete_tokens": False}},
    ]
    observed = benchmark.aggregate_pairs(pairs)
    assert observed["accepted_pairs"] == 2
    assert observed["uap_faster_pairs"] == 2
    assert observed["uap_duration_reduction_percent"] == 10.0
    assert observed["baseline_tool_calls"] == observed["uap_tool_calls"] == 5
    assert observed["artifact_probe_stops"] == 4
    assert observed["token_comparison_available"] is False
