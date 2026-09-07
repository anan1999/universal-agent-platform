"""Model catalog.

Model names are data, never code. Routing asks this registry "which models can
do X?" instead of "what model does role Y use?".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from adaptive_agent.core.capabilities import CapabilityProfile, Level, Requirement, normalize


#: Descriptive cost and latency buckets. Exact prices are intentionally absent;
#: they go stale and the router only needs an ordering.
COST_RANK = {"free": 0, "low": 1, "medium": 2, "high": 3, "very_high": 4, "unknown": 2}
LATENCY_RANK = {"instant": 0, "fast": 1, "medium": 2, "slow": 3, "unknown": 2}


@dataclass(slots=True)
class ModelDescriptor:
    id: str
    provider: str
    model_id: str
    display_name: str = ""
    capabilities: CapabilityProfile = field(default_factory=CapabilityProfile)
    cost: str = "unknown"
    latency: str = "unknown"
    context_size: int | None = None
    availability: str = "unknown"
    enabled: bool = True
    #: Descriptive summary only. Never used as a routing key.
    tier: str = "unknown"
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self) -> None:
        self.display_name = self.display_name or self.model_id

    @property
    def cost_rank(self) -> int:
        return COST_RANK.get(self.cost, 2)

    @property
    def latency_rank(self) -> int:
        return LATENCY_RANK.get(self.latency, 2)

    def level(self, capability: str) -> Level:
        return self.capabilities.level(capability)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "provider": self.provider, "model_id": self.model_id,
                "display_name": self.display_name, "capabilities": self.capabilities.to_dict(),
                "cost": self.cost, "latency": self.latency, "context_size": self.context_size,
                "availability": self.availability, "enabled": self.enabled, "tier": self.tier,
                "tags": list(self.tags), "notes": self.notes}

    @classmethod
    def from_config(cls, identifier: str, provider: str, data: dict[str, Any]) -> "ModelDescriptor":
        return cls(
            id=identifier,
            provider=provider,
            model_id=str(data.get("model_id", identifier)),
            display_name=str(data.get("display_name", "")),
            capabilities=CapabilityProfile({normalize(name): Level.coerce(level)
                                            for name, level in (data.get("capabilities") or {}).items()}),
            cost=str(data.get("cost", "unknown")),
            latency=str(data.get("latency", "unknown")),
            context_size=data.get("context_size"),
            availability=str(data.get("availability", "unknown")),
            enabled=bool(data.get("enabled", True)),
            tier=str(data.get("tier", "unknown")),
            tags=list(data.get("tags", [])),
            notes=str(data.get("notes", "")),
        )


class ModelRegistry:
    def __init__(self, models: Iterable[ModelDescriptor] = ()):
        self._models: dict[str, ModelDescriptor] = {model.id: model for model in models}

    @classmethod
    def from_yaml(cls, *paths: Path) -> "ModelRegistry":
        registry = cls()
        for path in paths:
            if not path or not Path(path).exists():
                continue
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
            for provider, entries in (data.get("models") or {}).items():
                for identifier, spec in (entries or {}).items():
                    descriptor = ModelDescriptor.from_config(identifier, provider, spec or {})
                    registry.add(descriptor, replace=True)
        return registry

    def add(self, model: ModelDescriptor, replace: bool = False) -> None:
        if model.id in self._models and not replace:
            raise ValueError(f"model already registered: {model.id}")
        self._models[model.id] = model

    def get(self, model_id: str) -> ModelDescriptor | None:
        if model_id in self._models:
            return self._models[model_id]
        return next((model for model in self._models.values() if model.model_id == model_id), None)

    def all(self) -> list[ModelDescriptor]:
        return list(self._models.values())

    def for_provider(self, provider: str) -> list[ModelDescriptor]:
        return [model for model in self._models.values() if model.provider == provider and model.enabled]

    def candidates(self, providers: Iterable[str], requirements: Iterable[Requirement]) -> list[ModelDescriptor]:
        """Models from the given providers that satisfy every mandatory requirement."""
        allowed = set(providers)
        wanted = list(requirements)
        return [model for model in self._models.values()
                if model.enabled and model.provider in allowed and not model.capabilities.gaps(wanted)]

    def to_dict(self) -> list[dict[str, Any]]:
        return [model.to_dict() for model in sorted(self._models.values(), key=lambda item: (item.provider, item.id))]
