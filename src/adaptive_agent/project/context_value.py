"""Deterministic value gate for optional model context.

Context is an investment: preloaded text is paid before the model proves it is
needed and may be carried through several provider turns. This module admits an
excerpt only when source-linked evidence predicts a larger avoided discovery
cost. It never uses another model call to decide what to load.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil


@dataclass(frozen=True, slots=True)
class ContextValueDecision:
    path: str
    selected: bool
    reason: str
    load_tokens: int
    expected_saved_tokens: int
    net_tokens: int
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def gate_source_excerpts(
    excerpts: list[dict], *, expected_avoided_chars: dict[str, int] | None = None,
    confidence: dict[str, float] | None = None, safety_margin: float = 1.25,
) -> tuple[list[dict], list[dict], list[ContextValueDecision]]:
    """Return selected excerpts, cheap pointers, and auditable decisions.

    `expected_avoided_chars` must come from prior measured tool output or another
    source-linked deterministic observation. A path without that evidence is a
    pointer, never speculative preload.
    """
    avoided = expected_avoided_chars or {}
    confidence_by_path = confidence or {}
    selected, pointers, decisions = [], [], []
    for excerpt in excerpts:
        path = str(excerpt.get("path", ""))
        body = str(excerpt.get("content", ""))
        load_tokens = ceil(len(body) / 4)
        expected_saved = ceil(max(0, int(avoided.get(path, 0))) / 4)
        certainty = max(0.0, min(1.0, float(confidence_by_path.get(path, 0.0))))
        adjusted_saved = int(expected_saved * certainty)
        worthwhile = certainty >= 0.8 and adjusted_saved > ceil(load_tokens * safety_margin)
        if worthwhile:
            selected.append(excerpt)
            reason = "measured avoided discovery exceeds preload cost and safety margin"
        else:
            pointers.append({
                "path": path,
                "excerpt_sha256": str(excerpt.get("excerpt_sha256", "")),
                "content_available_on_demand": True,
            })
            reason = ("insufficient source-linked savings evidence" if certainty < 0.8
                      else "expected savings do not exceed preload cost and safety margin")
        decisions.append(ContextValueDecision(
            path, worthwhile, reason, load_tokens, adjusted_saved,
            adjusted_saved - load_tokens, certainty,
        ))
    return selected, pointers, decisions
