# Adaptive Budget Policy v0

Adaptive Budget v0 is an opt-in efficiency policy for delegated provider execution. It decides only
between preserving the current NORMAL provider tool-call limit and using a REDUCED limit of six.
It never chooses four, three, or a generated arbitrary limit.

## Modes

```bash
agentctl run "<goal>" --budget normal
agentctl run "<goal>" --budget reduced
agentctl run "<goal>" --budget auto
```

- NORMAL preserves the existing user/project/provider limit. It is not a global synonym for eight.
- REDUCED is an explicit user override to at most six, but never raises an existing smaller hard
  limit. A user limit of four remains four.
- AUTO uses the deterministic v0 gates below. Any error or incomplete evidence returns NORMAL.
- No `--budget` flag means the old execution path is unchanged. The compatibility flag
  `--adaptive-provider-tool-budget` maps to AUTO.

To disable the feature, omit `--budget` or explicitly use `--budget normal`. Project evidence can
be inspected or removed with `agentctl budget status`, `budget reset "<goal>"`, and
`budget reset --all`.

## Comparable history

AUTO requires at least two independent experiment pairs. Each pair must contain one NORMAL arm and
one REDUCED arm with identical task signature, input signature, external acceptance contract,
task family, artifact type, complexity, provider, resolved model, and reasoning setting. Both arms
must complete and pass the external contract with provider-measured usage. A normal arm must have
a limit above six; its reduced mate must have limit six.

Unpaired production observations are retained for inspection but cannot drive AUTO. Re-importing a
run/task or the same pair arm is ignored by SQLite unique constraints. Missing acceptance remains
`not_run`; missing usage remains SQL `NULL`, never zero. Failed and budget-exhausted observations are
retained. Mock and synthetic observations never count as production evidence. Existing pre-v0
quality counters and 4/3-stage observations remain readable migration history but never drive v0.

The project-local database is `.agent/cache/adaptive-budgets.sqlite3`. It stores hashes, bounded
classification fields, provider/model settings, statuses, numeric usage, contract versions, and
timestamps. It does not store prompts, provider prose, command output, or secrets.

## AUTO gates

REDUCED requires all of the following:

1. Known task family and one known artifact type from the existing GoalAnalyzer/profile metadata.
2. TRIVIAL, SMALL, or NORMAL complexity.
3. A known provider, resolved model, reasoning setting, and current NORMAL limit above six.
4. Provider enforcement declared `hard`.
5. At least two valid comparable pairs from the most recent 20 within 30 days.
6. No recent non-synthetic reduced-quality failure for the same settings.
7. Reduced median provider tool calls no higher than normal.
8. Median total tokens, tool calls, or duration improves by at least 10%.
9. Median uncached input plus output does not regress by more than 20%.

Cross-domain pooled averages never become evidence for one family. UI/UX history does not shrink a
research or 3D task. Provider, model, or reasoning changes create a different comparison set.

## Enforcement and exhaustion

The provider owns provider-tool enforcement; it does not choose the policy. Codex JSONL execution
is `HARD`: `CodexEventBudget` counts actual command, MCP, and web-search events and terminates the
child before a seventh tool starts under REDUCED. The base provider contract is `UNSUPPORTED`.
Adapters that only add prompt wording must declare `SOFT_GUIDANCE`; AUTO will remain NORMAL.

UAP deterministic validation commands are counted separately from provider tool calls. Provider
invocations are also a separate metric. Combining many shell commands into one provider event does
not prove proportional subscription savings.

When a hard budget is exhausted, the receipt is `BUDGET_EXHAUSTED`. Existing artifacts and measured
usage remain recorded, but UAP does not silently retry NORMAL, increase the limit, switch models,
or add an agent. A user or an already-authorized recovery workflow must choose what happens next.

## Explainability

`budget explain` calls no AI and returns the same policy object used by execution when supplied the
same resolved settings:

```bash
agentctl budget explain "<goal>" --mode auto --provider codex \
  --model <resolved-model> --reasoning low --normal-limit 8 --enforcement hard --json
```

The result contains requested/selected mode, normal/effective limit, comparable pair count, stable
reason codes, evidence pair IDs, classification, execution settings, enforcement, `policy_wall_ms`,
and policy version. It does not report fake confidence decimals.

## Offline validation

The v0 suite covers no history, one/two pairs, quality failure, +35% uncached regression, high and
unknown complexity, provider/model/reasoning isolation, missing values, synthetic evidence,
idempotent replay, explicit modes, a user hard limit of four, policy exceptions, unsupported/soft
providers, Codex hard exhaustion, and explain parity. It also exercises six independent task
families, 12 domain/artifact combinations, and a 12-round conversation timeline that changes
provider, model, reasoning, override, enforcement, quality, and design domain. Tests use only
fixtures and controlled providers; real provider calls for this implementation pass are zero.

Prior real benchmarks motivated the thresholds but do not prove this new policy saves a future
task or subscription quota. Provider-reported token counts cannot be converted directly to Codex
subscription quota.
