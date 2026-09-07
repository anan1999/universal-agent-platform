# Architecture

The platform is global and repository adapters are local. `Orchestrator` creates a persisted run, routes every task with cost/risk/history rules, and emits an acyclic graph. `Scheduler` dispatches only ready tasks, limits total and strong-model concurrency, builds bounded packets from dependency receipts, and applies a two-step escalation budget. Providers return structured receipts. Every state transition emits an event to SQLite and optional JSONL. The API exposes telemetry only; no shell endpoint exists.
