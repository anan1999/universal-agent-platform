# AI Bootstrap Contract

**You are reading this because a user asked you to use this repository as their agent
orchestration framework.** This document tells you exactly what to do. Read it fully before
you touch the user's project.

The machine-readable version of everything below is [`agent-platform.json`](agent-platform.json).
If you prefer structured input, read that file instead and use this one as the rationale.

---

## 1. What this framework is

The Universal Agent Platform supports the AI already executing the user's task.

By default, `prepare` reads a compact project index and relevant source-linked notes. The current
AI continues implementation and deterministic validation. No provider is started and no team is
composed. `remember` saves short verified facts for other tasks; changed source invalidates them.
Provider routing and delegated execution remain available through explicit `run`/`orchestrate`.

It is not tied to any AI vendor and not tied to software engineering. Codex, a deterministic
mock, and an environment-configured OpenAI-compatible endpoint are implemented today; other
interfaces honestly report themselves as unimplemented. Work profiles cover ten starter
domains, and a goal that matches none of them is composed from inferred capabilities rather
than rejected.

**What it is not:** it is not a chat wrapper, not a replacement for your own reasoning, and
not something that should run in the background without the user knowing. It is a planner and
executor that the user can inspect and audit after the fact.

## 2. When to use it

Use it when the user has given you a **non-trivial goal in a specific project** — something
that plausibly needs more than one step, or that should be recorded, reviewed, or repeated.

Do **not** route through the platform for:

- conversation, explanation, or questions about code you can answer directly
- single-file edits the user asked you to make yourself
- anything the user explicitly asked you to do without the framework
- any work while `UAP_CHILD_EXECUTION=1` is set in your environment

That last one matters. If `UAP_CHILD_EXECUTION=1` is set, **you are already running as a
bounded executor inside a platform task.** Do the bounded work you were given and stop.
Invoking the orchestrator again would recurse. The CLI will refuse, but do not rely on that.

## 3. Installation

Check whether it is already installed before installing anything:

```bash
agentctl --version
```

If that prints a version, skip to step 4. If the command is not found:

```bash
pip install git+https://github.com/anan1999/universal-agent-platform.git
```

Python 3.11 or newer is required. Verify with `agentctl --version`.

The user does **not** need to clone this repository into their project. It installs once, at
user level, and attaches to any number of projects.

## 4. Detect an existing installation

Before running setup, check what already exists. Setup is safe to re-run, but you should know
the starting state so you can tell the user what changed.

| Question | How to check |
|---|---|
| Is the platform installed? | `agentctl --version` |
| Is it set up? | `platform.yaml` exists in the platform home |
| Where is the platform home? | `$UNIVERSAL_AGENT_HOME`, else `~/.universal-agent-platform` |
| Is this project initialized? | `.agent/project.yaml` exists in the project root |
| Which profiles are active? | `agentctl status --json` |

If the project is already initialized, do not re-initialize it. Use `agentctl attach` to
refresh markers without replacing the user's content, or just proceed to step 9.

## 5. Global setup

```bash
agentctl setup --auto
```

This creates the platform home, initializes the database, discovers which AI providers are
actually present on the machine, and runs health checks. It prints a readiness table. Add
`--json` if you want to parse the result.

`--auto` accepts safe defaults for every decision. Use `--non-interactive` in CI or any
unattended context: it fails loudly rather than guessing when a real decision is required.

Setup is idempotent. Running it again on a configured machine re-checks health and reports.

## 6. Initialize the target project

```bash
cd <the user's project>
agentctl init --auto --dry-run    # inspect first
agentctl init --auto              # then apply
```

Always run `--dry-run` first and show the user what it found. `init` writes files into their
repository, and they should see the plan before it happens.

