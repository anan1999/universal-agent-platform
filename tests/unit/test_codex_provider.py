import asyncio
import json
import sys

import pytest

from adaptive_agent.core.execution_packet import ExecutionPacketBuilder
from adaptive_agent.core.models import Receipt, Task
from adaptive_agent.providers.codex import RESULT_SCHEMA, CodexCapabilities, CodexErrorCode, CodexProvider
from adaptive_agent.providers.codex.provider import (
    CodexArtifactCompleted, CodexEventBudget, CodexTimeout,
)


def test_capability_detection_from_fake_executable(tmp_path):
    script = tmp_path / "fake_codex.py"
    script.write_text(
        "import sys\n"
        "if '--version' in sys.argv: print('codex-cli 9.9.9')\n"
        "elif '--help' in sys.argv: print('Run Codex non-interactively --model --config --output-schema --cd --json --approve-for-me')\n",
        encoding="utf-8",
    )
    capabilities = CodexCapabilities.probe(command_prefix=[sys.executable, str(script)])
    assert capabilities.version == "codex-cli 9.9.9"
    assert capabilities.supports_noninteractive
    assert capabilities.supports_model_selection
    assert capabilities.supports_reasoning_selection
    assert capabilities.supports_structured_output
    assert capabilities.supports_auto_approval
    assert capabilities.supports_usage_reporting is False


def test_execution_packet_is_bounded_and_has_no_chat_history(tmp_path):
    words = " ".join(f"word{i}" for i in range(400))
    receipt = Receipt("D", "explorer", "completed", words, files=["a.py"], findings=["root cause"])
    task = Task("T", "R", "Implement fix", "developer", dependencies=["D"])
    packet = ExecutionPacketBuilder(receipt_word_limit=20).build(task, tmp_path, "sample", "python", [receipt])
    rendered = packet.render()
    assert "DEPENDENCY RECEIPTS" in rendered
    assert "[truncated]" in rendered
    assert "chat history" not in rendered.lower()
    assert "stable project fact" in rendered
    assert "recurring role" not in rendered
    assert "empty learning_evidence array" in rendered
    assert "Never invent learning evidence" in rendered
    assert "learning_evidence" in RESULT_SCHEMA["required"]
    assert RESULT_SCHEMA["properties"]["learning_evidence"]["items"]["additionalProperties"] is False


def test_packet_exposes_canonical_validation_once_without_extra_workflow(tmp_path):
    task = Task("T", "R", "Implement fix", "developer", metadata={
        "project_intelligence": {"project_index": {
            "commands": {"test": "python -m pytest -q"},
        }},
    })
    rendered = ExecutionPacketBuilder().build(
        task, tmp_path, "sample", "python").render()
    assert "Validated commands: test=python -m pytest -q" in rendered
    assert "DETERMINISTIC VALIDATION" not in rendered
    assert "make one focused repair" not in rendered


def test_read_only_packet_does_not_request_extra_validation_workflow(tmp_path):
    task = Task("T", "R", "Review implementation", "reviewer", metadata={
        "read_only": True,
        "project_intelligence": {"project_index": {
            "commands": {"test": "python -m pytest -q"},
        }},
    })
    rendered = ExecutionPacketBuilder().build(
        task, tmp_path, "sample", "python").render()
    assert "DETERMINISTIC VALIDATION" not in rendered
    assert "make one focused repair" not in rendered


