# Codex provider

## Verified local contract

Verified on 2026-09-07 with `codex-cli 0.153.4` at `C:\Users\andrew.ja.chiao\AppData\Local\OpenAI\Codex\bin\8e5b6932251c2c1c\codex.exe`.

The provider invokes an argument list equivalent to:

```text
codex exec --ephemeral --ignore-user-config --json --color never
  --sandbox read-only|workspace-write
  -C WORKING_DIRECTORY
  --model MODEL
  --config model_reasoning_effort="EFFORT"
  --output-schema SCHEMA_FILE
  -
```

The bounded prompt is written to stdin. Stdout is JSONL, stderr is captured separately, exit status is checked, timeout is enforced, and cancellation terminates then kills only if graceful termination fails. `shell=True` is never used.

Local help and the [official Codex developer command reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli) confirm non-interactive `codex exec`, stdin prompts, `-C`, model override, JSONL output, output schema, and sandbox selection.

## Capabilities

- Non-interactive execution: supported and validated.
- Working directory: supported through `-C` and subprocess `cwd`.
- Model selection: supported through `--model`; local catalog includes `gpt-5.6-luna` and `gpt-5.6-sol`.
- Reasoning selection: supported through `--config model_reasoning_effort=...`; local catalog exposes supported levels.
- Structured output: supported through `--output-schema` and JSONL final agent messages.
- Usage reporting: validated in real JSONL `turn.completed` events with input, cached input, and output tokens.

Usage capability is reported PASS only after the platform database contains a measured real-run record. Provider errors retain bounded diagnostics and stable error codes.

