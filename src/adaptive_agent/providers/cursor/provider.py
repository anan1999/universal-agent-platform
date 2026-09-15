"""Cursor Agent CLI provider.

The adapter uses Cursor's authenticated headless CLI.  Cursor receives only the
explicit execution packet and the selected workspace; UAP never reads or logs
Cursor credentials.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Sequence

from adaptive_agent.core.capabilities import Support
from adaptive_agent.core.execution_packet import ExecutionPacket, ExecutionPacketBuilder
from adaptive_agent.core.models import Receipt, Task
from adaptive_agent.providers.base import (
    AIProvider,
    ExecutionMode,
    ProgressCallback,
    ProviderCapabilities,
    ProviderKind,
    ProviderProbe,
    ProviderState,
    UsageReport,
)


class CursorErrorCode(StrEnum):
    NOT_FOUND = "CURSOR_NOT_FOUND"
    AUTH_ERROR = "CURSOR_AUTH_ERROR"
    TIMEOUT = "CURSOR_TIMEOUT"
    INVALID_ARGUMENT = "CURSOR_INVALID_ARGUMENT"
    EXECUTION_FAILED = "CURSOR_EXECUTION_FAILED"
    OUTPUT_PARSE_FAILED = "CURSOR_OUTPUT_PARSE_FAILED"


def _find_executable() -> str | None:
    found = shutil.which("cursor-agent") or shutil.which("agent")
    if found:
        return found
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        candidate = Path(os.environ["LOCALAPPDATA"]) / "cursor-agent" / "agent.cmd"
        if candidate.is_file():
            return str(candidate)
    return None


def _default_command_prefix() -> list[str]:
    """Avoid the native Windows .cmd shim, which truncates multiline prompts."""
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        versions = Path(os.environ["LOCALAPPDATA"]) / "cursor-agent" / "versions"
        candidates = [item for item in versions.glob("*")
                      if (item / "node.exe").is_file() and (item / "index.js").is_file()]
        if candidates:
            current = max(candidates, key=lambda item: item.stat().st_mtime_ns)
            return [str(current / "node.exe"), str(current / "index.js")]
    executable = _find_executable()
    return [executable] if executable else []


@dataclass(slots=True)
class CursorCapabilities:
    available: bool = False
    authenticated: bool = False
    executable: str | None = None
    version: str | None = None
    supports_headless: bool = False
    supports_model_selection: bool = False
    supports_workspace: bool = False
    supports_json: bool = False
    supports_sandbox: bool = False
    probe_error: str | None = None

    @classmethod
    def probe(cls, executable: str | None = None, timeout: float = 10.0,
              command_prefix: Sequence[str] | None = None) -> "CursorCapabilities":
        path = executable or _find_executable()
        prefix = list(command_prefix) if command_prefix else ([path] if path else _default_command_prefix())
        if not prefix:
            return cls(probe_error="Cursor Agent executable not found")
        result = cls(available=True, executable=str(prefix[0]))
        options = {"capture_output": True, "text": True, "encoding": "utf-8",
                   "errors": "replace", "timeout": timeout, "check": False}
        try:
            version = subprocess.run([*prefix, "--version"], **options)
            help_result = subprocess.run([*prefix, "--help"], **options)
            status = subprocess.run([*prefix, "status"], **options)
            result.version = (version.stdout or version.stderr or "").strip().splitlines()[-1]
            help_text = (help_result.stdout or "") + (help_result.stderr or "")
            status_text = ((status.stdout or "") + (status.stderr or "")).lower()
            result.supports_headless = help_result.returncode == 0 and "--print" in help_text
            result.supports_model_selection = "--model" in help_text
            result.supports_workspace = "--workspace" in help_text
            result.supports_json = "--output-format" in help_text and "json" in help_text
            # The native Windows CLI currently exposes the flag but rejects it
            # at runtime; Cursor documents native sandboxing for macOS/Linux.
            result.supports_sandbox = "--sandbox" in help_text and os.name != "nt"
            result.authenticated = status.returncode == 0 and "not logged in" not in status_text
        except (OSError, subprocess.SubprocessError) as error:
            result.probe_error = str(error)
        return result

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CursorProvider(AIProvider):
    id = "cursor"
    display_name = "Cursor Agent"
    kind = ProviderKind.CLI
    implemented = True
    execution_mode = ExecutionMode.AGENTIC_LOCAL

    def __init__(self, executable: str | None = None, timeout: float = 900.0,
                 command_prefix: Sequence[str] | None = None,
                 capabilities: CursorCapabilities | None = None):
        resolved = executable or _find_executable()
        self.command_prefix = (list(command_prefix) if command_prefix else
                               ([resolved] if executable and resolved else _default_command_prefix()))
        self.timeout = timeout
        self.cursor_capabilities = capabilities or CursorCapabilities.probe(
            resolved, command_prefix=self.command_prefix or None)
        self.packet_builder = ExecutionPacketBuilder()
        self._usage = UsageReport(source="unavailable", invocation_count=0)

    def probe(self) -> ProviderProbe:
        probed = self.cursor_capabilities
        if not probed.available:
            return ProviderProbe(ProviderState.UNAVAILABLE, "Cursor Agent CLI not found",
                                 error=probed.probe_error)
        if not probed.supports_headless:
            return ProviderProbe(ProviderState.INSTALLED, "Cursor Agent headless mode is unavailable",
                                 version=probed.version, executable=probed.executable,
                                 error=probed.probe_error)
        if not probed.authenticated:
            return ProviderProbe(ProviderState.UNCONFIGURED, "Cursor Agent login is required",
                                 version=probed.version, executable=probed.executable,
                                 configuration={"authenticated": False})
        return ProviderProbe(ProviderState.CONNECTED, "Cursor Agent CLI is authenticated",
                             version=probed.version, executable=probed.executable,
                             error=probed.probe_error,
                             configuration={"authenticated": True})

    def capabilities(self) -> ProviderCapabilities:
        probed = self.cursor_capabilities
        flag = lambda value: Support.SUPPORTED if value else Support.UNSUPPORTED
        usable = probed.available and probed.authenticated and probed.supports_headless
        return ProviderCapabilities({
            "text": flag(usable),
            "vision": Support.MODEL_DEPENDENT,
            "tool_use": flag(usable),
            "filesystem": flag(usable and probed.supports_workspace),
            "write_access": flag(usable and probed.supports_workspace),
            "repository_access": flag(usable and probed.supports_workspace),
            "shell": flag(usable),
            "structured_output": flag(usable and probed.supports_json),
            "streaming": Support.UNSUPPORTED,
            "usage_reporting": flag(usable and probed.supports_json),
            "long_context": Support.MODEL_DEPENDENT,
            "image_generation": Support.UNSUPPORTED,
            "code_execution": flag(usable),
        })

    def usage(self) -> UsageReport:
        return self._usage

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.display_name, "kind": self.kind.value,
                "implemented": True, "execution_mode": self.execution_mode.value,
                "capabilities": self.capabilities().to_dict(),
                "cursor": self.cursor_capabilities.to_dict(), **self.probe().to_dict()}

    async def execute(self, task: Task, progress: ProgressCallback | None = None,
                      packet: ExecutionPacket | None = None, completion_probe=None) -> Receipt:
        started = time.monotonic()
        probed = self.cursor_capabilities
        model = task.metadata.get("model")
        if not self.command_prefix or not probed.available:
            return self._failure(task, CursorErrorCode.NOT_FOUND,
                                 "Cursor Agent executable is unavailable.", started, model)
        if not probed.authenticated:
            return self._failure(task, CursorErrorCode.AUTH_ERROR,
                                 "Cursor Agent login is required.", started, model)
        working_directory = Path(task.metadata.get("working_directory", Path.cwd())).resolve()
        packet = packet or self.packet_builder.build(task, working_directory,
                                                     working_directory.name, "unknown")
        args = [*self.command_prefix, "--print", "--trust", "--output-format", "json",
                "--workspace", str(packet.working_directory)]
        if probed.supports_sandbox:
            args.extend(["--sandbox", "enabled"])
        if packet.read_only:
            args.extend(["--mode", "ask"])
        else:
            args.append("--force")
        if model and probed.supports_model_selection:
            args.extend(["--model", str(model)])
        prompt = packet.render() + "\n\n" + self._result_contract()
        args.append(prompt)
        before = self._snapshot(packet.working_directory)
        if progress:
            progress(1, f"Spawning Cursor Agent for {task.title}")
        try:
            returncode, stdout, stderr = await self._communicate(args, packet.working_directory)
        except TimeoutError:
            return self._failure(task, CursorErrorCode.TIMEOUT,
                                 f"Cursor Agent exceeded {self.timeout:g}s timeout.", started, model)
        except OSError as error:
            return self._failure(task, CursorErrorCode.NOT_FOUND, str(error), started, model)
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        if returncode != 0:
            diagnostic = stdout_text.strip() or stderr_text.strip()
            return self._failure(task, self.classify_failure(diagnostic),
                                 self._bounded_error(diagnostic), started, model)
        try:
            result, usage, execution_id = self._parse_output(stdout_text)
        except (ValueError, json.JSONDecodeError) as error:
            return self._failure(task, CursorErrorCode.OUTPUT_PARSE_FAILED,
                                 str(error), started, model)
        observed_files = self._changed_files(before, self._snapshot(packet.working_directory))
        if observed_files:
            result["files"] = observed_files
        token_usage: dict[str, Any] = {
            "input": usage["input"], "output": usage["output"],
            "cached": usage["cached"], "source": "measured", "estimated": False,
            "invocation_count": 1,
        }
        if execution_id:
            token_usage["execution_id"] = execution_id
        self._usage = UsageReport(
            self._usage.input_tokens + usage["input"],
            self._usage.output_tokens + usage["output"],
            self._usage.cached_tokens + usage["cached"], "measured",
            self._usage.invocation_count + 1)
        if progress:
            progress(100, f"Cursor Agent completed {task.title}")
        return Receipt(
            task_id=task.id, agent=task.owner, status=result["status"],
            summary=result["summary"], files=result.get("files", []),
            findings=result.get("findings", []), token_usage=token_usage,
            confidence=result.get("confidence", "unknown"),
            uncertainty_reason=result.get("uncertainty_reason", ""),
            needs_escalation=bool(result.get("needs_escalation", False)),
            provider=self.id, model=str(model) if model else None,
            learning_evidence=(result.get("learning_evidence", [])
                               if isinstance(result.get("learning_evidence"), list) else []),
            duration_seconds=time.monotonic() - started,
        )

    async def _communicate(self, args: list[str], working_directory: Path) -> tuple[int, bytes, bytes]:
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(working_directory), env=os.environ.copy())
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except TimeoutError:
            process.terminate()
            await process.wait()
            raise
        except asyncio.CancelledError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()
            raise
        return process.returncode or 0, stdout, stderr

    @staticmethod
    def _result_contract() -> str:
        return (
            "FINAL RESPONSE CONTRACT: Return only one JSON object, without a Markdown fence. "
            "It must contain status (completed|failed|blocked), summary (string), files "
            "(changed path strings), findings (string array), confidence "
            "(high|medium|low|unknown), uncertainty_reason (string), needs_escalation "
            "(boolean), and learning_evidence (array; empty when no evidence qualifies). "
            "Every learning_evidence item must contain: type (one of knowledge, project_fact, "
            "validated_project_fact, decision, command, evaluation_rule, known_issue, procedure, "
            "skill, agent_role, or agent), summary (string), "
            "evidence (string array), related_paths (string array), capabilities (string array), "
            "tags (string array), expected_reuse (integer), validation (string), detail (string), "
            "rationale (string), alternatives (string array), procedure_steps (string array), "
            "inputs (string array), outputs (string array), and evaluation (string array)."
        )

    @staticmethod
    def _parse_output(output: str) -> tuple[dict[str, Any], dict[str, int], str | None]:
        envelope = json.loads(output.strip())
        if envelope.get("type") != "result" or envelope.get("subtype") != "success":
            raise ValueError("Cursor JSON output did not contain a successful result")
        text = envelope.get("result")
        if not isinstance(text, str):
            raise ValueError("Cursor JSON output did not contain a final response")
        raw = envelope.get("usage") if isinstance(envelope.get("usage"), dict) else {}
        direct = int(raw.get("inputTokens", 0) or 0)
        cache_read = int(raw.get("cacheReadTokens", 0) or 0)
        cache_write = int(raw.get("cacheWriteTokens", 0) or 0)
        usage = {"input": direct + cache_read + cache_write,
                 "output": int(raw.get("outputTokens", 0) or 0),
                 "cached": cache_read + cache_write}
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            stripped = "\n".join(lines[1:-1]).strip()
        try:
            result = json.loads(stripped)
        except json.JSONDecodeError:
            # Cursor models occasionally preface an otherwise valid object even
            # when explicitly asked for JSON-only output. Decode the first JSON
            # object, but never infer a receipt from arbitrary prose.
            start = stripped.find("{")
            if start < 0:
                # Cursor's print mode sometimes emits only its concise final
                # summary after a successful tool-using run. Independent UAP
                # quality gates validate the actual workspace result.
                result = {"status": "completed", "summary": stripped,
                          "files": [], "findings": [], "confidence": "unknown",
                          "uncertainty_reason": "Cursor returned a plain-text final summary.",
                          "needs_escalation": False, "learning_evidence": []}
            else:
                result, _ = json.JSONDecoder().raw_decode(stripped[start:])
        if not isinstance(result, dict) or result.get("status") not in {"completed", "failed", "blocked"}:
            raise ValueError("Cursor final response did not match the receipt contract")
        if not isinstance(result.get("summary"), str):
            raise ValueError("Cursor final response is missing summary")
        return result, usage, str(envelope.get("session_id") or "") or None

    @staticmethod
    def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
        ignored = {".git", ".agent", ".cursor", "node_modules", "__pycache__",
                   ".pytest_cache", ".benchmark-pytest-tmp"}
        snapshot: dict[str, tuple[int, int]] = {}
        for path in root.rglob("*"):
            if not path.is_file() or any(part in ignored for part in path.relative_to(root).parts):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            snapshot[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
        return snapshot

    @staticmethod
    def _changed_files(before: dict[str, tuple[int, int]],
                       after: dict[str, tuple[int, int]]) -> list[str]:
        return sorted(path for path, signature in after.items()
                      if before.get(path) != signature)

    @staticmethod
    def classify_failure(message: str) -> CursorErrorCode:
        lower = message.lower()
        if any(marker in lower for marker in ("not logged in", "unauthorized", "authentication", "401")):
            return CursorErrorCode.AUTH_ERROR
        if any(marker in lower for marker in ("unknown option", "invalid argument", "model not found")):
            return CursorErrorCode.INVALID_ARGUMENT
        return CursorErrorCode.EXECUTION_FAILED

    @staticmethod
    def _bounded_error(message: str, limit: int = 1200) -> str:
        compact = " ".join(message.split())
        return compact[:limit] + ("…" if len(compact) > limit else "")

    @staticmethod
    def _failure(task: Task, code: CursorErrorCode, message: str, started: float,
                 model: str | None = None) -> Receipt:
        return Receipt(task_id=task.id, agent=task.owner, status="failed", summary=message,
                       token_usage={"input": 0, "output": 0, "cached": 0,
                                    "source": "unavailable", "estimated": False},
                       confidence="unknown", uncertainty_reason=message,
                       needs_escalation=code not in {CursorErrorCode.NOT_FOUND,
                                                    CursorErrorCode.AUTH_ERROR,
                                                    CursorErrorCode.INVALID_ARGUMENT,
                                                    CursorErrorCode.TIMEOUT},
                       error_code=code.value, provider=CursorProvider.id,
                       model=str(model) if model else None,
                       duration_seconds=time.monotonic() - started)
