# Worktrees

Parallel coding tasks use task-scoped branches under `.agent-worktrees/`. Creation fails on an invalid repository, unsafe task identifier, existing destination, or Git error. Cleanup uses `git worktree remove` without force, so dirty or locked worktrees are preserved for manual recovery.

