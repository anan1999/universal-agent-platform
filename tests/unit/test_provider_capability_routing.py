from adaptive_agent.core.capabilities import CapabilityProfile, Level, Requirement, Support
from adaptive_agent.core.capability_router import CapabilityRouter
from adaptive_agent.core.models import Receipt, Task
from adaptive_agent.models.registry import ModelDescriptor, ModelRegistry
from adaptive_agent.providers.base import AIProvider, ExecutionMode, ProviderCapabilities, ProviderKind
from adaptive_agent.providers.registry import ProviderDescriptor, ProviderRegistry


class FakeProvider(AIProvider):
    def __init__(self, provider_id, mode, capabilities):
        self.id = provider_id
        self.execution_mode = mode
        self._capabilities = ProviderCapabilities(capabilities)

    def capabilities(self):
        return self._capabilities

    async def execute(self, task: Task, progress=None, packet=None) -> Receipt:  # pragma: no cover
        raise AssertionError("routing tests must remain offline")


def _router():
    api = lambda: FakeProvider("api", ExecutionMode.API_REASONING, {
        "text": Support.SUPPORTED, "filesystem": Support.UNSUPPORTED,
        "write_access": Support.UNSUPPORTED, "repository_access": Support.UNSUPPORTED,
    })
    local = lambda: FakeProvider("local", ExecutionMode.AGENTIC_LOCAL, {
        "text": Support.SUPPORTED, "filesystem": Support.SUPPORTED,
        "write_access": Support.SUPPORTED, "repository_access": Support.SUPPORTED,
    })
    providers = ProviderRegistry([
        ProviderDescriptor("api", "API", ProviderKind.API, api),
        ProviderDescriptor("local", "Local", ProviderKind.CLI, local),
    ])
    models = ModelRegistry([
        ModelDescriptor("api-model", "api", "api-real", capabilities=CapabilityProfile({"analysis": Level.HIGH})),
        ModelDescriptor("local-model", "local", "local-real", capabilities=CapabilityProfile({"analysis": Level.HIGH})),
    ])
    return CapabilityRouter(models, providers, preferences=["api", "local"])


def test_preference_cannot_override_hard_provider_capability():
    decision = _router().route([
        Requirement("analysis"), Requirement("filesystem"), Requirement("write_access")
    ], available_providers=["api", "local"])
    assert decision.provider == "local"
    assert "Preferred provider api rejected" in decision.reason
    rejected = [item for item in decision.candidates if item["provider"] == "api"]
    assert rejected and "filesystem" in rejected[0]["disqualified"]


def test_api_provider_remains_valid_for_reasoning_only_work():
    decision = _router().route([Requirement("analysis")], available_providers=["api", "local"])
    assert decision.provider == "api"
