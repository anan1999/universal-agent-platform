# UAP explicit-budget benchmark

## Problem

Add a GET /reports/monthly/{month} API endpoint that returns the selected month, total spending, and totals by category, then display that monthly total and category breakdown in the existing React dashboard. Preserve existing expense behavior and validate the work.

Both arms started from the same fixture hash, used the same model/reasoning, and were checked by the same offline acceptance test.

## Budget under test

One provider invocation, 8 advisory internal tool calls, no repeated command, one final validation pass, a 250-word final response, and a hard outer timeout.

## Results

| Arm | Quality | Tokens | Uncached tokens | Tool calls | Assistant messages | Message chars | Seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| Unbounded | PASS | 144807 | 25767 | 6 | 4 | 2618 | 109.783 |
| Budgeted | PASS | 131021 | 27085 | 5 | 4 | 2077 | 104.194 |

## Conclusion

Budget preserved quality and reduced measured tokens by 9.52%.

## Limits

- One ordered pair is evidence for this task, not a universal average.
- Subscription quota conversion is unavailable; measured provider tokens are reported when exposed.
- The Codex CLI child tool-call limit is advisory, while provider count and timeout are hard.
- Tool calls are observable JSONL events; hidden reasoning rounds are not observable.
