# Fresh-user cross-domain tool-budget benchmark

Every arm starts in a new Git project with no `.agent` directory, UAP history, project index, or learned budget. The experiment therefore tests whether the previously observed six-tool envelope transfers safely to unseen users and domains; it does not claim that a new user has already learned a project-specific policy.

| Domain | Order | Fixed quality | Candidate quality | Fixed tokens | Candidate tokens | Fixed tools | Candidate tools |
|---|---|---:|---:|---:|---:|---:|---:|
| product-strategy | fixed_8 → candidate_6 | PASS | PASS | 82388 | 80836 | 5 | 3 |
| research-synthesis | candidate_6 → fixed_8 | PASS | PASS | 80224 | 80801 | 3 | 3 |
| ui-ux | fixed_8 → candidate_6 | PASS | PASS | 92056 | 89723 | 5 | 3 |
| three-d-design | candidate_6 → fixed_8 | PASS | PASS | 163129 | 105573 | 5 | 4 |
| graphic-design | fixed_8 → candidate_6 | FAIL | FAIL | 121663 | 86078 | 5 | 4 |
| interior-lighting | candidate_6 → fixed_8 | PASS | PASS | 83830 | 81567 | 3 | 3 |

## Aggregate

- Quality: fixed 5/6; candidate 5/6
- Total-token reduction: 15.84%
- Uncached-token reduction: 2.65%
- Provider-tool reduction: 23.08%
- Assistant-message reduction: -20.0%
- Time reduction: 17.48%
- Per-domain token wins: 5/6

Decision: **INCOMPLETE_QUALITY**.

Quality means deterministic contract compliance, not subjective aesthetic preference. Provider tokens do not map directly to subscription quota units. Each domain has one pair, so this is a breadth check rather than a statistical estimate.
