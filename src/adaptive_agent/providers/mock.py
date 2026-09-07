from __future__ import annotations

import asyncio

from adaptive_agent.core.capabilities import Support
from adaptive_agent.core.models import Receipt, Task
from adaptive_agent.providers.base import (
    AIProvider,
    ProgressCallback,
    ProviderCapabilities,
    ProviderKind,
    ProviderProbe,
    ProviderState,
    UsageReport,
)


class MockProvider(AIProvider):
    """Deterministic provider used by every test. Consumes zero real AI quota."""

    id = "mock"
    display_name = "Mock"
    kind = ProviderKind.TEST
    implemented = True

    def __init__(self, delay: float = 0.02, fail_titles: set[str] | None = None):
        self.delay = delay
        self.fail_titles = fail_titles or set()
        self._usage = UsageReport(source="estimated", invocation_count=0)

    def probe(self) -> ProviderProbe:
        return ProviderProbe(ProviderState.CONNECTED, "Deterministic in-process provider.")

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities({
            "text": Support.SUPPORTED, "vision": Support.UNSUPPORTED,
            "tool_use": Support.SUPPORTED, "filesystem": Support.UNSUPPORTED,
            "shell": Support.UNSUPPORTED, "structured_output": Support.SUPPORTED,
            "streaming": Support.UNSUPPORTED, "usage_reporting": Support.UNSUPPORTED,
            "long_context": Support.UNKNOWN, "image_generation": Support.UNSUPPORTED,
            "code_execution": Support.UNSUPPORTED,
        })

    def usage(self) -> UsageReport:
        return self._usage

    async def execute(self, task: Task, progress: ProgressCallback | None = None, packet=None) -> Receipt:
        for percent in (10, 50, 100):
            if progress:
                progress(percent, f"{task.owner} processing {task.title}")
            await asyncio.sleep(self.delay)
        failed = task.title in self.fail_titles
        usage = {"input": 120 + len(task.title), "output": 40, "cached": 0,
                 "source": "estimated", "estimated": True}
        self._usage = UsageReport(self._usage.input_tokens + int(usage["input"]),
                                  self._usage.output_tokens + int(usage["output"]),
                                  0, "estimated", self._usage.invocation_count + 1)
        return Receipt(
            task_id=task.id,
            agent=task.owner,
            status="failed" if failed else "completed",
            summary=("Simulated failure" if failed else f"Completed: {task.title}"),
            findings=["Mock provider executed deterministic task contract."],
            token_usage=usage,
            confidence="low" if failed else "high",
            needs_escalation=failed,
            error_code="TASK_FAILURE" if failed else None,
            model=task.metadata.get("model", "mock-standard"),
        )
