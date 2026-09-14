"""Compile bounded evidence for one deterministic quality-repair attempt."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


_SECRET_PARTS = {".env", "secrets", "credentials", ".ssh", ".aws"}
_SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
_SENSITIVE_LINE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|password|client[_-]?secret)\s*[:=]"
)


@dataclass(frozen=True, slots=True)
class RepairEvidence:
    error: str
    excerpts: tuple[dict[str, str], ...]
    skipped_paths: tuple[dict[str, str], ...]
    context_chars: int
    max_context_chars: int

    def to_dict(self) -> dict:
        return asdict(self)


def _safe_path(root: Path, relative: str) -> tuple[Path | None, str | None]:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None, "outside_project"
    lowered = {part.lower() for part in candidate.parts}
    if lowered & _SECRET_PARTS or candidate.suffix.lower() in _SECRET_SUFFIXES:
        return None, "secret_like_path"
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, "outside_project"
    if not resolved.is_file():
        return None, "missing_or_not_file"
    return resolved, None


def _redact(text: str) -> str:
    return "\n".join(
        "[REDACTED SENSITIVE LINE]" if _SENSITIVE_LINE.search(line) else line
        for line in text.splitlines()
    )


def compile_repair_evidence(root: Path, error: str, candidate_paths: Iterable[str],
                            *, max_context_chars: int = 2400,
                            max_excerpt_chars: int = 1600) -> RepairEvidence:
    """Return deterministic, project-confined evidence for a single repair call.

    Candidates must come from trusted change/validation receipts. Unknown value
    never causes broad repository discovery here.
    """
    root = root.resolve()
    bounded_error = " ".join(str(error).split())[:800]
    if not bounded_error:
        raise ValueError("repair evidence requires a deterministic failure")
    if max_context_chars < 256 or max_excerpt_chars < 128:
        raise ValueError("repair evidence budgets are too small")
    remaining = max_context_chars - len(bounded_error)
    excerpts: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in candidate_paths:
        relative = Path(str(raw)).as_posix()
        if relative in seen:
            continue
        seen.add(relative)
        path, reason = _safe_path(root, relative)
        if path is None:
            skipped.append({"path": relative, "reason": reason or "unsafe"})
            continue
        if remaining <= 0:
            skipped.append({"path": relative, "reason": "context_budget_exhausted"})
            continue
        try:
            content = _redact(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            skipped.append({"path": relative, "reason": "not_safe_text"})
            continue
        excerpt = content[:min(max_excerpt_chars, remaining)]
        if not excerpt:
            skipped.append({"path": relative, "reason": "empty"})
            continue
        excerpts.append({
            "path": relative,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "content": excerpt,
        })
        remaining -= len(excerpt)
    return RepairEvidence(
        error=bounded_error,
        excerpts=tuple(excerpts),
        skipped_paths=tuple(skipped),
        context_chars=max_context_chars - max(0, remaining),
        max_context_chars=max_context_chars,
    )
