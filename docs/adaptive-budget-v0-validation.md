# UAP Adaptive Budget v0 — Implementation Status

Validated on 2026-09-14 on branch `feature/v2.3.1-adaptive-budget-v0`.

> Later correction: `refactor/reuse-first-core` classifies Codex JSONL enforcement as
> `OBSERVED_REACTIVE`, not `HARD`. Event-driven termination is not proof of a provider-native
> pre-execution limit, so AUTO conservatively remains NORMAL for this capability.

## Scope and reused components

The implementation extends the existing `ExecutionBudget`, `GoalAnalyzer`, provider contract,
Codex JSONL event monitor, project-local SQLite history, Orchestrator, and CLI. It does not add a
second budget manager, history store, classifier, provider, agent type, skill system, dashboard, or
benchmark platform.

The central policy and additive history schema live in
`src/adaptive_agent/project/adaptive_budget.py`. Integration changes are limited to the existing
Orchestrator, scheduler metrics, provider contracts, Codex event enforcement, and CLI surfaces.

## Behavior

- No budget option: the previous execution path and configured limit are unchanged.
- AUTO without sufficient comparable evidence: NORMAL.
- REDUCED eligibility: known eligible task metadata, normal limit above six, hard provider
  enforcement, two or more valid comparable NORMAL/REDUCED pairs, passing acceptance, complete
  measured usage, non-worse median tool calls, at least one 10% cost improvement, and no more than
  20% uncached regression.
- Explicit REDUCED: at most six provider tool calls and never raises a smaller user hard limit.
- A normal limit at or below six is preserved and is not reported as a new optimization.
- Policy errors, missing values, incompatible settings, and recent reduced-quality failures return
  NORMAL without relaxing any safety control.
- Budget exhaustion returns `BUDGET_EXHAUSTED`; it does not retry, switch model, add an agent, or
  increase the limit automatically.

## Provider enforcement

- Codex: `OBSERVED_REACTIVE`. `CodexEventBudget` counts reported command, MCP, and web-search starts
  and terminates after the next reported start exceeds the limit. It is not a proven provider-native
  pre-execution hard limit.
- Base/Mock provider: `UNSUPPORTED`.
- Prompt-only adapters must identify themselves as `SOFT_GUIDANCE`; AUTO does not reduce for them.

Dry-run resolves enforcement from the provider actually selected by routing, even though it uses a
Mock provider for execution safety.

## History correctness

Evidence is isolated by project identity, task family, artifact type, complexity, provider,
resolved model, reasoning setting, task/input signature, and acceptance contract. Missing usage is
NULL and missing acceptance is `not_run`, not zero or PASS. Synthetic and Mock evidence cannot drive
production AUTO. Unique constraints prevent completion replay and duplicate experiment arms from
inflating pair counts. Failed and budget-exhausted observations remain visible.

The decision-time project identity is derived from the resolved project path; the policy does not
scan repository contents. Input comparability remains enforced by the pair-level input signature.

## CLI validation

Supported modes:

```text
agentctl run "<goal>" --budget normal
agentctl run "<goal>" --budget reduced
agentctl run "<goal>" --budget auto
agentctl budget explain "<goal>" ...
```

`budget explain` returned `provider_calls: 0`. A clean-history AUTO dry-run with normal limit 8
returned NORMAL and effective limit 8. The earlier branch reported hard Codex enforcement; the
later correction above supersedes that capability claim.

## Offline test evidence

- Targeted adaptive and scheduler tests: 27 passed.
- Expanded adaptive policy suite: 21 passed.
- Full repository suite: 311 passed, one pre-existing Starlette/httpx deprecation warning.
- `python -m compileall -q src`: PASS.
- Measured `budget explain` policy time: 0.048 ms.
- Measured AUTO dry-run policy time: 0.036 ms.
- Local performance target: under 50 ms in both measured CLI checks; this is not a cross-machine
  hard assertion.
- Real provider calls: **0**.

## Breadth and longitudinal coverage

Offline tests separately validate six task families and 12 family/artifact scenarios: software
source/tests, research report/summary, product requirements/roadmap, UI/UX prototype/wireframe,
graphic poster/brand, and 3D model/scene. Each scenario must independently earn two comparable
pairs; no pooled cross-domain average is used.

A 12-round timeline covers cold start, one pair, ignored unpaired evidence, learned reduction,
provider change, model change, reasoning change, NORMAL override, REDUCED override, soft
enforcement, a reduced-quality failure, and a switch from UI/UX to graphic design. The expected
sequence proves conservative fallback and context isolation; it does not represent 12 paid model
calls.

## Confirmed limits and unverified claims

- This policy only controls observable provider tool-call starts. One tool event can contain work
  of very different size, so lower event count is not automatically lower cost.
- Stored token metrics and local durations are not Codex subscription quota measurements.
- Synthetic/offline tests prove policy correctness, not future task quality or savings.
- No new paid or real-provider experiment was run in this pass, as required by the v0 scope.

## Direct answers

1. **Does the policy logic pass offline tests?** YES — 311 repository tests passed.
2. **Has it proven cost savings on real tasks?** NOT_PROVEN.
3. **Has it proven savings in subscription quota?** NOT_PROVEN.