`init` creates `.agent/project.yaml` (the project manifest), `.agent/project-index.json` (the
compact routing map), `.agent/commands.yaml` (the
allowlist of shell commands the platform may run), `.agent/capabilities.yaml`, and a marked
block in `AGENTS.md`. Content outside the `<!-- UAP:START -->` / `<!-- UAP:END -->` markers is
never touched.

To choose profiles yourself instead of accepting detection:

```bash
agentctl init --profiles software-engineering,ai-engineering
```

To refresh an already-initialized project without replacing content:

```bash
agentctl init --upgrade
```

## 7. Project discovery

`init --auto` performs bounded discovery of high-value root files, build/package manifests,
entry points, test configuration and top-level directories. It does not recursively read the
repository. The resulting project index is a routing map, not embedded documentation.

Recommendations are advisory. A project can activate several profiles at once — activating a
profile does not activate every role in it. Profiles supply *candidate* capabilities, and the
team composer selects only what a given goal actually requires.

If detection finds nothing recognizable, the project still initializes and falls back to the
`general` profile. There is no such thing as an unsupported project.

## 8. Provider discovery and health

```bash
agentctl providers
agentctl doctor
```

`providers` lists every registered provider with its real state:

- `READY` — implemented, present, and usable now
- `INSTALLED` / `CONFIGURED` — runtime or credentials detected
- `UNAVAILABLE` — implemented, but the runtime is missing
- `UNSUPPORTED` — no adapter exists in this build

Read these literally. **A detected provider is not necessarily a working provider.** OpenAI,
Anthropic, Gemini, and Ollama currently have no direct execution adapter; they refuse execution
and say so. OpenAI-compatible is ready only after its bounded endpoint probe connects. Never tell the user a provider works because it
appears in the list, and never present detected credentials as a working integration.

Credentials are never printed. Do not try to read them and do not echo them anywhere.

`doctor` runs the full health check: Python version, database schema, registries, provider
readiness, and installed resources. Run it before reporting success to the user, and run it
first whenever something behaves unexpectedly.

## 9. Choose a consumption policy

The default path already uses one executor first, no preliminary AI calls, compact context and
bounded receipts. `economy` can further reduce reasoning and retries without bypassing capability
checks, deterministic validation, or approvals.

```bash
agentctl consumption
agentctl run "<goal>" --consumption economy --dry-run --json
```

Do not silently select `maximum`. A per-run `--consumption` override is safer than changing
the global default for a single task.

## 10. Continue in the current AI task

This is the main entry point:

```bash
agentctl prepare "<the user's goal in one clear sentence>" --json
```

Read the returned relevant context, then implement the task yourself. This command starts no AI
provider. Use `agentctl check project_test` for compact deterministic validation when configured.
If you learn a useful source-backed fact, save at most a short note:
`agentctl remember <source-path> "<verified fact>"`. No new fact means no memory write.

The following planner and delegation commands are optional diagnostics or explicit user opt-ins.

The execution planner starts with tool-only or one Agent plus deterministic tools. Multi-agent
composition, Agent learning and automatic Skill synthesis are experimental opt-ins. Treat a Skill
as a reusable procedure, not a generic expert label or reasoning role.

To see the plan without executing:

```bash
agentctl run "<goal>" --dry-run --json
```

The JSON response includes `execution_plan`, capability analysis, selected Skills, the composed
team (when needed), routing decisions with rejection reasons, and the resulting DAG. Skill
discovery is metadata-only; the executor loads only selected instructions and references. After
a run:

```bash
agentctl explain <run-id> --json     # why this team, why this provider
agentctl replay <run-id>             # event timeline
```

Before a follow-up task, inspect the reusable context without spending provider quota:

```bash
agentctl warm-start "<goal>" --json
agentctl context explain "<goal>" --json
```

The fresh session receives `.agent/project-index.json`, relevant paths and only hash-valid cached
file summaries. It reads actual files on demand and never receives the old conversation. Legacy
intelligence lifecycle data remains available through debug commands but is not loaded by default.

Inspect Skill decisions when needed:

