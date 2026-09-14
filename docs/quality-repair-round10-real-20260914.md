# Bounded quality-repair replay

Initial failure: `AssertionError: Path parameters cannot have a default value`

| Metric | Original control | Experimental + repair |
|---|---:|---:|
| External acceptance | PASS | PASS |
| Provider calls | 1 | 2 |
| Total tokens | 148454 | 192230 |
| Uncached tokens | 43494 | 48102 |
| Tool calls | 6 | 6 |
| Assistant messages | 5 | 4 |

Total-token reduction after repair: -29.49%.
Uncached-token reduction after repair: -10.59%.
Decision: **REJECT_COST**.

This is a replay of one observed failure, not a fresh randomized pair. It tests whether one bounded repair can close quality without erasing the observed saving.
