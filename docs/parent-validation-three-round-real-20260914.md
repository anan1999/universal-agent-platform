# Parent-owned deterministic validation benchmark

The control asks the AI task to run the project test suite. The treatment removes that command from AI context and runs the same allowlisted test once in the scheduler with zero provider tokens.

| Round | Order | Agent quality | Parent quality | Token reduction | Uncached reduction | Provider-tool delta |
|---:|---|---:|---:|---:|---:|---:|
| 1 | agent_owned → parent_owned | PASS | PASS | -45.93% | 36.06% | -2 |
| 2 | parent_owned → agent_owned | PASS | PASS | -175.67% | 18.22% | -5 |
| 3 | agent_owned → parent_owned | PASS | PASS | -54.04% | -112.99% | -2 |

## Aggregate

- Agent-owned quality: 3/3
- Parent-owned quality: 3/3
- Pooled total-token reduction: -88.24%
- Pooled uncached-token reduction: -7.48%
- Pooled provider-tool reduction: -128.57%
- Pooled end-to-end time reduction: -95.38%
- Provider validation actions, agent-owned: 3
- Provider validation actions, parent-owned: 6
- Parent deterministic tool calls: 3

Quality is decided by the benchmark-owned acceptance contract, not the model's claim.

Decision: **REJECT_COST** — quality held, but total tokens, uncached tokens, and provider tool calls all increased.

## Product decision

Parent-owned validation remains opt-in behind `UAP_EXPERIMENTAL_PARENT_VALIDATION`; the default keeps agent-owned validation. The treatment's soft prompt did not enforce the boundary: provider-side validation actions doubled from 3 to 6. A future trial must enforce the command boundary in the child execution interface instead of adding more prompt text.
