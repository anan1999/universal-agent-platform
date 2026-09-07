from pathlib import Path

from adaptive_agent.cli import _dry_run
from adaptive_agent.providers.mock import MockProvider
from adaptive_agent.providers.registry import ProviderDescriptor, ProviderRegistry
from adaptive_agent.providers.base import ProviderKind


ROOT = Path(__file__).resolve().parents[2]


def test_universal_core_has_no_codex_or_model_family_dependency():
    """Provider/model proper nouns belong to adapters and configuration."""
    source = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in (ROOT / "src" / "adaptive_agent" / "core").glob("*.py")
    )
    assert "providers.codex" not in source
    assert "gpt-5.6-luna" not in source
    assert "gpt-5.6-sol" not in source
    assert "gpt-6-astra" not in source


def test_provider_registry_owns_native_role_profiles():
    registry = ProviderRegistry([
        ProviderDescriptor("sample", "Sample", ProviderKind.TEST, MockProvider,
                           profile_for_role=lambda role: f"native-{role}")
    ])
    assert registry.profile_for("sample", "analyst") == "native-analyst"


def test_explicit_provider_constrains_capability_routing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    plan = _dry_run(
        "Read README.md and report its title. Do not modify anything.",
        "codex",
        profiles=["technical-writing"],
    )
    agent_tasks = [task for task in plan["tasks"] if task["kind"] == "agent"]
    assert agent_tasks
    assert {task["provider"] for task in agent_tasks} == {"codex"}
