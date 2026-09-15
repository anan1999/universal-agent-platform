# Reuse-first scale benchmark

Suite: `reuse-first-scale-v1`

| Scale | Task | Round | Order | Baseline acceptance | UAP acceptance | Baseline tokens | UAP tokens | Result |
|---:|---|---:|---|---:|---:|---:|---:|---|
| 2 | medium | 1 | disabled → enabled | PASS | PASS | 79660 | 82660 | NO |

## medium detail

- Baseline: provider `completed`, acceptance `PASS`, token source `measured`, duration 85.516s, non-cached input 21485, cached input 56576, output 1599, tools 3, messages 2, protocol `completed`, error `External acceptance passed, but local pytest errors were not investigated before the required stop.`.
- UAP: provider `completed`, acceptance `PASS`, token source `measured`, duration 103.25s, non-cached input 23056, cached input 57856, output 1748, tools 3, messages 2, protocol `controlled_stop`, error `none`.
- Conclusion: `NO` — no benefit claim is supported by this pair.

## Pooled observations

- Accepted pairs: 1.
- UAP faster pairs: 0.
- Provider duration: baseline 85.516s; UAP 103.25s; reduction -20.74%.
- Tool calls: baseline 3; UAP 3.
- Artifact-probe stops: 0; provider timeouts: 0.
- Exact token comparison available: True.

A token comparison is conclusive only when both arms pass acceptance and both providers report complete measured usage. Partial timeout telemetry is retained but never counted as proof of savings.

Exact formulas: total = input + output; non-cached input = input - cached input. Reasoning output is a subset of output and is not added again.

## Controlled-shutdown validation

The first clean medium run passed artifact acceptance but waited until the 240.109-second outer timeout after `turn/steer` was accepted. Its partial usage was correctly excluded. After adding a 20-second steer grace period, a controlled interrupt, and a 15-second terminal grace period, the UAP arm completed in 103.25 seconds with:

- `artifact=completed`
- `provider=controlled_stop`
- `usage_complete=true`
- `token_source=measured`
- exact total usage of 82660 tokens

The fix removed 136.859 seconds from the observed failure path and converted the previously inconclusive arm into valid exact evidence. It does not establish token savings: baseline used 79660 tokens, so UAP used 3000 more tokens (3.77%) in this pair.
