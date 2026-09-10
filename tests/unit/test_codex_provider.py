import asyncio
import json
import sys

from adaptive_agent.core.execution_packet import ExecutionPacketBuilder
from adaptive_agent.core.models import Receipt, Task
from adaptive_agent.providers.codex import CodexCapabilities, CodexErrorCode, CodexProvider


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


def test_real_provider_contract_with_fake_subprocess(tmp_path):
    result = {"status": "completed", "summary": "Located loader", "files": ["config.py"],
              "findings": ["load_config is responsible"], "confidence": "high",
              "uncertainty_reason": "", "needs_escalation": False}
    output = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "thread-real-1"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(result)}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 123, "cached_input_tokens": 20, "output_tokens": 45}}),
    ])
    capabilities = CodexCapabilities(available=True, supports_noninteractive=True, supports_model_selection=True,
                                    supports_reasoning_selection=True, supports_structured_output=True,
                                    supports_working_directory=True, supports_jsonl=True,
                                    supports_auto_approval=True)
    class FakeCodexProvider(CodexProvider):
        async def _communicate(self, args, prompt, working_directory):
            assert args[-1] == "-"
            assert "--approve-for-me" in args
            assert "--sandbox" not in args
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
        async def _communicate(self, args, prompt, working_directory):
            return 0, output.encode(), b""

    provider = BlockedCodexProvider(command_prefix=["fake-codex"], capabilities=capabilities)
    task = Task("T", "R", "Modify a file", "developer", metadata={"working_directory": str(tmp_path)})
    receipt = asyncio.run(provider.execute(task))
    assert receipt.error_code == CodexErrorCode.CAPABILITY_UNAVAILABLE.value
    assert receipt.needs_escalation is False