def test_real_provider_contract_with_fake_subprocess(tmp_path):
    result = {"status": "completed", "summary": "Located loader", "files": ["config.py"],
              "findings": ["load_config is responsible"], "confidence": "high",
              "uncertainty_reason": "", "needs_escalation": False}
    output = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "thread-real-1"}),
        json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(result)}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 123, "cached_input_tokens": 20, "output_tokens": 45}}),
    ])
    capabilities = CodexCapabilities(available=True, supports_noninteractive=True, supports_model_selection=True,
                                    supports_reasoning_selection=True, supports_structured_output=True,
                                    supports_working_directory=True, supports_jsonl=True,
                                    supports_auto_approval=True)
    class FakeCodexProvider(CodexProvider):
        async def _communicate(self, args, prompt, working_directory, budget=None):
            assert args[-1] == "-"
            assert "--approve-for-me" in args
            assert "--sandbox" not in args
            assert "--skip-git-repo-check" in args
            assert "ROLE:" in prompt
            return 0, output.encode(), b""

    provider = FakeCodexProvider(command_prefix=["fake-codex"], capabilities=capabilities, timeout=10)
    task = Task("T", "R", "Implement configuration loading.", "developer",
                metadata={"working_directory": str(tmp_path), "model": "gpt-5.6-luna"})
    receipt = asyncio.run(provider.execute(task))
    assert receipt.status == "completed", receipt
    assert receipt.model == "gpt-5.6-luna"
    assert receipt.token_usage["source"] == "measured"
    assert receipt.token_usage["cached"] == 20
    assert receipt.token_usage["invocation_count"] == 1
    assert receipt.token_usage["execution_id"] == "thread-real-1"
    assert receipt.token_usage["provider_tool_calls"] == 1
    assert receipt.token_usage["provider_messages"] == 1


def test_provider_failure_classification_and_no_reasoning_escalation():
    assert CodexProvider.classify_failure("401 unauthorized") == CodexErrorCode.AUTH_ERROR
    assert CodexProvider.classify_failure("unexpected argument --bad") == CodexErrorCode.INVALID_ARGUMENT
    assert CodexProvider.classify_failure("model_not_found: uap-invalid-model") == CodexErrorCode.INVALID_ARGUMENT
    task = Task("T", "R", "x", "explorer")
    receipt = CodexProvider._failure(task, CodexErrorCode.AUTH_ERROR, "login required", 0)
    assert receipt.needs_escalation is False


def test_describe_keeps_probe_and_execution_metadata():
    capabilities = CodexCapabilities(available=True, supports_noninteractive=True)
    description = CodexProvider(command_prefix=["fake-codex"], capabilities=capabilities).describe()
    assert description["id"] == "codex"
    assert description["execution_mode"] == "agentic_local"
    assert description["codex"]["supports_noninteractive"] is True


def test_policy_block_is_environment_failure_without_escalation(tmp_path):
    result = {"status": "blocked", "summary": "Workspace shell access was rejected by execution policy.",
              "files": [], "findings": [], "confidence": "unknown",
              "uncertainty_reason": "sandbox blocked", "needs_escalation": True}
    output = json.dumps({"type": "item.completed", "item": {
        "type": "agent_message", "text": json.dumps(result)}})
    capabilities = CodexCapabilities(available=True, supports_noninteractive=True,
                                    supports_structured_output=True, supports_working_directory=True,
                                    supports_jsonl=True)

    class BlockedCodexProvider(CodexProvider):
        async def _communicate(self, args, prompt, working_directory, budget=None):
            return 0, output.encode(), b""

    provider = BlockedCodexProvider(command_prefix=["fake-codex"], capabilities=capabilities)
    task = Task("T", "R", "Modify a file", "developer", metadata={"working_directory": str(tmp_path)})
    receipt = asyncio.run(provider.execute(task))
    assert receipt.error_code == CodexErrorCode.CAPABILITY_UNAVAILABLE.value
    assert receipt.needs_escalation is False


def test_timeout_preserves_partial_measured_usage(tmp_path):
    output = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "thread-timeout-1"}),
        json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}),
        json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 321, "cached_input_tokens": 120, "output_tokens": 45,
        }}),
        "{incomplete",
    ])
    capabilities = CodexCapabilities(
        available=True, supports_noninteractive=True, supports_structured_output=True,
        supports_working_directory=True, supports_jsonl=True,
    )

    class TimedOutProvider(CodexProvider):
        async def _communicate(self, args, prompt, working_directory, budget=None):
            raise CodexTimeout(output.encode(), b"")

    provider = TimedOutProvider(command_prefix=["fake"], capabilities=capabilities, timeout=1)
    task = Task("T", "R", "Modify a file", "developer",
                metadata={"working_directory": str(tmp_path)})
    receipt = asyncio.run(provider.execute(task))
    assert receipt.status == "failed"
    assert receipt.error_code == CodexErrorCode.TIMEOUT.value
    assert receipt.token_usage == {
        "input": 321, "output": 45, "cached": 120,
        "source": "partial_measured", "estimated": False, "complete": False,
        "invocation_count": 1, "provider_tool_calls": 1, "provider_messages": 0,
        "execution_id": "thread-timeout-1",
    }


