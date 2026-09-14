# Adaptive provider tool-budget benchmark

The control stays at eight provider tool calls. The adaptive arm preserves eight during three externally accepted learning runs, then follows the production recommendation. Both arms use twelve assistant messages, identical source, model, reasoning, prompt shape, and frozen external acceptance.

| Round | Order | Adaptive cap | Evidence before | Fixed quality | Adaptive quality |
|---:|---|---:|---:|---:|---:|
| 1 | fixed_8 → adaptive | 8 | 0 | PASS | PASS |
| 2 | adaptive → fixed_8 | 8 | 1 | PASS | PASS |
| 3 | fixed_8 → adaptive | 8 | 2 | PASS | PASS |
| 4 | adaptive → fixed_8 | 6 | 3 | PASS | PASS |
| 5 | fixed_8 → adaptive | 6 | 4 | PASS | PASS |
| 6 | adaptive → fixed_8 | 6 | 5 | PASS | PASS |

## Cumulative

- Quality: fixed 6/6; adaptive 6/6
- Total-token reduction: 13.93%
- Uncached-token reduction: 9.19%
- Provider-tool reduction: 9.09%
- Assistant-message reduction: 0.0%
- Time reduction: 10.27%

## Post-learning rounds 4–6

- Quality: fixed 3/3; adaptive 3/3
- Total-token reduction: 26.06%
- Uncached-token reduction: 34.71%
- Provider-tool reduction: 50.0%
- Assistant-message reduction: 15.38%
- Time reduction: 20.31%

Decision: **CANDIDATE**.

Provider token measurements do not map directly to subscription quota units. This benchmark covers one software task family; cross-domain adoption requires separate accepted evidence.
