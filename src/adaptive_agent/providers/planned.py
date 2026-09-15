"""Plugin-ready adapters that are not implemented yet.

These exist so the architecture, CLI, and API can talk about
OpenAI / Anthropic / Gemini / Ollama / OpenAI-compatible endpoints without
pretending they work. A `PlannedProvider` detects whether the runtime or
credentials are present, reports that honestly, and refuses to execute.

Implementing one of these for real means replacing the class here (or shipping
a provider plugin) with a full `AIProvider` — nothing else in the platform
changes.
"""

from __future__ import annotations

import os
import shutil
import time
from typing import ClassVar, Sequence

from adaptive_agent.core.capabilities import Support
from adaptive_agent.core.models import Receipt, Task
from adaptive_agent.providers.base import (
    AIProvider,
    ExecutionMode,
    ProgressCallback,
    ProviderCapabilities,
    ProviderKind,
    ProviderProbe,
    ProviderState,
)


NOT_IMPLEMENTED = "PROVIDER_NOT_IMPLEMENTED"


class PlannedProvider(AIProvider):
    implemented = False
    #: Environment variables that would configure this provider. Only presence
    #: is ever reported; values are never read into telemetry or API output.
    credential_variables: ClassVar[Sequence[str]] = ()
    #: Local executables that indicate the runtime is installed.
    executables: ClassVar[Sequence[str]] = ()
    #: Declared capability shape once an adapter exists.
    declared: ClassVar[dict[str, Support]] = {}

    def _configuration(self) -> dict[str, bool]:
        found = {name: bool(os.getenv(name)) for name in self.credential_variables}
        found.update({name: shutil.which(name) is not None for name in self.executables})
        return found

    def probe(self) -> ProviderProbe:
        configuration = self._configuration()
        detected = [name for name, present in configuration.items() if present]
        detail = ("Runtime or credentials detected, but no adapter is implemented in this build."
                  if detected else "No adapter is implemented in this build.")
        state = ProviderState.INSTALLED if detected else ProviderState.UNSUPPORTED
        return ProviderProbe(state, detail, configuration=configuration)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities({**{name: Support.UNKNOWN for name in self.declared},
                                     **self.declared})

    async def execute(self, task: Task, progress: ProgressCallback | None = None, packet=None,
                      completion_probe=None) -> Receipt:
        started = time.monotonic()
        message = (f"{self.display_name} is plugin-ready but has no execution adapter in this build. "
                   f"Route this task to an implemented provider or install a {self.id} provider plugin.")
        return Receipt(task_id=task.id, agent=task.owner, status="failed", summary=message,
                       token_usage={"input": 0, "output": 0, "cached": 0, "source": "unavailable", "estimated": False},
                       confidence="unknown", uncertainty_reason=message, needs_escalation=False,
                       error_code=NOT_IMPLEMENTED, duration_seconds=time.monotonic() - started)


class OpenAIProvider(PlannedProvider):
    id = "openai"
    display_name = "OpenAI"
    kind = ProviderKind.API
    credential_variables = ("OPENAI_API_KEY",)
    declared = {"text": Support.SUPPORTED, "vision": Support.MODEL_DEPENDENT,
                "tool_use": Support.SUPPORTED, "structured_output": Support.SUPPORTED,
                "streaming": Support.SUPPORTED, "usage_reporting": Support.SUPPORTED,
                "long_context": Support.MODEL_DEPENDENT, "image_generation": Support.MODEL_DEPENDENT,
                "filesystem": Support.UNSUPPORTED, "shell": Support.UNSUPPORTED,
                "code_execution": Support.MODEL_DEPENDENT}


class AnthropicProvider(PlannedProvider):
    id = "anthropic"
    display_name = "Claude"
    kind = ProviderKind.HYBRID
    credential_variables = ("ANTHROPIC_API_KEY",)
    executables = ("claude",)
    declared = {"text": Support.SUPPORTED, "vision": Support.MODEL_DEPENDENT,
                "tool_use": Support.SUPPORTED, "structured_output": Support.SUPPORTED,
                "streaming": Support.SUPPORTED, "usage_reporting": Support.SUPPORTED,
                "long_context": Support.SUPPORTED, "image_generation": Support.UNSUPPORTED,
                "filesystem": Support.MODEL_DEPENDENT, "shell": Support.MODEL_DEPENDENT,
                "code_execution": Support.MODEL_DEPENDENT}


class GeminiProvider(PlannedProvider):
    id = "gemini"
    display_name = "Gemini"
    kind = ProviderKind.HYBRID
    credential_variables = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    executables = ("gemini",)
    declared = {"text": Support.SUPPORTED, "vision": Support.SUPPORTED,
                "tool_use": Support.SUPPORTED, "structured_output": Support.SUPPORTED,
                "streaming": Support.SUPPORTED, "usage_reporting": Support.SUPPORTED,
                "long_context": Support.SUPPORTED, "image_generation": Support.MODEL_DEPENDENT,
                "filesystem": Support.UNSUPPORTED, "shell": Support.UNSUPPORTED,
                "code_execution": Support.MODEL_DEPENDENT}


class OllamaProvider(PlannedProvider):
    id = "ollama"
    display_name = "Ollama"
    kind = ProviderKind.LOCAL
    execution_mode = ExecutionMode.LOCAL_MODEL
    executables = ("ollama",)
    credential_variables = ("OLLAMA_HOST",)
    declared = {"text": Support.SUPPORTED, "vision": Support.MODEL_DEPENDENT,
                "tool_use": Support.MODEL_DEPENDENT, "structured_output": Support.MODEL_DEPENDENT,
                "streaming": Support.SUPPORTED, "usage_reporting": Support.MODEL_DEPENDENT,
                "long_context": Support.MODEL_DEPENDENT, "image_generation": Support.UNSUPPORTED,
                "filesystem": Support.UNSUPPORTED, "shell": Support.UNSUPPORTED,
                "code_execution": Support.UNSUPPORTED}


PLANNED_PROVIDERS: tuple[type[PlannedProvider], ...] = (
    OpenAIProvider, AnthropicProvider, GeminiProvider, OllamaProvider,
)
