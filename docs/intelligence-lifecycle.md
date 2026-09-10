# Intelligence lifecycle

1. Initialize an empty metadata index with `agentctl init --auto`.
2. Classify the run as cold, warm, or revalidation before provider execution.
3. Select relevant current metadata and load only bounded details.
4. Attach summaries, evidence attribution, active decisions, and known issues to execution
   packets before repository rediscovery.
5. Persist a compact lifecycle record in SQLite and `.agent/intelligence.json`.
6. After a cold run, distill deterministic project markers and allowlisted commands.
7. Store only a bounded outcome receipt—never provider prose, conversation, or chain-of-thought.
8. Invalidate source-related facts on hash changes and preserve superseded history.

The SQLite schema is additive. `project_intelligence_runs` stores lifecycle mode, reason, reuse,
rediscovery, and UAP context size. The Git-friendly JSON index remains the project-scoped source
of durable memory.
