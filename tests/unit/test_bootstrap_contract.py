"""The distribution contract: what an arbitrary AI assistant reads to bootstrap.

`AI-BOOTSTRAP.md`, `agent-platform.json` and the README are the whole interface for
the "point an AI at the GitHub repo" workflow. If a command named there does not
exist, the workflow silently breaks for someone we never hear from, so the manifest
is checked against the real CLI rather than trusted.
"""

import json
import re

import pytest

from adaptive_agent import __version__
from adaptive_agent.cli import parser
from adaptive_agent.runtime import PACKAGE_ROOT

MANIFEST_PATH = PACKAGE_ROOT / "agent-platform.json"
BOOTSTRAP_PATH = PACKAGE_ROOT / "AI-BOOTSTRAP.md"
README_PATH = PACKAGE_ROOT / "README.md"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _subcommands() -> set[str]:
    actions = [action for action in parser()._actions if action.choices]
    return set(actions[0].choices) if actions else set()


def test_manifest_declares_a_stable_schema(manifest):
    assert manifest["schema_version"] == "1"
    assert manifest["name"] == "Universal Agent Platform"
    assert manifest["type"] == "agent-orchestration-framework"
    assert manifest["version"] == __version__
    assert manifest["cli"] == "agentctl"


@pytest.mark.parametrize("section", ["bootstrap", "discovery", "orchestration"])
def test_every_manifest_command_exists_in_the_cli(manifest, section):
    known = _subcommands()
    for key, command in manifest[section].items():
        if not isinstance(command, str) or not command.startswith("agentctl "):
            continue
        subcommand = command.split()[1]
        assert subcommand in known, f"{section}.{key} names unknown command {subcommand!r}"


def test_manifest_is_honest_about_provider_support(manifest):
    architecture = manifest["provider_architecture"]
    assert set(architecture["implemented"]) == {"codex", "cursor", "mock", "openai_compatible"}
    assert "openai" in architecture["plugin_ready"]
    assert "openai_compatible" not in architecture["plugin_ready"]
    # Nothing may be listed as both real and aspirational.
    assert not set(architecture["implemented"]) & set(architecture["plugin_ready"])
    assert "unsupported" in architecture["states"]
    assert "model_dependent" in architecture["capability_values"]


def test_manifest_promises_profiles_are_not_a_closed_taxonomy(manifest):
    profiles = manifest["work_profiles"]
    assert profiles["closed_taxonomy"] is False
    assert profiles["multi_profile"] is True
    assert len(profiles["starter_packs"]) == 10
    assert "general" in profiles["starter_packs"]


def test_manifest_starter_packs_match_the_installed_profiles(manifest):
    installed = {path.stem for path in (PACKAGE_ROOT / "config" / "profiles").glob("*.yaml")}
    assert set(manifest["work_profiles"]["starter_packs"]) == installed


def test_manifest_documentation_targets_exist(manifest):
    for key, relative in manifest["documentation"].items():
        assert (PACKAGE_ROOT / relative).exists(), f"documentation.{key} points at a missing file"


def test_manifest_records_the_safety_posture(manifest):
    safety = manifest["safety"]
    assert safety["bundled_dashboard"] is False
    assert safety["untrusted_plugin_execution"] is False
    assert manifest["testing"]["real_ai_quota_consumed"] is False


def test_bootstrap_document_covers_every_required_section():
    text = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    for heading in ("What this framework is", "When to use it", "Installation",
                    "Detect an existing installation", "Global setup",
                    "Initialize the target project", "Project discovery",
                    "Provider discovery and health", "Continue in the current AI task", "Safety",
                    "Upgrade", "Uninstall and detach", "Troubleshooting"):
        assert heading in text, f"AI-BOOTSTRAP.md is missing the {heading!r} section"


def test_bootstrap_document_states_the_recursion_guard():
    text = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    assert "UAP_CHILD_EXECUTION=1" in text
    assert "AI assistants" in text


def test_bootstrap_commands_are_real_commands():
    known = _subcommands()
    text = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    named = set(re.findall(r"agentctl (?!--)([a-z][a-z-]*)", text)) - {"command"}
    unknown = named - known
    assert not unknown, f"AI-BOOTSTRAP.md names commands that do not exist: {sorted(unknown)}"


def test_readme_routes_ai_assistants_to_the_contract():
    text = README_PATH.read_text(encoding="utf-8")
    assert "FOR AI ASSISTANTS" in text
    assert "FOR HUMANS" in text
    assert "AI-BOOTSTRAP.md" in text and "agent-platform.json" in text
    # The promise the whole product rests on.
    assert "Stop making every AI session rediscover your project." in text
    assert text.index("FOR AI ASSISTANTS") < text.index("FOR HUMANS")


def test_url_only_entry_is_visible_and_matches_the_manifest(manifest):
    readme = README_PATH.read_text(encoding="utf-8")
    bootstrap = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    entry = manifest["url_only_entry"]
    url = "https://github.com/anan1999/universal-agent-platform"
    assert "Start with a goal and this URL" in readme[:1800]
    assert url in readme[:1800] and url in entry["user_message"]
    assert "URL-only entry point" in bootstrap[:1800]
    assert entry["assistant_first_read"] == ["README.md", "AI-BOOTSTRAP.md", "agent-platform.json"]
    assert entry["continue_in_current_task"] is True
    assert entry["respect_host_permissions"] is True
    assert "agentctl prepare" in readme[:1800]
    assert "GitHub" in entry["requires"][0]


def test_url_only_entry_handles_outdated_installs():
    readme = README_PATH.read_text(encoding="utf-8")
    bootstrap = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    command = "pip install --upgrade git+https://github.com/anan1999/universal-agent-platform.git"
    assert command in readme and command in bootstrap
    assert "older" in readme[:3500] and "older" in bootstrap[:3500]
