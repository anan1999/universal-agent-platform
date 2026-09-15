# Reuse-first scale benchmark

Suite: `reuse-first-scale-v1`

| Scale | Task | Round | Order | Baseline acceptance | UAP acceptance | Baseline tokens | UAP tokens | Result |
|---:|---|---:|---|---:|---:|---:|---:|---|
| 1 | small | 1 | disabled → enabled | PASS | PASS | 81269 | 103871 | NO |

## small detail

- Baseline: provider `completed`, acceptance `PASS`, token source `measured`, duration 77.093s, non-cached input 14657, cached input 65280, output 1332, tools 3, messages 2, protocol `completed`, error `Local test execution was blocked; acceptance success was reported by the user.`.
- UAP: provider `completed`, acceptance `PASS`, token source `measured`, duration 90.281s, non-cached input 23927, cached input 78464, output 1480, tools 4, messages 3, protocol `completed`, error `Local summary tests were blocked by filesystem permissions; external acceptance passed per user report.`.
- Conclusion: `NO` — no benefit claim is supported by this pair.

## Pooled observations

- Accepted pairs: 1.
- UAP faster pairs: 0.
- Provider duration: baseline 77.093s; UAP 90.281s; reduction -17.11%.
- Tool calls: baseline 3; UAP 4.
- Artifact-probe stops: 0; provider timeouts: 0.
- Exact token comparison available: True.

A token comparison is conclusive only when both arms pass acceptance and both providers report complete measured usage. Partial timeout telemetry is retained but never counted as proof of savings.

Exact formulas: total = input + output; non-cached input = input - cached input. Reasoning output is a subset of output and is not added again.

## Live usage lifecycle validation

- Codex app-server emitted cumulative token-usage notifications during execution.
- External acceptance passed while the provider turn was still active.
- UAP sent `turn/steer`; Codex accepted it and the original execution turn then completed normally.
- The final UAP receipt records `artifact=completed`, `provider=completed`, `usage_complete=true`, and `token_source=measured`.
- UAP exact usage: input 102391 (cached 78464; non-cached 23927), output 1480 (reasoning 26), total 103871.
- This closes the previous failure mode where the artifact was complete but a timeout prevented complete usage from qualifying as exact evidence.

This run validates measurement correctness, not token savings. Both arms passed the same acceptance contract, but UAP used 22602 more total tokens (27.81%) in this pair, so the benchmark correctly reports `NO`.
