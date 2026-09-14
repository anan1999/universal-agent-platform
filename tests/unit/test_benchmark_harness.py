import json

from scripts.benchmark_harness import Checkpoints, PreparedFixture, experiment_signature, tree_hash


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


def test_checkpoint_only_resumes_matching_completed_arm(tmp_path):
    checkpoints = Checkpoints(tmp_path)
    signature = experiment_signature({"task": "small", "model": "test"})
    checkpoints.save("small", "enabled", signature, {"status": "completed", "tokens": 10})
    assert checkpoints.completed("small", "enabled", signature)["tokens"] == 10
    assert checkpoints.completed("small", "enabled", "different") is None
    checkpoints.save("small", "disabled", signature, {"status": "failed"})
    assert checkpoints.completed("small", "disabled", signature) is None


def test_atomic_checkpoint_leaves_no_temporary_file(tmp_path):
    checkpoints = Checkpoints(tmp_path)
    checkpoints.save("large", "disabled", "sig", {"status": "completed"})
    path = tmp_path / "checkpoints" / "large" / "disabled.json"
    assert json.loads(path.read_text(encoding="utf-8"))["terminal"] is True
    assert not path.with_suffix(".json.tmp").exists()
