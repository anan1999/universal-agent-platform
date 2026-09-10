# Project intelligence

Project Intelligence is durable, project-scoped evidence—not conversation memory. Its metadata
index is `.agent/intelligence.json`; optional details live under `.agent/knowledge/` and are
loaded only after metadata retrieval selects an item for the current goal.

Supported categories are knowledge, decisions, Skills, Agent roles, commands, evaluations,
artifacts, known issues, task history, and compact receipts. Every item has an identity,
summary, evidence, validation state, source paths and hashes when applicable, confidence,
status, verification time, and reuse count.

Creation gates require a non-empty summary and explicit evidence. Reusable Skills and Agent
roles additionally require validation and expected reuse of at least two tasks. Re-adding an
identical identity is deduplicated. A contradictory replacement supersedes the prior item; it
does not erase history.

Source hashes are checked before selection. Changed or missing related files move an item to
`needs_revalidation`, preventing silent reuse. Maintenance returns archive, review,
revalidation, and prune recommendations but never deletes evidence automatically.

Maturity is derived from evidence:

| Level | Meaning |
|---:|---|
| 0 | Unknown: no current intelligence |
| 1 | Discovered: evidence exists, little demonstrated reuse |
| 2 | Learned: multiple runs and reuse hits |
| 3 | Optimized: at least five runs and five reuse hits |

Inspect it with `agentctl status --json` or `agentctl context explain "<goal>" --json`.

## Layered retrieval

Execution context is assembled in layers: project knowledge and decisions, current task,
validated Agent-role context, selected Skill instructions/references, dependency receipts, and
provider/model routing. Project metadata is ranked first; only selected detail files enter the
packet. The explain payload names each item and its evidence so context is attributable.
