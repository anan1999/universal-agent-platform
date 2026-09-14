# Live Codex provider-budget acceptance

## Result

Both live cancellation paths returned `BUDGET_EXHAUSTED` without automatic retry.

| Limit | Envelope | Observed | Duration | Result |
|---|---|---|---:|---:|
| Assistant messages | 1 message | stopped after the second completed message; 0 tools | 18.468 s | PASS |
| Provider tools | 0 tools | stopped when the first tool started; 0 completed tools and 0 messages | 5.672 s | PASS |

The tool test used `benchmark-fixtures/live-budget`, not the UAP source workspace. This
avoids confusing the counter with a host read-only execution-policy rejection. One retained
negative run against the source workspace returned `CODEX_CAPABILITY_UNAVAILABLE` before a
tool event and is not counted as a budget success.

## What is enforced

`CodexProvider` reads JSONL incrementally. Completed command, MCP and web-search events count
as provider tools. When a new tool starts after the allowance is consumed, UAP terminates the
child process. Completed assistant-message events are counted independently; exceeding that
allowance also terminates the child.

This is a fail-closed execution limit, not a token-saving guarantee. A stopped child produces
no successful receipt, provider usage may be unavailable, and any edits completed before the
limit remain in its isolated workspace for inspection.
