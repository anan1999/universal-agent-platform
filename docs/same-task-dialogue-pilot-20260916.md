# Same-task dialogue pilot (2026-09-16)

This is the first paired *persistent-thread* test. Each arm used one Codex
app-server thread with two successive user turns, not two fresh provider
sessions. The model was `gpt-5.6-sol` at low reasoning. Both arms began from
the same UI/UX medication-planner fixture and received the same two goals.
The baseline used a short plain request. The UAP arm used project initialization
and a rendered UAP execution packet on each turn. This tests a UAP-conditioned
conversation, **not** the entire Orchestrator and not cross-task memory.

| Arm | Turn 1 total | Turn 2 total | Two-turn total | Cached input | Uncached input + output | Contract |
|---|---:|---:|---:|---:|---:|---|
| Baseline | 127,698 | 247,733 | 375,431 | 344,064 | 31,367 | 2/2 pass |
| UAP-conditioned | 109,265 | 161,615 | 270,880 | 211,328 | 59,552 | 2/2 pass |

Provider-reported cumulative token usage was differenced at each turn; cached
input is included within input, not added again. On this single paired case,
UAP-conditioned total tokens were **27.85% lower**, but *uncached* tokens were
**89.86% higher**. Turn 2 was more expensive than turn 1 in both arms. The
roughly 211–213 seconds per arm were similar. A lower total here must not be
equated with lower subscription quota consumption or model cost.

Both artifacts passed the same deterministic `design-longitudinal-v1` checks
for the first two rounds. This does not establish equivalent aesthetic quality,
usability, or absence of untested defects. The arms were run sequentially, with
only one pair, and the UAP arm changed both project setup and prompt policy;
therefore this result does not isolate which UAP component caused the difference.
It also does not prove that longer conversations get progressively cheaper.

The raw run report and artifacts are in
`.benchmark-same-task-dialogue-sol-20260916-r3/` (local, untracked evidence).
The runner is `scripts/same_task_dialogue_benchmark.py`. A next experiment
should replicate across projects/domains, counterbalance arm order, run a third
follow-up, and separately compare actual Orchestrator behavior and cross-task
Project Intelligence reuse. Quality-sensitive design work should also have
blind human review.
