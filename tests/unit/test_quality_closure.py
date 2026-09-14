from pathlib import Path

import pytest

from adaptive_agent.project.quality_closure import compile_repair_evidence


def test_repair_evidence_is_bounded_and_project_confined(tmp_path: Path):
    (tmp_path / "app.py").write_text("x = 1\n" * 1000, encoding="utf-8")
    result = compile_repair_evidence(
        tmp_path, "AssertionError: broken contract", ["app.py", "../outside.py"],
        max_context_chars=700, max_excerpt_chars=500,
    )
    assert result.context_chars <= 700
    assert result.excerpts[0]["path"] == "app.py"
    assert len(result.excerpts[0]["content"]) == 500
    assert result.skipped_paths == ({"path": "../outside.py", "reason": "outside_project"},)


def test_repair_evidence_skips_secret_paths_and_redacts_sensitive_lines(tmp_path: Path):
    (tmp_path / ".env").write_text("API_KEY=secret", encoding="utf-8")
    (tmp_path / "settings.py").write_text(
        "API_KEY = 'secret'\nSAFE = 1\n", encoding="utf-8")
    result = compile_repair_evidence(
        tmp_path, "validation failed", [".env", "settings.py"])
    assert result.skipped_paths[0]["reason"] == "secret_like_path"
    assert "secret" not in result.excerpts[0]["content"]
    assert "SAFE = 1" in result.excerpts[0]["content"]


def test_repair_evidence_requires_failure(tmp_path: Path):
    with pytest.raises(ValueError, match="deterministic failure"):
        compile_repair_evidence(tmp_path, "  ", [])
