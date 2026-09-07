import json
import sqlite3

from adaptive_agent.cli import main, requires_orchestration
from adaptive_agent.project.adapter import UAP_END, UAP_START, initialize_project, orchestration_config
from adaptive_agent.providers.codex import CodexProvider
from adaptive_agent.storage.database import Database, SCHEMA_VERSION


def _templates(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "capabilities.yaml").write_text("capabilities: {}\n", encoding="utf-8")
    return templates


def test_init_declares_owner_and_preserves_agents_content(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# User rules\n\nKeep this.\n", encoding="utf-8")
    initialize_project(tmp_path, _templates(tmp_path))
    assert orchestration_config(tmp_path) == {
        "owner": "universal-agent-platform", "threshold": "non_trivial"
    }
    content = agents.read_text(encoding="utf-8")
    assert "Keep this." in content
    assert content.count(UAP_START) == content.count(UAP_END) == 1


def test_upgrade_updates_marker_and_preserves_commands(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    templates = _templates(tmp_path)
    initialize_project(tmp_path, templates)
    commands = tmp_path / ".agent" / "commands.yaml"
    commands.write_text("commands:\n  custom:\n    command: safe-tool\n", encoding="utf-8")
    agents = tmp_path / "AGENTS.md"
    agents.write_text(agents.read_text(encoding="utf-8").replace("Universal Agent Platform", "old text"), encoding="utf-8")
    initialize_project(tmp_path, templates, upgrade=True)
    assert "Universal Agent Platform" in agents.read_text(encoding="utf-8")
    assert "safe-tool" in commands.read_text(encoding="utf-8")


def test_child_guard_and_threshold(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UAP_CHILD_EXECUTION", "1")
    assert main(["orchestrate", "Fix runtime bug", "--json", "--provider", "mock"]) == 3
    assert "Recursion blocked" in capsys.readouterr().err
    assert CodexProvider.child_environment()["UAP_CHILD_EXECUTION"] == "1"
    assert requires_orchestration("Fix this runtime bug and validate it")
    assert not requires_orchestration("What does this function do?")


def test_orchestrate_json_persists_parent_entry(monkeypatch, tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    initialize_project(tmp_path, _templates(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert main(["orchestrate", "Locate config. Do not modify anything.", "--json", "--provider", "mock"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["orchestration_owner"] == "universal-agent-platform"
    assert payload["entry_source"] == "codex_parent"
    assert payload["dashboard_url"].startswith("http://127.0.0.1:")


def test_v2_database_migrates_without_data_loss(tmp_path):
    path = tmp_path / "existing.db"
    with sqlite3.connect(path) as existing:
        existing.execute("CREATE TABLE runs(id TEXT PRIMARY KEY, project_id TEXT, goal TEXT, status TEXT, created_at TEXT, completed_at TEXT)")
        existing.execute("INSERT INTO runs(id,goal,status) VALUES('OLD','preserve me','completed')")
    migrated = Database(path)
    assert {row["version"] for row in migrated.query("SELECT version FROM schema_migrations")} >= {SCHEMA_VERSION}
    columns = {row["name"] for row in migrated.query("PRAGMA table_info(runs)")}
    assert {"orchestration_owner", "entry_source"} <= columns
    assert migrated.query("SELECT goal FROM runs WHERE id='OLD'")[0]["goal"] == "preserve me"
