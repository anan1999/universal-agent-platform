# Reuse-first scale benchmark

Suite: `reuse-first-scale-v1`

| Scale | Task | Round | Order | Baseline acceptance | UAP acceptance | Baseline tokens | UAP tokens | Result |
|---:|---|---:|---|---:|---:|---:|---:|---|
| 3 | large | 1 | disabled → enabled | PASS | PASS | 79406 | 83793 | NO |

## large detail

- Baseline: provider `completed`, acceptance `PASS`, token source `measured`, duration 104.344s, non-cached input 40816, cached input 37120, output 1470, tools 3, messages 2, protocol `controlled_stop`, error `none`.
- UAP: provider `completed`, acceptance `PASS`, token source `measured`, duration 120.657s, non-cached input 23321, cached input 58240, output 2232, tools 4, messages 2, protocol `controlled_stop`, error `none`.
- Conclusion: `NO` — no benefit claim is supported by this pair.

## Pooled observations

- Accepted pairs: 1.
- UAP faster pairs: 0.
- Provider duration: baseline 104.344s; UAP 120.657s; reduction -15.63%.
- Tool calls: baseline 3; UAP 4.
- Artifact-probe stops: 0; provider timeouts: 0.
- Exact token comparison available: True.

A token comparison is conclusive only when both arms pass acceptance and both providers report complete measured usage. Partial timeout telemetry is retained but never counted as proof of savings.

Exact formulas: total = input + output; non-cached input = input - cached input. Reasoning output is a subset of output and is not added again.

## Large-task interpretation

- Both arms passed the same backend and React acceptance contract.
- Both arms reached a terminal `controlled_stop`; usage is complete and provider-measured.
- UAP reduced non-cached input from 40816 to 23321 tokens (42.86% lower).
- UAP increased cached input from 37120 to 58240, output from 1470 to 2232, and tool calls from 3 to 4.
- Net total usage increased from 79406 to 83793 tokens (4387, or 5.52%), while duration increased from 104.344 to 120.657 seconds (15.63%).

The reusable context is therefore selecting useful information on this larger task, but the execution policy is not converting that advantage into lower total work.
