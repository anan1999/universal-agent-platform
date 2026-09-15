# PocketFlow longitudinal results

## Method

Five implementation tasks were executed sequentially in the same fresh project. Each task compared direct Codex against UAP from the same accepted source checkpoint; provider sessions were ephemeral while UAP retained project-local reusable state.

## Environment

- UAP: 2.3.1
- Commit: 4276959fb3ec930be83a263bcba9184d3f2bb188
- Provider: codex
- Model: gpt-6-astra
- Canonical source: baseline
- Date: 2026-09-15T04:12:03Z

## Task 1

- Goal: Implement the backend foundation for a personal expense app: FastAPI, SQLite, an Expense model, CRUD API, and backend tests.
- Provider/model: baseline=codex/gpt-6-astra; UAP=codex/gpt-6-astra
- Baseline: completed, 124911 tokens (measured)
- UAP: completed, 107579 tokens (measured)
- Token reduction: 13.88%
- Quality: baseline=True, UAP=True
- State: WARM
- Paired comparison valid: True
- Canonical source: baseline
- Reuse hits: 0; rediscovery: 0

## Task 2

- Goal: Implement a compact React expense dashboard that calls the existing API and handles loading and error states.
- Provider/model: baseline=codex/gpt-6-astra; UAP=codex/gpt-6-astra
- Baseline: completed, 272101 tokens (measured)
- UAP: completed, 115217 tokens (measured)
- Token reduction: 57.66%
- Quality: baseline=True, UAP=True
- State: WARM
- Paired comparison valid: True
- Canonical source: baseline
- Reuse hits: 1; rediscovery: 0

## Task 3

- Goal: Add GET /exports/expenses.csv with columns id,amount,category,description,date, add a dashboard download link to that exact endpoint, and add deterministic tests.
- Provider/model: baseline=codex/gpt-6-astra; UAP=codex/gpt-6-astra
- Baseline: completed, 137276 tokens (measured)
- UAP: completed, 130456 tokens (measured)
- Token reduction: 4.97%
- Quality: baseline=True, UAP=True
- State: WARM
- Paired comparison valid: True
- Canonical source: baseline
- Reuse hits: 0; rediscovery: 0

## Task 4

- Goal: Add GET /reports/monthly/{month} returning exactly month, total, and by_category, with money represented as two-decimal strings; include only dates inside that calendar month and add boundary regression tests.
- Provider/model: baseline=codex/gpt-6-astra; UAP=codex/gpt-6-astra
- Baseline: completed, 157067 tokens (measured)
- UAP: completed, 133843 tokens (measured)
- Token reduction: 14.79%
- Quality: baseline=True, UAP=True
- State: WARM
- Paired comparison valid: True
- Canonical source: baseline
- Reuse hits: 0; rediscovery: 0

## Task 5

- Goal: Add a dashboard month input that calls /reports/monthly/{month} and renders the returned total and by_category breakdown, with deterministic tests.
- Provider/model: baseline=codex/gpt-6-astra; UAP=codex/gpt-6-astra
- Baseline: completed, 135250 tokens (measured)
- UAP: completed, 116790 tokens (measured)
- Token reduction: 13.65%
- Quality: baseline=True, UAP=True
- State: WARM
- Paired comparison valid: True
- Canonical source: baseline
- Reuse hits: 0; rediscovery: 0

## Cumulative

- Baseline total: 826605
- UAP total: 603885
- Token reduction: 26.94%
- Valid paired tasks: 5
- Paired measurement claimable: True
- Savings claimable: True
- Learning reuse validated: True
- Learning savings claimable: True
- Break-even: 1

## Intelligence ROI

- Final state: `{"measurement_source": "paired task receipts and project index", "project_index_present": true, "project_index_sources": 2, "benchmark_runs": 5, "warm_runs": 5, "revalidation_runs": 0, "reuse_hits": 1, "rediscovery": 0, "decision_context_items": 0, "legacy_store": {"schema_version": 1, "level": 0, "level_name": "unknown", "items": 0, "current": 0, "counts": {"knowledge": 0, "decision": 0, "skill": 0, "agent": 0, "command": 0, "evaluation": 0, "artifact": 0, "known_issue": 0, "task_history": 0, "receipt": 0}, "runs": 0, "reuse_hits": 0, "reusable_intelligence_hits": 0, "validated_reusable_hits": 0, "historical": {"receipt": 0, "task_history": 0}, "typed_reuse_hits": {"decision": 0, "knowledge": 0, "command": 0, "evaluation": 0, "agent": 0, "skill": 0, "known_issue": 0}, "selected_only": 0, "selected_reuse_hits": 0, "validated_reuse": 0, "knowledge_created": 0, "skill_reuse_hits": 0, "agent_reuse_hits": 0, "rediscovery_count": 0, "context_chars": 0, "estimated_context_tokens": 0, "cold_runs": 0, "warm_runs": 0, "revalidation_runs": 0}}`

## Limitations

Provider sessions are ephemeral, but provider-side caching may still exist. Files explored are unavailable unless the provider reports them. Paired task inputs are reset to the same accepted source checkpoint. When both systems pass, the predeclared canonical source is baseline; if only one passes, the passing result is canonical. Token outcomes never choose the checkpoint. All paired tasks used the single provider codex. A valid paired measurement and validated learning reuse do not imply token savings; break-even must also be reached. UAP alone retains durable `.agent` intelligence.
