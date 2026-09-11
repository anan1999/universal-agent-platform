# PocketFlow benchmark results

## Environment

- UAP: 2.3.1
- Commit: bd93acb56b3b771c4c66aa2d3b33970564368031
- Provider: codex
- Model: provider default
- Mode: longitudinal-learning
- Hypothesis: unknown
- Source policy: unknown
- Date: 2026-09-11T04:28:35Z

## Interrupted

- Task: 1
- Stage: baseline
- Status: failed
- Error: CODEX_TIMEOUT
- Detail: Codex exceeded 900s timeout.

## Cumulative

- Baseline total: 0
- UAP total: 0
- Valid paired tasks: 0
- Paired measurement claimable: False
- Savings claimable: False
- Learning reuse validated: False
- Learning savings claimable: False
- Learning observation: LEARNING_NOT_OBSERVED
- Break-even: NOT_CLAIMABLE

## Intelligence ROI

- Final state: `{"schema_version": 1, "level": 0, "level_name": "unknown", "items": 0, "current": 0, "counts": {"knowledge": 0, "decision": 0, "skill": 0, "agent": 0, "command": 0, "evaluation": 0, "artifact": 0, "known_issue": 0, "task_history": 0, "receipt": 0}, "runs": 0, "reuse_hits": 0, "reusable_intelligence_hits": 0, "validated_reusable_hits": 0, "historical": {"task_history": 0, "receipt": 0}, "typed_reuse_hits": {"knowledge": 0, "command": 0, "agent": 0, "evaluation": 0, "known_issue": 0, "skill": 0, "decision": 0}, "selected_only": 0, "selected_reuse_hits": 0, "validated_reuse": 0, "validated_context_reuse": 0, "knowledge_created": 0, "skill_reuse_hits": 0, "agent_reuse_hits": 0, "rediscovery_count": 0, "context_chars": 0, "estimated_context_tokens": 0, "cold_runs": 0, "warm_runs": 0, "revalidation_runs": 0, "learning_yield": {"tasks_run": 0, "tasks_with_learning_evidence": 0, "evidence_emitted": 0, "candidates_created": 0, "durable_items_created": 0, "durable_items_reused": 0, "durable_items_validated": 0}}`

## Limitations

Provider sessions are ephemeral, but provider-side caching may still exist. Files explored are unavailable unless the provider reports them. Baseline and UAP preserve independent longitudinal source lines; source trees are never swapped between them. This is a mixed-provider sequence: . Provider-side caching may still exist. Repository exploration is not inferred when the provider does not report it. Validated context reuse means selected context plus successful external acceptance; it does not prove semantic reliance or token causality. Break-even requires every preceding pair to remain VALID and quality-equivalent.
