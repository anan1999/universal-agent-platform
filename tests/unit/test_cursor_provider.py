import asyncio
import json
import os
import sys

from adaptive_agent.core.models import Task
from adaptive_agent.providers.cursor import CursorCapabilities, CursorErrorCode, CursorProvider


def capable() -> CursorCapabilities:
    return CursorCapabilities(available=True, authenticated=True, executable="fake-agent",
                              version="1.2.3", supports_headless=True,
                              supports_model_selection=True, supports_workspace=True,
                              supports_json=True, supports_sandbox=True)


def test_cursor_capability_probe(tmp_path):
    script = tmp_path / "fake_cursor.py"
    script.write_text(
        "import sys\n"
        "if '--version' in sys.argv: print('cursor-agent 1.2.3')\n"
        "elif '--help' in sys.argv: print('--print --model --workspace --output-format json --sandbox')\n"
        "elif 'status' in sys.argv: print('Logged in')\n",
        encoding="utf-8")
    result = CursorCapabilities.probe(command_prefix=[sys.executable, str(script)])
    assert result.available and result.authenticated and result.supports_headless
    assert result.supports_workspace and result.supports_json
    assert result.supports_sandbox is (os.name != "nt")


def test_cursor_provider_normalizes_result_and_usage(tmp_path):
    final = {"status": "completed", "summary": "Implemented filter", "files": ["app.py"],
             "findings": ["tests pass"], "confidence": "high", "uncertainty_reason": "",
             "needs_escalation": False, "learning_evidence": []}
    envelope = {"type": "result", "subtype": "success", "result": json.dumps(final),
                "session_id": "cursor-session-1",
                "usage": {"inputTokens": 5, "outputTokens": 7,
                          "cacheReadTokens": 100, "cacheWriteTokens": 20}}

    class FakeCursor(CursorProvider):
        async def _communicate(self, args, working_directory):
            assert "--print" in args and "--trust" in args and "--force" in args
            assert "--sandbox" in args and "enabled" in args
            assert "--workspace" in args and str(tmp_path.resolve()) in args
            assert "--model" in args and "gpt-test" in args
            assert "FINAL RESPONSE CONTRACT" in args[-1]
            return 0, json.dumps(envelope).encode(), b""

    provider = FakeCursor(command_prefix=["fake-agent"], capabilities=capable())
    task = Task("T", "R", "Implement filter", "developer",
                metadata={"working_directory": str(tmp_path), "model": "gpt-test"})
    receipt = asyncio.run(provider.execute(task))
    assert receipt.status == "completed"
    assert receipt.provider == "cursor"
    assert receipt.token_usage == {"input": 125, "output": 7, "cached": 120,
                                   "source": "measured", "estimated": False,
                                   "invocation_count": 1, "execution_id": "cursor-session-1"}


def test_cursor_read_only_mode_and_failure_classification(tmp_path):
    class ReadOnlyCursor(CursorProvider):
        async def _communicate(self, args, working_directory):
            assert "--mode" in args and "ask" in args and "--force" not in args
            payload = {"type": "result", "subtype": "success",
                       "result": '{"status":"completed","summary":"ok"}', "usage": {}}
            return 0, json.dumps(payload).encode(), b""

    provider = ReadOnlyCursor(command_prefix=["fake-agent"], capabilities=capable())
    task = Task("T", "R", "Inspect only", "reviewer",
                metadata={"working_directory": str(tmp_path), "read_only": True})
    assert asyncio.run(provider.execute(task)).status == "completed"
    assert CursorProvider.classify_failure("401 unauthorized") == CursorErrorCode.AUTH_ERROR
    assert CursorProvider.classify_failure("unknown option --bad") == CursorErrorCode.INVALID_ARGUMENT


def test_cursor_parser_accepts_prefaced_json_but_not_prose_only():
    final = '{"status":"completed","summary":"ok"}'
    envelope = {"type": "result", "subtype": "success",
                "result": "Completed work.\n" + final,
                "usage": {"cacheWriteTokens": 9}}
    result, usage, _ = CursorProvider._parse_output(json.dumps(envelope))
    assert result["status"] == "completed"
    assert usage["input"] == 9

    envelope["result"] = "Implemented the requested change and tests pass."
    result, usage, _ = CursorProvider._parse_output(json.dumps(envelope))
    assert result["status"] == "completed"
    assert result["confidence"] == "unknown"
    assert usage["input"] == 9


def test_cursor_file_snapshot_ignores_runtime_trees(tmp_path):
    before = CursorProvider._snapshot(tmp_path)
    (tmp_path / "src.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "noise.js").write_text("noise", encoding="utf-8")
    after = CursorProvider._snapshot(tmp_path)
    assert CursorProvider._changed_files(before, after) == ["src.py"]


def test_registry_exposes_cursor():
    from adaptive_agent.providers.registry import default_registry

    descriptor = default_registry().get("cursor")
    assert descriptor.implemented is True
    assert descriptor.display_name == "Cursor Agent"


def test_windows_command_prefix_bypasses_cmd_shim(monkeypatch, tmp_path):
    import adaptive_agent.providers.cursor.provider as module

    versions = tmp_path / "cursor-agent" / "versions" / "2026.09.10-deadbeef"
    versions.mkdir(parents=True)
    (versions / "node.exe").touch()
    (versions / "index.js").touch()
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    prefix = module._default_command_prefix()
    assert prefix[0].endswith("node.exe")
    assert prefix[1].endswith("index.js")
