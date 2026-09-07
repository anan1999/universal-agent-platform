"""Codex execution provider.

Every Codex-specific concept lives in this package: CLI discovery, `codex exec`
argument construction, JSONL parsing, reasoning flags, measured token
extraction, the child-execution guard, and read-only Codex agent profiles.
None of it is visible to the universal core, which only sees `AIProvider`.
"""

from adaptive_agent.providers.codex.agent_config import CodexAgentConfigAdapter, ImportedCodexAgent
from adaptive_agent.providers.codex.bindings import codex_profile_for, provider_bindings
from adaptive_agent.providers.codex.provider import (
    RESULT_SCHEMA,
    CodexCapabilities,
    CodexErrorCode,
    CodexProvider,
)

__all__ = [
    "CodexAgentConfigAdapter",
    "CodexCapabilities",
    "CodexErrorCode",
    "CodexProvider",
    "ImportedCodexAgent",
    "RESULT_SCHEMA",
    "codex_profile_for",
    "provider_bindings",
]
