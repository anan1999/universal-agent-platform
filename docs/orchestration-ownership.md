# Orchestration ownership

UAP-enabled projects declare `orchestration.owner: universal-agent-platform` in `.agent/project.yaml`. Their
marked `AGENTS.md` block tells a parent Codex session to forward a non-trivial goal directly to
`agentctl orchestrate "<goal>" --json`, without first duplicating repository analysis.

The ownership chain is intentionally one-way:

```text
User goal
  -> Codex parent (handoff only)
  -> Universal Agent Platform (final planner/router authority)
  -> logical Agent role
  -> CodexProvider
  -> optional read-only native profile
  -> selected model and reasoning effort
```

Every Codex child inherits `UAP_CHILD_EXECUTION=1` and `UAP_ORCHESTRATION_OWNER=universal-agent-platform`.
Its bounded execution packet explicitly forbids invoking `agentctl` or another routing authority.
The `orchestrate` command rejects calls carrying the child marker.

Run provenance stores both `orchestration_owner` and `entry_source` in SQLite. Supported entry
sources include `codex_parent`, `cli`, `dashboard`, and `api`. UAP does not claim to detect arbitrary
manual activity outside its process boundary.

The Agent and Skill views preserve four separate concepts: logical Agent, Codex native profile,
model, and Skill. Profile discovery reads known descriptive fields only and offers no mutation route.
The installed `agents/*.toml` custom-agent definitions are not the same as the CLI `--profile`
configuration overlay. UAP records the logical binding and selects the verified model/reasoning pair;
it does not misroute an `agents/*.toml` name through `codex exec --profile`.
