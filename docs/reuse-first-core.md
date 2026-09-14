# Reuse-First Core Architecture

Reuse-First makes previously verified project navigation, rules, decisions, and procedures
available to a fresh session without turning memory into authority or a second execution system.

## Main flow

```text
original goal + existing authorization
  -> GoalAnalyzer suggestions
  -> ProjectContextIndex asset selection (zero AI calls)
  -> one compact ExecutionPacket
  -> existing provider and Scheduler
  -> provider completion
  -> actual artifacts + deterministic acceptance
  -> bounded, source-backed index update
```

The selection contract contains `suggested_paths`, project facts, constraints, decisions, selected
skill/reference identifiers, source references, and stale/unavailable items. A cache miss or stale
file enables targeted source exploration; it does not fail the task or claim a reuse hit. Only the
changed cached file is invalidated. A corrupt index is deterministically rebuilt and reported as
`CACHE_INVALID`.

## Optional paths

Adaptive Budget, multi-agent composition, project Skill synthesis, and Agent-role reuse remain
opt-in or experimental. Ordinary selection and packet construction add no provider invocation.
Empty `learning_evidence` is valid, and no extra model is asked to manufacture memory.

Reusable procedures continue to use the existing project-local Skill package and registry.
Reappearing evidence resolves to the existing item/package rather than appending a duplicate.

## Navigation and authorization boundary

`suggested_paths` are a starting map only. They never populate `allowed_scope`. The executor may
inspect other necessary paths inside its existing workspace authorization. Explicit project
`constraints.allowed_files` and `constraints.denied_files` populate the packet's access policy;
existing sandbox, network, approval, and command allowlist controls remain authoritative. Invalid
scope configuration raises an error instead of silently widening access.

The compatibility field `allowed_files` now mirrors explicit allowed scope. Existing compact
indexes remain readable and `relevant_paths` remains available as a navigation alias, so projects
do not need to re-run initialization.

## Reuse and evidence boundary

Compact constraints and decisions now reach the provider packet along with source references.
Assets are deduplicated while assembling the packet; a loaded Skill is not repeated as project
knowledge or dependency context. Provider-proposed stable facts or decisions are persisted only
when they have explicit evidence, expected reuse, and an existing project-local source path.
Provider text claiming `validation=validated` is insufficient by itself. Provider-proposed commands
are not promoted into the canonical command index; `.agent/commands.yaml` remains authoritative.

The configured execution budget is immutable. Each composition derives a run-local effective
budget used consistently by Composition, tasks, and Scheduler. A REDUCED run cannot shrink a later
NORMAL run on the same Orchestrator.

## Completion and acceptance boundary

Provider completion, artifact production, and acceptance are separate observations. No configured
or executed acceptance check means `evaluation_passed=null`, not verified PASS. Required sections
are searched in actual declared artifact files, never only in the provider receipt summary.
File existence proves existence, not application behavior or subjective design quality. Mechanical
checks and human-quality judgment must therefore be reported separately.

Codex JSONL budget monitoring is classified `OBSERVED_REACTIVE`: UAP terminates after observing an
over-limit start event, but does not claim a provider-native pre-execution hard limit. AUTO budget
selection remains NORMAL for that capability.

## Validation and limits

The refactor is covered by offline provider stubs and deterministic checks for navigation versus
permission, compact constraints/decisions in the packet, corrupt-cache fallback, unverified
completion, actual artifact inspection, run-local budgets, a two-session receipt-to-packet flow,
Skill deduplication, and a non-software brand-design fixture. The prepared benchmark uses the same
UAP path, provider/model/reasoning, source hash, and acceptance for both arms; only reusable context
is toggled. Asset creation cost is reported separately.

This refactor adds no default AI call and does not prove real token, monetary, quality, or
subscription-quota savings. No real-provider experiment was run.
