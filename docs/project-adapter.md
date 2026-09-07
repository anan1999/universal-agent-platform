# Project adapter

`agentctl init` creates `.agent/project.yaml`, `capabilities.yaml`, `commands.yaml`, and `knowledge/`. Detection never claims an unsupported platform. Project history is keyed separately in the global SQLite database, while source and worktrees remain with the repository.

