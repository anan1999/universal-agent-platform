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

The current AI executes work directly. Use `agentctl prepare "<goal>" --json` for
compact context, then read relevant source and validate the result.
Use `agentctl remember <source-path> "<short verified fact>"` only for useful new knowledge.
Delegated execution through `agentctl orchestrate` requires explicit user intent.
An `UAP_CHILD_EXECUTION=1` process is a bounded executor and must never invoke UAP again.
Trivial conversation, explanation-only requests, and explicit user bypass requests may run directly.
<!-- UAP:END -->
