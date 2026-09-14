"""Small, dependency-free adapter for OpenAI-compatible HTTP endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from adaptive_agent.core.capabilities import Support
from adaptive_agent.core.models import Receipt, Task
from adaptive_agent.providers.base import (
    AIProvider,
    ExecutionMode,
    ProgressCallback,
    ProviderCapabilities,
    ProviderKind,
    ProviderProbe,
    ProviderState,
    UsageReport,
)


Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, bytes]]


def _stdlib_transport(method: str, url: str, headers: dict[str, str],
                      body: bytes | None, timeout: float) -> tuple[int, bytes]:
    request = Request(url, data=body, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is explicit user config
        return int(response.status), response.read()


class OpenAICompatibleProvider(AIProvider):
    """Execute text reasoning against a user-configured compatible endpoint.

    Configuration is environment-only. Project files may name environment
    variables, but never contain their values.
    """

    id = "openai_compatible"
    display_name = "OpenAI-compatible endpoint"
    kind = ProviderKind.API
    execution_mode = ExecutionMode.API_REASONING
    implemented = True

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: float = 30.0,
                 transport: Transport | None = None):
        self.base_url = (base_url or os.getenv("UAP_OPENAI_COMPATIBLE_BASE_URL") or
                         os.getenv("OPENAI_COMPATIBLE_BASE_URL") or
                         os.getenv("OPENAI_BASE_URL") or "").rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("UAP_OPENAI_COMPATIBLE_API_KEY", "")
        if not self.api_key:
            key_variable = os.getenv("UAP_OPENAI_COMPATIBLE_API_KEY_ENV", "OPENAI_API_KEY")
            self.api_key = os.getenv(key_variable, "")
        self.model = model or os.getenv("UAP_OPENAI_COMPATIBLE_MODEL", "")
        self.timeout = max(0.1, min(float(timeout), 60.0))
        self.transport = transport or _stdlib_transport
        self._usage = UsageReport(source="unavailable", invocation_count=0)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def probe(self) -> ProviderProbe:
        configuration = {"base_url": bool(self.base_url), "api_key": bool(self.api_key),
                         "model": bool(self.model)}
        if not self.base_url:
            return ProviderProbe(ProviderState.UNCONFIGURED,
                                 "Set UAP_OPENAI_COMPATIBLE_BASE_URL to configure this adapter.",
                                 configuration=configuration)
        try:
            status, body = self.transport("GET", f"{self.base_url}/models", self._headers(),
                                          None, min(self.timeout, 3.0))
            if status < 200 or status >= 300:
                return ProviderProbe(ProviderState.CONFIGURED,
                                     f"Endpoint configured but health probe returned HTTP {status}.",
                                     error=f"HTTP_{status}", configuration=configuration)
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("models response is not an object")
            return ProviderProbe(ProviderState.CONNECTED, "Compatible endpoint answered the models probe.",
                                 configuration=configuration)
        except HTTPError as error:
            return ProviderProbe(ProviderState.CONFIGURED,
                                 f"Endpoint configured but health probe returned HTTP {error.code}.",
                                 error=f"HTTP_{error.code}", configuration=configuration)
        except (TimeoutError, URLError, OSError, ValueError, json.JSONDecodeError) as error:
            return ProviderProbe(ProviderState.CONFIGURED,
                                 "Endpoint configured but the bounded health probe did not connect.",
                                 error=type(error).__name__, configuration=configuration)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities({
            "text": Support.SUPPORTED,
            "vision": Support.MODEL_DEPENDENT,
            "tool_use": Support.MODEL_DEPENDENT,
            "filesystem": Support.UNSUPPORTED,
            "write_access": Support.UNSUPPORTED,
            "repository_access": Support.UNSUPPORTED,
            "shell": Support.UNSUPPORTED,
            "structured_output": Support.MODEL_DEPENDENT,
            "streaming": Support.UNSUPPORTED,
            "usage_reporting": Support.MODEL_DEPENDENT,
            "long_context": Support.MODEL_DEPENDENT,
            "image_generation": Support.UNSUPPORTED,
            "code_execution": Support.UNSUPPORTED,
        })

    def usage(self) -> UsageReport:
        return self._usage

    async def execute(self, task: Task, progress: ProgressCallback | None = None, packet=None) -> Receipt:
        started = time.monotonic()
        model = str(task.metadata.get("model") or self.model)
        if model.startswith("env:"):
            model = self.model
        if not self.base_url or not model:
            return self._failure(task, "PROVIDER_UNCONFIGURED",
                                 "OpenAI-compatible base URL and model must be configured.", started, model)
        if progress:
            progress(10, f"Sending bounded request for {task.title}")
        prompt = packet.render() if packet is not None else str(task.metadata.get("goal") or task.title)
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        budget = task.metadata.get("execution_budget", {})
        if budget.get("max_output_tokens") is not None:
            payload["max_tokens"] = int(budget["max_output_tokens"])
        if task.metadata.get("structured_output"):
            payload["response_format"] = {"type": "json_object"}
        try:
            try:
                status, raw = await asyncio.to_thread(self._request, payload)
            except HTTPError as error:
                if error.code not in {400, 422} or "response_format" not in payload:
                    raise
                payload.pop("response_format")
                status, raw = await asyncio.to_thread(self._request, payload)
            if status in {400, 422} and "response_format" in payload:
                payload.pop("response_format")
                status, raw = await asyncio.to_thread(self._request, payload)
            if status < 200 or status >= 300:
                code = "PROVIDER_AUTH_ERROR" if status in {401, 403} else f"PROVIDER_HTTP_{status}"
                return self._failure(task, code,
                                     f"Compatible endpoint returned HTTP {status}.", started, model)
            response = json.loads(raw.decode("utf-8"))
            output = self._content(response)
            usage = response.get("usage") if isinstance(response, dict) else None
            token_usage = self._normalized_usage(usage)
            self._accumulate(token_usage)
            if progress:
                progress(100, f"Compatible endpoint completed {task.title}")
            learning_evidence: list[dict[str, Any]] = []
            try:
                structured = json.loads(output)
                if isinstance(structured, dict) and isinstance(structured.get("learning_evidence"), list):
                    learning_evidence = [item for item in structured["learning_evidence"] if isinstance(item, dict)]
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
            return Receipt(task_id=task.id, agent=task.owner, status="completed", summary=output,
                           findings=["API-only reasoning completed; no project filesystem was exposed."],
                           token_usage=token_usage, confidence="medium", provider=self.id, model=model,
                           learning_evidence=learning_evidence,
                           duration_seconds=time.monotonic() - started)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return self._failure(task, "PROVIDER_TIMEOUT", "Compatible endpoint timed out.", started, model)
        except HTTPError as error:
            code = "PROVIDER_AUTH_ERROR" if error.code in {401, 403} else f"PROVIDER_HTTP_{error.code}"
            return self._failure(task, code, f"Compatible endpoint returned HTTP {error.code}.", started, model)
        except (URLError, OSError) as error:
            return self._failure(task, "PROVIDER_CONNECTION", type(error).__name__, started, model)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            return self._failure(task, "PROVIDER_INVALID_RESPONSE", str(error), started, model)

    def _request(self, payload: dict[str, Any]) -> tuple[int, bytes]:
        return self.transport("POST", f"{self.base_url}/chat/completions", self._headers(),
                              json.dumps(payload).encode("utf-8"), self.timeout)

    @staticmethod
    def _content(response: Any) -> str:
        content = response["choices"][0]["message"]["content"]
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = [item.get("text", "") for item in content if isinstance(item, dict)]
            return "".join(text_parts)
        raise ValueError("response message content is missing")

    @staticmethod
    def _normalized_usage(usage: Any) -> dict[str, int | bool | str]:
        if not isinstance(usage, dict):
            return {"input": 0, "output": 0, "cached": 0,
                    "source": "unavailable", "estimated": False}
        details = usage.get("prompt_tokens_details") or {}
        return {"input": int(usage.get("prompt_tokens", 0) or 0),
                "output": int(usage.get("completion_tokens", 0) or 0),
                "cached": int(details.get("cached_tokens", 0) or 0),
                "source": "measured", "estimated": False}

    def _accumulate(self, usage: dict[str, int | bool | str]) -> None:
        self._usage = UsageReport(self._usage.input_tokens + int(usage["input"]),
                                  self._usage.output_tokens + int(usage["output"]),
                                  self._usage.cached_tokens + int(usage["cached"]),
                                  str(usage["source"]), self._usage.invocation_count + 1)

    def _failure(self, task: Task, code: str, message: str, started: float, model: str) -> Receipt:
        return Receipt(task_id=task.id, agent=task.owner, status="failed", summary=message,
                       token_usage={"input": 0, "output": 0, "cached": 0,
                                    "source": "unavailable", "estimated": False},
                       confidence="unknown", uncertainty_reason=message, needs_escalation=False,
                       error_code=code, provider=self.id, model=model or None,
                       duration_seconds=time.monotonic() - started)
