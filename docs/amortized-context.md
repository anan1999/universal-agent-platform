# Amortized context

V2.3 treats project understanding as an investment that should be reused across tasks. The
first run may need repository discovery; later runs retrieve verified project intelligence
before exploring. The platform therefore reports both per-task cost and cumulative cost.

The lifecycle metric records provider tokens separately from UAP-controlled context size.
`context_chars` and `estimated_tokens` measure only selected durable context; provider tokens
remain `measured`, `estimated`, or `unavailable` according to the provider receipt. These values
must not be conflated.

Break-even is the smallest task number where cumulative UAP cost is no greater than cumulative
direct-provider baseline cost. A cold task may cost more. If no break-even occurs, the report
must say so rather than extrapolating savings.

Use `ProjectIntelligenceStore.amortization()` for deterministic accounting and the explicit
PocketFlow benchmark for provider-measured evidence.
