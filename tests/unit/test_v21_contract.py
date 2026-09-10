import json

import yaml

from adaptive_agent import __version__
from adaptive_agent.project.adapter import detach_project, initialize_project
from adaptive_agent.runtime import PACKAGE_ROOT, RESOURCE_ROOT


def test_version_and_install_contract_are_consistent():
    manifest = json.loads((PACKAGE_ROOT / "agent-platform.json").read_text(encoding="utf-8"))
    project = (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert __version__ == "2.2.0" == manifest["version"]
    assert 'version = "2.2.0"' in project
    assert manifest["install"]["recommended"] == (
        "pip install git+https://github.com/anan1999/universal-agent-platform.git"
    )
    assert manifest["install"]["from_pypi"] is None


def test_runtime_resources_are_inside_the_importable_package():
    required = [
        RESOURCE_ROOT / "config" / "models.yaml",
        RESOURCE_ROOT / "config" / "profiles" / "general.yaml",
        RESOURCE_ROOT / "templates" / "capabilities.yaml",
        RESOURCE_ROOT / "skills" / "w8a8-validation" / "skill.json",
        RESOURCE_ROOT / "skills" / "w8a8-validation" / "SKILL.md",
    ]
    assert all(path.is_file() for path in required)
    for directory in ("config", "templates"):
        public = PACKAGE_ROOT / directory
        packaged = RESOURCE_ROOT / directory
        for path in public.rglob("*"):
            if path.is_file():
                assert (packaged / path.relative_to(public)).read_bytes() == path.read_bytes()


def test_init_is_idempotent_and_detach_preserves_user_content(tmp_path):
    (tmp_path / "README.md").write_text("# Non-software project\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# User rules\n\nKeep this.\n", encoding="utf-8")
    templates = RESOURCE_ROOT / "templates"
    initialize_project(tmp_path, templates, auto=True)
    project_path = tmp_path / ".agent" / "project.yaml"
    data = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    data["providers"] = {"preference": ["openai_compatible", "codex"]}
    project_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    initialize_project(tmp_path, templates, auto=True)
    again = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    assert again["providers"]["preference"] == ["openai_compatible", "codex"]
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8").count("<!-- UAP:START -->") == 1

    detach_project(tmp_path)
    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "Keep this." in agents
    assert "<!-- UAP:START -->" not in agents
    assert project_path.exists()
    assert yaml.safe_load(project_path.read_text(encoding="utf-8"))["orchestration"]["owner"] == "manual"
