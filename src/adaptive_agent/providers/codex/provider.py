from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Sequence

from adaptive_agent import __version__
from adaptive_agent.core.capabilities import Support
from adaptive_agent.core.execution_packet import ExecutionPacket, ExecutionPacketBuilder
from adaptive_agent.core.models import Receipt, Task
from adaptive_agent.providers.base import (
    AIProvider,
    CompletionProbe,
    ExecutionMode,
    ProgressCallback,
    ProviderCapabilities,
    ProviderKind,
    ProviderProbe,
    ProviderState,
    UsageReport,
)


class CodexErrorCode(StrEnum):
    NOT_FOUND = "CODEX_NOT_FOUND"
    AUTH_ERROR = "CODEX_AUTH_ERROR"
    TIMEOUT = "CODEX_TIMEOUT"
    INVALID_ARGUMENT = "CODEX_INVALID_ARGUMENT"
    EXECUTION_FAILED = "CODEX_EXECUTION_FAILED"
    OUTPUT_PARSE_FAILED = "CODEX_OUTPUT_PARSE_FAILED"
    CAPABILITY_UNAVAILABLE = "CODEX_CAPABILITY_UNAVAILABLE"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


class CodexBudgetExceeded(RuntimeError):
    def __init__(self, reason: str, tool_calls: int, assistant_messages: int):
        super().__init__(reason)
        self.reason = reason
        self.tool_calls = tool_calls
        self.assistant_messages = assistant_messages


class CodexTimeout(TimeoutError):
    """Timeout that preserves bounded subprocess telemetry collected so far."""

    def __init__(self, stdout: bytes, stderr: bytes):
        super().__init__("Codex execution timed out")
        self.stdout = stdout
        self.stderr = stderr


class CodexArtifactCompleted(RuntimeError):
    """The external artifact probe passed before Codex emitted its final receipt."""

    def __init__(self, stdout: bytes, stderr: bytes):
        super().__init__("Artifact completion probe passed")
        self.stdout = stdout
        self.stderr = stderr


class CodexControlledStop(RuntimeError):
    """A steered turn reached an interrupted terminal state after acceptance."""

    def __init__(self, stdout: bytes, stderr: bytes):
        super().__init__("Accepted artifact reached a controlled provider stop")
        self.stdout = stdout
        self.stderr = stderr


@dataclass(slots=True)
class CodexEventBudget:
    max_tool_calls: int | None = None
    max_assistant_messages: int | None = None
    tool_calls: int = 0
    assistant_messages: int = 0

    def observe(self, line: bytes) -> str | None:
        try:
            event = json.loads(line.decode("utf-8", errors="replace"))
        except (ValueError, json.JSONDecodeError):
            return None
        item = event.get("item")
        if not isinstance(item, dict):
            return None
        kind = item.get("type")
        tools = {"command_execution", "mcp_tool_call", "web_search"}
        if event.get("type") == "item.started" and kind in tools:
            if self.max_tool_calls is not None and self.tool_calls >= self.max_tool_calls:
                return f"provider tool-call budget exhausted at {self.tool_calls}"
        if event.get("type") == "item.completed" and kind in tools:
            self.tool_calls += 1
            if self.max_tool_calls is not None and self.tool_calls > self.max_tool_calls:
                return f"provider tool-call budget exhausted at {self.tool_calls}"
        if event.get("type") == "item.completed" and kind == "agent_message":
            self.assistant_messages += 1
            if (self.max_assistant_messages is not None and
                    self.assistant_messages > self.max_assistant_messages):
                return f"provider assistant-message budget exhausted at {self.assistant_messages}"
        return None


@dataclass(slots=True)
class CodexCapabilities:
    available: bool = False
    executable: str | None = None
    version: str | None = None
    supports_noninteractive: bool = False
    supports_model_selection: bool = False
    supports_reasoning_selection: bool = False
    supports_structured_output: bool = False
    supports_usage_reporting: bool = False
    supports_working_directory: bool = False
    supports_jsonl: bool = False
    supports_auto_approval: bool = False
    probe_error: str | None = None

    @classmethod
    def probe(cls, executable: str | None = None, timeout: float = 10.0,
              command_prefix: Sequence[str] | None = None) -> "CodexCapabilities":
        path = executable or shutil.which("codex")
        prefix = list(command_prefix) if command_prefix else ([path] if path else [])
        if not prefix:
            return cls(probe_error="codex executable not found")
        result = cls(available=True, executable=str(Path(prefix[0]).resolve()))
        try:
            options = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace",
                       "timeout": timeout, "check": False}
            version = subprocess.run([*prefix, "--version"], **options)
            help_result = subprocess.run([*prefix, "exec", "--help"], **options)
            result.version = (version.stdout or version.stderr or "").strip().splitlines()[-1]
            help_text = (help_result.stdout or "") + (help_result.stderr or "")
            result.supports_noninteractive = help_result.returncode == 0 and "Run Codex non-interactively" in help_text
            result.supports_model_selection = "--model" in help_text
            result.supports_reasoning_selection = "--config" in help_text
            result.supports_structured_output = "--output-schema" in help_text
            result.supports_working_directory = "--cd" in help_text
            result.supports_jsonl = "--json" in help_text
            result.supports_auto_approval = "--approve-for-me" in help_text
            # A real JSONL execution must confirm usage events before this becomes true.
            result.supports_usage_reporting = False
        except (OSError, subprocess.SubprocessError) as error:
            result.probe_error = str(error)
        return result

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


