# Universal Agent Platform Engineering Rules

## Architecture principles

- Keep the global platform separate from per-project adapters.
- Keep agents, skills, providers, storage, and project commands behind explicit contracts.
- Prefer deterministic DAG orchestration over agent-to-agent conversation.
- SQLite is the source of truth; JSONL is an append-only observability aid.

## Coding style and tests

- Target Python 3.11+, type public interfaces, and keep modules focused.
- Add unit tests for rules and integration tests for complete run behavior.
- A change is done only when relevant tests, CLI smoke checks, and security constraints pass.

## Security constraints

- Never expose arbitrary shell execution through the browser.
- Execute project commands only from `.agent/commands.yaml`.
- Never store plaintext secrets or perform automatic destructive Git recovery.

## Token efficiency

Treat context as expensive. Search before reading large files. Do not reread files when receipts already contain sufficient findings. Do not use strong models for mechanical work. Do not paste full logs when a concise root-cause summary is sufficient. Rotate an agent after three substantial assignments or when its context is fatigued.

<!-- UAP:START -->
# Universal Agent Platform

This repository uses Universal Agent Platform as the primary task orchestrator.
For non-trivial project tasks, route the concise user goal and essential constraints through
`agentctl orchestrate "<goal>" --json`. UAP owns the task DAG, logical agents, model routing,
skills, and escalation. AI providers are bounded execution backends beneath UAP.
An `UAP_CHILD_EXECUTION=1` process is a bounded executor and must never invoke UAP again.
Trivial conversation, explanation-only requests, and explicit user bypass requests may run directly.
<!-- UAP:END -->
