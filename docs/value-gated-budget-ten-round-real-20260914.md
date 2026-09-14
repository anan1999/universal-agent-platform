# UAP Pi-inspired context + budget benchmark

Context strategy: `value_gated`. Both arms use the existing explicit budget. The experimental arm additionally uses hard-bounded progressive project context.

| Round | Order | Quality | Total token reduction | Uncached reduction | Tool-call delta | Message delta | Time reduction |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | budget_only → pi_context | PASS | 37.82% | 69.59% | -1 | +1 | 40.76% |
| 2 | pi_context → budget_only | PASS | 17.26% | 59.89% | -1 | +0 | 17.3% |
| 3 | budget_only → pi_context | PASS | 0.42% | -5.03% | -1 | +2 | 0.63% |
| 4 | pi_context → budget_only | PASS | -24.83% | 31.28% | -1 | -1 | -2.68% |
| 5 | budget_only → pi_context | PASS | -49.5% | -69.38% | -4 | -2 | -48.5% |
| 6 | pi_context → budget_only | PASS | 33.83% | 4.48% | +0 | +1 | 16.89% |
| 7 | budget_only → pi_context | PASS | -1.15% | -9.1% | +3 | -1 | 11.88% |
| 8 | pi_context → budget_only | PASS | 43.42% | 16.43% | +4 | -1 | 33.59% |
| 9 | budget_only → pi_context | PASS | 30.1% | -36.12% | +1 | -1 | 19.55% |
| 10 | pi_context → budget_only | FAIL | 39.93% | 8.55% | +3 | +2 | 24.89% |

## Aggregate

- Quality preserved in every pair: False
- Pi-context total-token wins: 7/10
- Pi-context uncached-token wins: 6/10
- Median total-token reduction: 23.68%
- Median uncached-token reduction: 6.52%
- Pooled total-token reduction: 19.17%
- Pooled uncached-token reduction: 16.85%
- Pooled tool-call reduction: 6.12%
- Pooled assistant-message reduction: 0.0%
- Pooled assistant-message-character reduction: -4.67%
- Pooled time reduction: 14.91%

## Interpretation

Positive values favor the Pi-inspired context arm. Provider-reported cached input is removed in the uncached view. This measures one task family; it does not convert tokens into subscription quota units.


Value-gated mode defaults to path/hash pointers and admits source bodies only when source-linked measured savings exceed preload cost plus a safety margin. External acceptance remains authoritative.
Across this run, the gate admitted 0 source bodies; this is therefore a pointer-only progressive-context test, not evidence that preloading source code helps.

Decision: reject value-gated progressive context as a default in its current form. Aggregate cost improved, but one experimental implementation failed deterministic external acceptance while its control passed. Keep the gate opt-in until a repair/verification loop preserves quality across repeated and cross-domain benchmarks.