RESULT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "additionalProperties": False,
    "required": ["status", "summary", "files", "findings", "confidence", "uncertainty_reason",
                 "needs_escalation", "learning_evidence"],
    "properties": {
        "status": {"type": "string", "enum": ["completed", "failed", "blocked"]},
        "summary": {"type": "string"},
        "files": {"type": "array", "items": {"type": "string"}},
        "findings": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["high", "medium", "low", "unknown"]},
        "uncertainty_reason": {"type": "string"},
        "needs_escalation": {"type": "boolean"},
        "learning_evidence": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["type", "summary", "evidence", "related_paths", "capabilities",
                         "tags", "expected_reuse", "validation", "detail", "rationale",
                         "alternatives", "procedure_steps", "inputs", "outputs", "evaluation"],
            "properties": {
                "type": {"type": "string"}, "summary": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "related_paths": {"type": "array", "items": {"type": "string"}},
                "capabilities": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "expected_reuse": {"type": "integer"}, "validation": {"type": "string"},
                "detail": {"type": "string"}, "rationale": {"type": "string"},
                "alternatives": {"type": "array", "items": {"type": "string"}},
                "procedure_steps": {"type": "array", "items": {"type": "string"}},
                "inputs": {"type": "array", "items": {"type": "string"}},
                "outputs": {"type": "array", "items": {"type": "string"}},
                "evaluation": {"type": "array", "items": {"type": "string"}},
            },
        }},
    },
}


