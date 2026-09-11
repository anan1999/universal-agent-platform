import json

import pytest

from adaptive_agent.intelligence.project import (
    ContextSelection,
    IntelligenceItem,
    IntelligenceKind,
    IntelligenceStatus,
    ProjectIntelligenceStore,
)
from adaptive_agent.project.adapter import initialize_project
from adaptive_agent.runtime import RESOURCE_ROOT


def item(**overrides):
    values = dict(id="architecture", kind="knowledge",
                  summary="Python service architecture and test workflow",
                  capabilities=["python", "testing"], tags=["service"],
                  evidence=["pyproject.toml declares the Python package"],
                  related_paths=["pyproject.toml"], confidence="high")
    values.update(overrides)
    return IntelligenceItem(**values)


def test_init_creates_concise_git_friendly_index(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\n", encoding="utf-8")
    initialize_project(tmp_path, RESOURCE_ROOT / "templates", auto=True)
    value = json.loads((tmp_path / ".agent" / "intelligence.json").read_text(encoding="utf-8"))
    assert value == {"schema_version": 1, "items": [], "runs": []}
    assert "reuse_before_relearn" in (tmp_path / ".agent" / "project.yaml").read_text(encoding="utf-8")


def test_metadata_first_progressive_detail_loading(tmp_path):
    (tmp_path / "pyproject.toml").write_text("stable", encoding="utf-8")
    store = ProjectIntelligenceStore(tmp_path)
    store.add(item(), detail="Only load this architecture detail when relevant.")
    raw = json.loads(store.path.read_text(encoding="utf-8"))["items"][0]
    assert "detail" not in raw
    selected = store.select("test the python service")
    assert selected.temperature == "warm"
    assert selected.items[0]["detail"].startswith("Only load")
    assert selected.loaded_detail_paths


def test_source_change_invalidates_without_silent_reuse(tmp_path):
    source = tmp_path / "pyproject.toml"
    source.write_text("first", encoding="utf-8")
    store = ProjectIntelligenceStore(tmp_path)
    store.add(item())
    source.write_text("changed", encoding="utf-8")
    selected = store.select("python testing")
    assert selected.temperature == "revalidation"
    assert selected.stale_items == ["architecture"]
    assert selected.reuse_hits == 0
    assert store.items()[0].status == IntelligenceStatus.NEEDS_REVALIDATION.value
    assert store.select("python testing").temperature == "revalidation"


def test_revalidation_refreshes_hash_and_timestamp(tmp_path):
    source = tmp_path / "pyproject.toml"
    source.write_text("first", encoding="utf-8")
    store = ProjectIntelligenceStore(tmp_path)
    original = store.add(item())
    source.write_text("changed", encoding="utf-8")
    store.invalidate_changed()
    refreshed = store.revalidate("architecture", ["reviewed after source change"])
    assert refreshed.status == "current"
    assert refreshed.source_hashes != original.source_hashes
    assert "reviewed after source change" in refreshed.evidence


def test_revalidation_explains_exact_changed_paths(tmp_path):
    source = tmp_path / "schema.py"
    source.write_text("VERSION = 1\n", encoding="utf-8")
    store = ProjectIntelligenceStore(tmp_path)
    store.add(IntelligenceItem(
        id="schema-contract", kind="knowledge", summary="Schema version contract",
        capabilities=["schema"], related_paths=["schema.py"], evidence=["accepted task"]))
    source.write_text("VERSION = 2\n", encoding="utf-8")
    selection = store.select("schema change")
    assert selection.temperature == "revalidation"
    assert selection.stale_reasons[0]["id"] == "schema-contract"
    assert selection.stale_reasons[0]["reason"] == "source_hash_changed"
    assert selection.stale_reasons[0]["changed_paths"] == ["schema.py"]


def test_dedup_and_contradiction_supersession(tmp_path):
    (tmp_path / "pyproject.toml").write_text("stable", encoding="utf-8")
    store = ProjectIntelligenceStore(tmp_path)
    first = store.add(item())
    assert store.add(item()).created_at == first.created_at
    newer = store.add(item(summary="Python library architecture and test workflow"))
    all_items = store.items(include_inactive=True)
    assert len(all_items) == 2
    assert all_items[0].status == "superseded"
    assert newer.supersedes == "architecture"


def test_creation_gates_block_unvalidated_skill_and_agent(tmp_path):
    store = ProjectIntelligenceStore(tmp_path)
    for kind in (IntelligenceKind.SKILL.value, IntelligenceKind.AGENT.value):
        with pytest.raises(ValueError, match="validation"):
            store.add(item(id=kind, kind=kind, expected_reuse=4, validation="evidence_backed"))
    accepted = store.add(item(id="repeat-review", kind="skill", expected_reuse=3,
                              validation="validated"))
    assert accepted.kind == "skill"


def test_context_budget_and_attribution(tmp_path):
    (tmp_path / "pyproject.toml").write_text("stable", encoding="utf-8")
    store = ProjectIntelligenceStore(tmp_path)
    store.add(item(), detail="x" * 500)
    selected = store.select("python testing", max_chars=120)
    assert selected.context_chars <= 120
    assert selected.estimated_tokens == (selected.context_chars + 3) // 4
    assert selected.items[0]["evidence"]


def test_maturity_is_derived_from_runs_and_reuse(tmp_path):
    (tmp_path / "pyproject.toml").write_text("stable", encoding="utf-8")
    store = ProjectIntelligenceStore(tmp_path)
    assert store.status()["level"] == 0
    store.add(item())
    assert store.status()["level"] == 1
    for index in range(2):
        selected = store.select("python testing", record_reuse=True)
        store.record_run(f"run-{index}", selected)
    assert store.status()["level"] == 2
    for index in range(2, 6):
        selected = store.select("python testing", record_reuse=True)
        store.record_run(f"run-{index}", selected)
    assert store.status()["level"] == 3


def test_amortized_accounting_and_break_even():
    result = ProjectIntelligenceStore.amortization(1000, [400, 350, 300, 250])
    assert result["actual_cost"] == 2300
    assert result["baseline_cost"] == 5000
    assert result["savings"] == 2700
    assert result["break_even_run"] == 2


def test_compact_receipt_does_not_store_transcript(tmp_path):
    store = ProjectIntelligenceStore(tmp_path)
    receipt = store.record_compact_receipt("RUN-1", "completed", "Implement a small API", 3)
    assert receipt.kind == "receipt"
    raw = store.path.read_text(encoding="utf-8").lower()
    assert "chain-of-thought" not in raw and "conversation" not in raw


def test_structured_run_distillation_indexes_artifacts_not_provider_prose(tmp_path):
    artifact = tmp_path / "result.txt"
    artifact.write_text("artifact", encoding="utf-8")
    store = ProjectIntelligenceStore(tmp_path)
    learned = store.distill_run("RUN-2", "completed", "Create result", 2,
                                ["result.txt"], evaluation_passed=True)
    assert {value.kind for value in learned} == {"receipt", "task_history", "artifact", "evaluation"}
    assert "artifact" not in json.loads(store.path.read_text(encoding="utf-8"))["items"][0]


def test_maintenance_is_recommendation_only(tmp_path):
    store = ProjectIntelligenceStore(tmp_path)
    store.add(item(id="old", related_paths=[]))
    store.add(item(id="old", summary="new version", related_paths=[]))
    before = len(store.items(include_inactive=True))
    assert store.maintenance()["archive"] == ["old"]
    assert len(store.items(include_inactive=True)) == before


def test_run_record_is_bounded_and_replaced_by_id(tmp_path):
    store = ProjectIntelligenceStore(tmp_path)
    selection = ContextSelection("cold", "first", rediscovery_count=1)
    store.record_run("RUN-1", selection)
    store.record_run("RUN-1", ContextSelection("warm", "second"))
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert len(raw["runs"]) == 1
    assert raw["runs"][0]["temperature"] == "warm"


def test_real_benchmark_requires_opt_in_and_forbids_mock():
    script = (RESOURCE_ROOT.parents[2] / "scripts" / "pocketflow_longitudinal_benchmark.py").read_text(
        encoding="utf-8")
    assert "--execute" in script
    assert 'args.provider == "mock"' in script
    assert "Mock fallback is prohibited" in script
    assert script.count('"Implement the backend foundation') == 1
    assert "TASKS = [" in script and len(__import__("re").findall(r'^    "', script, __import__("re").M)) >= 5
    assert 'checkpoints / f"task-{number}"' in script
    assert "Cannot safely roll back" in script
    assert '"Read(../**)"' in script and '"WebFetch(*)"' in script
    assert 'choices=("baseline", "uap")' in script
    assert 'BenchmarkMode.LONGITUDINAL_LEARNING' in script
    assert '"independent longitudinal baseline and UAP lines"' in script
    assert 'reset_source(baseline_checkpoint, baseline)' in script
    assert 'reset_source(uap_checkpoint, uap, include_agent=True)' in script
    assert 'benchmark-fixtures" / "pocketflow" / "acceptance" / "contract.py"' in script
    assert '"quality_source": "benchmark_owned_external_acceptance"' in script
