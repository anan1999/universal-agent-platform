# Cold, warm, and revalidation starts

A **cold start** has no current, relevant Project Intelligence. The task may inspect the
repository, and deterministic project discovery is distilled only after execution.

A **warm start** retrieves current metadata first, ranks it against goal capabilities and tags,
then loads bounded details. Reuse is counted only for context actually loaded into execution.

A **revalidation start** occurs when a related source hash changes. Stale items are listed with
the reason and excluded. Other current items may still be reused. Revalidation refreshes the
source hashes, evidence, verification timestamp, and commit before the item becomes current.

`agentctl warm-start "<goal>" --json` and its `resume` alias are read-only previews. They do not
claim a reuse hit until an execution is recorded.
