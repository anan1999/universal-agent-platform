# Silent validation-memory benchmark

The cold arm receives three validation candidates. After one zero-AI successful check, the warm arm receives the same context shape with only the proven candidate.

| Round | Order | Cold quality | Warm quality | Total reduction | Uncached reduction | Tool delta | Message delta | Time reduction |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | cold_candidates → silent_memory | PASS | PASS | 23.67% | 48.28% | +1 | +1 | 38.34% |
| 2 | silent_memory → cold_candidates | PASS | PASS | -64.42% | 12.04% | -1 | -1 | -118.77% |
| 3 | cold_candidates → silent_memory | PASS | PASS | 15.28% | -90.44% | +1 | -1 | 16.99% |

## Aggregate

- Cold quality: 3/3
- Silent-memory quality: 3/3
- Pooled total-token reduction: -1.25%
- Pooled uncached-token reduction: -1.14%
- Pooled tool-call reduction: 10.0%
- Pooled assistant-message reduction: -8.33%
- Pooled time reduction: -2.5%

Positive values favor silent validation memory. Quality remains a hard gate.

Decision: **INCONCLUSIVE** — silent selection preserved quality and reduced tool calls, but did not reduce pooled measured tokens. Keep it opt-in; move validation execution to a deterministic parent task before claiming amortized token savings.
