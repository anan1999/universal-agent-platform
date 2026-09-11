# Universal Agent Platform

**Stop making every AI session rediscover your project.**

Learn the repository once. Reuse the useful context later.

UAP keeps a compact project map, reusable project procedures, and validated commands with the
repository. A fresh AI session reads only the project context it needs, goes directly to relevant
files, executes with one AI agent first, and validates the result with deterministic tools.

It is provider-agnostic, capability-first, work-profile-driven, local-first, inspectable,
auditable, and extensible. It is not tied to software engineering. Version **2.3.1**.

The default path performs no preliminary AI calls, embeddings, recursive repository scan, Agent
learning, Skill synthesis, maturity routing, or payback analysis. Those existing mechanisms remain
available for explicit experiments; they do not tax ordinary tasks.

Example: on the first session UAP inspects `package.json`, `app/main.py`, top-level directories and
test/build configuration, then records FastAPI, React, SQLite, important paths and canonical
commands in `.agent/project-index.json`. On a later request such as “Add monthly spending summary,”
the fresh session receives the backend/API/frontend paths and commands instead of starting with a
full repository rediscovery.

---

## FOR AI ASSISTANTS

**If a user asks you to use this repository as their agent orchestration framework, read
[`AI-BOOTSTRAP.md`](AI-BOOTSTRAP.md) before you modify their project.**

The machine-readable contract is [`agent-platform.json`](agent-platform.json).

The short version:

```bash
agentctl --version
# If missing: pip install git+https://github.com/anan1999/universal-agent-platform.git
agentctl setup --auto         # once per machine
cd <the user's project>
agentctl init --auto --dry-run    # show the user before applying
agentctl init --auto
agentctl doctor
agentctl orchestrate "<the user's goal>" --json
```

Pass the goal and its real constraints. Do not pass agent names, model names, providers, or a
task breakdown — deciding those is the platform's job. If `UAP_CHILD_EXECUTION=1` is set in
your environment you are already running inside a platform task: do the bounded work and do
not orchestrate again.

---

## Install once

```bash
pip install git+https://github.com/anan1999/universal-agent-platform.git
agentctl setup --auto
```

Python 3.11 or newer is required.

## Use in any project

```bash
cd my-project
agentctl init --auto --dry-run
agentctl init --auto
agentctl doctor
```

Then use your preferred AI normally, or preview a plan with
`agentctl run "<your goal>" --dry-run`.

## Control subscription usage

UAP has three quota-conscious orchestration policies. `balanced` preserves the normal V2.3
behavior. `economy` runs agents sequentially, prefers lower-cost compatible models and lower
reasoning for non-high-risk work, carries fewer and shorter receipts, caps team growth, and
allows only one escalation per task. `maximum` provides wider concurrency, context and
escalation budgets for difficult work. Capabilities, deterministic validation and approval
gates remain mandatory in every mode.

```bash
agentctl consumption                 # show the global policy
agentctl consumption economy         # set the global policy
agentctl run "<your goal>" --consumption economy --dry-run
```

Set `consumption.mode` in `.agent/project.yaml` for a project default. A per-run flag takes
precedence over the project setting, which takes precedence over the global setting.

## Reuse compact project context

Project initialization creates `.agent/project-index.json`, intentionally targeted at 4 KiB with
an 8 KiB soft maximum. It is a routing map rather than full documentation. Useful file summaries
are added incrementally to `.agent/cache/files.json`; a changed file hash invalidates its summary.

```bash
agentctl warm-start "<your next goal>" --json
agentctl context --json
agentctl context explain "<your next goal>" --json
agentctl status --json
```

The older `.agent/intelligence.json` data remains readable through debug/experimental commands,
but its maturity, promotion and payback lifecycle is not part of the default execution path.
See [V2.3.1 simplified core](docs/v2.3.1-simplified-core.md) for budgets, feature flags and the
isolated context-cache benchmark contract.

## Copy this into any AI assistant

```text
I want to build <describe your project>.

Use the following repository as the agent orchestration framework:
https://github.com/anan1999/universal-agent-platform

Read AI-BOOTSTRAP.md and agent-platform.json. If the platform is not installed,
install it using the documented GitHub installation method. Set it up once for
this machine, initialize the current project, run health checks, then use the
platform to determine capabilities, select the minimum sufficient execution strategy,
read the compact project index, route one executor to relevant files, optionally load one clearly
useful procedure Skill, select a compatible provider/model, and validate the work. Do not manually assign agents, models, or providers unless the framework
explicitly requires a user decision. After initialization succeeds, proceed
directly with the requested work.
```

