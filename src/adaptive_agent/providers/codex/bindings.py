"""Optional, provider-specific role bindings.

Role-to-native-profile bindings are one environment's convention, not platform
architecture, so they live in `config/provider_bindings.yaml` and are read only by the provider
that owns them. The universal router never consults this file.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from adaptive_agent.runtime import RESOURCE_ROOT, platform_home


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@lru_cache(maxsize=8)
def _load(provider: str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for path in (RESOURCE_ROOT / "config" / "provider_bindings.yaml",
                 platform_home() / "provider_bindings.yaml"):
        data = _read(path).get("providers", {}).get(provider, {})
        for section, values in data.items():
            if isinstance(values, dict):
                merged.setdefault(section, {}).update(values)
            else:
                merged[section] = values
    return merged


def provider_bindings(provider: str = "codex") -> dict[str, Any]:
    """Role -> provider profile/model hints for one provider. Always optional."""
    return dict(_load(provider))


def codex_profile_for(role: str | None) -> str | None:
    """The Codex agent profile conventionally used for a logical role, if any."""
    if not role:
        return None
    return _load("codex").get("role_profiles", {}).get(str(role))


def clear_cache() -> None:
    _load.cache_clear()
