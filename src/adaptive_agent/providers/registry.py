"""Provider plugin registry.

Adding a provider means registering one `ProviderDescriptor`. No orchestration,
planning, routing, or dashboard code changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from adaptive_agent.providers.base import AIProvider, ProviderKind, ProviderState


@dataclass(slots=True)
class ProviderDescriptor:
    id: str
    display_name: str
    kind: ProviderKind
    factory: Callable[..., AIProvider]
    implemented: bool = True
    #: Where this adapter came from: built_in | plugin | user
    trust: str = "built_in"
    notes: str = ""
    profile_for_role: Callable[[str], str | None] | None = None


class ProviderRegistry:
    """Ordered registry of available adapters."""

    def __init__(self, descriptors: Iterable[ProviderDescriptor] = ()):
        self._descriptors: dict[str, ProviderDescriptor] = {}
        for descriptor in descriptors:
            self.register(descriptor)

    def register(self, descriptor: ProviderDescriptor, replace: bool = False) -> None:
        if descriptor.id in self._descriptors and not replace:
            raise ValueError(f"provider already registered: {descriptor.id}")
        self._descriptors[descriptor.id] = descriptor

    def __contains__(self, provider_id: object) -> bool:
        return provider_id in self._descriptors

    def ids(self) -> list[str]:
        return list(self._descriptors)

    def implemented_ids(self) -> list[str]:
        return [key for key, value in self._descriptors.items() if value.implemented]

    def get(self, provider_id: str) -> ProviderDescriptor:
        if provider_id not in self._descriptors:
            raise KeyError(f"unknown provider: {provider_id}")
        return self._descriptors[provider_id]

    def create(self, provider_id: str, **kwargs: Any) -> AIProvider:
        descriptor = self.get(provider_id)
        return descriptor.factory(**kwargs)

    def profile_for(self, provider_id: str, role: str) -> str | None:
        """Resolve optional provider-native metadata without leaking it into core."""
        resolver = self.get(provider_id).profile_for_role
        return resolver(role) if resolver else None

    def instance(self, provider_id: str, **kwargs: Any) -> AIProvider:
        """Create an adapter for inspection, tolerating constructor failures."""
        try:
            return self.create(provider_id, **kwargs)
        except Exception:  # pragma: no cover - defensive: a broken plugin must not break discovery
            return self.create(provider_id)

    def discover(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Probe every registered adapter. Never returns credential values."""
        results = []
        for descriptor in self._descriptors.values():
            try:
                provider = descriptor.factory(**kwargs) if descriptor.implemented else descriptor.factory()
                probe = provider.probe()
                capabilities = provider.capabilities().to_dict()
                error = probe.error
                state = probe.state
                detail = probe.detail
            except Exception as failure:  # pragma: no cover - broken plugin
                capabilities, error, detail = {}, str(failure), "adapter failed to initialize"
                state = ProviderState.UNAVAILABLE
            results.append({
                "id": descriptor.id, "name": descriptor.display_name, "type": descriptor.kind.value,
                "status": state.value, "ready": state.ready, "implemented": descriptor.implemented,
                "trust": descriptor.trust, "detail": detail, "notes": descriptor.notes,
                "error": error, "capabilities": capabilities,
            })
        return results

    def ready_ids(self, **kwargs: Any) -> list[str]:
        return [item["id"] for item in self.discover(**kwargs) if item["ready"]]


def _codex_factory(**kwargs: Any) -> AIProvider:
    from adaptive_agent.providers.codex import CodexProvider

    timeout = kwargs.get("timeout", 900.0)
    return CodexProvider(timeout=timeout)


def _mock_factory(**kwargs: Any) -> AIProvider:
    from adaptive_agent.providers.mock import MockProvider

    return MockProvider(delay=kwargs.get("delay", 0.02))


def _codex_profile(role: str) -> str | None:
    from adaptive_agent.providers.codex import codex_profile_for

    return codex_profile_for(role)


def default_registry() -> ProviderRegistry:
    from adaptive_agent.providers.planned import PLANNED_PROVIDERS

    registry = ProviderRegistry([
        ProviderDescriptor("codex", "Codex", ProviderKind.CLI, _codex_factory,
                           notes="First validated real adapter.", profile_for_role=_codex_profile),
        ProviderDescriptor("mock", "Mock", ProviderKind.TEST, _mock_factory,
                           notes="Deterministic; consumes zero AI quota."),
    ])
    for planned in PLANNED_PROVIDERS:
        registry.register(ProviderDescriptor(
            planned.id, planned.display_name, planned.kind, planned, implemented=False,
            notes="Plugin-ready interface; no execution adapter in this build."))
    return registry


_DEFAULT: ProviderRegistry | None = None


def providers() -> ProviderRegistry:
    """Process-wide registry. Plugins register into this instance."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = default_registry()
    return _DEFAULT
