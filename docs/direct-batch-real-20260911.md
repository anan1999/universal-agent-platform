# Batched source context — fixed-contract benchmark

Implementation: `fe01b8c931834d25e994fadb357bf34f5bb9ab2e`.
Codex `gpt-5.6-luna`, low reasoning; one ordered fresh-session pair.
Both sides received the same goal, executor instruction and explicit API wire schema.
The acceptance file was frozen before execution and unchanged afterwards.
Unlike the previous run, no offline test suite ran concurrently with this benchmark.

| Measurement | Baseline | UAP with batched source |
|---|---:|---:|
| Fixed acceptance | PASS | PASS |
| Input tokens | 172,595 | 158,633 |
| Cached input, included in input | 158,464 | 132,352 |
| Non-cached input | 14,131 | 26,281 |
| Output tokens | 4,526 | 3,545 |
| Total tokens | 177,121 | 162,178 |
| Provider execution seconds | 136.147 | 133.434 |
| Seconds including acceptance | 139.685 | 135.871 |
| Provider invocations | 1 | 1 |
| Completed tool calls | 5 | 9 |
| Assistant messages | 4 | 4 |
| Assistant message characters | 1,583 | 2,024 |

The harness's `conclusion: YES` means only that both sides passed and UAP used fewer total
measured tokens in this pair (14,943 fewer, 8.44%). **The broader goal of fewer interactions
and shorter messages is NOT met:** tool calls increased, message count was unchanged, and
message characters increased. Non-cached input also increased; no subscription-quota savings
can be inferred. Small latency differences from a single pair are not conclusive.

The initial deterministic index took 324.955 ms. The warm `prepare` function, including bounded
source retrieval, took 31.327 ms and produced 4,374 characters of support context. These are
function timings, not end-to-end CLI startup measurements. There were zero preparatory AI calls.

## Completed fixes

- The wire format is explicit and identical for both variants, eliminating the earlier ambiguity.
- `prepare --read` batches at most six relevant files and 12,000 source characters; truncated
  excerpts are identified, and unrelated directories are excluded.
- Current-task execution remains direct with no delegated provider by default.
- `check git_status` preserves the useful changed-file list on success.
- `remember` returns a nonzero exit code if the source cannot be stored.
- Human/AI onboarding, project markers, manifest and both template copies use the new path.

Validation: 41 relevant tests passed across direct execution, benchmark contract, onboarding,
ownership, package resources and simplified-core integration. Python compilation and diff checks
passed. Existing historical benchmark results have not been replaced.

## Remaining limits

This experiment does not establish a general reduction in tool use or private reasoning. It
tests targeted source delivery, not measured amortization of AI-authored knowledge from an
earlier task. Hash-validated note reuse is covered offline. Acceptance verifies backend behavior
and frontend integration source, not browser rendering. Provider cache/order effects and model
variability remain uncontrolled in a single pair.

Raw evidence: [direct-batch-real-20260911.json](../benchmark-results/direct-batch-real-20260911.json).
