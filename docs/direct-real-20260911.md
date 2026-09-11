# Direct task benchmark — 2026-09-11

Measured implementation: `4587496ce4280e30afd84922627d97d3410e1b6c`.
Provider: Codex, model `gpt-5.6-luna`, reasoning `low`.
Task: add a monthly spending endpoint and integrate it with the React dashboard.

| Measurement | Baseline | UAP direct support |
|---|---:|---:|
| Fixed acceptance | PASS | FAIL |
| Input tokens | 191,351 | 173,359 |
| Cached input tokens (included in input) | 142,336 | 147,456 |
| Non-cached input tokens | 49,015 | 25,903 |
| Output tokens | 4,685 | 3,837 |
| Total tokens | 196,036 | 177,196 |
| Duration including acceptance, seconds | 161.934 | 172.976 |
| Provider invocations | 1 | 1 |
| Observable completed tool calls | 8 | 11 |
| Assistant messages | 4 | 4 |
| Assistant message characters | 2,391 | 1,733 |

UAP context preparation made zero provider calls. Initial deterministic index creation took
203.573 ms; warm preparation took 2.834 ms. The support packet added 661 characters. The two
application source hashes matched. Acceptance SHA-256 was locked before execution and unchanged.

The fixed result is **INCONCLUSIVE** for equal-quality cost reduction. Total measured tokens were
18,840 lower (9.61%), but tool calls increased, message count was unchanged, and elapsed time
increased. This does not prove reduced internal reasoning or reduced subscription usage.

## Failure diagnosis

UAP implemented the endpoint, frontend integration and a test, but used response keys
`selected_month`, `total_spending`, and `totals_by_category`. The fixed acceptance expects
`month`, `total`, and `categories` (or `by_category`). The original task described these concepts
without spelling out wire keys. This is a benchmark specification ambiguity, not evidence that
the endpoint was absent. We preserve the raw FAIL and have not changed the evaluator or outputs
after the run. A subsequent harness correction explicitly supplies the expected wire schema to
both variants. That correction has only been tested offline and has not been benchmarked again.

## Scope and limitations

- One ordered pair; model variability and provider cache effects are not controlled.
- Offline regression tests ran concurrently; elapsed time is not an isolated latency measurement.
- Acceptance tests backend behavior and frontend source integration, not browser rendering.
- Observable tool calls and assistant messages are not private reasoning rounds.
- This pair tests index reuse and compact instructions; source-linked notes from a previous AI
  task are covered by offline invalidation/retrieval tests, not a measured learning-cost experiment.
- The direct CLI removes UAP-owned provider delegation by construction. Both benchmark variants
  intentionally use a single provider invocation, so the pair does not measure that structural
  change against the old orchestrator.

Raw evidence: [direct-real-20260911.json](../benchmark-results/direct-real-20260911.json).

Offline validation: 193 tests passed (one existing Starlette deprecation warning), plus the
post-run wire-contract regression tests. CLI `prepare`, `--help`, and `check project_test`
were exercised; the latter ran the fixture's test and returned only a compact success result.
