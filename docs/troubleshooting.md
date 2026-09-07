# Troubleshooting

- `agentctl doctor` prints runtime paths, database writability, provider choice, and Codex CLI detection.
- If pytest cannot use the system temporary directory, pass `--basetemp` pointing to a writable folder.
- If project detection is `unknown`, edit `.agent/project.yaml` and add only reviewed commands.
- If a worktree cannot be removed, commit or preserve its changes and use Git's normal worktree diagnostics; the platform never forces deletion.
- `CODEX_AUTH_ERROR` requires `codex login`; model escalation cannot fix authentication.
- `CODEX_TIMEOUT` terminates the child process and does not consume the reasoning escalation budget.
- Windows warnings about Codex PATH alias cleanup are decoded as UTF-8 and retained as diagnostics; run permissions may still need to permit the installed Codex executable.
- High measured input token totals may include Codex base instructions and tool context. Inspect the bounded execution packet separately before enlarging it.

