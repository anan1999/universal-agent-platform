# Adaptive provider tool budgets

> Historical pre-v0 experiment. Its cap-4/cap-3 rules are not used by the current policy.
> See [Adaptive Budget Policy v0](adaptive-budget-v0.md) for supported behavior and commands.

This opt-in experiment targets a narrow source of subscription-AI overhead: a capable agent
continuing to inspect or converse with itself after comparable tasks have repeatedly passed an
external quality contract. It does not assume that shorter prompts or fewer tools always mean
fewer tokens.

## First-principles contract

1. No history means no learned restriction. UAP preserves the normal provider budget.
2. Comparability requires the same project environment fingerprint and a bounded task-family
   signature derived from profiles, capabilities, artifact types, complexity, risk, and read/write
   mode. Raw goal text is not stored.
3. Model-reported completion is never learning evidence.
4. A deterministic project command must be user-allowlisted and explicitly carry
   `acceptance: true`.
5. Three consecutive accepted runs can select cap 6 only when measured tool counts fit. Caps 4
   and 3 additionally require the preceding stage's median total and uncached tokens not to
   worsen, and all three recent accepted runs to fit the next cap. Missing or estimated cost never
   promotes a budget.
6. A declared acceptance failure deletes the evidence for that family. Environment changes make
   old evidence ineligible. Explicit user limits take precedence.

Enable it per run:

```bash
agentctl run "<goal>" --adaptive-provider-tool-budget
```

Inspect the selected source and evidence count using `--dry-run`. The decision appears under
`project_intelligence.adaptive_tool_budget` and the effective value appears under
`execution_budget.max_provider_tool_calls`.

The same decision is available without planning or a provider call:

```bash
agentctl budget status
agentctl budget explain "<goal>"
agentctl budget reset "<goal>"
agentctl budget reset --all
```

`status` never returns raw goals, prompts, commands, outputs, or model messages. A reset with no
goal is rejected unless `--all` is explicit, and it affects only adaptive evidence for the
current project environment.

Evidence is stored locally in `.agent/cache/adaptive-budgets.sqlite3`. It expires after 30 days
and contains task/environment hashes, accepted and measured sample counts, bounded numeric cost
metrics, effective caps, and timestamps. It is a performance hint, not proof that a future result
is correct.

## Real benchmark, 2026-09-14

Six counterbalanced pairs used the same fixture, frozen external acceptance, Codex model,
reasoning level, message cap, and prompt shape apart from the effective tool cap. The control
remained at cap 8. The adaptive arm used `8, 8, 8, 6, 6, 6` after accumulating three accepted
runs. All 12 outputs passed the external contract.

| Window | Quality | Total tokens | Uncached tokens | Provider tools | Time |
|---|---:|---:|---:|---:|---:|
| All six rounds | 6/6 vs 6/6 | 13.93% lower | 9.19% lower | 9.09% lower | 10.27% lower |
| Post-learning rounds 4–6 | 3/3 vs 3/3 | 26.06% lower | 34.71% lower | 50.0% lower | 20.31% lower |

Positive values favor adaptive. This is candidate evidence, not a universal default: one task
family cannot establish performance across research, design, documents, data analysis, or other
projects. Provider-reported tokens also do not map directly to subscription quota units.

Full measured output: [`adaptive-tool-six-round-real-20260914.md`](adaptive-tool-six-round-real-20260914.md).
