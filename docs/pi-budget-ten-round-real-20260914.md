# UAP Pi-inspired context + budget benchmark

Both arms use the existing explicit budget. The experimental arm additionally uses a hard-bounded, progressively disclosed project context and source excerpts.

| Round | Order | Quality | Total token reduction | Uncached reduction | Tool-call delta | Message delta | Time reduction |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | budget_only → pi_context | PASS | -21.69% | 68.17% | +0 | +0 | -16.27% |
| 2 | pi_context → budget_only | PASS | -28.15% | 34.15% | +0 | -1 | -51.9% |
| 3 | budget_only → pi_context | PASS | -40.72% | -27.88% | +0 | +0 | -48.42% |
| 4 | pi_context → budget_only | FAIL | -4.7% | -3.76% | -1 | +0 | -2.47% |
| 5 | budget_only → pi_context | PASS | -2.09% | -26.67% | +0 | +2 | 12.16% |
| 6 | pi_context → budget_only | PASS | -86.15% | -40.06% | -3 | -1 | -55.11% |
| 7 | budget_only → pi_context | PASS | 11.23% | -1.79% | +1 | +1 | 14.38% |
| 8 | pi_context → budget_only | PASS | 29.45% | -17.81% | +6 | +1 | 31.13% |
| 9 | budget_only → pi_context | PASS | 41.03% | -89.33% | +3 | +0 | 37.35% |
| 10 | pi_context → budget_only | PASS | -94.44% | -82.46% | -2 | +0 | -40.69% |

## Aggregate

- Quality preserved in every pair: False
- Pi-context total-token wins: 3/10
- Pi-context uncached-token wins: 2/10
- Median total-token reduction: -13.2%
- Median uncached-token reduction: -22.24%
- Pooled total-token reduction: -15.58%
- Pooled uncached-token reduction: -5.85%
- Pooled tool-call reduction: 8.16%
- Pooled assistant-message reduction: 4.76%
- Pooled assistant-message-character reduction: 9.69%
- Pooled time reduction: -7.9%

## Interpretation

Positive values favor the Pi-inspired context arm. Provider-reported cached input is removed in the uncached view. This measures one task family; it does not convert tokens into subscription quota units.

The fixed 4,000-character source-context policy is rejected as a default: it reduced observable interactions but increased pooled total tokens, uncached tokens, and elapsed time, and one experimental result failed external acceptance. Keep explicit hard budgets; load source excerpts only when expected avoided discovery cost exceeds their context cost, and never bypass deterministic acceptance gates.