def test_telemetry_parses_exact_persisted_token_count_without_estimation():
    output = json.dumps({
        "type": "event_msg",
        "payload": {"type": "token_count", "info": {"total_token_usage": {
            "input_tokens": 1200, "cached_input_tokens": 900,
            "cache_write_input_tokens": 7, "output_tokens": 80,
            "reasoning_output_tokens": 25, "total_tokens": 1280,
        }}},
    })
    usage, _ = CodexProvider._parse_telemetry(output)
    assert usage == {
        "input_tokens": 1200, "cached_input_tokens": 900,
        "cache_write_input_tokens": 7, "output_tokens": 80,
        "reasoning_output_tokens": 25, "total_tokens": 1280,
    }


def test_telemetry_normalizes_app_server_token_usage_notification():
    output = json.dumps({"method": "thread/tokenUsage/updated", "params": {
        "threadId": "thread-1", "turnId": "turn-1", "tokenUsage": {"total": {
            "inputTokens": 100, "cachedInputTokens": 40, "cacheWriteInputTokens": 0,
            "outputTokens": 10, "reasoningOutputTokens": 3, "totalTokens": 110,
        }}}})
    usage, _ = CodexProvider._parse_telemetry(output)
    assert usage["input_tokens"] == 100
    assert usage["cached_input_tokens"] == 40
    assert usage["reasoning_output_tokens"] == 3
    assert usage["total_tokens"] == 110


def test_artifact_probe_completion_is_distinct_from_provider_receipt(tmp_path):
    output = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "thread-probe-1"}),
        json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}),
    ])
    capabilities = CodexCapabilities(
        available=True, supports_noninteractive=True, supports_structured_output=True,
        supports_working_directory=True, supports_jsonl=True,
    )

    class ProbeCompletedProvider(CodexProvider):
        async def _communicate(self, args, prompt, working_directory, budget=None,
                               completion_probe=None):
            assert completion_probe is not None
            raise CodexArtifactCompleted(output.encode(), b"")

    provider = ProbeCompletedProvider(command_prefix=["fake"], capabilities=capabilities)
    task = Task("T", "R", "Modify a file", "developer",
                metadata={"working_directory": str(tmp_path)})
    receipt = asyncio.run(provider.execute(task, completion_probe=lambda: True))
    assert receipt.status == "completed"
    assert receipt.completion == {
        "artifact": "completed", "provider": "stopped",
        "reason": "external_completion_probe",
    }
    assert receipt.token_usage["source"] == "unavailable"
    assert receipt.token_usage["provider_tool_calls"] == 1


def test_live_event_budget_stops_before_accepting_an_extra_tool():
    monitor = CodexEventBudget(max_tool_calls=2, max_assistant_messages=1)
    completed = lambda kind: (json.dumps({"type": "item.completed", "item": {"type": kind}}) + "\n").encode()
    started = lambda kind: (json.dumps({"type": "item.started", "item": {"type": kind}}) + "\n").encode()
    assert monitor.observe(completed("command_execution")) is None
    assert monitor.observe(completed("mcp_tool_call")) is None
    reason = monitor.observe(started("web_search"))
    assert reason == "provider tool-call budget exhausted at 2"
    assert monitor.tool_calls == 2


def test_live_message_budget_is_counted_without_reading_message_text():
    monitor = CodexEventBudget(max_assistant_messages=1)
    secret = "DO_NOT_PERSIST_SECRET"
    line = lambda: (json.dumps({"type": "item.completed", "item": {
        "type": "agent_message", "text": secret}}) + "\n").encode()
    assert monitor.observe(line()) is None
    reason = monitor.observe(line())
    assert reason == "provider assistant-message budget exhausted at 2"
    assert secret not in reason


