# V2 validation record

Validated on 2026-09-07 on Windows with Python 3.11.2. Normal tests used the
deterministic Mock provider and consumed no external AI quota.

## Automated validation

- `pytest -q --basetemp work/pytest-uap-release-2`: 93 tests passed (one upstream
  Starlette `TestClient` deprecation warning).
- `python -m compileall -q src`: passed.
- Domain matrix: 18 scenarios passed across software engineering, AI
  engineering, UI/UX, design, product, research, DevOps, data analysis,
  technical writing, general, mixed-profile, and unknown-domain goals.
- Schema/project upgrade suite: existing database rows and project-owned files
  remain intact while schema v5 columns and UAP markers are installed.
- Architecture boundary tests verify that the universal core contains no Codex
  import or Luna/Sol/Astra model literal and has no fixed-role planner.

## Bootstrap and CLI

The following were run successfully against isolated platform and project
directories:

```text
agentctl --version                 -> 2.0.0
agentctl setup --auto --json       -> schema v5, 10 profiles, 7 models
agentctl init <fixture> --auto     -> detected unknown project, selected general
agentctl attach <fixture> --json   -> attached with general profile
agentctl providers                 -> 7 registered, Codex and Mock ready
agentctl profiles                  -> 10 built-in starter profiles
agentctl doctor                    -> platform/project/provider checks passed
```

The help contracts for `setup`, `init`, and `attach` were also exercised.

## Dashboard

The dashboard was served on localhost and returned HTTP 200 for the six main
views (`/`, `/agents`, `/skills`, `/tools`, `/providers`, `/profiles`) and for
the provider, profile, tool, and run-composition APIs. The run composition API
rendered the real-provider validation run described below.

## Bounded real Codex validation

Successful run: `RUN-3801490D25`.

- Path: capability-first universal orchestration.
- Goal: a read-only, tool-free text verification with an unknown-domain
  fallback and the technical-writing starter profile.
- Composition: two dynamically selected read-only roles.
- Provider: Codex for both tasks, selected because `--provider codex` was
  explicit.
- Result: 2/2 tasks completed; both receipts returned
  `capability-first orchestration works.` with high confidence.
- Escalations: 0.
- Usage: measured by the provider, two invocations; normal tests remained mock
  only.
- Workspace mutations: none.

A separate diagnostic probe that asked child Codex to read a file was rejected
by the host's nested-command policy. That probe is not counted as a platform
pass; it demonstrated correct failure receipts and motivated the tool-free
bounded validation above.

## Product boundary

The repository contains one orchestration path: capability-first composition.
Software-engineering roles live in their optional profile; no fixed-role
planner, role-to-model router, compatibility mode, or legacy demo is shipped.
