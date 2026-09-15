# Reuse-first scale benchmark

Suite: `reuse-first-scale-v1`

| Scale | Task | Round | Order | Baseline acceptance | UAP acceptance | Baseline tokens | UAP tokens | Result |
|---:|---|---:|---|---:|---:|---:|---:|---|
| 1 | small | 1 | disabled → enabled | PASS | PASS | 89921 | UNAVAILABLE | INCONCLUSIVE |

## small detail

- Baseline: provider `completed`, acceptance `PASS`, token source `measured`, duration 89.312s, non-cached input 19711, cached input 68992, output 1218, tools 4, messages 3, protocol `completed`, error `none`.
- UAP: provider `failed`, acceptance `PASS`, token source `unavailable`, duration 240.094s, non-cached input 0, cached input 0, output 0, tools UNAVAILABLE, messages UNAVAILABLE, protocol `failed`, error `CODEX_TIMEOUT`.
- Conclusion: `INCONCLUSIVE` — no benefit claim is supported by this pair.

## Pooled observations

- Accepted pairs: 1.
- UAP faster pairs: 0.
- Provider duration: baseline 89.312s; UAP 240.094s; reduction -168.83%.
- Tool calls: baseline None; UAP None.
- Artifact-probe stops: 0; provider timeouts: 1.
- Exact token comparison available: False.

A token comparison is conclusive only when both arms pass acceptance and both providers report complete measured usage. Partial timeout telemetry is retained but never counted as proof of savings.

Exact formulas: total = input + output; non-cached input = input - cached input. Reasoning output is a subset of output and is not added again.
