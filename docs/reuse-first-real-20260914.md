# Compact Project Context benchmark

Task: Add a GET /reports/monthly/{month} API endpoint that returns the selected month, total spending, and totals by category, then display that monthly total and category breakdown in the existing React dashboard. Preserve existing expense behavior and validate the work.

| Metric | Baseline | UAP |
|---|---:|---:|
| Acceptance | PASS | PASS |
| Input tokens | 0 | 0 |
| Cached input | 0 | 0 |
| Output tokens | 0 | 0 |
| Total tokens | 0 | 0 |
| Duration seconds | 900.094 | 900.094 |
| AI invocations | 1 | 1 |

Project context: 613 chars; paths: app/, frontend/.
Pre-task AI calls: 0.
Conclusion: **INCONCLUSIVE** — no benefit claim is supported by this pair.

This is one ordered pair. Provider-side caching and unavailable file-read telemetry remain limitations.

## Interpretation

Both fresh Codex processes reached the 900-second adapter timeout before returning a final
structured receipt. Their reported status is therefore `failed` with `CODEX_TIMEOUT`, even though
the independent `context-cache-monthly-v1` acceptance contract passed against both workspaces.
The zero token values are unavailable measurements, not measured zero usage, and must not be used
as evidence of savings.

The two arms began from the same source hash and both produced functioning but non-identical
implementations. Their post-run source hashes differ, which is acceptable for quality equivalence
but prevents file-by-file identity from being used as a cost proxy. Because neither process emitted
measured usage or a completed receipt, this pair cannot answer whether reusable context reduced
tokens or latency.

Two earlier sandboxed launch attempts failed before model execution with Windows access errors;
they reported unavailable usage and are excluded from the experiment. The recorded pair above is
the sandbox-exempt run authorized by the user.

Result: **quality completion observed, efficiency effect NOT_PROVEN**. A future comparison should
use a smaller bounded task or stream partial usage/progress so both arms can complete within the
receipt timeout. No automatic retry was performed.
