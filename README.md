# Universal Agent Platform

**Bring your goal. Bring your AI. The platform builds the team.**

Give it a goal in plain language. It works out which capabilities the work needs, composes the
minimum sufficient team of reasoning roles, routes each role to a provider and model that can
actually do the job, builds a dependency-ordered task DAG, executes it, and records receipts,
artifacts and performance history that a local dashboard renders.

It is not tied to one AI vendor and not tied to software engineering. Version **2.0.0**.

---

## FOR AI ASSISTANTS

**If a user asks you to use this repository as their agent orchestration framework, read
[`AI-BOOTSTRAP.md`](AI-BOOTSTRAP.md) before you modify their project.**

The machine-readable contract is [`agent-platform.json`](agent-platform.json).

The short version:

```bash
agentctl --version            # install with `pip install -e .` only if missing
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

## FOR HUMANS

### Install

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Activation on Linux/macOS is `source .venv/bin/activate`. Python 3.11 or newer is required.
You install the platform once; you do not clone it into every project.

```bash
agentctl setup --auto
```

Setup creates the platform home, initializes the database, discovers which providers are
actually present, and runs health checks.

### Use it on a project

```bash
cd my-project
agentctl init --auto
agentctl run "Build the model upload API"
agentctl dashboard
```

`init --auto` reads the repository, recommends work profiles with the evidence behind each
recommendation, and writes `.agent/`. Run it with `--dry-run` first if you want to see the plan
before anything is written. Then open `http://127.0.0.1:8787`.

### Example prompts to your AI assistant

> I want to build a FastAPI application. Use `<repo URL>` for agent orchestration. Follow
> AI-BOOTSTRAP.md and then implement the project.

> I want to redesign a dashboard. Use `<repo URL>` for agent management. Initialize the
> appropriate profiles and proceed.

> I want to benchmark an edge AI model. Use `<repo URL>` as the orchestration framework.

> I want to plan an interior design project. Use `<repo URL>` for agent orchestration. Infer
> the required capabilities and create temporary specialists if no existing profile covers the
> work.

The last one is the point: a domain with no predefined profile still produces a valid
capability-driven plan.

## How a goal becomes work

```text
Goal -> Goal Analyzer -> Capability Resolver -> Work Profiles -> Team Composer
     -> Task Planner -> Task DAG (agent | tool | approval | artifact)
     -> Provider Router -> Execution -> Receipts / Artifacts / Evaluation
     -> Performance History -> Dashboard
```

The **Goal Analyzer** derives capabilities, complexity and risk from the goal text
deterministically, with no AI call. The **Capability Resolver** prefers, in order, an existing
agent, an existing skill, a deterministic tool, a creatable skill, and only then a temporary
specialist. The **Team Composer** picks reasoning roles — never models — and records why each
role was chosen and why each candidate was left out. The **Provider Router** then maps required
capabilities plus risk, history and availability onto a concrete `(provider, model)` pair.

Team size scales with the work: trivial goals get one agent, critical goals get specialists,
evaluation and an approval gate.

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

## Providers

```bash
agentctl providers
```

| Provider | State in this build |
|---|---|
| Codex | implemented, validated against the real CLI |
| Mock | implemented, deterministic and offline |
| OpenAI, Anthropic, Gemini, Ollama, OpenAI-compatible | plugin-ready interface only |

Plugin-ready providers report their real detection state — they will tell you if credentials or
a binary are present — but they refuse to execute rather than pretend. Provider states are
`available`, `installed`, `configured`, `connected`, `unavailable` and `unsupported`, and
capabilities are `supported`, `unsupported`, `model_dependent` or `unknown`. Credentials are
never printed.

Selection defaults to `auto`. To bias it: `agentctl provider prefer codex`, or set
`providers.preference` in `.agent/project.yaml`. No provider is ever required.

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

The dashboard binds to `127.0.0.1` and the browser cannot execute arbitrary shell. Only
commands named in `.agent/commands.yaml` run. Destructive actions, deployments and publishing
pass through human approval gates. Git recovery is never automatic and dirty trees are reported
rather than discarded. Secrets are never stored in plaintext. Community profiles and plugins
are `untrusted` until you say otherwise, and untrusted plugins never execute automatically —
treat anything you download as untrusted input.

## CLI

```bash
agentctl setup | init | attach | doctor | status
agentctl run | orchestrate | explain | replay | dashboard
agentctl agents | skills | tools | profiles | providers | models
```

`agentctl orchestrate "<goal>" --json` is the canonical entry point for an AI assistant.
`agentctl run --dry-run` plans without executing. Add `--json` to anything you want to parse.

## Development

```bash
python -m pip install -e ".[dev]"
pytest -q
python scripts/domain_matrix.py    # cross-domain composition, offline
```

Tests consume **zero real AI quota** — the mock provider is deterministic and in-process. On a
restricted Windows host, pass a writable `--basetemp` to pytest. Design and operational detail
is in `docs/`. The release evidence, including the bounded real-provider run, is recorded in
[`docs/v2-validation.md`](docs/v2-validation.md).

## Known limitations

- Goal analysis and planning are deterministic and rule-based, not LLM-generated. This keeps
  planning free and reproducible, but it will not infer intent that the goal text does not
  state.
- Only Codex and Mock execute. The other providers are interfaces awaiting implementation.
- Adaptive routing needs five comparable samples before history influences a decision, and it
  ranks candidates rather than modifying policy.
- Worktree integration exposes safe primitives but does not auto-merge branches.
- Codex CLI base instructions can dominate input tokens even when the platform packet is small.
- Provenance is authoritative only for runs entering through the platform; work done outside it
  is invisible.
- Authentication, distributed execution, Kubernetes and multi-user tenancy are out of scope.
