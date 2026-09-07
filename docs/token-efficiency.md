# Token efficiency

Before every request, `ExecutionPacketBuilder` includes only role, task and overall goal, minimal project identity, at most four summarized dependency receipts, allowed files, required skills, constraints, and the expected schema. Each receipt summary is capped at 160 words.

The analyzer flags strong models on mechanical tasks, oversized receipts, and excessive escalation. Codex model input usage can remain large because the CLI supplies its own base instructions and tool context; measured usage describes the whole Codex turn, not only the platform packet. Cached tokens are stored separately.

