# PocketFlow benchmark results

## Environment

- UAP: 2.3.1
- Commit: 4af9e94f1972b81e83bb9ae6b658fc7e4d9c49ee
- Provider: codex
- Model: gpt-5.6-luna
- Mode: longitudinal-learning
- Hypothesis: amortized_project_intelligence
- Source policy: independent longitudinal baseline and UAP lines
- Date: 2026-09-11T04:35:24Z

## Task 1

- Provider/model: baseline=codex/gpt-5.6-luna; UAP=codex/gpt-5.6-luna
- Baseline: completed, 130808 tokens (measured)
- UAP: completed, 224980 tokens (measured)
- Result state: INVALID_QUALITY
- Quality equivalent: False (external contract=pocketflow-v1)
- State: COLD
- Paired comparison valid: False
- Validated context reuse: 0
- Reuse candidate found: False
- Rediscovery avoidance: UNAVAILABLE
- Source lineage: baseline ad0874d957c5→19ee537ac0e9; UAP f9934830d549→262ab0cbbc57

### Learning funnel

- Provider evidence: 1 (validated_command)
- Distiller: 1 input → 0 candidates
- Persisted: 0 accepted; 0 rejected
- Accepted by kind: {"agent": 0, "command": 0, "decision": 0, "evaluation": 0, "knowledge": 0, "known_issue": 0, "skill": 0}
- Rejected by reason: {"duplicate": 0, "expected_reuse_too_low": 0, "generic": 0, "missing_evidence": 0, "other": 0, "stale": 0, "unsupported": 0, "weak_validation": 0}
- Materialized: none

### Reuse funnel

- Considered: 0; selected: 0
- Knowledge/Skills/Decisions/Commands: 0/0/0/0
- Selected context: 0 chars / ~0 tokens
- Successful selected items: 0

### External acceptance failures

- baseline/external_backend_crud_persistence: AssertionError: {"detail":[{"type":"missing","loc":["body","spent_at"],"msg":"Field required","input":{"amount":12.5,"category":"food","description":"benchmark expense","date":"2026-01-31"}}]}
- uap/external_backend_crud_persistence: AssertionError: {"detail":[{"type":"missing","loc":["body","expense_date"],"msg":"Field required","input":{"amount":12.5,"category":"food","description":"benchmark expense","date":"2026-01-31"}}]}

## Cumulative

- Baseline total: 130808
- UAP total: 224980
- Valid paired tasks: 0
- Paired measurement claimable: False
- Savings claimable: False
- Learning reuse validated: False
- Learning savings claimable: False
- Learning observation: LEARNING_NOT_OBSERVED
- Break-even: NOT_CLAIMABLE

## Intelligence ROI

- Final state: `{"schema_version": 1, "level": 1, "level_name": "discovered", "items": 5, "current": 5, "counts": {"knowledge": 1, "decision": 0, "skill": 0, "agent": 0, "command": 1, "evaluation": 0, "artifact": 1, "known_issue": 0, "task_history": 1, "receipt": 1}, "runs": 1, "reuse_hits": 0, "reusable_intelligence_hits": 0, "validated_reusable_hits": 0, "historical": {"receipt": 1, "task_history": 1}, "typed_reuse_hits": {"agent": 0, "known_issue": 0, "skill": 0, "command": 0, "evaluation": 0, "decision": 0, "knowledge": 0}, "selected_only": 0, "selected_reuse_hits": 0, "validated_reuse": 0, "validated_context_reuse": 0, "knowledge_created": 1, "skill_reuse_hits": 0, "agent_reuse_hits": 0, "rediscovery_count": 1, "context_chars": 0, "estimated_context_tokens": 0, "cold_runs": 1, "warm_runs": 0, "revalidation_runs": 0, "learning_yield": {"tasks_run": 1, "tasks_with_learning_evidence": 1, "evidence_emitted": 1, "candidates_created": 0, "durable_items_created": 0, "durable_items_reused": 0, "durable_items_validated": 0}}`

## Limitations

Provider sessions are ephemeral, but provider-side caching may still exist. Files explored are unavailable unless the provider reports them. Baseline and UAP preserve independent longitudinal source lines; source trees are never swapped between them. All paired tasks used the single provider codex. Provider-side caching may still exist. Repository exploration is not inferred when the provider does not report it. Validated context reuse means selected context plus successful external acceptance; it does not prove semantic reliance or token causality. Break-even requires every preceding pair to remain VALID and quality-equivalent.
