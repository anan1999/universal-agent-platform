# PocketFlow longitudinal results

## Environment

- UAP: 2.3.0
- Commit: 2400cf1f6c8dcbba73eefc54f57b82de69ccec73
- Provider: codex
- Model: gpt-5.6-luna
- Date: 2026-09-10T06:29:46Z

## Task 1

- Baseline: completed, 137365 tokens (measured)
- UAP: failed, 48930 tokens (measured)
- Quality: baseline=True, UAP=False
- State: COLD
- Reuse hits: 0; rediscovery: 1

## Task 2

- Baseline: failed, 0 tokens (unavailable)
- UAP: failed, 0 tokens (unavailable)
- Quality: baseline=False, UAP=False
- State: WARM
- Reuse hits: 3; rediscovery: 0

## Task 3

- Baseline: failed, 0 tokens (unavailable)
- UAP: failed, 0 tokens (unavailable)
- Quality: baseline=False, UAP=False
- State: WARM
- Reuse hits: 5; rediscovery: 0

## Task 4

- Baseline: failed, 0 tokens (unavailable)
- UAP: failed, 0 tokens (unavailable)
- Quality: baseline=False, UAP=False
- State: WARM
- Reuse hits: 8; rediscovery: 0

## Task 5

- Baseline: failed, 0 tokens (unavailable)
- UAP: failed, 0 tokens (unavailable)
- Quality: baseline=False, UAP=False
- State: WARM
- Reuse hits: 8; rediscovery: 0

## Cumulative

- Baseline measured total: 137,365 for the one completed baseline task; later tasks unavailable
- UAP measured total: 48,930 for the one blocked UAP task; later tasks unavailable
- Quality: baseline Task 1 passed; UAP Task 1 failed; later paired quality unavailable
- Break-even: **not claimable** because paired tasks did not have equivalent successful quality

## Intelligence ROI

- Final state: `{"schema_version": 1, "level": 3, "level_name": "optimized", "items": 12, "current": 12, "counts": {"knowledge": 1, "decision": 0, "skill": 0, "agent": 0, "command": 1, "evaluation": 0, "artifact": 0, "known_issue": 0, "task_history": 5, "receipt": 5}, "runs": 5, "reuse_hits": 24, "knowledge_created": 1, "skill_reuse_hits": 0, "agent_reuse_hits": 0, "rediscovery_count": 1, "context_chars": 3697, "estimated_context_tokens": 926, "cold_runs": 1, "warm_runs": 4, "revalidation_runs": 0}`

## Limitations

This is an **inconclusive acceptance run**, not evidence of savings. Task 1 UAP was blocked by a
read-only execution-policy classification; Tasks 2–5 hit the provider usage limit. The harness
was corrected to use implementation-coded goals and an explicit software-engineering profile;
run it again after the usage window resets. Provider sessions are ephemeral, but provider-side
caching may still exist. Files explored are unavailable unless the provider reports them. Paired
task inputs are reset to the same accepted source checkpoint; UAP alone retains its durable
`.agent` intelligence.
