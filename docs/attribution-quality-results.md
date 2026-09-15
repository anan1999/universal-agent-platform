# PocketFlow longitudinal results

## Method

Five implementation tasks were executed sequentially in the same fresh project. Each task compared direct Codex against UAP from the same accepted source checkpoint; provider sessions were ephemeral while UAP retained project-local reusable state.

## Environment

- UAP: 2.3.1
- Commit: dd6116062ee2f3bbf65bf8bc4ce5be520b8b9156
- Provider: codex
- Model: gpt-6-astra
- Canonical source: baseline
- Date: 2026-09-15T05:16:53Z

## Task 1

- Goal: Implement the backend foundation for a personal expense app: FastAPI, SQLite, an Expense model, CRUD API, and backend tests.
- Provider/model: baseline=codex/gpt-6-astra; UAP=codex/gpt-6-astra
- Baseline: completed, 152727 tokens (measured)
- UAP: completed, 126873 tokens (measured)
- Token reduction: 16.93%
- Quality: baseline=True, UAP=True
- Independent quality score: baseline=98.75; UAP=98.75
- Provider tool windows: baseline=3; UAP=4
- Baseline token attribution: 7 windows (after_command_execution=86184, after_file_change=66543)
- UAP token attribution: 6 windows (after_command_execution=80883, after_file_change=45990)
- State: WARM
- Paired comparison valid: True
- Canonical source: baseline
- Reuse hits: 0; rediscovery: 0

## Post-hoc independent quality audit

- Audited tasks: 1
- Quality equivalent: True
- Quality-adjusted savings claimable: True
- Task 1: baseline=98.75/100 (PASS), UAP=100.0/100 (PASS)
- Limitation: Only the latest paired arm artifacts remain available; earlier task arms were intentionally replaced by canonical checkpoints.

## Cumulative

- Baseline total: 152727
- UAP total: 126873
- Token reduction: 16.93%
- Valid paired tasks: 1
- Paired measurement claimable: True
- Savings claimable: True
- Learning reuse validated: False
- Learning savings claimable: False
- Break-even: 1

## Intelligence ROI

- Final state: `{"measurement_source": "paired task receipts and project index", "project_index_present": true, "project_index_sources": 0, "benchmark_runs": 1, "warm_runs": 1, "revalidation_runs": 0, "reuse_hits": 0, "rediscovery": 0, "decision_context_items": 0, "legacy_store": {"schema_version": 1, "level": 0, "level_name": "unknown", "items": 0, "current": 0, "counts": {"knowledge": 0, "decision": 0, "skill": 0, "agent": 0, "command": 0, "evaluation": 0, "artifact": 0, "known_issue": 0, "task_history": 0, "receipt": 0}, "runs": 0, "reuse_hits": 0, "reusable_intelligence_hits": 0, "validated_reusable_hits": 0, "historical": {"task_history": 0, "receipt": 0}, "typed_reuse_hits": {"agent": 0, "skill": 0, "command": 0, "knowledge": 0, "decision": 0, "evaluation": 0, "known_issue": 0}, "selected_only": 0, "selected_reuse_hits": 0, "validated_reuse": 0, "knowledge_created": 0, "skill_reuse_hits": 0, "agent_reuse_hits": 0, "rediscovery_count": 0, "context_chars": 0, "estimated_context_tokens": 0, "cold_runs": 0, "warm_runs": 0, "revalidation_runs": 0}}`

## Limitations

Provider sessions are ephemeral, but provider-side caching may still exist. Files explored are unavailable unless the provider reports them. Paired task inputs are reset to the same accepted source checkpoint. When both systems pass, the predeclared canonical source is baseline; if only one passes, the passing result is canonical. Token outcomes never choose the checkpoint. All paired tasks used the single provider codex. A valid paired measurement and validated learning reuse do not imply token savings; break-even must also be reached. UAP alone retains durable `.agent` intelligence.
