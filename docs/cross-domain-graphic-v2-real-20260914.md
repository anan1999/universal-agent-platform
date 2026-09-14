# Fresh-user cross-domain tool-budget benchmark

Every arm starts in a new Git project with no `.agent` directory, UAP history, project index, or learned budget. The experiment therefore tests whether the previously observed six-tool envelope transfers safely to unseen users and domains; it does not claim that a new user has already learned a project-specific policy.

| Domain | Order | Fixed quality | Candidate quality | Fixed tokens | Candidate tokens | Fixed tools | Candidate tools |
|---|---|---:|---:|---:|---:|---:|---:|
| graphic-design | fixed_8 → candidate_6 | PASS | FAIL | 84828 | 84893 | 3 | 4 |

## Aggregate

- Quality: fixed 1/1; candidate 0/1
- Total-token reduction: -0.08%
- Uncached-token reduction: -146.82%
- Provider-tool reduction: -33.33%
- Assistant-message reduction: 33.33%
- Time reduction: -2.82%
- Per-domain token wins: 0/1

Decision: **REJECT_QUALITY**.

Quality means deterministic contract compliance, not subjective aesthetic preference. Provider tokens do not map directly to subscription quota units. Each domain has one pair, so this is a breadth check rather than a statistical estimate.
