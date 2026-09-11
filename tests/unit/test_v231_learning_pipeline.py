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
             "procedure_steps": ["update schema", "run pytest"], "evidence": ["successful contract test"],
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
    assert "1. update schema" in loaded.instructions


def test_distiller_accepts_provider_project_fact_aliases():
    result = IntelligenceDistiller().distill(
        run_id="RUN-CURSOR", status="completed", goal="monthly report", task_count=1,
        structured_evidence=[
            {"type": "project_fact", "summary": "Reports use YYYY-MM", "evidence": ["app/main.py"]},
            {"type": "validated_project_fact", "summary": "Invalid months return 422",
             "evidence": ["tests/test_expenses.py"]},
        ])
    assert [item["kind"] for item in result.candidates] == ["knowledge", "knowledge"]


def test_selector_normalizes_monthly_and_plural_terms(tmp_path):
    store = ProjectIntelligenceStore(tmp_path)
    result = IntelligenceDistiller().distill(
        run_id="RUN-1", status="completed", goal="month reports", task_count=1,
        structured_evidence=[{
            "type": "knowledge", "summary": "Month report categories use expense records",
            "evidence": ["app/main.py"], "capabilities": ["category report"],
        }])
    store.learn_candidates(result.candidates, run_id="RUN-1")
    selection = store.select("Create monthly reports for expenses", record_reuse=True)
    assert selection.reuse_hits == 1
    assert selection.temperature == "warm"


def test_learning_funnel_reports_every_rejection_stage(tmp_path):
    evidence = [
        {"type": "knowledge", "summary": "Stable API prefix", "evidence": ["app.py"],
         "chain_of_thought": "must never persist"},
        {"type": "procedure", "summary": "Coding best practices",
         "procedure_steps": ["code"], "evidence": ["generic"]},
        {"type": "knowledge", "summary": "Missing proof", "evidence": []},
        {"type": "mystery", "summary": "Unknown", "evidence": ["x"]},
    ]
    distillation = IntelligenceDistiller().distill(
        run_id="RUN-FUNNEL", status="completed", goal="API", task_count=1,
        structured_evidence=evidence, evaluation_passed=True)
    assert len(distillation.candidates) == 1
    assert distillation.rejected_by_reason["generic"] == 1
    assert distillation.rejected_by_reason["missing_evidence"] == 1
    assert distillation.rejected_by_reason["unsupported"] == 1

    store = ProjectIntelligenceStore(tmp_path)
    store.record_run("RUN-FUNNEL", store.select("API"), success=True, evaluation_passed=True)
    persistence = store.learn_candidates_with_report(distillation.candidates, "RUN-FUNNEL")
    funnel = store.record_learning_funnel("RUN-FUNNEL", evidence, distillation, persistence)
    assert funnel["provider_learning_evidence_count"] == 4
    assert funnel["persistence_accepted_count"] == 1
    assert funnel["accepted_by_kind"]["knowledge"] == 1
    assert "chain_of_thought" not in funnel["provider_learning_evidence"][0]
    assert store.status()["learning_yield"]["evidence_emitted"] == 4


def test_failed_acceptance_rejects_provider_candidates_as_weak_validation(tmp_path):
    store = ProjectIntelligenceStore(tmp_path)
    result = store.learn_candidates_with_report([{
        "kind": "knowledge", "summary": "Unverified output", "evidence": ["provider said so"],
    }], "RUN-FAIL", quality_passed=False)
    assert not result.accepted
    assert result.rejected_by_reason["weak_validation"] == 1


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
