# Project Agent Adapter

Use the global Universal Agent Platform registry. Project-specific facts belong in `.agent/`.
Execute only commands explicitly listed in `.agent/commands.yaml`. Never perform destructive Git recovery automatically.
Use `agentctl prepare "<goal>" --read --json` in the current AI task. No delegated AI is required.
Read `.agent/project-index.json` before repository exploration. Start with its relevant paths,
reuse only valid entries from `.agent/cache/files.json`, and prefer targeted reads over recursive
discovery. Use one executor first and validate with commands from `.agent/commands.yaml`.