class CodexProvider(AIProvider):
    id = "codex"
    display_name = "Codex"
    kind = ProviderKind.CLI
    implemented = True
    execution_mode = ExecutionMode.AGENTIC_LOCAL
    # JSONL reports that a tool has started; termination is reactive and is not
    # evidence of a provider-native pre-execution hard limit.
    provider_tool_budget_enforcement = "observed_reactive"

    def __init__(self, executable: str | None = None, timeout: float = 900.0,
                 command_prefix: Sequence[str] | None = None, capabilities: CodexCapabilities | None = None):
        resolved = executable or shutil.which("codex")
        self.command_prefix = list(command_prefix) if command_prefix else ([resolved] if resolved else [])
        self.timeout = timeout
        # Cache the probe result; `capabilities()` exposes the generic contract.
        self.codex_capabilities = capabilities or CodexCapabilities.probe(resolved)
        self.packet_builder = ExecutionPacketBuilder()
        self._usage = UsageReport(source="unavailable", invocation_count=0)

    @staticmethod
    def available() -> bool:
        return shutil.which("codex") is not None

    def probe(self) -> ProviderProbe:
        probed = self.codex_capabilities
        if not probed.available:
            return ProviderProbe(ProviderState.UNAVAILABLE, "codex executable not found",
                                 error=probed.probe_error)
        if not probed.supports_noninteractive:
            return ProviderProbe(ProviderState.INSTALLED, "codex found but non-interactive mode is unavailable",
                                 version=probed.version, executable=probed.executable, error=probed.probe_error)
        return ProviderProbe(ProviderState.CONNECTED, "codex exec is available",
                             version=probed.version, executable=probed.executable,
                             error=probed.probe_error,
                             configuration={"codex_home": (Path.home() / ".codex").is_dir()})

    def capabilities(self) -> ProviderCapabilities:
        probed = self.codex_capabilities
        flag = lambda value: Support.SUPPORTED if value else Support.UNSUPPORTED
        return ProviderCapabilities({
            "text": flag(probed.available),
            "vision": Support.MODEL_DEPENDENT,
            "tool_use": flag(probed.available),
            "filesystem": flag(probed.supports_working_directory),
            "write_access": flag(probed.supports_working_directory),
            "repository_access": flag(probed.supports_working_directory),
            "shell": flag(probed.available),
            "structured_output": flag(probed.supports_structured_output),
            "streaming": flag(probed.supports_jsonl),
            "usage_reporting": flag(probed.supports_usage_reporting),
            "long_context": Support.MODEL_DEPENDENT,
            "image_generation": Support.UNSUPPORTED,
            "code_execution": flag(probed.available),
        })

    def usage(self) -> UsageReport:
        return self._usage

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.display_name, "kind": self.kind.value,
                "implemented": True, "execution_mode": self.execution_mode.value,
                "provider_tool_budget_enforcement": self.provider_tool_budget_enforcement,
                "capabilities": self.capabilities().to_dict(),
                "codex": self.codex_capabilities.to_dict(), **self.probe().to_dict()}

    def _accumulate(self, usage: dict[str, int | bool | str]) -> None:
        self._usage = UsageReport(
            self._usage.input_tokens + int(usage.get("input", 0) or 0),
            self._usage.output_tokens + int(usage.get("output", 0) or 0),
            self._usage.cached_tokens + int(usage.get("cached", 0) or 0),
            str(usage.get("source", "unavailable")),
            self._usage.invocation_count + 1,
        )

    async def execute(self, task: Task, progress: ProgressCallback | None = None,
                      packet: ExecutionPacket | None = None,
                      completion_probe: CompletionProbe | None = None) -> Receipt:
        started = time.monotonic()
        probed = self.codex_capabilities
        if not self.command_prefix or not probed.available:
            return self._failure(task, CodexErrorCode.NOT_FOUND, "Codex executable is unavailable.", started)
        if not probed.supports_noninteractive:
            return self._failure(task, CodexErrorCode.CAPABILITY_UNAVAILABLE, "Codex non-interactive mode is unavailable.", started)
        working_directory = Path(task.metadata.get("working_directory", Path.cwd())).resolve()
        packet = packet or self.packet_builder.build(task, working_directory, working_directory.name, "unknown")
        schema_path = self._write_schema(working_directory)
        model = task.metadata.get("model")
        args = [*self.command_prefix, "exec", "--ephemeral", "--ignore-user-config", "--json",
                "--color", "never", "-C", str(packet.working_directory)]
        if not (working_directory / ".git").exists():
            args.append("--skip-git-repo-check")
        # Codex 0.153+ makes --approve-for-me mutually exclusive with an
        # explicit --sandbox; the flag itself uses the workspace-write sandbox.
        if not packet.read_only and probed.supports_auto_approval:
            args.append("--approve-for-me")
        else:
            args.extend(["--sandbox", "read-only" if packet.read_only else "workspace-write"])
        if model and probed.supports_model_selection:
            args.extend(["--model", str(model)])
        if task.reasoning and probed.supports_reasoning_selection:
            args.extend(["--config", f'model_reasoning_effort="{task.reasoning}"'])
        if probed.supports_structured_output:
            args.extend(["--output-schema", str(schema_path)])
        args.append("-")
        if progress:
            progress(1, f"Spawning Codex for {task.title}")
        try:
            budget = task.metadata.get("execution_budget", {})
            if completion_probe is not None and task.metadata.get("codex_live_usage"):
                returncode, stdout, stderr = await self._communicate_app_server(
                    packet.render(), packet.working_directory, budget, completion_probe,
                    model=str(model) if model else None, reasoning=task.reasoning,
                    read_only=packet.read_only)
            elif completion_probe is None:
                returncode, stdout, stderr = await self._communicate(
                    args, packet.render(), packet.working_directory, budget)
            else:
                returncode, stdout, stderr = await self._communicate(
                    args, packet.render(), packet.working_directory, budget, completion_probe)
        except CodexBudgetExceeded as error:
            return self._failure(
                task, CodexErrorCode.BUDGET_EXHAUSTED,
                (f"{error.reason}; observed tool_calls={error.tool_calls}, "
                 f"assistant_messages={error.assistant_messages}."),
                started, model=model)
        except CodexTimeout as error:
            message = f"Codex exceeded {self.timeout:g}s timeout."
            stdout_text = error.stdout.decode("utf-8", errors="replace")
            usage, execution_id = self._parse_telemetry(stdout_text)
            if not usage:
                return self._failure(task, CodexErrorCode.TIMEOUT, message, started, model=model)
            token_usage: dict[str, int | bool | str] = {
                "input": int(usage.get("input_tokens", 0)),
                "output": int(usage.get("output_tokens", 0)),
                "cached": int(usage.get("cached_input_tokens", 0)),
                "source": "partial_measured",
                "estimated": False,
                "complete": False,
                "invocation_count": 1,
                **self._execution_counts(stdout_text),
                **self._usage_breakdown(usage),
            }
            if execution_id:
                token_usage["execution_id"] = execution_id
            self._accumulate(token_usage)
            receipt = self._failure(task, CodexErrorCode.TIMEOUT, message, started, model=model)
            receipt.token_usage = token_usage
            steer_state = self._completion_steer_state(stdout_text)
            if steer_state:
                receipt.completion = {
                    "artifact": "completed", "provider": "timeout",
                    "reason": "timeout_after_external_completion_probe",
                    "steer_state": steer_state,
                }
            return receipt
        except CodexControlledStop as stopped:
            stdout_text = stopped.stdout.decode("utf-8", errors="replace")
            usage, execution_id = self._parse_telemetry(stdout_text)
            source = "measured" if usage else "unavailable"
            token_usage: dict[str, int | bool | str] = {
                "input": int(usage.get("input_tokens", 0)),
                "output": int(usage.get("output_tokens", 0)),
                "cached": int(usage.get("cached_input_tokens", 0)),
                "source": source, "estimated": False, "complete": bool(usage),
                "invocation_count": 1, **self._execution_counts(stdout_text),
                **self._usage_breakdown(usage),
            }
            if execution_id:
                token_usage["execution_id"] = execution_id
            self._accumulate(token_usage)
            return Receipt(
                task_id=task.id, agent=task.owner, status="completed",
                summary="External acceptance passed; Codex reached a controlled terminal stop.",
                token_usage=token_usage, confidence="high", provider=self.id,
                model=str(model) if model else None,
                completion={"artifact": "completed", "provider": "controlled_stop",
                            "reason": "interrupted_after_accepted_completion_steer"},
                duration_seconds=time.monotonic() - started,
            )
        except CodexArtifactCompleted as completed:
            stdout_text = completed.stdout.decode("utf-8", errors="replace")
            usage, execution_id = self._parse_telemetry(stdout_text)
            source = "partial_measured" if usage else "unavailable"
            token_usage: dict[str, int | bool | str] = {
                "input": int(usage.get("input_tokens", 0)),
                "output": int(usage.get("output_tokens", 0)),
                "cached": int(usage.get("cached_input_tokens", 0)),
                "source": source, "estimated": False, "complete": False,
                "invocation_count": 1, **self._execution_counts(stdout_text),
                **self._usage_breakdown(usage),
            }
            if execution_id:
                token_usage["execution_id"] = execution_id
            self._accumulate(token_usage)
            if progress:
                progress(100, f"Artifact completion probe passed for {task.title}")
            return Receipt(
                task_id=task.id, agent=task.owner, status="completed",
                summary="Artifact completion probe passed; provider stopped before final receipt.",
                token_usage=token_usage, confidence="medium", provider=self.id,
                model=str(model) if model else None,
                completion={"artifact": "completed", "provider": "stopped",
                            "reason": "external_completion_probe"},
                duration_seconds=time.monotonic() - started,
            )
        except TimeoutError:
            return self._failure(task, CodexErrorCode.TIMEOUT, f"Codex exceeded {self.timeout:g}s timeout.", started, model=model)
        except FileNotFoundError as error:
            return self._failure(task, CodexErrorCode.NOT_FOUND, str(error), started, model=model)
        except OSError as error:
            return self._failure(task, CodexErrorCode.EXECUTION_FAILED,
                                 f"Codex could not be started: {error}", started, model=model)
        except RuntimeError as error:
            return self._failure(task, CodexErrorCode.EXECUTION_FAILED,
                                 self._bounded_error(str(error)), started, model=model)
        finally:
            schema_path.unlink(missing_ok=True)
        stderr_text = stderr.decode("utf-8", errors="replace")
        stdout_text = stdout.decode("utf-8", errors="replace")
        if returncode != 0:
            diagnostic = stdout_text.strip() or stderr_text.strip()
            return self._failure(task, self.classify_failure(diagnostic),
                                 self._bounded_error(diagnostic), started, model=model)
        try:
            result, usage, execution_id = self._parse_jsonl(stdout_text)
        except (ValueError, json.JSONDecodeError) as error:
            return self._failure(task, CodexErrorCode.OUTPUT_PARSE_FAILED, str(error), started, model=model)
        if progress:
            progress(100, f"Codex completed {task.title}")
        source = "measured" if usage else "estimated"
        token_usage: dict[str, int | bool | str] = {
            "input": int(usage.get("input_tokens", 0)), "output": int(usage.get("output_tokens", 0)),
            "cached": int(usage.get("cached_input_tokens", 0)), "source": source, "estimated": source != "measured",
            "complete": source == "measured",
            "invocation_count": 1,
            **self._execution_counts(stdout_text),
            **self._usage_breakdown(usage),
        }
        if execution_id:
            token_usage["execution_id"] = execution_id
        if source == "estimated":
            token_usage["input"] = max(1, len(packet.render()) // 4)
            token_usage["output"] = max(1, len(json.dumps(result)) // 4)
        self._accumulate(token_usage)
        status = result["status"]
        error_code = None
        needs_escalation = bool(result.get("needs_escalation", False))
        environment_text = " ".join([
            str(result.get("summary", "")), str(result.get("uncertainty_reason", "")),
            *[str(item) for item in result.get("findings", [])],
        ]).lower()
        if status == "blocked" and any(marker in environment_text for marker in (
                "sandbox", "execution policy", "workspace is read-only", "workspace is mounted read-only",
                "filesystem access", "shell access", "command execution was rejected")):
            error_code = CodexErrorCode.CAPABILITY_UNAVAILABLE.value
            needs_escalation = False
        completion = ({"artifact": "completed", "provider": "completed",
                       "reason": "steered_after_external_completion_probe"}
                      if self._has_completion_steer(stdout_text) else {})
        return Receipt(task_id=task.id, agent=task.owner, status=status, summary=result["summary"],
                       files=result.get("files", []), findings=result.get("findings", []), token_usage=token_usage,
                       confidence=result.get("confidence", "unknown"), uncertainty_reason=result.get("uncertainty_reason", ""),
                       needs_escalation=needs_escalation, error_code=error_code, provider=self.id,
                       model=str(model) if model else None,
                       completion=completion,
                       learning_evidence=(result.get("learning_evidence", [])
                                          if isinstance(result.get("learning_evidence", []), list) else []),
                       duration_seconds=time.monotonic() - started)
    async def _communicate(self, args: list[str], prompt: str, working_directory: Path,
                           budget: dict[str, Any] | None = None,
                           completion_probe: CompletionProbe | None = None) -> tuple[int, bytes, bytes]:
        child_environment = self.child_environment()
        process = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=str(working_directory), env=child_environment,
        )
        monitor = CodexEventBudget(
            max_tool_calls=(budget or {}).get("max_provider_tool_calls"),
            max_assistant_messages=(budget or {}).get("max_provider_messages"),
        )
        stdout_parts: list[bytes] = []
        stderr_task = asyncio.create_task(process.stderr.read())
        probe_passes = max(1, int((budget or {}).get("completion_probe_passes", 2)))
        probe_grace = min(10.0, max(0.0, float(
            (budget or {}).get("completion_probe_grace_seconds", 1.0))))

        async def artifact_is_complete() -> bool:
            if completion_probe is None:
                return False
            for attempt in range(probe_passes):
                try:
                    passed = await asyncio.to_thread(completion_probe)
                except Exception:
                    return False
                if not passed:
                    return False
                if attempt + 1 < probe_passes and probe_grace:
                    await asyncio.sleep(probe_grace)
                if process.returncode is not None:
                    return False
            return True

        async def communicate() -> tuple[bytes, bytes]:
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write(prompt.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                stdout_parts.append(line)
                reason = monitor.observe(line)
                if reason:
                    stopped = False
                    try:
                        process.terminate()
                        stopped = True
                    except OSError as terminate_error:
                        try:
                            process.kill()
                            stopped = True
                        except OSError as kill_error:
                            reason += (f"; child termination unavailable "
                                       f"({type(terminate_error).__name__}/{type(kill_error).__name__})")
                    if stopped:
                        await process.wait()
                        await stderr_task
                    else:
                        stderr_task.cancel()
                    raise CodexBudgetExceeded(reason, monitor.tool_calls,
                                              monitor.assistant_messages)
                if self._is_completed_tool_event(line) and await artifact_is_complete():
                    try:
                        process.terminate()
                    except OSError:
                        process.kill()
                    await process.wait()
                    stderr = await stderr_task if not stderr_task.cancelled() else b""
                    raise CodexArtifactCompleted(b"".join(stdout_parts), stderr)
            await process.wait()
            return b"".join(stdout_parts), await stderr_task

        try:
            stdout, stderr = await asyncio.wait_for(communicate(), timeout=self.timeout)
        except TimeoutError:
            process.terminate()
            await process.wait()
            if stderr_task.done() and not stderr_task.cancelled():
                stderr = stderr_task.result()
            else:
                stderr_task.cancel()
                stderr = b""
            raise CodexTimeout(b"".join(stdout_parts), stderr)
        except asyncio.CancelledError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()
            if not stderr_task.done():
                stderr_task.cancel()
            raise
        return process.returncode or 0, stdout, stderr

    async def _communicate_app_server(
            self, prompt: str, working_directory: Path, budget: dict[str, Any] | None,
            completion_probe: CompletionProbe, *, model: str | None, reasoning: str | None,
            read_only: bool) -> tuple[int, bytes, bytes]:
        """Run one turn over Codex app-server and retain live usage notifications."""
        process = await asyncio.create_subprocess_exec(
            *self.command_prefix, "app-server", "--listen", "stdio://",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=str(working_directory),
            env=self.child_environment(),
            # Completed file-change items can legitimately exceed asyncio's
            # 64 KiB default even when delta notifications are disabled.
            limit=8 * 1024 * 1024,
        )
        assert process.stdin is not None and process.stdout is not None
        stderr_task = asyncio.create_task(process.stderr.read())
        events: list[bytes] = []
        request_id = 0
        thread_id: str | None = None
        turn_id: str | None = None
        relevant_turn_ids: set[str] = set()
        steer_request_id: int | None = None
        steer_accepted = False
        steer_deadline: float | None = None
        interrupt_request_id: int | None = None
        interrupt_deadline: float | None = None
        artifact_completed = False
        controlled_stop = False
        completed = False
        monitor = CodexEventBudget(
            max_tool_calls=(budget or {}).get("max_provider_tool_calls"),
            max_assistant_messages=(budget or {}).get("max_provider_messages"),
        )

        async def send(method: str, params: dict[str, Any] | None = None,
                       *, notification: bool = False) -> int | None:
            nonlocal request_id
            payload: dict[str, Any] = {"method": method}
            if params is not None:
                payload["params"] = params
            if not notification:
                request_id += 1
                payload["id"] = request_id
            process.stdin.write((json.dumps(payload, separators=(",", ":")) + "\n").encode())
            await process.stdin.drain()
            return None if notification else request_id

        async def response(expected: int) -> dict[str, Any]:
            while True:
                line = await process.stdout.readline()
                if not line:
                    raise RuntimeError("Codex app-server closed before responding")
                events.append(line)
                value = json.loads(line)
                if value.get("id") == expected:
                    if value.get("error"):
                        raise RuntimeError(f"Codex app-server error: {value['error']}")
                    return value.get("result", {})

        async def artifact_is_complete() -> bool:
            passes = max(1, int((budget or {}).get("completion_probe_passes", 2)))
            grace = min(10.0, max(0.0, float(
                (budget or {}).get("completion_probe_grace_seconds", 1.0))))
            for attempt in range(passes):
                try:
                    if not await asyncio.to_thread(completion_probe):
                        return False
                except Exception:
                    return False
                if attempt + 1 < passes and grace:
                    await asyncio.sleep(grace)
            return True

        async def run() -> tuple[int, bytes, bytes]:
            nonlocal thread_id, turn_id, steer_request_id, steer_accepted
            nonlocal steer_deadline, interrupt_request_id, interrupt_deadline
            nonlocal artifact_completed, controlled_stop, completed
            initialize = await send("initialize", {
                "clientInfo": {"name": "universal-agent-platform", "title": "UAP",
                               "version": __version__},
                "capabilities": {"experimentalApi": True, "requestAttestation": False,
                                 "optOutNotificationMethods": [
                                     "command/exec/outputDelta", "item/agentMessage/delta",
                                     "item/plan/delta", "item/fileChange/outputDelta",
                                     "item/reasoning/summaryTextDelta", "item/reasoning/textDelta"]},
            })
            await response(int(initialize))
            await send("initialized", notification=True)
            started = await send("thread/start", {
                "cwd": str(working_directory), "runtimeWorkspaceRoots": [str(working_directory)],
                "model": model, "approvalPolicy": "never",
                "sandbox": "read-only" if read_only else "workspace-write",
                "ephemeral": True, "threadSource": "universal-agent-platform",
            })
            thread_result = await response(int(started))
            thread_id = str(thread_result["thread"]["id"])
            turn_request = await send("turn/start", {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt, "text_elements": []}],
                "model": model, "effort": reasoning, "outputSchema": RESULT_SCHEMA,
                "approvalPolicy": "never",
                "sandboxPolicy": ({"type": "readOnly", "networkAccess": False} if read_only else
                                  {"type": "workspaceWrite", "writableRoots": [str(working_directory)],
                                   "networkAccess": False}),
            })
            turn_result = await response(int(turn_request))
            turn_id = str(turn_result["turn"]["id"])
            relevant_turn_ids.add(turn_id)
            while True:
                deadline = interrupt_deadline or steer_deadline
                try:
                    if deadline is None:
                        line = await process.stdout.readline()
                    else:
                        remaining = max(0.001, deadline - time.monotonic())
                        line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
                except TimeoutError:
                    if interrupt_request_id is not None or not artifact_completed:
                        raise
                    interrupt_id = await send("turn/interrupt", {
                        "threadId": thread_id, "turnId": turn_id})
                    interrupt_request_id = int(interrupt_id)
                    steer_deadline = None
                    interrupt_deadline = time.monotonic() + max(
                        1.0, float((budget or {}).get("completion_interrupt_grace_seconds", 15.0)))
                    events.append((json.dumps({"type": "uap.completion_interrupt_requested"}) + "\n").encode())
                    continue
                if not line:
                    break
                events.append(line)
                event = json.loads(line)
                method = event.get("method")
                params = event.get("params")
                item = params.get("item") if isinstance(params, dict) else None
                if steer_request_id is not None and event.get("id") == steer_request_id:
                    if event.get("error"):
                        events.append((json.dumps({"type": "uap.completion_steer_failed"}) + "\n").encode())
                        steer_request_id = None
                    else:
                        result = event.get("result")
                        if isinstance(result, dict) and result.get("turnId"):
                            # App-server versions may report either the active turn or a
                            # successor turn here.  Both belong to the same steered
                            # execution.  Do not discard the original id: its normal
                            # completion is sufficient to close the provider lifecycle.
                            turn_id = str(result["turnId"])
                            relevant_turn_ids.add(turn_id)
                        events.append((json.dumps({"type": "uap.completion_steered"}) + "\n").encode())
                        steer_accepted = True
                if interrupt_request_id is not None and event.get("id") == interrupt_request_id:
                    if event.get("error"):
                        events.append((json.dumps({"type": "uap.completion_interrupt_failed"}) + "\n").encode())
                    else:
                        events.append((json.dumps({"type": "uap.completion_interrupted"}) + "\n").encode())
                if method == "item/completed" and isinstance(item, dict):
                    synthetic = {"type": "item.completed", "item": {
                        "type": {"commandExecution": "command_execution",
                                 "mcpToolCall": "mcp_tool_call",
                                 "webSearch": "web_search",
                                 "agentMessage": "agent_message"}.get(item.get("type"), item.get("type"))}}
                    reason = monitor.observe((json.dumps(synthetic) + "\n").encode())
                    if reason:
                        raise CodexBudgetExceeded(reason, monitor.tool_calls,
                                                  monitor.assistant_messages)
                    if (steer_request_id is None and not steer_accepted and item.get("type") in
                            {"commandExecution", "mcpToolCall", "webSearch", "fileChange"}
                            and await artifact_is_complete()):
                        artifact_completed = True
                        steer_id = await send("turn/steer", {
                            "threadId": thread_id, "expectedTurnId": turn_id,
                            "input": [{"type": "text", "text": (
                                "External acceptance has passed. Stop all further inspection and "
                                "tool use now; return the required final JSON receipt immediately."),
                                "text_elements": []}],
                        })
                        steer_request_id = int(steer_id)
                        steer_deadline = time.monotonic() + max(
                            1.0, float((budget or {}).get("completion_steer_grace_seconds", 20.0)))
                        events.append((json.dumps({"type": "uap.completion_steer_requested"}) + "\n").encode())
                if method == "turn/completed" and isinstance(params, dict):
                    completed_turn = params.get("turn", {})
                    completed_id = str(completed_turn.get("id"))
                    if completed_id in relevant_turn_ids:
                        terminal_status = completed_turn.get("status")
                        completed = terminal_status == "completed"
                        controlled_stop = bool(
                            artifact_completed and terminal_status == "interrupted")
                        if completed or controlled_stop or not (
                                steer_request_id is not None or steer_accepted):
                            break
            if controlled_stop:
                events.append((json.dumps({"type": "uap.completion_controlled_stop"}) + "\n").encode())
                raise CodexControlledStop(b"".join(events), b"")
            if not completed:
                raise RuntimeError("Codex app-server turn did not complete")
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.terminate()
                await process.wait()
            return process.returncode or 0, b"".join(events), await stderr_task

        try:
            return await asyncio.wait_for(run(), timeout=self.timeout)
        except TimeoutError:
            if thread_id and turn_id and process.returncode is None:
                try:
                    await send("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
                except (OSError, RuntimeError):
                    pass
            process.terminate()
            await process.wait()
            if not stderr_task.done():
                stderr_task.cancel()
            raise CodexTimeout(b"".join(events), b"")
        except Exception:
            if process.returncode is None:
                process.terminate()
                await process.wait()
            if not stderr_task.done():
                stderr_task.cancel()
            raise

    @staticmethod
    def _is_completed_tool_event(line: bytes) -> bool:
        try:
            event = json.loads(line.decode("utf-8", errors="replace"))
        except (ValueError, json.JSONDecodeError):
            return False
        item = event.get("item")
        return bool(event.get("type") == "item.completed" and isinstance(item, dict)
                    and item.get("type") in {"command_execution", "mcp_tool_call", "web_search"})

    @staticmethod
    def child_environment() -> dict[str, str]:
        environment = os.environ.copy()
        environment.update({"UAP_CHILD_EXECUTION": "1", "UAP_ORCHESTRATION_OWNER": "universal-agent-platform"})
        return environment

    @staticmethod
    def classify_failure(message: str) -> CodexErrorCode:
        lower = message.lower()
        if any(value in lower for value in ("not logged in", "unauthorized", "authentication", "401")):
            return CodexErrorCode.AUTH_ERROR
        if any(value in lower for value in (
                "unexpected argument", "invalid argument", "unrecognized option", "unknown option",
                "cannot be used with",
                "model_not_found", "model not found", "unknown model", "unsupported model",
                "does not exist or you do not have access")):
            return CodexErrorCode.INVALID_ARGUMENT
        return CodexErrorCode.EXECUTION_FAILED

    @staticmethod
    def _parse_jsonl(output: str) -> tuple[dict[str, Any], dict[str, int], str | None]:
        final_text: str | dict[str, Any] | None = None
        usage, execution_id = CodexProvider._parse_telemetry(output)
        for line in output.splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            item = event.get("item")
            params = event.get("params")
            if event.get("method") == "item/completed" and isinstance(params, dict):
                app_item = params.get("item")
                if isinstance(app_item, dict) and app_item.get("type") == "agentMessage":
                    final_text = app_item.get("text") or final_text
            if isinstance(item, dict) and item.get("type") == "agent_message":
                final_text = item.get("text") or item.get("content")
            if event.get("type") in {"message", "agent_message"}:
                final_text = event.get("text") or event.get("message") or final_text
        if not final_text:
            raise ValueError("Codex JSONL did not contain a final agent message")
        result = json.loads(final_text) if isinstance(final_text, str) else final_text
        if not isinstance(result, dict) or "status" not in result or "summary" not in result:
            raise ValueError("Codex final message did not match the receipt contract")
        return result, usage, execution_id

    @staticmethod
    def _parse_telemetry(output: str) -> tuple[dict[str, int], str | None]:
        """Extract the latest provider-reported usage and execution id.

        Codex exec emits snake_case usage on ``turn.completed``. Persisted
        rollouts/app-server notifications use a cumulative token-count event.
        Both are provider measurements; this method never tokenizes text or
        derives a count from characters.
        """
        usage: dict[str, int] = {}
        execution_id: str | None = None
        for line in output.splitlines():
            try:
                event = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                continue
            candidate = event.get("usage")
            payload = event.get("payload")
            if (isinstance(payload, dict) and payload.get("type") == "token_count"
                    and isinstance(payload.get("info"), dict)):
                candidate = payload["info"].get("total_token_usage") or candidate
            params = event.get("params")
            if isinstance(params, dict) and isinstance(params.get("tokenUsage"), dict):
                candidate = params["tokenUsage"].get("total") or candidate
            if isinstance(candidate, dict):
                aliases = {
                    "inputTokens": "input_tokens",
                    "cachedInputTokens": "cached_input_tokens",
                    "cacheWriteInputTokens": "cache_write_input_tokens",
                    "outputTokens": "output_tokens",
                    "reasoningOutputTokens": "reasoning_output_tokens",
                    "totalTokens": "total_tokens",
                }
                usage.update({aliases.get(key, key): int(value)
                              for key, value in candidate.items()
                              if isinstance(value, (int, float))})
            if event.get("type") == "thread.started" and event.get("thread_id"):
                execution_id = str(event["thread_id"])
            if event.get("method") == "thread/started" and isinstance(event.get("params"), dict):
                thread = event["params"].get("thread")
                if isinstance(thread, dict) and thread.get("id"):
                    execution_id = str(thread["id"])
            if event.get("id") and isinstance(event.get("result"), dict):
                thread = event["result"].get("thread")
                if isinstance(thread, dict) and thread.get("id"):
                    execution_id = str(thread["id"])
        return usage, execution_id

    @staticmethod
    def _execution_counts(output: str) -> dict[str, int]:
        """Return bounded event counts without retaining commands or message text."""
        tool_kinds = {"command_execution", "mcp_tool_call", "web_search"}
        tools = 0
        messages = 0
        for line in output.splitlines():
            try:
                event = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                continue
            item = event.get("item")
            if event.get("method") == "item/completed" and isinstance(event.get("params"), dict):
                item = event["params"].get("item")
                if isinstance(item, dict):
                    kind = item.get("type")
                    tools += kind in {"commandExecution", "mcpToolCall", "webSearch"}
                    messages += kind == "agentMessage"
                continue
            if event.get("type") != "item.completed" or not isinstance(item, dict):
                continue
            tools += item.get("type") in tool_kinds
            messages += item.get("type") == "agent_message"
        return {"provider_tool_calls": tools, "provider_messages": messages}

    @staticmethod
    def _has_completion_steer(output: str) -> bool:
        return any('"type": "uap.completion_steered"' in line or
                   '"type":"uap.completion_steered"' in line
                   for line in output.splitlines())

    @staticmethod
    def _completion_steer_state(output: str) -> str | None:
        if CodexProvider._has_completion_steer(output):
            return "accepted"
        if any('"type": "uap.completion_steer_requested"' in line or
               '"type":"uap.completion_steer_requested"' in line
               for line in output.splitlines()):
            return "requested"
        return None

    @staticmethod
    def _usage_breakdown(usage: dict[str, int]) -> dict[str, int]:
        """Preserve optional provider fields without changing legacy receipts."""
        mapping = {
            "total_tokens": "total",
            "reasoning_output_tokens": "reasoning_output",
            "cache_write_input_tokens": "cache_write_input",
        }
        return {target: int(usage[source]) for source, target in mapping.items()
                if source in usage}

    @staticmethod
    def _bounded_error(message: str, limit: int = 1200) -> str:
        compact = " ".join(message.split())
        return compact[:limit] + ("…" if len(compact) > limit else "")

    @staticmethod
    def _write_schema(directory: Path) -> Path:
        handle, name = tempfile.mkstemp(prefix="agentctl-result-", suffix=".json", dir=directory)
        os.close(handle)
        path = Path(name)
        path.write_text(json.dumps(RESULT_SCHEMA), encoding="utf-8")
        return path

    @staticmethod
    def _failure(task: Task, code: CodexErrorCode, message: str, started: float,
                 model: str | None = None) -> Receipt:
        environment = code in {CodexErrorCode.NOT_FOUND, CodexErrorCode.AUTH_ERROR,
                               CodexErrorCode.INVALID_ARGUMENT, CodexErrorCode.CAPABILITY_UNAVAILABLE}
        return Receipt(task_id=task.id, agent=task.owner, status="failed", summary=message,
                       token_usage={"input": 0, "output": 0, "cached": 0, "source": "unavailable", "estimated": False},
                       confidence="unknown", uncertainty_reason=message,
                       needs_escalation=(not environment and
                                         code not in {CodexErrorCode.TIMEOUT,
                                                      CodexErrorCode.BUDGET_EXHAUSTED}),
                       error_code=code.value, provider=CodexProvider.id, model=str(model) if model else None,
                       duration_seconds=time.monotonic() - started)
