# Plugin and profile packaging

This describes the portable package format that profiles, skills, tools and providers share.
There is no hosted marketplace and this document does not propose one; the point is that the
format is stable enough that distribution can be added later without breaking what people have
already written.

## Layout

```text
my-plugin/
  plugin.yaml        # required manifest
  profile.yaml       # for profile plugins
  agents/            # optional role definitions
  skills/            # optional skill definitions
  tools/             # optional tool specifications
  README.md          # what it does, who wrote it, what it touches
```

Only `plugin.yaml` is required. A profile plugin that ships nothing but `profile.yaml` is
valid, and that is the common case.

## Manifest

```yaml
schema_version: "1"
name: qnn-edge-ai
version: "1.0.0"
type: profile              # provider | profile | skill | tool | integration
description: Qualcomm QNN benchmarking and quantization workflows.
capabilities:
  - quantization
  - benchmarking
compatibility: ">=2.0"
entrypoint: profile.yaml   # required for provider plugins
permissions:
  - read_project
  - run_commands
author: someone
homepage: https://example.invalid/qnn-edge-ai
```

`name`, `version` and `type` are required. `entrypoint` is required for provider plugins,
which are the only kind that contribute executable code.

### Permissions

A plugin gets what it declares and nothing more. An undeclared permission is denied, and an
unrecognized one is an error rather than a grant, so a typo cannot quietly widen access.

| Permission | Grants |
|---|---|
| `read_project` | read files in the target project |
| `write_project` | modify files in the target project |
| `run_commands` | execute commands from the project allowlist |
| `network` | reach the network |
| `read_credentials` | read provider credentials from the environment |
| `register_provider` | add an execution backend |

The last four are dangerous: they can change the user's repository, run code, read secrets, or
decide where prompts are sent. Requesting any of them requires explicit approval before the
plugin loads.

## Trust

| State | Meaning |
|---|---|
| `built_in` | ships with the platform |
| `trusted` | the user approved it explicitly |
| `untrusted` | everything else, including anything just downloaded |

Discovery reads manifests; it never imports plugin code. An untrusted plugin is listed, with
its declared permissions and any validation errors, and is not loaded. Promotion to `trusted`
is always a deliberate user action — the platform will not infer trust from the fact that
something was installed, and it will not auto-promote a plugin that has been working fine.

## Supply-chain risk

Treat a downloaded profile or plugin exactly as you would an unreviewed dependency.

The realistic threats are worth naming. A **profile** is data, but it steers which roles get
created and which evaluation runs, so a hostile one can quietly weaken review on work that
needed it. A **tool plugin** proposes commands; those still pass through `.agent/commands.yaml`,
so the allowlist is the real boundary, and widening it on a plugin's say-so removes that
boundary. A **provider plugin** is the serious case: it is executable code that receives your
prompts, your project context and potentially your credentials, and it decides where they go.

So, before trusting anything:

- Read `plugin.yaml`. If the permissions exceed what the description justifies, stop.
- Read the profile and tool definitions. They are YAML; they are meant to be readable.
- For provider plugins, read the code. There is no way around this one.
- Prefer pinned versions over tracking a branch.

The platform enforces the boundaries it can — allowlisted commands only, no shell from the
browser, approval gates on destructive actions, no automatic loading of untrusted code. It
cannot tell you whether a profile's advice is good. That judgment stays with you.
