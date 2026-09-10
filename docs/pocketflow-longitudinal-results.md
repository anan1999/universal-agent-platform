# PocketFlow longitudinal results

## Environment

- UAP: 2.3.1
- Commit: 00fa3b5aa2b3bebc5a26bb8ced5775850c2ac887
- Provider: codex
- Model: provider default
- Date: 2026-09-10T12:49:30Z

## Task 1

- Baseline: completed, 144020 tokens (measured)
- UAP: completed, 90577 tokens (measured)
- Quality: baseline=True, UAP=True
- State: COLD
- Paired comparison valid: True
- Canonical source: baseline
- Reuse hits: 0; rediscovery: 1

## Task 2

- Baseline: completed, 485468 tokens (measured)
- UAP: completed, 100109 tokens (measured)
- Quality: baseline=True, UAP=True
- State: REVALIDATION
- Paired comparison valid: True
- Canonical source: uap (legacy evaluator recovery)
- Reuse hits: 0; rediscovery: 0

## Interrupted

- Task: 3
- Stage: baseline
- Status: blocked
- Error: none
- Detail: Task 3 baseline returned blocked after modifying and testing the project; the original ephemeral provider summary was unavailable.

## Cumulative

- Baseline total: 629488
- UAP total: 190686
- Valid paired tasks: 2
- Savings claimable: False
- Break-even: NOT_CLAIMABLE

## Intelligence ROI

- Final state: `{"schema_version": 1, "level": 0, "level_name": "unknown", "items": 8, "current": 5, "counts": {"knowledge": 0, "decision": 0, "skill": 0, "agent": 0, "command": 0, "evaluation": 0, "artifact": 1, "known_issue": 0, "task_history": 2, "receipt": 2}, "runs": 2, "reuse_hits": 0, "reusable_intelligence_hits": 0, "validated_reusable_hits": 0, "historical": {"receipt": 2, "task_history": 2}, "typed_reuse_hits": {"evaluation": 0, "agent": 0, "knowledge": 0, "command": 0, "skill": 0, "decision": 0, "known_issue": 0}, "selected_only": 0, "selected_reuse_hits": 0, "validated_reuse": 0, "knowledge_created": 0, "skill_reuse_hits": 0, "agent_reuse_hits": 0, "rediscovery_count": 1, "context_chars": 0, "estimated_context_tokens": 0, "cold_runs": 1, "warm_runs": 0, "revalidation_runs": 1}`

## Limitations

Provider sessions are ephemeral, but provider-side caching may still exist. Files explored are unavailable unless the provider reports them. Paired task inputs are reset to the same accepted source checkpoint. Canonical checkpoint policy is fixed: if both systems pass, baseline is canonical; if only one passes, the passing result is canonical; token counts never choose the checkpoint. Task 2 used the UAP checkpoint only as a documented recovery exception after the former App.jsx-only evaluator produced a false negative and had already discarded the baseline tree. UAP alone retains durable `.agent` intelligence.