## FOR HUMANS

### Development install

```powershell
git clone https://github.com/anan1999/universal-agent-platform.git
cd universal-agent-platform
python -m pip install -e ".[dev]"
```

Editable installation is for contributors; it is not required for normal use.

### Use it on a project

```bash
cd my-project
agentctl init --auto
agentctl run "Build the model upload API"
agentctl explain <run-id>
```

`init --auto` reads the repository, recommends work profiles with the evidence behind each
recommendation, and writes `.agent/`. Run it with `--dry-run` first if you want to see the plan
before anything is written. Inspect completed runs with `agentctl explain` and `agentctl replay`.

### Example prompts to your AI assistant

> I want to build a FastAPI application. Use `<repo URL>` for agent orchestration. Follow
> AI-BOOTSTRAP.md and then implement the project.

> I want to redesign a dashboard. Use `<repo URL>` for agent management. Initialize the
> appropriate profiles and proceed.

> I want to benchmark an edge AI model. Use `<repo URL>` as the orchestration framework.

> I want to plan an interior design project. Use `<repo URL>` for agent orchestration. Infer
> the required capabilities and reuse or propose Skills before creating any temporary specialist.

The last one is the point: a domain with no predefined profile still produces a valid
capability-driven plan.

## How a goal becomes work

```text
Goal -> Compact Project Index -> Relevant Paths -> Optional Procedure Skill
     -> One AI Executor -> Deterministic Validation -> Compact Receipt
```

The **Goal Analyzer** derives capabilities, complexity and risk from the goal text
deterministically, with no AI call. The **Capability Resolver** prefers, in order, a deterministic
tool, an existing Skill, an existing reasoning role, a creatable temporary Skill, and only then a
temporary specialist. The **Execution Planner** chooses the smallest sufficient strategy. The
**Team Composer** runs only when multiple independent reasoning roles are justified and records why each
role was chosen and why each candidate was left out. The **Provider Router** then maps required
capabilities plus risk, history and availability onto a concrete `(provider, model)` pair.

Deterministic requests can still be tool-only. Ordinary work starts with one Agent; multi-agent
composition and automatic Skill synthesis require explicit experimental flags. Approval gates and
provider capability checks remain active.

### The layers stay independent

An **Agent** is a reasoning responsibility. A **Skill** is reusable knowledge. A **Tool** is a
deterministic action. A **Provider** is an execution backend. A **Model** is what the provider
runs. None of these determines another, which is why a single run can span providers and why a
new provider does not require touching the orchestrator.

## Work profiles

Ten starter packs ship built in: `general`, `software-engineering`, `ai-engineering`, `uiux`,
`design`, `product`, `research`, `devops`, `data-analysis`, `technical-writing`.

Profiles are starter packs, **not a closed taxonomy**. They suggest capabilities, roles, skills,
tools, evaluation strategies and artifact types. A project can activate several at once, and
activating a profile does not activate every role in it — the composer selects only what the
goal requires. A goal matching no profile falls back to `general` and is composed from inferred
capabilities. "Unsupported domain" is not a failure mode.

Add your own by dropping a YAML file into `$UNIVERSAL_AGENT_HOME/profiles/`. No code changes.

```bash
agentctl profiles
agentctl profile show uiux
```

## Skill intelligence

A Skill is a versioned reusable procedure with a machine-readable `skill.json`, instructions in
`SKILL.md`, and optional references or examples. Discovery indexes metadata only. Instructions
and explicitly selected references enter context only for the task that uses them, and every run
records the exact Skill version and context attribution.

```bash
agentctl skill explain w8a8-validation
agentctl skill validate w8a8-validation
agentctl skill candidates "w8a8 validation"
agentctl skill history w8a8-validation
```

Unknown reusable procedures may produce a specification-first temporary Skill. Generated Skills
are `temporary` and `review_required`; executable unverified content cannot run without explicit
approval. Three successful validated uses create only a promotion candidate—promotion is never
automatic. See [Skill architecture](docs/skill-architecture.md),
[authoring](docs/skill-authoring.md), [security](docs/skill-security.md), and
[quality](docs/skill-quality.md).

## Providers

```bash
agentctl providers
```

| Provider | State in this build |
|---|---|
| Codex | ✅ Implemented and validated against the real CLI |
| Cursor Agent | ✅ Implemented and validated against the authenticated real CLI |
| Mock | ✅ Implemented, deterministic and offline |
| OpenAI-compatible | ✅ Implemented; ready only after a successful endpoint probe |
| Ollama | 🟡 Runtime detection only; direct adapter not implemented |
| OpenAI | ⚪ Adapter not implemented |
| Anthropic / Claude | ⚪ Adapter not implemented |
| Gemini | ⚪ Adapter not implemented |

