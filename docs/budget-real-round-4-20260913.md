# UAP explicit-budget benchmark

## Problem

Add a GET /reports/monthly/{month} API endpoint that returns the selected month, total spending, and totals by category, then display that monthly total and category breakdown in the existing React dashboard. Preserve existing expense behavior and validate the work.

Both arms started from the same fixture hash, used the same model/reasoning, and were checked by the same offline acceptance test.

## Budget under test

One provider invocation, 8 advisory internal tool calls, no repeated command, one final validation pass, a 250-word final response, and a hard outer timeout.

## Results

| Arm | Quality | Tokens | Uncached tokens | Tool calls | Assistant messages | Message chars | Seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| Unbounded | PASS | 126737 | 44049 | 5 | 4 | 2175 | 106.474 |
| Budgeted | PASS | 152000 | 13760 | 5 | 4 | 2322 | 103.848 |

## Conclusion

Budget preserved quality but did not reduce measured tokens in this pair.

## Limits

- One ordered pair is evidence for this task, not a universal average.
- Subscription quota conversion is unavailable; measured provider tokens are reported when exposed.
- The Codex CLI child tool-call limit is advisory, while provider count and timeout are hard.
- Tool calls are observable JSONL events; hidden reasoning rounds are not observable.