def test_streaming_subprocess_is_terminated_when_next_tool_exceeds_budget(monkeypatch, tmp_path):
    class Input:
        def write(self, value):
            self.value = value
        async def drain(self):
            return None
        def close(self):
            return None

    class Reader:
        def __init__(self, lines=()):
            self.lines = list(lines)
        async def readline(self):
            return self.lines.pop(0) if self.lines else b""
        async def read(self):
            return b"".join(self.lines)

    class Process:
        def __init__(self):
            self.stdin = Input()
            events = [
                {"type": "item.completed", "item": {"type": "command_execution"}},
                {"type": "item.completed", "item": {"type": "mcp_tool_call"}},
                {"type": "item.started", "item": {"type": "web_search"}},
            ]
            self.stdout = Reader((json.dumps(event) + "\n").encode() for event in events)
            self.stderr = Reader()
            self.returncode = None
            self.terminated = False
        def terminate(self):
            self.terminated = True
            self.returncode = -15
        def kill(self):
            self.terminate()
        async def wait(self):
            return self.returncode

    process = Process()
    async def create(*args, **kwargs):
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    provider = CodexProvider(command_prefix=["fake"], capabilities=CodexCapabilities(
        available=True, supports_noninteractive=True, supports_jsonl=True), timeout=5)
    with pytest.raises(Exception, match="provider tool-call budget exhausted at 2") as error:
        asyncio.run(provider._communicate(
            ["fake"], "prompt", tmp_path, {"max_provider_tool_calls": 2}))
    assert type(error.value).__name__ == "CodexBudgetExceeded"
    assert process.terminated is True


def test_streaming_completion_probe_requires_two_passes_before_stopping(monkeypatch, tmp_path):
    class Input:
        def write(self, value):
            self.value = value
        async def drain(self):
            return None
        def close(self):
            return None

    class Reader:
        def __init__(self, lines=()):
            self.lines = list(lines)
        async def readline(self):
            return self.lines.pop(0) if self.lines else b""
        async def read(self):
            return b""

    class Process:
        def __init__(self):
            self.stdin = Input()
            event = {"type": "item.completed", "item": {"type": "command_execution"}}
            self.stdout = Reader([(json.dumps(event) + "\n").encode()])
            self.stderr = Reader()
            self.returncode = None
            self.terminated = False
        def terminate(self):
            self.terminated = True
            self.returncode = -15
        def kill(self):
            self.terminate()
        async def wait(self):
            return self.returncode

    process = Process()
    async def create(*args, **kwargs):
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    provider = CodexProvider(command_prefix=["fake"], capabilities=CodexCapabilities(
        available=True, supports_noninteractive=True, supports_jsonl=True), timeout=5)
    calls = 0
    def probe():
        nonlocal calls
        calls += 1
        return True
    with pytest.raises(CodexArtifactCompleted):
        asyncio.run(provider._communicate(
            ["fake"], "prompt", tmp_path,
            {"completion_probe_passes": 2, "completion_probe_grace_seconds": 0}, probe))
    assert calls == 2
    assert process.terminated is True