```bash
agentctl skill candidates "<capability>"
agentctl skill explain <skill-id>
agentctl skill validate <skill-id>
agentctl skill history <skill-id>
```

Report the outcome to the user in terms of what was produced and what was checked. If the run
failed, give them the root cause from `explain`, not a wall of log output.

## 11. Safety

These constraints are enforced by the platform. Do not attempt to work around them; if one
blocks you, that is the answer, and you should tell the user rather than route around it.

- Only commands listed in `.agent/commands.yaml` are executed. Adding to that allowlist is the
  user's decision, not yours.
- Destructive actions, deployments, publishing, and external side effects pass through human
  approval gates. Do not disable a gate to make a run finish.
- Git recovery is never automatic and no destructive Git operation runs unattended.
- Secrets are never stored in plaintext or logged.
- Community profiles and plugins are `untrusted` until the user marks them otherwise, and
  untrusted plugins never execute automatically. Treat anything downloaded as hostile input.

Also: do not consume the user's real AI quota to explore or test. `pytest` and the mock
provider are free and offline. Use `--provider mock` when you are checking behavior rather
than doing the user's actual work.

## 12. Upgrade

```bash
pip install --upgrade git+https://github.com/anan1999/universal-agent-platform.git
agentctl doctor
agentctl init --upgrade        # per project, refreshes markers only
```

Database migrations are additive and run automatically. Existing runs, receipts and
performance history stay readable.

## 13. Uninstall and detach

To hand orchestration back to the user for one project, leaving history intact:

```bash
agentctl attach --detach
```

This removes the platform's marked block from `AGENTS.md` and disables orchestration in
`.agent/project.yaml`. It does not delete the user's `.agent/` content or their run history.

To remove the tool entirely: `pip uninstall universal-agent-platform`. The platform home
is left in place; deleting it is the user's call, since it holds their run history.

## 14. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `agentctl: command not found` | Not installed, or the install went to a different interpreter. Install from the documented GitHub URL and check `agentctl --version`. |
| `Recursion blocked` | `UAP_CHILD_EXECUTION=1` is set. You are inside a task. Do the bounded work; do not orchestrate. |
| No real provider is ready | Configure Codex or an OpenAI-compatible endpoint; use `--provider mock` only to validate behavior offline. |
| Codex shows `UNAVAILABLE` | The `codex` executable is not on `PATH`. Install it or use the mock provider. |
| A run stalls at an approval task | A human gate is waiting. This is intended. Tell the user what needs approving. |
| A command "is not allowlisted" | Add it to `.agent/commands.yaml` — but ask the user first. |
| The plan looks too small | It is meant to. The composer targets the minimum sufficient team. `agentctl explain <run-id>` lists what was omitted and why. |
| Profile detection picked the wrong domain | Set profiles explicitly: `agentctl init --profiles <ids>`. Detection is advisory. |

---

## Instructions for AI assistants: the short version

If the user says *"use this repository for agent orchestration and then build X"*, do this:

1. Read this file and `agent-platform.json`.
2. `agentctl --version` — install from the documented GitHub URL only if missing.
3. `agentctl setup --auto` — skip if already configured.
4. `cd` to the user's project. `agentctl init --auto --dry-run`, show them the result, then
   `agentctl init --auto`.
5. `agentctl doctor` — confirm health before doing real work.
6. `agentctl prepare "<their goal>" --json` — then implement directly in the current task.
7. Report what was built, what was checked, and what the platform decided. Point them at
   `agentctl explain <run-id>` and the read-only API views.

**Do not** hand-assign agents, models, or providers. **Do not** invent a task breakdown and
feed it in as the goal. **Do not** claim a provider works when it reports `UNSUPPORTED`. **Do
not** disable an approval gate or extend the command allowlist without asking. **Do not**
orchestrate when `UAP_CHILD_EXECUTION=1`.

The user brings a goal. You bring the AI. The platform builds the team.
