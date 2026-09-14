import json

from adaptive_agent.core.execution_packet import ExecutionPacket
from adaptive_agent.core.tools import compact_tool_output
from adaptive_agent.project.direct import _fit_context
from adaptive_agent.project.direct import prepare


def test_final_context_envelope_includes_source_excerpts():
    context = {
        "architecture": {"language": "python"},
        "paths": ["src"],
        "notes": [{"path": f"src/{index}.py", "summary": "n" * 200} for index in range(8)],
        "source_excerpts": [
            {"path": f"src/{index}.py", "content": "x" * 4000,
             "truncated": False, "excerpt_sha256": str(index)}
            for index in range(3)
        ],
    }
    fitted = _fit_context(context, 3000)
    assert len(json.dumps(fitted, ensure_ascii=False, separators=(",", ":"))) <= 3000
    assert all(item["path"] and item["excerpt_sha256"] for item in fitted["source_excerpts"])
    assert any(item["truncated"] for item in fitted["source_excerpts"])


def test_tool_compaction_keeps_head_and_terminal_failure():
    output = "SETUP\n" + "noise\n" * 1000 + "AssertionError: expected 2 got 3"
    compacted = compact_tool_output(output, 300)
    assert len(compacted) == 300
    assert compacted.startswith("SETUP")
    assert compacted.endswith("AssertionError: expected 2 got 3")
    assert "middle truncated" in compacted
    assert compact_tool_output(output, 10) == output[-10:]


def test_context_envelope_has_metadata_only_fallback():
    fitted = _fit_context({"architecture": {"huge": "x" * 10000},
                           "paths": ["src"], "source_excerpts": []}, 512)
    assert len(json.dumps(fitted, ensure_ascii=False, separators=(",", ":"))) <= 512
    assert fitted["context_truncated"] is True


def test_execution_packet_uses_stable_prefix_and_omits_empty_sections(tmp_path):
    packet = ExecutionPacket("Developer", "Fix bug", "demo", "python", tmp_path)
    rendered = packet.render()
    assert rendered.startswith("STABLE EXECUTION CONTRACT")
    assert "REQUIRED SKILLS" not in rendered
    assert "SELECTED SKILL PROCEDURES" not in rendered
    assert "None" not in rendered


def test_value_gated_prepare_uses_pointers_without_speculative_bodies(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print('hello')", encoding="utf-8")
    result = prepare(tmp_path, "change backend", read_sources=True, value_gated=True)
    assert result["context_value_gate"]["selected_excerpts"] == 0
    assert result["context_value_gate"]["deferred_excerpts"] == 1
    assert "source_excerpts" not in result["context"]
    assert result["context"]["source_pointers"][0]["path"] == "app/main.py"
