# Reuse-first scale benchmark

Suite: `reuse-first-scale-v1`

| Scale | Task | Baseline acceptance | UAP acceptance | Baseline tokens | UAP tokens | Result |
|---:|---|---:|---:|---:|---:|---|
| 1 | small | PASS | PASS | 90795 | UNAVAILABLE | INCONCLUSIVE |

## small detail

- Baseline: provider `completed`, acceptance `PASS`, token source `measured`, duration 83.453s, non-cached input 7360, cached input 81920, output 1515, tools 5, messages 3, error `none`.
- UAP: provider `failed`, acceptance `PASS`, token source `unavailable`, duration 300.093s, non-cached input 0, cached input 0, output 0, tools UNAVAILABLE, messages UNAVAILABLE, error `CODEX_TIMEOUT`.
- Conclusion: `INCONCLUSIVE` — no benefit claim is supported by this pair.

A token comparison is conclusive only when both arms pass acceptance and both providers report complete measured usage. Partial timeout telemetry is retained but never counted as proof of savings.
