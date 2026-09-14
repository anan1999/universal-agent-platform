# Exact in-session validation benchmark

Treatment command: `python .agent/acceptance.py --project .`

| Round | Order | Generic quality | Declared quality | Total token reduction | Uncached reduction | Tool delta | Message delta | Time reduction |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | generic_validation → declared_validation | PASS | PASS | 0.34% | 2.6% | +0 | +0 | 12.1% |
| 2 | declared_validation → generic_validation | PASS | PASS | 0.79% | -92.04% | +0 | +1 | 5.52% |
| 3 | generic_validation → declared_validation | PASS | PASS | -28.71% | -85.51% | -1 | -1 | -19.88% |

## Aggregate

- Generic quality: 3/3
- Declared-command quality: 3/3
- Quality repairs: 0
- Quality regressions: 0
- Pooled total-token reduction: -9.12%
- Pooled uncached-token reduction: -63.97%
- Pooled tool-call reduction: -16.67%
- Pooled assistant-message reduction: 0.0%
- Pooled time reduction: -0.45%

Positive reductions favor the exact declared validation command. This small run is a screening test, not sufficient evidence for a default policy.

Decision: reject explicit prompt emphasis of the declared validation command as a default. The compact context already exposes the canonical command; repeating and emphasizing it preserved quality but increased aggregate execution cost.
