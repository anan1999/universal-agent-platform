# Reuse-first scale benchmark

Suite: `reuse-first-scale-v1`

| Scale | Task | Round | Order | Baseline acceptance | UAP acceptance | Baseline tokens | UAP tokens | Result |
|---:|---|---:|---|---:|---:|---:|---:|---|
| 1 | small | 1 | disabled → enabled | PASS | PASS | UNAVAILABLE | UNAVAILABLE | INCONCLUSIVE |
| 1 | small | 2 | enabled → disabled | PASS | PASS | UNAVAILABLE | UNAVAILABLE | INCONCLUSIVE |

## small detail

- Baseline: provider `completed`, acceptance `PASS`, token source `unavailable`, duration 62.265s, non-cached input 0, cached input 0, output 0, tools 3, messages 2, protocol `stopped`, error `none`.
- UAP: provider `completed`, acceptance `PASS`, token source `unavailable`, duration 55.125s, non-cached input 0, cached input 0, output 0, tools 3, messages 2, protocol `stopped`, error `none`.
- Conclusion: `INCONCLUSIVE` — no benefit claim is supported by this pair.

## small detail

- Baseline: provider `completed`, acceptance `PASS`, token source `unavailable`, duration 63.468s, non-cached input 0, cached input 0, output 0, tools 3, messages 2, protocol `stopped`, error `none`.
- UAP: provider `completed`, acceptance `PASS`, token source `unavailable`, duration 59.407s, non-cached input 0, cached input 0, output 0, tools 3, messages 2, protocol `stopped`, error `none`.
- Conclusion: `INCONCLUSIVE` — no benefit claim is supported by this pair.

## Pooled observations

- Accepted pairs: 2.
- UAP faster pairs: 2.
- Provider duration: baseline 125.733s; UAP 114.532s; reduction 8.91%.
- Tool calls: baseline 6; UAP 6.
- Artifact-probe stops: 4; provider timeouts: 0.
- Exact token comparison available: False.

A token comparison is conclusive only when both arms pass acceptance and both providers report complete measured usage. Partial timeout telemetry is retained but never counted as proof of savings.
