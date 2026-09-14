# UAP Reuse-First Core — Validation Report

Validated on 2026-09-14 on branch `refactor/reuse-first-core`, based on
`feature/v2.3.1-adaptive-budget-v0` commit `f976f9b`.

## Delivered architecture

The normal path now keeps the original goal and existing authorization, selects relevant project
assets deterministically, builds one compact packet, executes through the existing provider and
Scheduler, separates completion from artifact/acceptance evidence, and performs only a bounded
source-backed index update. Adaptive Budget, multi-agent composition, Skill synthesis, and Agent
reuse remain optional.

No parallel memory framework, history store, task classifier, AI judge, provider, Agent type, or
Skill schema was introduced.

## Modified files and reasons

- `project/context_index.py`: returns one explicit selection contract with suggested paths, facts,
  constraints, decisions, skill identifiers, sources, stale assets, and fallback state. Cache
  validation occurs once and invalidates only changed entries.
- `core/execution_packet.py`: consumes the selection contract, separates navigation from access
  policy, carries index constraints/decisions/sources, and removes duplicate asset content.
- `project/adapter.py`: reads explicit allowed/denied project scope with fail-closed shape checking.
- `core/orchestrator.py`: attaches navigation and authority separately, requires local source
  evidence before stable persistence, and derives an effective budget per run.
- `core/artifact_evaluator.py`: checks required sections in actual declared files rather than
  provider summaries.
- `providers/codex/provider.py` and `cli.py`: expose JSONL termination honestly as
  `observed_reactive`, which is ineligible for automatic reduction.
- `scripts/context_cache_benchmark.py`: both arms now use the same UAP composition/packet path;
  only reusable-context loading changes, and creation cost is separate.
- Integration/unit tests: cover all required architecture boundaries with local stubs and
  deterministic checks.
- README and docs: document the authority, verification, compatibility, and claim boundaries.

## Test evidence

- Focused reuse, simplified-core, Adaptive Budget, and Codex suites: 53 passed.
- Final full repository suite: **321 passed**, one existing Starlette/httpx deprecation warning.
- `python -m compileall -q src`: PASS.
- Fresh-session flow: a first local provider-stub run emitted a source-backed brand decision; a
  second fresh Orchestrator loaded it from disk into the actual provider packet exactly once.
- Permission/navigation: an API suggestion did not exclude an authorized date utility; an explicit
  denied directory remained in the packet's denied scope.
- Missing/corrupt cache: deterministic rebuild, `CACHE_INVALID`, zero reuse hits, targeted
  exploration allowed.
- Verification: provider completion without acceptance recorded `evaluation_passed=null` and no
  validated reuse. Required sections were checked against artifact content.
- Run-local budget: REDUCED produced 6 for Task A; NORMAL returned to configured 8 for Task B on
  the same Orchestrator; the configured object remained 8.
- Non-software fixture: brand constraints and delivery decision reached the packet without coding,
  pytest, or software-directory defaults.
- Repeated procedure: one existing project Skill package remained and was reloadable through the
  existing SkillRegistry.
- Real AI provider calls: **0**.

## Prepared comparison, not executed

The existing context-cache benchmark now records equal source hash, provider/model/reasoning,
acceptance, and UAP execution path for both arms. Its only variable is
`reusable_context_enabled`. The dry-run returned `ready=true`, `provider_calls=0`, and asset
creation `ai_invocations=0`. No real comparison was run and no saving claim is made.

## Compatibility and remaining risk

- Existing project indexes remain readable; no re-init is required. `relevant_paths` remains a
  compatibility alias for navigation, while `allowed_files` now mirrors explicit access scope.
- An empty explicit allowed scope delegates to the host's existing workspace/sandbox policy; it is
  not an unrestricted permission grant.
- Historical intelligence remains available behind its experimental flag. Its completion and
  evaluation fields are now kept distinct.
- Mechanical artifact checks do not prove runtime behavior, research validity, or subjective
  design quality. Those remain unverified without their own acceptance evidence or human review.
- A provider can report a misleading related path; persistence verifies that the path is local and
  exists, but does not prove every semantic statement in the summary. Source references are kept so
  later sessions can re-check them.
- Codex JSONL termination is reactive. It is not evidence of provider-native pre-execution
  enforcement, so AUTO will not reduce on that basis.
- Real token, cost, quality, and subscription-quota effects remain **NOT_PROVEN**.

## Direct answers

1. **Were new default AI calls added?** No.
2. **Must every task generate a Skill or Agent?** No; empty learning evidence is valid and synthesis
   remains optional.
3. **Are retrieval hints still treated as permission?** No. They are `suggested_paths`; explicit
   project and host policy determine access.
4. **Does no acceptance still produce verified PASS?** No. It records unverified/null.
5. **Were real token savings measured?** No — **NOT_PROVEN**.
