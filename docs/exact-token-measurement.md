# Exact token measurement

UAP treats only provider-reported usage as exact. It does not estimate tokens
from characters, words, elapsed time, tool calls, or a local tokenizer.

For a completed Codex turn, the measured fields are:

- `input_tokens`: all input tokens, including cached input.
- `cached_input_tokens`: the subset of input served from cache.
- `cache_write_input_tokens`: input written to a provider cache, when reported.
- `output_tokens`: all output tokens, including reasoning output.
- `reasoning_output_tokens`: the subset of output used for reasoning.
- `total_tokens`: `input_tokens + output_tokens`.

Derived comparisons use:

```text
non_cached_input_tokens = input_tokens - cached_input_tokens
total_tokens            = input_tokens + output_tokens
```

Do not add `reasoning_output_tokens` to `output_tokens`; it is already a
subset. Likewise, do not add `cached_input_tokens` to `input_tokens`.

`scripts/context_cache_benchmark.py` defaults to `--metric exact-tokens`.
Both arms must finish normally, pass the same acceptance test, and report
`token_source=measured`. Otherwise the pair is inconclusive and no token-saving
claim is allowed.

The artifact early-completion probe intentionally interrupts the provider. It
can measure latency and observable tool calls, but cannot prove complete token
usage because a final in-flight response may not have emitted usage. Therefore
`--early-completion` is rejected in exact-token mode. It is available only with
an explicit `--metric latency` selection.

Codex subscription quota percentage is a separate service limit. UAP records
provider token usage, but does not claim a token-to-subscription-quota conversion
because no stable conversion is exposed to the benchmark.
