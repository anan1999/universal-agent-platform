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
        "elif '--help' in sys.argv: print('Run Codex non-interactively --model --config --output-schema --cd --json')\n",
        encoding="utf-8",
    )
    capabilities = CodexCapabilities.probe(command_prefix=[sys.executable, str(script)])
    assert capabilities.version == "codex-cli 9.9.9"
    assert capabilities.supports_noninteractive
    assert capabilities.supports_model_selection
    assert capabilities.supports_reasoning_selection
    assert capabilities.supports_structured_output
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
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(result)}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 123, "cached_input_tokens": 20, "output_tokens": 45}}),
    ])
    capabilities = CodexCapabilities(available=True, supports_noninteractive=True, supports_model_selection=True,
                                    supports_reasoning_selection=True, supports_structured_output=True,
                                    supports_working_directory=True, supports_jsonl=True)
    class FakeCodexProvider(CodexProvider):
        async def _communicate(self, args, prompt, working_directory):
            assert args[-1] == "-"
            assert "ROLE:" in prompt
            return 0, output.encode(), b""

    provider = FakeCodexProvider(command_prefix=["fake-codex"], capabilities=capabilities, timeout=10)
    task = Task("T", "R", "Locate configuration loading. Do not modify anything.", "explorer",
                metadata={"working_directory": str(tmp_path), "model": "gpt-5.6-luna"})
    receipt = asyncio.run(provider.execute(task))
    assert receipt.status == "completed", receipt
    assert receipt.model == "gpt-5.6-luna"
    assert receipt.token_usage["source"] == "measured"
    assert receipt.token_usage["cached"] == 20


def test_provider_failure_classification_and_no_reasoning_escalation():
    assert CodexProvider.classify_failure("401 unauthorized") == CodexErrorCode.AUTH_ERROR
    assert CodexProvider.classify_failure("unexpected argument --bad") == CodexErrorCode.INVALID_ARGUMENT
    task = Task("T", "R", "x", "explorer")
    receipt = CodexProvider._failure(task, CodexErrorCode.AUTH_ERROR, "login required", 0)
    assert receipt.needs_escalation is False
