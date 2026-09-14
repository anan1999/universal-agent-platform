# Hard tail-budget benchmark

Both arms keep validation inside the agent. The treatment changes only the provider tool-call limit from eight to three; both arms allow twelve assistant messages.

| Round | Order | Flexible quality | Hard quality | Token reduction | Uncached reduction | Tool delta | Message delta |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | flexible_8 → hard_3 | PASS | PASS | 0.72% | 5.18% | +0 | +0 |
| 2 | hard_3 → flexible_8 | PASS | PASS | 1.56% | 26.63% | +1 | +0 |
| 3 | flexible_8 → hard_3 | PASS | PASS | 0.28% | -70.02% | +1 | +0 |

## Aggregate

- Flexible quality: 3/3
- Hard-budget quality: 3/3
- Pooled total-token reduction: 0.85%
- Pooled uncached-token reduction: -27.54%
- Pooled provider-tool reduction: 25.0%
- Pooled assistant-message reduction: 0.0%
- Pooled time reduction: 21.33%

Decision: **INCONCLUSIVE** — measured cost signals disagree.
