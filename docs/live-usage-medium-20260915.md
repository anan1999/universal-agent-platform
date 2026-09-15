# Reuse-first scale benchmark

Suite: `reuse-first-scale-v1`

| Scale | Task | Round | Order | Baseline acceptance | UAP acceptance | Baseline tokens | UAP tokens | Result |
|---:|---|---:|---|---:|---:|---:|---:|---|
| 2 | medium | 1 | disabled → enabled | PASS | PASS | 79660 | UNAVAILABLE | INCONCLUSIVE |

## medium detail

- Baseline: provider `completed`, acceptance `PASS`, token source `measured`, duration 85.516s, non-cached input 21485, cached input 56576, output 1599, tools 3, messages 2, protocol `completed`, error `External acceptance passed, but local pytest errors were not investigated before the required stop.`.
- UAP: provider `failed`, acceptance `PASS`, token source `partial_measured`, duration 240.109s, non-cached input 9292, cached input 70528, output 1545, tools 4, messages 2, protocol `timeout`, error `CODEX_TIMEOUT`.
- Conclusion: `INCONCLUSIVE` — no benefit claim is supported by this pair.

## Pooled observations

- Accepted pairs: 1.
- UAP faster pairs: 0.
- Provider duration: baseline 85.516s; UAP 240.109s; reduction -180.78%.
- Tool calls: baseline 3; UAP 4.
- Artifact-probe stops: 0; provider timeouts: 1.
- Exact token comparison available: False.

A token comparison is conclusive only when both arms pass acceptance and both providers report complete measured usage. Partial timeout telemetry is retained but never counted as proof of savings.

Exact formulas: total = input + output; non-cached input = input - cached input. Reasoning output is a subset of output and is not added again.

## Measurement finding

- The first attempt exposed an app-server JSON line larger than asyncio's 64 KiB default. The provider now uses a tested 8 MiB bounded stream limit (`0675364`). That failed infrastructure attempt is not included as a sample.
- The clean rerun preserved a complete baseline checkpoint: 78061 input, 56576 cached input, 1599 output, and 79660 total tokens.
- UAP passed the same external acceptance and emitted measured cumulative usage, but `turn/steer` acceptance did not lead to a terminal completion within 240 seconds.
- Its 81365-token notification is retained as `partial_measured`; it is deliberately excluded from the A/B token conclusion because `usage_complete=false`.

Small-scale normal closure therefore does not yet generalize to medium tasks. Do not run the large case until the post-acceptance terminal lifecycle is bounded and observable without discarding the final usage notification.
