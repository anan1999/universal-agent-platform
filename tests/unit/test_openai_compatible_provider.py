import asyncio
import json

from adaptive_agent.core.models import Task
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
