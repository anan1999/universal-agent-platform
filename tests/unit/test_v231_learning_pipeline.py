from adaptive_agent.intelligence.project import IntelligenceDistiller, ProjectIntelligenceStore
from adaptive_agent.skills.manifest import SkillTrust
from adaptive_agent.skills.registry import SkillRegistry
from adaptive_agent.skills.resolver import SkillResolver


def test_distiller_normalizes_external_evidence_and_materializes_skill(tmp_path):
    result = IntelligenceDistiller().distill(
        run_id="RUN-1", status="completed", goal="API work", task_count=1,
        structured_evidence=[
            {"type": "knowledge", "summary": "API base path is /api", "evidence": ["backend/app.py"]},
            {"type": "procedure", "summary": "PocketFlow API contract validation",
             "procedure": "1. update schema\n2. run pytest", "evidence": ["successful contract test"],
             "capabilities": ["api"], "expected_reuse": 3, "validation": "evidence_backed"},
            {"type": "agent_role", "summary": "backend-maintainer", "evidence": ["two maintenance tasks"],
             "capabilities": ["backend"], "expected_reuse": 1},
        ],
    )
    store = ProjectIntelligenceStore(tmp_path)
    learned = store.learn_candidates(result.candidates, run_id="RUN-1")
    assert {item.kind for item in learned} == {"knowledge", "skill", "agent"}
    skill = next(item for item in learned if item.kind == "skill")
    assert skill.status == "temporary"
    assert (tmp_path / ".agent" / "skills" / skill.id / "skill.json").is_file()
    assert next(item for item in learned if item.kind == "agent").status == "needs_review"

    fresh = SkillRegistry()
    discovered = fresh.discover_directory(tmp_path / ".agent" / "skills", SkillTrust.PROJECT_LOCAL)
    assert skill.id in discovered
    selected, _ = SkillResolver(fresh.manifests()).select(["api"])
    assert selected and selected[0].manifest.id == skill.id
    loaded = fresh.load_selected(skill.id)
    assert "Procedure" in loaded.instructions


def test_learning_evidence_is_not_invented_and_quality_gates_reuse(tmp_path):
    store = ProjectIntelligenceStore(tmp_path)
    assert IntelligenceDistiller().distill(run_id="R", status="completed", goal="x", task_count=1,
                                           structured_evidence=[]).candidates == []
    result = IntelligenceDistiller().distill(
        run_id="R1", status="completed", goal="api", task_count=1,
        structured_evidence=[{"type": "knowledge", "summary": "API base path is /api", "evidence": ["test"]}],
    )
    store.learn_candidates(result.candidates, run_id="R1")
    selection = store.select("api", record_reuse=True)
    store.record_run("R2", selection, success=False, evaluation_passed=False)
    assert store.status()["validated_reusable_hits"] == 0 if "validated_reusable_hits" in store.status() else store.status()["validated_reuse"] == 0


def test_paired_amortization_reports_task_three_and_quality_mismatch():
    valid = ProjectIntelligenceStore.amortization(
        baseline_costs=[100, 90, 95, 100], uap_costs=[150, 50, 45, 40],
        baseline_quality=[True] * 4, uap_quality=[True] * 4)
    assert valid["break_even_task"] == 3
    invalid = ProjectIntelligenceStore.amortization(
        baseline_costs=[100], uap_costs=[50], baseline_quality=[True], uap_quality=[False])
    assert invalid["break_even_task"] == "NOT_CLAIMABLE"
