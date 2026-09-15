# Exact-token scale summary — 2026-09-15

All three tasks used Codex `gpt-6-astra` with low reasoning, the same fixed fixture, one AI invocation per arm, independent acceptance, and provider-measured usage. Every included arm passed acceptance and reported complete usage.

| Scale | Baseline total | UAP total | Total change | Baseline non-cached | UAP non-cached | Non-cached change |
|---|---:|---:|---:|---:|---:|---:|
| Small | 81269 | 103871 | +27.81% | 14657 | 23927 | +63.25% |
| Medium | 79660 | 82660 | +3.77% | 21485 | 23056 | +7.31% |
| Large | 79406 | 83793 | +5.52% | 40816 | 23321 | -42.86% |
| Pooled | 240335 | 270324 | +12.48% | 76958 | 70304 | -8.65% |

## What the current evidence says

Reusable context does not yet reduce total tokens. Across these three pairs, UAP used 29989 more total tokens. On the large task it sharply reduced non-cached input, and pooled non-cached input is 6654 tokens lower, but extra cached input, output, and tool activity more than offset that gain.

The next optimization target is execution behavior after retrieval, not further compression of the 608–617 character context packet. UAP should use retrieved paths to eliminate one discovery/tool step and prevent redundant explanation or validation work.

These are three different scale tasks with one pair each and a fixed baseline-first order, not a randomized multi-round estimate. They support diagnosis and the next experiment, not a universal savings claim.