def test_app_server_accepts_original_turn_completion_after_steer(monkeypatch, tmp_path):
    result = {"status": "completed", "summary": "done"}
    server_events = [
        {"id": 1, "result": {"userAgent": "test"}},
        {"id": 2, "result": {"thread": {"id": "thread-live"}}},
        {"id": 3, "result": {"turn": {"id": "turn-live", "status": "inProgress"}}},
        {"method": "item/completed", "params": {"threadId": "thread-live",
         "turnId": "turn-live", "item": {"type": "commandExecution", "id": "cmd-1"}}},
        {"id": 4, "result": {"turnId": "turn-steered"}},
        {"method": "thread/tokenUsage/updated", "params": {
            "threadId": "thread-live", "turnId": "turn-steered", "tokenUsage": {"total": {
                "inputTokens": 100, "cachedInputTokens": 60, "cacheWriteInputTokens": 0,
                "outputTokens": 20, "reasoningOutputTokens": 5, "totalTokens": 120,
            }}}},
        {"method": "item/completed", "params": {"threadId": "thread-live",
         "turnId": "turn-steered", "item": {"type": "agentMessage", "id": "msg-1",
         "text": json.dumps(result), "phase": "final_answer"}}},
        {"method": "turn/completed", "params": {"threadId": "thread-live",
         "turn": {"id": "turn-live", "status": "completed", "items": []}}},
    ]

    class Input:
        def __init__(self):
            self.values = []
        def write(self, value):
            self.values.append(value)
        async def drain(self):
            return None
        def close(self):
            return None

    class Reader:
        def __init__(self, lines=()):
            self.lines = list(lines)
        async def readline(self):
            return self.lines.pop(0) if self.lines else b""
        async def read(self):
            return b"".join(self.lines)

    class Process:
        def __init__(self):
            self.stdin = Input()
            self.stdout = Reader((json.dumps(event) + "\n").encode() for event in server_events)
            self.stderr = Reader()
            self.returncode = None
            self.subprocess_options = {}
        def terminate(self):
            self.returncode = -15
        async def wait(self):
            if self.returncode is None:
                self.returncode = 0
            return self.returncode

    process = Process()
    async def create(*args, **kwargs):
        process.subprocess_options.update(kwargs)
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    provider = CodexProvider(command_prefix=["fake"], capabilities=CodexCapabilities(
        available=True, supports_noninteractive=True, supports_jsonl=True), timeout=5)
    code, stdout, _ = asyncio.run(provider._communicate_app_server(
        "prompt", tmp_path, {"completion_probe_passes": 2,
                             "completion_probe_grace_seconds": 0},
        lambda: True, model="model", reasoning="low", read_only=False))
    requests = [json.loads(value) for value in process.stdin.values]
    assert code == 0
    assert process.subprocess_options["limit"] == 8 * 1024 * 1024
    assert [item["method"] for item in requests] == [
        "initialize", "initialized", "thread/start", "turn/start", "turn/steer"]
    assert requests[-1]["params"]["expectedTurnId"] == "turn-live"
    parsed, usage, execution_id = provider._parse_jsonl(stdout.decode())
    assert parsed == result
    assert usage["total_tokens"] == 120
    assert usage["reasoning_output_tokens"] == 5
    assert execution_id == "thread-live"
    assert provider._execution_counts(stdout.decode()) == {
        "provider_tool_calls": 1, "provider_messages": 1}
    assert provider._has_completion_steer(stdout.decode()) is True
    assert provider._completion_steer_state(stdout.decode()) == "accepted"


def test_execute_uses_live_usage_as_complete_measured_receipt(tmp_path):
    result = {"status": "completed", "summary": "accepted", "files": [],
              "findings": [], "confidence": "high", "uncertainty_reason": "",
              "needs_escalation": False, "learning_evidence": []}
    output = "\n".join([
        json.dumps({"id": 2, "result": {"thread": {"id": "thread-live"}}}),
        json.dumps({"method": "thread/tokenUsage/updated", "params": {
            "threadId": "thread-live", "turnId": "turn-live", "tokenUsage": {"total": {
                "inputTokens": 500, "cachedInputTokens": 300, "cacheWriteInputTokens": 0,
                "outputTokens": 50, "reasoningOutputTokens": 12, "totalTokens": 550}}}}),
        json.dumps({"method": "item/completed", "params": {"item": {
            "type": "agentMessage", "text": json.dumps(result)}}}),
        json.dumps({"type": "uap.completion_steered", "request_id": 4}),
        json.dumps({"method": "turn/completed", "params": {
            "threadId": "thread-live", "turn": {"id": "turn-live", "status": "completed"}}}),
    ])

    class LiveProvider(CodexProvider):
        async def _communicate_app_server(self, prompt, working_directory, budget,
                                          completion_probe, **kwargs):
            assert completion_probe()
            return 0, output.encode(), b""

    capabilities = CodexCapabilities(
        available=True, supports_noninteractive=True, supports_structured_output=True,
        supports_working_directory=True, supports_jsonl=True)
    provider = LiveProvider(command_prefix=["fake"], capabilities=capabilities)
    task = Task("T", "R", "Modify a file", "developer", metadata={
        "working_directory": str(tmp_path), "codex_live_usage": True})
    receipt = asyncio.run(provider.execute(task, completion_probe=lambda: True))
    assert receipt.status == "completed"
    assert receipt.token_usage["source"] == "measured"
    assert receipt.token_usage["input"] == 500
    assert receipt.token_usage["cached"] == 300
    assert receipt.token_usage["output"] == 50
    assert receipt.token_usage["reasoning_output"] == 12
    assert receipt.token_usage["total"] == 550
    assert receipt.completion == {
        "artifact": "completed", "provider": "completed",
        "reason": "steered_after_external_completion_probe"}
