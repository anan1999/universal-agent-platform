# Compact Project Context benchmark

Task: Add a GET /reports/monthly/{month} API endpoint that returns the selected month, total spending, and totals by category, then display that monthly total and category breakdown in the existing React dashboard. Preserve existing expense behavior and validate the work.

| Metric | Baseline | UAP |
|---|---:|---:|
| Acceptance | PASS | FAIL |
| Input tokens | 153819 | 50065 |
| Cached input | 128256 | 16128 |
| Output tokens | 3337 | 784 |
| Total tokens | 157156 | 50849 |
| Duration seconds | 112.235 | 32.156 |
| AI invocations | 1 | 1 |

Project context: 600 chars; paths: app/, frontend/.
Pre-task AI calls: 0.
Conclusion: **INCONCLUSIVE** — no benefit claim is supported by this pair.

This is one ordered pair. Provider-side caching and unavailable file-read telemetry remain limitations.

The acceptance contract was reevaluated offline after the run to accept either `categories` or
`by_category`; the task required category totals but did not prescribe the response-key spelling.
No provider was rerun. Baseline then passed. UAP still failed because the endpoint was absent.

Post-run diagnosis found that deterministic goal analysis activated the software profile but did
not classify the words `endpoint` and `validate` as coding/testing capabilities. UAP consequently
assigned an Analyst responsibility, which returned a completed receipt without changing the
workspace. The lexicon and a regression test were corrected after this measured pair. Because the
tested UAP output failed acceptance, the result remains **INCONCLUSIVE** regardless of its lower
measured tokens and duration.
