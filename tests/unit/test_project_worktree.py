import subprocess

from adaptive_agent.git.worktree import WorktreeManager
from adaptive_agent.project.adapter import approved_command, initialize_project
from adaptive_agent.project.discovery import discover


def test_python_project_discovery_and_init(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "capabilities.yaml").write_text("capabilities: {}\n", encoding="utf-8")
    (templates / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
    assert discover(tmp_path).type == "python"
    initialize_project(tmp_path, templates)
    assert approved_command(tmp_path, "test")["command"] == "pytest"


def test_worktree_manager(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    (tmp_path / "README.md").write_text("test", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "initial"], check=True, capture_output=True)
    manager = WorktreeManager(tmp_path)
    destination = manager.create("TASK-001")
    assert destination.exists()
    assert manager.dirty() is False
    manager.remove("TASK-001")
    assert not destination.exists()
