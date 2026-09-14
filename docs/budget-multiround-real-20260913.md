# UAP explicit-budget multi-round benchmark

## Problem

Add a GET /reports/monthly/{month} API endpoint that returns the selected month, total spending, and totals by category, then display that monthly total and category breakdown in the existing React dashboard. Preserve existing expense behavior and validate the work.

Five independent paired runs use the same source fixture, model, reasoning level and offline acceptance contract. Execution order alternates between arms.

## Per-round results

| Round | Order | Quality | Total token reduction | Uncached reduction | Tool-call delta | Time reduction |
|---:|---|---:|---:|---:|---:|---:|
| 1 | unbounded → budgeted | PASS | 29.81% | 13.74% | +2 | 28.33% |
| 2 | budgeted → unbounded | PASS | 25.58% | 11.74% | +1 | 27.79% |
| 3 | unbounded → budgeted | PASS | 9.52% | -5.12% | +1 | 5.09% |
| 4 | budgeted → unbounded | PASS | -19.93% | 68.76% | +0 | 2.47% |
| 5 | unbounded → budgeted | PASS | -2.33% | -70.22% | -2 | -24.77% |

## Aggregate

- Quality preserved in every pair: True
- Budget won total-token rounds: 3/5
- Budget won uncached-token rounds: 3/5
- Median total-token reduction: 9.52%
- Median uncached-token reduction: 11.74%
- Median time reduction: 5.09%
- Mean tool-call reduction: 0.4
- Pooled total-token reduction: 8.77%
- Pooled uncached-token reduction: 11.55%
- Pooled tool-call reduction: 7.41%
- Pooled time reduction: 7.81%
- Pooled assistant-message reduction: -11.11%
- Pooled assistant-message-character reduction: -5.54%
- Budgeted rounds within the advisory 8-tool cap: 5/5
- Budgeted rounds with no repeated exact command: 4/5

## Interpretation

A positive reduction means the budgeted arm used less. Uncached tokens are the conservative quota-oriented view. The median and pooled results favor the budget, but only 3/5 individual pairs won and one round became materially worse. The budget is therefore a useful default guardrail, not a guaranteed saving. This benchmark still covers one task family and cannot establish a universal default by itself.

## Enforcement boundary

Provider count and outer timeout are hard. UAP scheduler limits are hard across provider calls and DAG tool tasks. The number of tools used inside one Codex CLI process remains an advisory prompt contract.
