from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import time

from pathlib import Path
from typing import Sequence

from adaptive_agent.core.capability_router import CapabilityRouter
from adaptive_agent.core.artifact_evaluator import DeclaredArtifactEvaluator
from adaptive_agent.core.consumption import ExecutionBudget
from adaptive_agent.core.escalation import EscalationManager
from adaptive_agent.core.execution_packet import ExecutionPacketBuilder
from adaptive_agent.core.models import Event, Receipt, Task, TaskKind, TaskStatus
from adaptive_agent.core.tools import ToolExecutor, ToolRegistry
from adaptive_agent.observability.efficiency import TokenEfficiencyAnalyzer
from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.observability.performance import PerformanceTracker
from adaptive_agent.providers.base import AIProvider
from adaptive_agent.providers.registry import ProviderRegistry
from adaptive_agent.runtime import RESOURCE_ROOT, platform_home
from adaptive_agent.skills.manifest import SkillTrust
from adaptive_agent.skills.registry import SkillRegistry
from adaptive_agent.skills.quality import SkillQualityStore
from adaptive_agent.storage.database import Database
from adaptive_agent.tasks.graph import TaskGraph
from adaptive_agent.tasks.receipt import ReceiptStore


class Scheduler:
    def __init__(self, database: Database, events: EventBus, provider: AIProvider,
                 provider_name: str = "mock",
                 max_parallel_agents: int = 3, max_parallel_strong_agents: int = 1,
                 max_escalations: int = 2, capability_router: CapabilityRouter | None = None,
                 tools: ToolRegistry | None = None, approvals: Sequence[str] = (),
                 provider_registry: ProviderRegistry | None = None,
                 receipt_word_limit: int = 160, max_context_receipts: int = 4,
                 skill_registry: SkillRegistry | None = None,
                 execution_budget: ExecutionBudget | None = None):
        self.database = database
        self.events = events
        self.provider = provider
        self.capability_router = capability_router
        self.provider_name = provider_name
        self.tools = tools or ToolRegistry.default()
        self.approvals = {str(item) for item in approvals}
        self.provider_registry = provider_registry
        self.receipts = ReceiptStore(database)
        self.performance = PerformanceTracker(database)
        self.efficiency = TokenEfficiencyAnalyzer()
        self.escalation = EscalationManager(max_escalations)
        self.parallel = asyncio.Semaphore(max_parallel_agents)
        self.strong_parallel = asyncio.Semaphore(max_parallel_strong_agents)
        self.completed_receipts: dict[str, Receipt] = {}
        self._provider_cache: dict[str, AIProvider] = {provider_name: provider}
        self.packet_builder = ExecutionPacketBuilder(receipt_word_limit, max_context_receipts)
        self.skill_registry = skill_registry or SkillRegistry.from_yaml(
            RESOURCE_ROOT / "config" / "default_skills.yaml")
        self.skill_quality = SkillQualityStore(database)
        self.budget = execution_budget or ExecutionBudget()
        self._budget_started = time.monotonic()
        self._provider_calls = 0
        self._tool_calls = 0
        self._tokens = 0
        self._provider_metric_attempts = 0
        self._provider_metrics_complete = True
        self._measured_total_tokens = 0
        self._measured_cached_tokens = 0
        self._provider_tool_calls = 0
        self._provider_messages = 0
        self._provider_duration_seconds = 0.0

    def budget_status(self) -> dict[str, object]:
        return {
            **self.budget.to_dict(),
            "provider_calls_used": self._provider_calls,
            "tool_calls_used": self._tool_calls,
            "tokens_used": self._tokens,
            "elapsed_seconds": round(time.monotonic() - self._budget_started, 3),
        }

    def adaptive_metrics(self) -> dict[str, object]:
        """Aggregate bounded provider measurements across every attempted AI task."""
        if not self._provider_metric_attempts or not self._provider_metrics_complete:
            return {"source": "unavailable"}
        return {
            "source": "measured",
            "provider_tool_calls": self._provider_tool_calls,
            "provider_messages": self._provider_messages,
            "total_tokens": self._measured_total_tokens,
            "uncached_tokens": max(
                0, self._measured_total_tokens - self._measured_cached_tokens),
            "duration_seconds": round(self._provider_duration_seconds, 3),
            "provider_attempts": self._provider_metric_attempts,
        }

    def _remaining_seconds(self) -> float | None:
        if self.budget.max_wall_seconds is None:
            return None
        return self.budget.max_wall_seconds - (time.monotonic() - self._budget_started)

    @staticmethod
    def _is_verification(task: Task) -> bool:
        text = f"{task.owner} {task.title} {task.metadata.get('task_type', '')}".lower()
        return any(value in text for value in ("review", "verify", "validation", "test", "audit"))

    def _claim_provider(self, task: Task, estimated_input_tokens: int) -> str | None:
        remaining_seconds = self._remaining_seconds()
        if remaining_seconds is not None and remaining_seconds <= 0:
            return "wall-time budget exhausted"
        if (self.budget.max_provider_calls is not None and
                self._provider_calls >= self.budget.max_provider_calls):
            return "provider-call budget exhausted"
        if self.budget.max_total_tokens is not None:
            token_limit = self.budget.max_total_tokens
            if not self._is_verification(task):
                token_limit = token_limit * (100 - self.budget.verification_reserve_percent) // 100
            if self._tokens + estimated_input_tokens > token_limit:
                return "token budget cannot fit the next provider input"
        self._provider_calls += 1
        return None

    def _claim_tool(self) -> str | None:
        remaining_seconds = self._remaining_seconds()
        if remaining_seconds is not None and remaining_seconds <= 0:
            return "wall-time budget exhausted"
        if self.budget.max_tool_calls is not None and self._tool_calls >= self.budget.max_tool_calls:
            return "tool-call budget exhausted"
        self._tool_calls += 1
        return None

    def _budget_failure(self, task: Task, reason: str) -> bool:
        task.status = TaskStatus.FAILED
        task.metadata["budget"] = self.budget_status() | {"exhausted_reason": reason}
        receipt = Receipt(
            task.id, task.owner, "failed", f"Budget exhausted: {reason}.",
            findings=["Completed work remains recorded; no automatic budget extension was allowed."],
            token_usage={"input": 0, "output": 0, "cached": 0, "source": "unavailable",
                         "estimated": False, "invocation_count": 0},
            confidence="unknown", uncertainty_reason=reason, needs_escalation=False,
            error_code="BUDGET_EXHAUSTED",
        )
        self._record_attempt(task, receipt)
        self.completed_receipts[task.id] = receipt
        self._persist(task)
        self.events.emit(Event("budget_exhausted", task.run_id, task.owner, task.id,
                               {"reason": reason, "budget": self.budget_status()}))
        return False

    async def run(self, graph: TaskGraph) -> bool:
        graph.validate()
        try:
            while not graph.complete():
                ready = graph.ready()
                if not ready:
                    return False
                results = await asyncio.gather(*(self._execute_task(task) for task in ready))
                if not all(results):
                    return False
            return True
        except asyncio.CancelledError:
            self.events.emit(Event("run_cancelled", next(iter(graph.tasks.values())).run_id if graph.tasks else None))
            raise

    async def _execute_task(self, task: Task) -> bool:
        if task.kind is TaskKind.TOOL:
            return self._execute_tool(task)
        if task.kind is TaskKind.APPROVAL:
            return self._execute_approval(task)
        if task.kind is TaskKind.ARTIFACT:
            return self._execute_artifact(task)
        return await self._execute_agent(task)

    def _execute_artifact(self, task: Task) -> bool:
        task.status = TaskStatus.COMPLETED
        receipt = Receipt(task.id, task.owner, "completed", "Artifact recorded without an AI invocation.",
                          token_usage={"input": 0, "output": 0, "cached": 0,
                                       "source": "unavailable", "estimated": False,
                                       "invocation_count": 0})
        self._record_attempt(task, receipt)
        self.completed_receipts[task.id] = receipt
        self._persist(task)
        self.events.emit(Event("artifact_recorded", task.run_id, task.owner, task.id))
        return True

    def _execute_tool(self, task: Task) -> bool:
        """Deterministic execution. Consumes no AI quota and reports no tokens."""
        exhausted = self._claim_tool()
        if exhausted:
            return self._budget_failure(task, exhausted)
        task.status = TaskStatus.RUNNING
        self._persist(task)
        self.events.emit(Event("tool_started", task.run_id, task.owner, task.id,
                               {"tool": task.metadata.get("tool", task.owner)}))
        workspace = Path(task.metadata.get("working_directory", "."))
        executor = ToolExecutor(self.tools, workspace, self.approvals)
        result = executor.run(str(task.metadata.get("tool", task.owner)))
        receipt = Receipt(task_id=task.id, agent=task.owner,
                          status="completed" if result.status in {"completed", "skipped"} else result.status,
                          summary=result.summary, findings=result.findings or ([result.output] if result.output else []),
                          token_usage={"input": 0, "output": 0, "cached": 0, "source": "unavailable",
                                       "estimated": False, "invocation_count": 0},
                          confidence="high" if result.status == "completed" else "unknown",
                          model=None, duration_seconds=result.duration_seconds)
        self._record_attempt(task, receipt)
        self.completed_receipts[task.id] = receipt
        task.status = TaskStatus.COMPLETED if receipt.status == "completed" else TaskStatus.FAILED
        task.metadata["tool_result"] = result.to_dict()
        self._persist(task)
        self.events.emit(Event("tool_completed" if task.status == TaskStatus.COMPLETED else "tool_failed",
                               task.run_id, task.owner, task.id, {"status": result.status,
                                                                  "exit_code": result.exit_code}))
        return task.status == TaskStatus.COMPLETED

    def _execute_approval(self, task: Task) -> bool:
        """Approval gates never auto-pass. Without approval the run stops here."""
        gate = str(task.metadata.get("approval_gate", "approval"))
        approved = gate in self.approvals
        task.status = TaskStatus.COMPLETED if approved else TaskStatus.WAITING
        summary = (f"Approved: {gate}." if approved else
                   f"Waiting for human approval of '{gate}'. "
                   f"Re-run with --approve {gate} once a human has authorised it.")
        receipt = Receipt(task_id=task.id, agent=task.owner,
                          status="completed" if approved else "blocked", summary=summary,
                          token_usage={"input": 0, "output": 0, "cached": 0, "source": "unavailable",
                                       "estimated": False, "invocation_count": 0},
                          confidence="high" if approved else "unknown", uncertainty_reason="" if approved else summary)
        self._record_attempt(task, receipt)
        self.completed_receipts[task.id] = receipt
        self._persist(task)
        self.events.emit(Event("approval_granted" if approved else "approval_required",
                               task.run_id, task.owner, task.id, {"gate": gate}))
        return approved

    def _provider_for(self, task: Task) -> AIProvider:
        """Per-task provider resolution; a team may span providers."""
        name = str(task.metadata.get("provider") or self.provider_name)
        if name in self._provider_cache:
            return self._provider_cache[name]
        if self.provider_registry is None or name not in self.provider_registry:
            return self.provider
        try:
            resolved = self.provider_registry.create(name)
        except Exception:
            return self.provider
        self._provider_cache[name] = resolved
        return resolved

    async def _execute_agent(self, task: Task) -> bool:
        async with self.parallel:
            provider = self._provider_for(task)
            task.status = TaskStatus.RUNNING
            self._persist(task)
            self._set_skill_activity(task, True)
            self.events.emit(Event("agent_spawned", task.run_id, task.owner, task.id,
                                   {"model": task.metadata.get("model"), "reasoning": task.reasoning,
                                    "provider": getattr(provider, "id", self.provider_name)}))
            attempts = 0
            while True:
                self.events.emit(Event("task_started", task.run_id, task.owner, task.id,
                                       {"model": task.metadata.get("model"), "attempt": attempts + 1}))

                def progress(percent: int, message: str) -> None:
                    self.events.emit(Event("task_progress", task.run_id, task.owner, task.id,
                                           {"progress": percent, "message": message}))

                context_ids = task.metadata.get("context_receipts", task.dependencies)
                dependency_receipts = [self.completed_receipts[item] for item in context_ids if item in self.completed_receipts]
                try:
                    loaded_skills = self._load_skills(task)
                except (KeyError, ValueError, PermissionError) as error:
                    receipt = Receipt(task.id, task.owner, "failed", str(error),
                                      token_usage={"input": 0, "output": 0, "cached": 0,
                                                   "source": "unavailable", "estimated": False,
                                                   "invocation_count": 0},
                                      error_code="SKILL_VALIDATION_FAILED", needs_escalation=False)
                    self._record_attempt(task, receipt)
                    task.status = TaskStatus.FAILED
                    self._persist(task)
                    self._set_skill_activity(task, False)
                    return False
                packet = self.packet_builder.build(
                    task,
                    task.metadata.get("working_directory", "."),
                    task.metadata.get("project_name", "project"),
                    task.metadata.get("project_type", "unknown"),
                    dependency_receipts,
                    loaded_skills=loaded_skills,
                )
                estimated_input = max(1, len(packet.render()) // 4)
                exhausted = self._claim_provider(task, estimated_input)
                if exhausted:
                    self._set_skill_activity(task, False)
                    return self._budget_failure(task, exhausted)
                try:
                    async with self._model_slot(task.model_class):
                        remaining_seconds = self._remaining_seconds()
                        execution = provider.execute(task, progress, packet)
                        receipt = (await asyncio.wait_for(execution, remaining_seconds)
                                   if remaining_seconds is not None else await execution)
                except TimeoutError:
                    self._set_skill_activity(task, False)
                    return self._budget_failure(task, "wall-time budget exhausted")
                except asyncio.CancelledError:
                    task.status = TaskStatus.CANCELLED
                    self._persist(task)
                    self.events.emit(Event("task_cancelled", task.run_id, task.owner, task.id))
                    raise
                usage = receipt.token_usage
                self._tokens += int(usage.get("input", 0)) + int(usage.get("output", 0))
                task.metadata["budget"] = self.budget_status()
                receipt.retry_count = attempts
                receipt.escalated = attempts > 0
                self._evaluate_artifact(task, receipt)
                decision = self.escalation.decide(task, receipt, attempts)
                if (decision.escalate and self.budget.max_retry_rounds is not None and
                        attempts >= self.budget.max_retry_rounds):
                    decision.escalate = False
                    receipt.needs_escalation = False
                    receipt.findings.append("Retry suppressed by the run budget.")
                    task.metadata["budget_retry_suppressed"] = True
                    self.events.emit(Event("budget_retry_suppressed", task.run_id, task.owner,
                                           task.id, {"attempts": attempts,
                                                     "max_retry_rounds": self.budget.max_retry_rounds}))
                self._record_attempt(task, receipt)
                self._record_skill_quality(task, receipt, loaded_skills)
                if decision.escalate:
                    attempts += 1
                    old_model = task.metadata.get("model")
                    task.model_class = decision.next_model_class or task.model_class
                    task.reasoning = decision.next_reasoning or task.reasoning
                    self._reroute(task)
                    self.events.emit(Event("task_escalating", task.run_id, task.owner, task.id,
                                           {"from_model": old_model, "to_model": task.metadata.get("model"),
                                            "failure_kind": decision.failure_kind.value, "reason": decision.reason,
                                            "attempt": attempts + 1}))
                    self._persist(task)
                    continue
                task.status = TaskStatus.COMPLETED if receipt.status == "completed" else TaskStatus.FAILED
                self.completed_receipts[task.id] = receipt
                task.metadata["last_receipt"] = {"confidence": receipt.confidence, "error_code": receipt.error_code,
                                                  "duration_seconds": receipt.duration_seconds}
                warnings = [warning.to_dict() for warning in self.efficiency.analyze(task, receipt)]
                if warnings:
                    task.metadata["efficiency_warnings"] = warnings
                    self.events.emit(Event("efficiency_warning", task.run_id, task.owner, task.id, {"warnings": warnings}))
                self._persist(task)
                self._set_skill_activity(task, False)
                self.events.emit(Event("task_completed" if task.status == TaskStatus.COMPLETED else "task_failed",
                                       task.run_id, task.owner, task.id,
                                       {"confidence": receipt.confidence, "error_code": receipt.error_code}))
                return task.status == TaskStatus.COMPLETED

    def _evaluate_artifact(self, task: Task, receipt: Receipt) -> None:
        if receipt.status != "completed":
            return
        if not task.metadata.get("required_artifacts") and not task.metadata.get("required_sections"):
            return
        workspace = Path(task.metadata.get("working_directory", ".")).resolve()
        evaluator = DeclaredArtifactEvaluator()
        quality = evaluator.evaluate(task, receipt, workspace)
        task.metadata["artifact_quality"] = quality.to_dict()
        self.database.execute(
            "INSERT INTO artifact_evaluations(run_id,task_id,evaluator,passed,quality_json) "
            "VALUES(?,?,?,?,?)",
            (task.run_id, task.id, evaluator.id, int(quality.passed),
             self.database.json(quality.to_dict())))
        self.events.emit(Event("artifact_evaluated", task.run_id, task.owner, task.id,
                               {"evaluator": evaluator.id, "passed": quality.passed,
                                "failures": quality.failures}))
        if not quality.passed:
            receipt.status = "failed"
            receipt.error_code = "ARTIFACT_VALIDATION_FAILED"
            receipt.confidence = "low"
            receipt.needs_escalation = True
            receipt.uncertainty_reason = "; ".join(quality.failures)
            receipt.findings.extend(quality.failures)

    def _load_skills(self, task: Task):
        workspace = Path(task.metadata.get("working_directory", ".")).resolve()
        self.skill_registry.discover_directory(RESOURCE_ROOT / "skills", SkillTrust.BUILT_IN)
        self.skill_registry.discover_directory(platform_home() / "skills", SkillTrust.TRUSTED)
        self.skill_registry.discover_directory(workspace / ".agent" / "skills", SkillTrust.PROJECT_LOCAL)
        reference_map = task.metadata.get("skill_references", {})
        loaded = []
        for skill_id in task.metadata.get("required_skills", []):
            validation = self.skill_registry.validate(skill_id)
            if not validation["valid"]:
                raise ValueError("; ".join(validation["errors"]))
            if validation["approval_required"] and f"skill:{skill_id}" not in self.approvals:
                raise PermissionError(f"Skill '{skill_id}' requires explicit approval before execution.")
            item = self.skill_registry.load_selected(skill_id, list(reference_map.get(skill_id, [])))
            loaded.append(item)
            self.database.execute(
                "INSERT INTO run_skills(run_id,task_id,skill_id,version,loaded_references_json,context_tokens) "
                "VALUES(?,?,?,?,?,?)",
                (task.run_id, task.id, skill_id, item.manifest.version,
                 self.database.json(list(item.references)), item.estimated_context_tokens))
        return loaded

    def _record_skill_quality(self, task: Task, receipt: Receipt, loaded_skills) -> None:
        usage = receipt.token_usage
        tokens = int(usage.get("input", 0)) + int(usage.get("output", 0))
        for item in loaded_skills:
            self.skill_quality.record(
                item.manifest.id, item.manifest.version, task.run_id, task.id,
                receipt.status == "completed",
                (task.metadata.get("artifact_quality") or {}).get("correctness"),
                int(usage.get("invocation_count", 1)),
                tokens if usage.get("source") == "measured" else None,
                str(usage.get("source", "unavailable")), item.estimated_context_tokens,
                receipt.provider or str(task.metadata.get("provider", "")),
                receipt.model or str(task.metadata.get("model", "")),
                safety_failure=receipt.error_code == "SKILL_VALIDATION_FAILED")
            quality = self.skill_quality.get(item.manifest.id, item.manifest.version)
            if quality.promotion_candidate and quality.runs == 3:
                self.events.emit(Event(
                    "skill_promotion_candidate", task.run_id, task.owner, task.id,
                    {"skill": item.manifest.id, "version": item.manifest.version,
                     "runs": quality.runs, "reliability": quality.reliability},
                ))

    def _reroute(self, task: Task) -> None:
        """Pick the next model after an escalation.

        Uses the capability router's ranked candidates.
        """
        recorded = task.metadata.get("routing")
        if self.capability_router and isinstance(recorded, dict) and recorded.get("candidates"):
            from adaptive_agent.core.capability_router import RoutingDecision

            current = RoutingDecision(
                provider=recorded.get("provider", self.provider_name), model=recorded.get("model"),
                reasoning=task.reasoning, capability_signature=recorded.get("capability_signature", ""),
                required_capabilities=list(recorded.get("required_capabilities", [])),
                risk=recorded.get("risk", "low"), complexity=recorded.get("complexity", "normal"),
                candidates=list(recorded.get("candidates", [])), agent=task.owner,
                task_type=recorded.get("task_type", "unknown"))
            stronger = self.capability_router.escalate(current, task.metadata.get("tried_models", []))
            if stronger is not None:
                task.metadata.setdefault("tried_models", []).append(recorded.get("model"))
                task.metadata.update({"model": stronger.model, "provider": stronger.provider,
                                      "routing": stronger.to_dict(), "routing_reason": stronger.reason})
                task.model_class = stronger.model_class
                return

    def _set_skill_activity(self, task: Task, loaded: bool) -> None:
        for skill in task.metadata.get("required_skills", []):
            if loaded:
                self.database.execute(
                    "INSERT OR REPLACE INTO agent_skills(agent_id,skill_id,source,configured,loaded,run_id,task_id) VALUES(?,?,?,0,1,?,?)",
                    (task.owner, skill, "runtime", task.run_id, task.id))
            else:
                self.database.execute("UPDATE agent_skills SET loaded=0 WHERE run_id=? AND task_id=? AND skill_id=?",
                                      (task.run_id, task.id, skill))
            self.events.emit(Event("skill_loaded" if loaded else "skill_unloaded", task.run_id, task.owner,
                                   task.id, {"skill": skill}))

    def _record_attempt(self, task: Task, receipt: Receipt) -> None:
        self.receipts.save(receipt)
        usage = receipt.token_usage
        source = str(usage.get("source", "estimated" if usage.get("estimated", True) else "measured"))
        if task.kind is TaskKind.AGENT:
            self._provider_metric_attempts += 1
            measured = (
                source == "measured"
                and isinstance(usage.get("provider_tool_calls"), int)
                and isinstance(usage.get("provider_messages"), int)
            )
            self._provider_metrics_complete = self._provider_metrics_complete and measured
            if measured:
                self._measured_total_tokens += int(usage.get("input", 0)) + int(usage.get("output", 0))
                self._measured_cached_tokens += int(usage.get("cached", 0))
                self._provider_tool_calls += int(usage["provider_tool_calls"])
                self._provider_messages += int(usage["provider_messages"])
                self._provider_duration_seconds += max(0.0, float(receipt.duration_seconds))
        # Invocation count is first-class: a run's cost is not only tokens, and
        # not every provider reports tokens at all.
        invocations = int(usage.get("invocation_count", 1 if task.kind is TaskKind.AGENT else 0))
        self.database.execute(
            "INSERT INTO token_usage(run_id,task_id,agent,input_tokens,output_tokens,estimated,cached_tokens,"
            "token_source,provider,invocation_count) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (task.run_id, task.id, task.owner, int(usage.get("input", 0)), int(usage.get("output", 0)),
             int(source == "estimated"), int(usage.get("cached", 0)), source,
             str(task.metadata.get("provider", self.provider_name)), invocations),
        )
        self.performance.record(task, receipt)
        self.events.emit(Event("receipt_created", task.run_id, task.owner, task.id,
                               {"token_source": source, "retry_count": receipt.retry_count,
                                "invocation_count": invocations}))

    @asynccontextmanager
    async def _model_slot(self, model_class: str):
        if model_class in {"strong", "strongest"}:
            async with self.strong_parallel:
                yield
        else:
            yield

    def _persist(self, task: Task) -> None:
        self.database.execute("UPDATE tasks SET status=?,data_json=? WHERE id=?",
                              (task.status.value, self.database.json(task.to_dict()), task.id))
