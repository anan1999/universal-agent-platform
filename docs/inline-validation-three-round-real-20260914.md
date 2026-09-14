# Exact in-session validation benchmark

Treatment command: `python .agent/acceptance.py --project .`

| Round | Order | Generic quality | Declared quality | Total token reduction | Uncached reduction | Tool delta | Message delta | Time reduction |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | generic_validation → declared_validation | PASS | PASS | -55.24% | -372.89% | -1 | -1 | -44.78% |
| 2 | declared_validation → generic_validation | PASS | PASS | -0.62% | 67.2% | +0 | -1 | 3.71% |
| 3 | generic_validation → declared_validation | PASS | PASS | -29.02% | 26.36% | -1 | -1 | -38.31% |

## Aggregate

- Generic quality: 3/3
- Declared-command quality: 3/3
- Quality repairs: 0
- Quality regressions: 0
- Pooled total-token reduction: -28.3%
- Pooled uncached-token reduction: -3.49%
- Pooled tool-call reduction: -33.33%
- Pooled assistant-message reduction: -30.0%
- Pooled time reduction: -25.49%

Positive reductions favor the exact declared validation command. This small run is a screening test, not sufficient evidence for a default policy.

Decision: reject the verbose declared-validation and repair instruction as a default. It preserved quality but increased aggregate execution cost. Test a minimal canonical command handle without anticipatory repair instructions next.
