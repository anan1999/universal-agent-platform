from __future__ import annotations

import subprocess
from pathlib import Path


class WorktreeManager:
    def __init__(self, repository: Path):
        self.repository = repository.resolve()
        self.root = self.repository / ".agent-worktrees"

    def is_repository(self) -> bool:
        result = subprocess.run(["git", "-C", str(self.repository), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, check=False)
        return result.returncode == 0

    def dirty(self) -> bool:
        result = subprocess.run(["git", "-C", str(self.repository), "status", "--porcelain"], capture_output=True, text=True, check=True)
        return bool(result.stdout.strip())

    def create(self, task_id: str, start_point: str = "HEAD") -> Path:
        if not self.is_repository():
            raise ValueError("not a git repository")
        if not task_id.replace("-", "").isalnum():
            raise ValueError("unsafe task id")
        destination = (self.root / task_id).resolve()
        if self.root.resolve() not in destination.parents:
            raise ValueError("worktree path escaped managed root")
        if destination.exists():
            raise FileExistsError(destination)
        self.root.mkdir(exist_ok=True)
        self._ensure_excluded()
        branch = f"agent/{task_id.lower()}"
        result = subprocess.run(["git", "-C", str(self.repository), "worktree", "add", "-b", branch, str(destination), start_point], capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        return destination

    def _ensure_excluded(self) -> None:
        common = subprocess.run(["git", "-C", str(self.repository), "rev-parse", "--git-common-dir"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        common_dir = Path(common.stdout.strip())
        if not common_dir.is_absolute():
            common_dir = (self.repository / common_dir).resolve()
        exclude = common_dir / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        rule = ".agent-worktrees/"
        if rule not in {line.strip() for line in existing.splitlines()}:
            separator = "" if not existing or existing.endswith("\n") else "\n"
            exclude.write_text(existing + separator + rule + "\n", encoding="utf-8")

    def remove(self, task_id: str) -> None:
        destination = (self.root / task_id).resolve()
        if self.root.resolve() not in destination.parents or not destination.exists():
            raise ValueError("unknown managed worktree")
        result = subprocess.run(["git", "-C", str(self.repository), "worktree", "remove", str(destination)], capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
