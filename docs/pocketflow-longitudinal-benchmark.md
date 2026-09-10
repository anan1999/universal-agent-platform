# PocketFlow longitudinal benchmark

The manual benchmark builds a Personal Expense Management App across five dependent tasks:

1. FastAPI, SQLite, expense model, CRUD API, and backend tests.
2. React dashboard.
3. Category filtering and breakdown.
4. A realistic monthly/date-filter bug fix.
5. Monthly spending report and summary.

Each task compares a fresh-session direct-provider baseline with UAP using the same explicit real
provider, goal, reasoning setting, source checkpoint, and deterministic test command. The UAP
condition retains only `.agent` Project Intelligence between tasks; neither condition receives
hidden conversation continuity. Mock fallback is forbidden.

Run manually:

```bash
python scripts/pocketflow_longitudinal_benchmark.py --execute --provider codex
```

The harness refuses to run without `--execute`, writes structured JSON under
`benchmark-results/`, and generates `docs/pocketflow-longitudinal-results.md`. It is never called
by normal pytest. Provider tokens retain their source label; unavailable metrics are not
fabricated. The script reports deviations when paired source state, provider, model, or
evaluation could not be kept equivalent.
