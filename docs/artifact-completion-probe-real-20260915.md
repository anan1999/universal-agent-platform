# Artifact completion probe — real small-task validation

The opt-in artifact completion probe was tested with Codex (`gpt-6-astra`, low reasoning) on the fixed `small` contract. Both arms began from the same fixture hash and both passed independent acceptance.

| Run | Arm | Acceptance | Provider protocol | Duration | Tools | Messages | Usage |
|---|---|---:|---|---:|---:|---:|---|
| Normal completion | Baseline | PASS | completed | 83.453s | 5 | 3 | measured |
| Normal completion | UAP | PASS | timeout | 300.093s | unavailable | unavailable | unavailable |
| Early completion | Baseline | PASS | stopped after probe | 60.313s | 3 | 2 | unavailable |
| Early completion | UAP | PASS | stopped after probe | 76.703s | 4 | 2 | unavailable |

The early-completion run used 137.016 seconds of provider time versus the earlier run's bounded 383.546 seconds: a directional reduction of 246.530 seconds, or 64.3%. The UAP arm no longer waited for the 180-second timeout and finished its accepted artifact in 76.703 seconds.

This comparison demonstrates that the completion mechanism prevents post-artifact idle work in this observed case. It does **not** prove a 64.3% token reduction: early termination intentionally occurs before Codex emits `turn.completed`, so exact usage is unavailable. The runs are also independent stochastic executions, not repeated randomized trials.

The probe was invoked only after completed provider-tool events. It required two consecutive acceptance passes separated by a one-second grace interval. Both receipts distinguish `artifact=completed` from `provider=stopped`. The harness independently recovered the three changed files from content hashes even though no final provider receipt was available.

Evidence:

- Normal run: `benchmark-results/measurement-real-small-20260915.json`
- Early-completion run: `benchmark-results/measurement-early-small-20260915.json`
- Generated early-completion report: `docs/measurement-early-small-20260915.md`

Next validation should repeat the small pair with alternating order before enabling this by default or moving to medium and large tasks.
