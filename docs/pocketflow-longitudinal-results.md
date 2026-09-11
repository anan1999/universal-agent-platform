# PocketFlow longitudinal results

## Environment

- UAP: 2.3.1
- Commit: 72aec75d5786b6b39bb045981c2a14cf671c0885
- Provider: codex
- Model: gpt-5.6-luna
- Canonical source: uap
- Date: 2026-09-11T02:49:57Z

## Task 1

- Provider/model: baseline=codex/gpt-5.6-luna; UAP=codex/gpt-5.6-luna
- Baseline: completed, 113551 tokens (measured)
- UAP: completed, 173667 tokens (measured)
- Quality: baseline=True, UAP=True
- State: COLD
- Paired comparison valid: True
- Canonical source: uap
- Reuse hits: 0; rediscovery: 1

## Task 2

- Provider/model: baseline=codex/gpt-5.6-luna; UAP=codex/gpt-5.6-luna
- Baseline: completed, 160795 tokens (measured)
- UAP: completed, 144371 tokens (measured)
- Quality: baseline=True, UAP=True
- State: WARM
- Paired comparison valid: True
- Canonical source: uap
- Reuse hits: 1; rediscovery: 0

## Task 3

- Provider/model: baseline=codex/gpt-5.6-luna; UAP=codex/gpt-5.6-luna
- Baseline: completed, 257526 tokens (measured)
- UAP: completed, 310625 tokens (measured)
- Quality: baseline=True, UAP=True
- State: WARM
- Paired comparison valid: True
- Canonical source: uap
- Reuse hits: 4; rediscovery: 0

## Task 4

- Provider/model: baseline=codex/gpt-5.6-luna; UAP=codex/gpt-5.6-luna
- Baseline: completed, 142666 tokens (measured)
- UAP: completed, 116064 tokens (measured)
- Quality: baseline=True, UAP=True
- State: REVALIDATION
- Paired comparison valid: True
- Canonical source: uap
- Reuse hits: 3; rediscovery: 0

## Task 5

- Provider/model: baseline=codex/gpt-5.6-luna; UAP=codex/gpt-5.6-luna
- Baseline: completed, 187231 tokens (measured)
- UAP: completed, 171440 tokens (measured)
- Quality: baseline=True, UAP=True
- State: REVALIDATION
- Paired comparison valid: True
- Canonical source: uap
- Reuse hits: 4; rediscovery: 0

## Cumulative

- Baseline total: 861769
- UAP total: 916167
- Valid paired tasks: 5
- Paired measurement claimable: True
- Savings claimable: False
- Learning reuse validated: True
- Learning savings claimable: False
- Break-even: not reached

The learning loop is real: later UAP runs selected and reused validated project intelligence. It did not reduce cumulative token usage in this five-task sequence. UAP used 54,398 more measured tokens than baseline (+6.31%), so token savings and break-even are not claimed.

## Intelligence ROI

- Final state: `{"schema_version": 1, "level": 2, "level_name": "learned", "items": 19, "current": 15, "counts": {"knowledge": 2, "decision": 0, "skill": 0, "agent": 0, "command": 1, "evaluation": 0, "artifact": 2, "known_issue": 0, "task_history": 5, "receipt": 5}, "runs": 5, "reuse_hits": 12, "reusable_intelligence_hits": 9, "validated_reusable_hits": 9, "historical": {"task_history": 5, "receipt": 5}, "typed_reuse_hits": {"known_issue": 0, "evaluation": 0, "agent": 0, "skill": 0, "command": 3, "knowledge": 6, "decision": 0}, "selected_only": 0, "selected_reuse_hits": 9, "validated_reuse": 12, "knowledge_created": 2, "skill_reuse_hits": 0, "agent_reuse_hits": 0, "rediscovery_count": 1, "context_chars": 1795, "estimated_context_tokens": 450, "cold_runs": 1, "warm_runs": 2, "revalidation_runs": 2}`

## Limitations

Provider sessions are ephemeral, but provider-side caching may still exist. Files explored are unavailable unless the provider reports them. Both sides used Codex with `gpt-5.6-luna`, and paired task inputs were reset to the same accepted source checkpoint. The UAP output was selected as the canonical checkpoint for this run so source hashes remain compatible with UAP's durable intelligence across tasks; this measures longitudinal reuse but may favor continuity of UAP-produced structure. Token counts never choose the checkpoint. The five-task sample validates reuse behavior, not a general token-efficiency advantage. UAP alone retains durable `.agent` intelligence.
