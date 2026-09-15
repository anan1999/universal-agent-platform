# Reuse-first scale benchmark

Suite: `reuse-first-scale-v1`

| Scale | Task | Round | Order | Baseline acceptance | UAP acceptance | Baseline tokens | UAP tokens | Result |
|---:|---|---:|---|---:|---:|---:|---:|---|
| 1 | small | 1 | disabled → enabled | PASS | PASS | UNAVAILABLE | UNAVAILABLE | INCONCLUSIVE |

## small detail

- Baseline: provider `completed`, acceptance `PASS`, token source `unavailable`, duration 60.313s, non-cached input 0, cached input 0, output 0, tools 3, messages 2, protocol `stopped`, error `none`.
- UAP: provider `completed`, acceptance `PASS`, token source `unavailable`, duration 76.703s, non-cached input 0, cached input 0, output 0, tools 4, messages 2, protocol `stopped`, error `none`.
- Conclusion: `INCONCLUSIVE` — no benefit claim is supported by this pair.

A token comparison is conclusive only when both arms pass acceptance and both providers report complete measured usage. Partial timeout telemetry is retained but never counted as proof of savings.
