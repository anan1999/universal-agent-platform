import asyncio
import json

from adaptive_agent.core.models import Task
from adaptive_agent.core.escalation import EscalationManager, FailureKind
from adaptive_agent.providers.base import ProviderState
from adaptive_agent.providers.openai_compatible import OpenAICompatibleProvider


def test_probe_requires_connection_and_never_exposes_secret():
    unconfigured = OpenAICompatibleProvider()
    assert unconfigured.probe().state is ProviderState.UNCONFIGURED

    calls = []

    def transport(method, url, headers, body, timeout):
        calls.append((method, url, headers, body, timeout))
        return 200, b'{"object":"list","data":[]}'

    provider = OpenAICompatibleProvider("http://localhost:9999/v1", "top-secret", "test-model",
                                        transport=transport)
    probe = provider.probe()
    assert probe.state is ProviderState.CONNECTED
    assert probe.ready
    assert "top-secret" not in json.dumps(probe.to_dict())
    assert calls[0][2]["Authorization"] == "Bearer top-secret"


def test_execute_normalizes_result_and_measured_usage():
    def transport(method, url, headers, body, timeout):
        assert method == "POST"
        assert url.endswith("/chat/completions")
        return 200, json.dumps({
            "choices": [{"message": {"content": "UAP_PROVIDER_OK"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2,
                      "prompt_tokens_details": {"cached_tokens": 1}},
        }).encode()

    provider = OpenAICompatibleProvider("http://localhost:9999/v1", model="real-model",
                                        transport=transport)
    task = Task("TASK-1", "RUN-1", "Return exactly: UAP_PROVIDER_OK", "tester", ["text"])
    receipt = asyncio.run(provider.execute(task))
    assert receipt.status == "completed"
    assert receipt.summary == "UAP_PROVIDER_OK"
    assert receipt.provider == "openai_compatible"
    assert receipt.model == "real-model"
    assert receipt.token_usage == {"input": 4, "output": 2, "cached": 1,
                                   "source": "measured", "estimated": False}


def test_execute_passes_explicit_output_budget_to_compatible_api():
    bodies = []

    def transport(method, url, headers, body, timeout):
        bodies.append(json.loads(body))
        return 200, b'{"choices":[{"message":{"content":"bounded"}}]}'

    provider = OpenAICompatibleProvider("http://localhost:9999/v1", model="test-model",
                                        transport=transport)
    task = Task("TASK-BUDGET", "RUN", "bounded", "tester", ["text"],
                metadata={"execution_budget": {"max_output_tokens": 321}})
    assert asyncio.run(provider.execute(task)).status == "completed"
    assert bodies[0]["max_tokens"] == 321


def test_execute_classifies_timeout_without_fabricating_usage():
    def timeout(*args):
        raise TimeoutError

    provider = OpenAICompatibleProvider("http://localhost:9999/v1", model="test-model",
                                        transport=timeout)
    task = Task("TASK-2", "RUN-2", "tiny request", "tester", ["text"])
    receipt = asyncio.run(provider.execute(task))
    assert receipt.status == "failed"
    assert receipt.error_code == "PROVIDER_TIMEOUT"
    assert receipt.token_usage["source"] == "unavailable"


def test_structured_output_falls_back_once_when_endpoint_rejects_it():
    bodies = []

    def transport(method, url, headers, body, timeout):
        payload = json.loads(body)
        bodies.append(payload)
        if len(bodies) == 1:
            return 400, b'{"error":"response_format unsupported"}'
        return 200, b'{"choices":[{"message":{"content":"fallback ok"}}]}'

    provider = OpenAICompatibleProvider("http://localhost:9999/v1", model="test-model",
                                        transport=transport)
    task = Task("TASK-3", "RUN-3", "structured", "tester", ["text"],
                metadata={"structured_output": True})
    receipt = asyncio.run(provider.execute(task))
    assert receipt.status == "completed"
    assert "response_format" in bodies[0]
    assert "response_format" not in bodies[1]


def test_auth_failure_is_classified_and_never_requests_stronger_model():
    provider = OpenAICompatibleProvider(
        "http://localhost:9999/v1", model="test-model",
        transport=lambda *args: (401, b'{"error":"invalid key"}'),
    )
    task = Task("TASK-AUTH", "RUN", "tiny request", "tester", ["text"], model_class="cheap")
    receipt = asyncio.run(provider.execute(task))
    decision = EscalationManager().decide(task, receipt, 0)
    assert receipt.error_code == "PROVIDER_AUTH_ERROR"
    assert receipt.needs_escalation is False
    assert decision.failure_kind is FailureKind.ENVIRONMENT
    assert decision.escalate is False


def test_invalid_model_http_failure_does_not_auto_escalate():
    provider = OpenAICompatibleProvider(
        "http://localhost:9999/v1", model="missing-model",
        transport=lambda *args: (404, b'{"error":"model not found"}'),
    )
    task = Task("TASK-MODEL", "RUN", "tiny request", "tester", ["text"], model_class="cheap")
    receipt = asyncio.run(provider.execute(task))
    assert receipt.error_code == "PROVIDER_HTTP_404"
    assert EscalationManager().decide(task, receipt, 0).escalate is False


def test_malformed_json_is_environment_failure_without_usage_or_escalation():
    provider = OpenAICompatibleProvider(
        "http://localhost:9999/v1", model="test-model",
        transport=lambda *args: (200, b'not-json'),
    )
    task = Task("TASK-JSON", "RUN", "tiny request", "tester", ["text"], model_class="cheap")
    receipt = asyncio.run(provider.execute(task))
    decision = EscalationManager().decide(task, receipt, 0)
    assert receipt.error_code == "PROVIDER_INVALID_RESPONSE"
    assert receipt.token_usage["source"] == "unavailable"
    assert decision.failure_kind is FailureKind.ENVIRONMENT
    assert decision.escalate is False
