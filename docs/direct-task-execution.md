# Direct task execution

The current AI task is the executor. UAP supplies deterministic context and checks without
starting a second AI. This removes platform-owned planning, role selection and handoff calls
from the ordinary path; it does not control the host model's private reasoning.

```bash
agentctl init --auto --upgrade
agentctl prepare "<task goal>" --read --json
# The current AI reads relevant source, implements and validates.
agentctl check project_test
agentctl remember app/main.py "<short fact verified against this source>"
```

Initialization upgrades only the UAP marker in AGENTS.md, preserving user instructions outside
the marker. Existing projects need this upgrade to replace older delegation instructions.
The `prepare` command also works on a fresh project: it creates the compact index lazily.
No global setup, provider probe, SQLite database or model selection is needed by these three
direct commands. Standalone delegated `run` and `orchestrate` remain opt-in.

`prepare` returns relevant path hints, architecture, commands to verify, and up to eight
source-linked notes. It reads no prior conversation. The current task still reads actual source
when needed. `remember` accepts one short fact tied to one file, capped at 320 characters.
With `--read`, bounded directory discovery adds up to six relevant source excerpts, capped at
12,000 characters total. It examines only the selected directories and their immediate `src`
children. Excerpts are marked when truncated. Omit this option when path hints suffice.
It hashes that file; this proves source freshness, not factual correctness of AI-authored text.
The executing AI is responsible for checking its fact before saving it. No useful new fact
means no write. Commit useful `.agent` context with the corresponding source changes so later
tasks/worktrees receive it. Concurrent tasks should merge their source and notes through Git;
unmerged knowledge is not automatically shared across worktrees.

`check` uses existing allowlisted tools and returns compact JSON. Successful command logs are
suppressed; failures retain bounded output. Missing commands or skipped checks yield a nonzero
exit status. Check only what is relevant, and repeat checks only after new changes or failures.
`git_status` retains successful output because the changed-file list is its useful result.

## Benchmark protocol

`scripts/direct_benchmark.py` creates two isolated Git workspaces with identical application
source and the same goal, executor instruction, model, reasoning setting and external acceptance.
Baseline gets the goal. UAP gets the same goal plus `prepare` output. Neither receives an
orchestrator-selected role or spawns extra agents. Both are fresh ephemeral Codex executions.

The harness records total/input/output/cached tokens, elapsed time, observable completed tool
calls, assistant message count/characters, and acceptance. It locks the acceptance file hash
before execution and never reruns an AI automatically. Results are persisted after each side.
Internal reasoning rounds and subscription quota conversion are unavailable. A short visible
response is not evidence of reduced internal reasoning. One ordered pair cannot establish
general savings or eliminate provider caching/order effects.

This pair tests index reuse and direct-task instructions. Cross-task AI-authored notes and stale
source rejection are verified offline; this pair does not claim measured amortization of a
previous AI task's learning cost. The acceptance checks backend behavior and frontend source
integration, not browser rendering or a complete production-quality audit.

Latest [fixed-contract benchmark](direct-batch-real-20260911.md): both variants passed and UAP
used 8.44% fewer total tokens in one pair, but tool calls and visible message length increased.
This is not evidence of fewer interactions or lower subscription-quota usage.
