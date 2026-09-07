"""Provider-agnostic execution contract.

`AIProvider` is the only thing the universal core knows about an AI backend.
Only `execute()` is mandatory. Everything else has a safe default so a minimal
adapter stays small and an unimplemented adapter can report the truth instead of
pretending.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

from adaptive_agent.core.capabilities import Support
from adaptive_agent.core.models import Receipt, Task

if False:  # pragma: no cover - typing-only import without a runtime cycle
    from adaptive_agent.core.execution_packet import ExecutionPacket


ProgressCallback = Callable[[int, str], None]


class ProviderState(StrEnum):
    """Lifecycle of an adapter, from "we ship code for it" to "it answered us"."""

    AVAILABLE = "available"      # adapter exists in this build
    INSTALLED = "installed"      # runtime or binary detected on this machine
    CONFIGURED = "configured"    # credentials or settings present
    CONNECTED = "connected"      # probe reached the backend successfully
    UNAVAILABLE = "unavailable"  # cannot be used right now
    UNSUPPORTED = "unsupported"  # no working adapter in this build

    @property
    def ready(self) -> bool:
        return self in {ProviderState.CONFIGURED, ProviderState.CONNECTED}


class ProviderKind(StrEnum):
    CLI = "cli"
    API = "api"
    LOCAL = "local"
    TEST = "test"
    HYBRID = "hybrid"


#: Capability vocabulary every provider is described against. Providers may
#: report capabilities outside this list; these are simply the well-known ones.
PROVIDER_CAPABILITIES: tuple[str, ...] = (
    "text", "vision", "tool_use", "filesystem", "shell", "structured_output",
    "streaming", "usage_reporting", "long_context", "image_generation", "code_execution",
)


@dataclass(slots=True)
class ProviderCapabilities:
    """Declared support per capability. Absent entries are `unknown`, not `false`."""

    values: dict[str, Support] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.values = {str(name): Support(value) if not isinstance(value, Support) else value
                       for name, value in self.values.items()}

    def get(self, name: str) -> Support:
        return self.values.get(name, Support.UNKNOWN)

    def supports(self, name: str, allow_uncertain: bool = True) -> bool:
        support = self.get(name)
        return support is Support.SUPPORTED or (allow_uncertain and support.usable)

    def with_values(self, **updates: Support) -> "ProviderCapabilities":
        return ProviderCapabilities({**self.values, **updates})

    def to_dict(self) -> dict[str, str]:
        merged = {name: self.get(name).value for name in PROVIDER_CAPABILITIES}
        merged.update({name: support.value for name, support in self.values.items()})
        return dict(sorted(merged.items()))

    @classmethod
    def unknown(cls) -> "ProviderCapabilities":
        return cls({name: Support.UNKNOWN for name in PROVIDER_CAPABILITIES})


@dataclass(slots=True)
class ProviderProbe:
    """Result of asking an adapter whether it can actually run right now."""

    state: ProviderState = ProviderState.UNAVAILABLE
    detail: str = ""
    version: str | None = None
    executable: str | None = None
    error: str | None = None
    #: Never contains secret values, only whether configuration was found.
    configuration: dict[str, bool] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.state.ready

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state.value, "detail": self.detail, "version": self.version,
                "executable": self.executable, "error": self.error,
                "configuration": dict(self.configuration)}


@dataclass(slots=True)
class UsageReport:
    """Provider-reported or estimated consumption for a single execution."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    #: measured | estimated | unavailable
    source: str = "unavailable"
    invocation_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"input": self.input_tokens, "output": self.output_tokens,
                "cached": self.cached_tokens, "source": self.source,
                "estimated": self.source == "estimated",
                "invocation_count": self.invocation_count}


class AIProvider(ABC):
    """An AI execution backend.

    Subclasses must implement `execute`. `probe`, `capabilities`, `usage`,
    `cancel`, and `stream` are optional; the defaults are honest rather than
    optimistic.
    """

    id: ClassVar[str] = "unknown"
    display_name: ClassVar[str] = "Unknown Provider"
    kind: ClassVar[ProviderKind] = ProviderKind.API
    #: False for adapters that only exist as a plugin surface.
    implemented: ClassVar[bool] = True

    @abstractmethod
    async def execute(
        self,
        task: Task,
        progress: ProgressCallback | None = None,
        packet: "ExecutionPacket | None" = None,
    ) -> Receipt:
        raise NotImplementedError

    def probe(self) -> ProviderProbe:
        return ProviderProbe(ProviderState.AVAILABLE, "Adapter present; readiness not probed.")

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities.unknown()

    def usage(self) -> UsageReport:
        """Cumulative usage since construction. `unavailable` when not tracked."""
        return UsageReport()

    async def cancel(self, task: Task | None = None) -> None:
        """Best-effort cancellation. The scheduler also cancels the asyncio task."""
        return None

    def supports_streaming(self) -> bool:
        return self.capabilities().get("streaming") is Support.SUPPORTED

    async def stream(
        self,
        task: Task,
        packet: "ExecutionPacket | None" = None,
    ) -> AsyncIterator[str]:
        raise NotImplementedError(f"{self.id} does not implement streaming")
        yield ""  # pragma: no cover - makes the signature an async generator

    def describe(self) -> dict[str, Any]:
        probe = self.probe()
        return {"id": self.id, "name": self.display_name, "kind": self.kind.value,
                "implemented": self.implemented, "capabilities": self.capabilities().to_dict(),
                **probe.to_dict()}
