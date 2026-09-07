from __future__ import annotations

from adaptive_agent.core.models import Task, TaskStatus


class TaskGraph:
    def __init__(self, tasks: list[Task] | None = None):
        self.tasks: dict[str, Task] = {}
        for task in tasks or []:
            self.add(task)

    def add(self, task: Task) -> None:
        if task.id in self.tasks:
            raise ValueError(f"duplicate task: {task.id}")
        self.tasks[task.id] = task

    def validate(self) -> None:
        for task in self.tasks.values():
            missing = set(task.dependencies) - self.tasks.keys()
            if missing:
                raise ValueError(f"{task.id} has missing dependencies: {sorted(missing)}")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError("task graph contains a cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in self.tasks[task_id].dependencies:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in self.tasks:
            visit(task_id)

    def ready(self) -> list[Task]:
        ready = []
        for task in self.tasks.values():
            if task.status in {TaskStatus.QUEUED, TaskStatus.READY} and all(
                self.tasks[dependency].status == TaskStatus.COMPLETED for dependency in task.dependencies
            ):
                task.status = TaskStatus.READY
                ready.append(task)
        return sorted(ready, key=lambda task: (-task.priority, task.id))

    def complete(self) -> bool:
        return bool(self.tasks) and all(task.status == TaskStatus.COMPLETED for task in self.tasks.values())

