"""Deterministic, quota-free proof that routing can span provider types."""

from adaptive_agent.core.capabilities import CapabilityProfile, Level, Requirement, Support
from adaptive_agent.core.capability_router import CapabilityRouter
from adaptive_agent.core.models import Receipt, Task
from adaptive_agent.models.registry import ModelDescriptor, ModelRegistry
from adaptive_agent.providers.base import AIProvider, ExecutionMode, ProviderCapabilities, ProviderKind
from adaptive_agent.providers.registry import ProviderDescriptor, ProviderRegistry


class _DemoProvider(AIProvider):
    def __init__(self, provider_id: str, execution_mode: ExecutionMode,
                 values: dict[str, Support]):
        self.id = provider_id
        self.execution_mode = execution_mode
        self._values = values

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(self._values)

    async def execute(self, task: Task, progress=None, packet=None) -> Receipt:  # pragma: no cover
        raise RuntimeError("cross-provider demo is routing-only and never executes providers")


def cross_provider_demo() -> dict:
    api = lambda: _DemoProvider("mock_api", ExecutionMode.API_REASONING, {
        "text": Support.SUPPORTED, "filesystem": Support.UNSUPPORTED,
        "write_access": Support.UNSUPPORTED, "repository_access": Support.UNSUPPORTED,
    })
    local = lambda: _DemoProvider("mock_agentic", ExecutionMode.AGENTIC_LOCAL, {
        "text": Support.SUPPORTED, "filesystem": Support.SUPPORTED,
        "write_access": Support.SUPPORTED, "repository_access": Support.SUPPORTED,
    })
    providers = ProviderRegistry([
        ProviderDescriptor("mock_api", "Mock API reasoning", ProviderKind.TEST, api),
        ProviderDescriptor("mock_agentic", "Mock agentic local", ProviderKind.TEST, local),
    ])
    models = ModelRegistry([
        ModelDescriptor("mock-api-model", "mock_api", "mock-api-model",
                        capabilities=CapabilityProfile({"analysis": Level.HIGH, "review": Level.HIGH}),
                        cost="low", latency="fast"),
        ModelDescriptor("mock-agentic-model", "mock_agentic", "mock-agentic-model",
                        capabilities=CapabilityProfile({"coding": Level.HIGH, "analysis": Level.HIGH}),
                        cost="medium", latency="medium"),
    ])
    router = CapabilityRouter(models, providers, preferences=["mock_api", "mock_agentic"])
    available = ["mock_api", "mock_agentic"]
    planning = router.route([Requirement("analysis")], task_type="planning",
                            available_providers=available)
    coding = router.route([
        Requirement("coding"), Requirement("filesystem"), Requirement("write_access"),
        Requirement("repository_access")], task_type="coding", available_providers=available)
    review = router.route([Requirement("review")], task_type="review",
                          available_providers=available)
    return {"offline": True, "quota_consumed": False,
            "goal": "Build a simple product landing page.",
            "routes": {"product_planner": planning.to_dict(),
                       "developer": coding.to_dict(), "ui_reviewer": review.to_dict()}}
