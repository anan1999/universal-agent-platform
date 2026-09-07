"""Deprecated import path.

Codex agent-profile discovery moved to `adaptive_agent.providers.codex` in V2 so
that no Codex knowledge sits in the generic `agents` package. This shim keeps
existing imports working; see the deprecation register in
`docs/v2-migration-audit.md`.
"""

from adaptive_agent.providers.codex.agent_config import CodexAgentConfigAdapter, ImportedCodexAgent

__all__ = ["CodexAgentConfigAdapter", "ImportedCodexAgent"]
