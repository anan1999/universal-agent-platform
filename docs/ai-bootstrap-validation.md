# AI bootstrap validation

Validated for V2.1 by reading only `README.md`, `AI-BOOTSTRAP.md`, and
`agent-platform.json`, as a new assistant with no repository-specific knowledge.

| Question | Result | Contract location |
|---|---|---|
| How do I install? | Clear | Git URL command in all three entry documents |
| How do I detect an existing install? | Clear | `agentctl --version` |
| How do I set up the machine? | Clear | `agentctl setup --auto` |
| How do I initialize a project? | Clear | dry-run, then `agentctl init --auto` |
| How do I avoid recursion? | Clear | `UAP_CHILD_EXECUTION=1` guard |
| How do I health-check? | Clear | `agentctl doctor` |
| How do I invoke orchestration? | Clear | `agentctl orchestrate "<goal>" --json` |
| How do I explain a run? | Clear | `agentctl explain <run-id> --json` |
| How do I avoid fake providers? | Clear | state model and truthful provider table |
| How do I respect approval gates? | Clear | no gate bypass; explicit human authorization |

The canonical sequence is consistent: detect, Git-install if missing, setup once, inspect init,
apply init, run doctor, then orchestrate. Editable installation appears only in contributor
instructions. The manifest intentionally sets `from_pypi` to `null` because no PyPI release is
claimed.