Unimplemented providers report their real detection state — they will tell you if credentials or
a binary are present — but they refuse to execute rather than pretend. Provider states are
`available`, `installed`, `unconfigured`, `configured`, `connected`, `unavailable` and `unsupported`, and
capabilities are `supported`, `unsupported`, `model_dependent` or `unknown`. Credentials are
never printed.

Selection defaults to `auto`. To bias it: `agentctl provider prefer codex`, or set
`providers.preference` in `.agent/project.yaml`. No provider is ever required.

The OpenAI-compatible adapter reads its base URL, model, and optional key from environment
variables; it never stores or prints key values and it has no project filesystem access.

The Cursor adapter uses an existing `agent login` session and never reads or stores Cursor
credentials. Native Windows currently has no Cursor OS sandbox, so automated write runs use
project-local CLI deny rules and must be limited to a trusted, isolated workspace. Cursor documents
these rules as best-effort guardrails rather than a security boundary.

```bash
export UAP_OPENAI_COMPATIBLE_BASE_URL=http://127.0.0.1:11434/v1
export UAP_OPENAI_COMPATIBLE_MODEL=qwen2.5-coder:7b
agentctl provider-test openai_compatible
```

Set `UAP_OPENAI_COMPATIBLE_API_KEY` when the endpoint needs authentication, or set
`UAP_OPENAI_COMPATIBLE_API_KEY_ENV` to the name of an existing secret environment variable.
Project files must not contain the secret value. Run `agentctl demo --delay 0` for a completely
offline cross-provider routing demonstration.

Adding one means implementing `AIProvider` in `providers/<name>/`, registering a descriptor,
and adding models to `config/models.yaml`. The orchestrator does not change.

## Models

`config/models.yaml` is the catalog: provider, model id, capability levels, cost, latency,
context size, availability. Routing selects from it by capability, so no model name appears in
core routing code. Override or extend it at `$UNIVERSAL_AGENT_HOME/models.yaml`.

```bash
agentctl models
```

## Explainability

Every run answers two questions:

```bash
agentctl explain RUN_ID
```

**Why this team?** — the capabilities the goal required, the roles selected, and the roles
deliberately omitted with the reason for each. **Why this provider?** — the capabilities
required, the candidates considered, and why one won. Never "because Developer always uses
Sol".

## Safety

Only commands named in `.agent/commands.yaml` run. Destructive actions, deployments and publishing
pass through human approval gates. Git recovery is never automatic and dirty trees are reported
rather than discarded. Secrets are never stored in plaintext. Community profiles and plugins
are `untrusted` until you say otherwise, and untrusted plugins never execute automatically —
treat anything you download as untrusted input.

## CLI

```bash
agentctl setup | init | attach | doctor | status
agentctl run | orchestrate | explain | replay
agentctl agents | skills | skill | tools | profiles | providers | models
```

`agentctl orchestrate "<goal>" --json` is the canonical entry point for an AI assistant.
`agentctl run --dry-run` plans without executing. Add `--json` to anything you want to parse.

## Development

```bash
python -m pip install -e ".[dev]"
pytest -q
python scripts/domain_matrix.py    # cross-domain composition, offline
python scripts/skill_context_benchmark.py --json
```

Tests consume **zero real AI quota** — the mock provider is deterministic and in-process. On a
restricted Windows host, pass a writable `--basetemp` to pytest. Design and operational detail
is in `docs/`. The release evidence, including the bounded real-provider run, is recorded in
[`docs/v2.2-validation.md`](docs/v2.2-validation.md).

## Known limitations

- Goal analysis and planning are deterministic and rule-based, not LLM-generated. This keeps
  planning free and reproducible, but it will not infer intent that the goal text does not
  state.
- Codex, Cursor Agent, Mock, and the configured OpenAI-compatible adapter execute. Other provider names are
  truthful placeholders awaiting adapters.
- Adaptive routing needs five comparable samples before history influences a decision, and it
  ranks candidates rather than modifying policy.
- Worktree integration exposes safe primitives but does not auto-merge branches.
- Codex CLI base instructions can dominate input tokens even when the platform packet is small.
- Provenance is authoritative only for runs entering through the platform; work done outside it
  is invisible.
- Temporary Skill repair, promotion, and publication require human review; V2.2 records the
  evidence and candidate state but does not mutate trusted packages autonomously.
- Authentication, distributed execution, Kubernetes and multi-user tenancy are out of scope.
