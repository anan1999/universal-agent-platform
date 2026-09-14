# Adaptive Budget Policy v0 — implementation audit

Baseline: `f3e7be1` on `feature/v2.3.1-simplified-core`.

1. The current provider tool limit originates in
   `ExecutionBudget.max_provider_tool_calls`. CLI values enter the budget once,
   Orchestrator copies the effective budget to agent-task metadata, and the
   provider receives that metadata.
2. `CodexEventBudget` counts actual Codex JSONL `command_execution`,
   `mcp_tool_call`, and `web_search` events. Scheduler separately aggregates
   reported counts and usage across attempts; provider invocation count is not
   treated as a tool-call count.
3. `CodexProvider._communicate` can stop the child before a tool starts once the
   configured count has been reached. This is a verified hard run-time limit.
   The base provider contract and other providers do not currently declare such
   enforcement, so they must remain unsupported rather than inheriting Codex's
   claim.
4. The existing project-local SQLite records controller-observed external
   acceptance and measured totals, but it cannot distinguish experiment pairs,
   provider, resolved model, reasoning, artifact type, acceptance contract, or
   synthetic evidence. It is therefore insufficient for the v0 AUTO decision.
   Existing rows must remain migration history and must not drive v0.
5. The minimum implementation surface is the existing
   `project/adaptive_budget.py`, provider enforcement metadata, the single
   Orchestrator integration point after routing, Scheduler measurement fields,
   CLI mode plumbing/explanation, focused tests, and concise documentation.
   No second budget manager, history store, task classifier, agent, provider,
   skill system, or benchmark platform is required.
