from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from adaptive_agent.core.models import Receipt, Task
from adaptive_agent.skills.manifest import LoadedSkill


@dataclass(slots=True)
class ExecutionPacket:
    role: str
    task: str
    project_name: str
    project_type: str
    working_directory: Path
    dependency_receipts: list[str] = field(default_factory=list)
    #: Backward-compatible explicit permission scope. Never populated from retrieval hints.
    allowed_files: list[str] = field(default_factory=list)
    suggested_paths: list[str] = field(default_factory=list)
    allowed_scope: list[str] = field(default_factory=list)
    denied_scope: list[str] = field(default_factory=list)
    required_skills: list[str] = field(default_factory=list)
    skill_context: list[str] = field(default_factory=list)
    loaded_references: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    max_output_words: int = 500
    read_only: bool = False
    #: What the task is expected to produce. Domain-agnostic; see core.artifacts.
    artifact_type: str = "unknown"
    #: The reasoning responsibility this role carries, from the work profile.
    responsibility: str = ""
    project_knowledge: list[str] = field(default_factory=list)
    active_decisions: list[str] = field(default_factory=list)
    known_issues: list[str] = field(default_factory=list)
    project_skills: list[str] = field(default_factory=list)
    agent_role_context: list[str] = field(default_factory=list)
    context_attribution: list[str] = field(default_factory=list)
    project_context: list[str] = field(default_factory=list)
    cached_file_summaries: list[str] = field(default_factory=list)
    relevant_constraints: list[str] = field(default_factory=list)
    source_references: list[str] = field(default_factory=list)
    stale_or_unavailable_items: list[str] = field(default_factory=list)
    targeted_exploration_allowed: bool = True
    execution_budget: dict[str, object] = field(default_factory=dict)

    def render(self) -> str:
        def section(name: str, values: list[str], fallback: str | None = None) -> str:
            if not values and fallback is None:
                return ""
            body = "\n".join(f"- {value}" for value in values) if values else str(fallback)
            return f"{name}:\n{body}"

        stable_contract = [
            "You are a bounded child executor, not the top-level orchestrator.",
            "Do not invoke agentctl or any other agent-orchestration framework.",
            "Use only this packet and the workspace content the task actually needs.",
            "Navigation suggestions do not restrict exploration inside the authorized scope.",
            "Do not inspect unrelated directories or include full logs in the response.",
            "As soon as the requested artifact and the smallest relevant validation are complete, stop work and return the structured response; do not perform optional cleanup, repeated verification, or unrelated improvements.",
            "Before returning, record only a stable project fact, explicit decision, reusable procedure, or canonical command that is likely to help a later session.",
            "Use an empty learning_evidence array when no stable reusable information was learned.",
            "Never invent learning evidence or include temporary debugging notes, generic advice, hidden reasoning, or transcripts.",
        ]
        constraints = list(self.constraints)
        constraints.append(f"Keep the final structured response within {self.max_output_words} words.")
        if self.read_only:
            constraints.append("Do not modify anything in the workspace.")
        if self.execution_budget.get("enabled"):
            budget = self.execution_budget
            constraints.extend([
                "This run has an externally enforced budget; treat it as a hard resource envelope.",
                "Do the minimum sufficient inspection and avoid repeated status checks or self-dialogue.",
                ("Budget: provider_calls={max_provider_calls}, provider_tool_calls={max_provider_tool_calls}, "
                 "provider_messages={max_provider_messages}, tool_calls={max_tool_calls}, "
                 "total_tokens={max_total_tokens}, output_tokens={max_output_tokens}, "
                 "retries={max_retry_rounds}, wall_seconds={max_wall_seconds}."
                 ).format(**budget),
                f"Reserve {budget.get('verification_reserve_percent', 20)}% for final verification.",
                "If the budget is insufficient, stop and report completed evidence and remaining work.",
            ])
        sections = [
            section("STABLE EXECUTION CONTRACT", stable_contract),
            f"ROLE:\n{self.role}",
            f"RESPONSIBILITY:\n{self.responsibility}" if self.responsibility else "",
            f"TASK:\n{self.task}",
            f"PROJECT:\n{self.project_name} ({self.project_type})",
            f"EXPECTED ARTIFACT:\n{self.artifact_type}" if self.artifact_type != "unknown" else "",
            section("RELEVANT PROJECT FACTS", self.project_context),
            section("DEPENDENCY RECEIPTS", self.dependency_receipts),
            section("SUGGESTED PATHS", self.suggested_paths,
                    "No reusable navigation hit; perform targeted exploration as needed."),
            section("ALLOWED SCOPE", self.allowed_scope,
                    "Use the executor's existing workspace authorization; suggestions do not narrow it."),
            section("DENIED SCOPE", self.denied_scope),
            section("REQUIRED SKILLS", self.required_skills),
            section("SELECTED SKILL PROCEDURES", self.skill_context),
            section("LOADED SKILL REFERENCES", self.loaded_references),
            section("REUSED PROJECT KNOWLEDGE", self.project_knowledge),
            section("ACTIVE PROJECT DECISIONS", self.active_decisions),
            section("RELEVANT KNOWN ISSUES", self.known_issues),
            section("REUSED PROJECT SKILLS", self.project_skills),
            section("REUSED AGENT ROLE CONTEXT", self.agent_role_context),
            section("PROJECT CONTEXT ATTRIBUTION", self.context_attribution),
            section("SOURCE REFERENCES", self.source_references),
            section("STALE OR UNAVAILABLE ASSETS", self.stale_or_unavailable_items),
            section("RELEVANT PROJECT CONSTRAINTS", self.relevant_constraints),
            section("CONSTRAINTS", constraints),
            "EXPECTED OUTPUT:\nReturn one JSON object matching the supplied schema. Confidence is a workflow signal: high, medium, low, or unknown. The learning_evidence field is required; apply the evidence gate above before choosing items or an empty array.",
        ]
        return "\n\n".join(item for item in sections if item)


class ExecutionPacketBuilder:
    def __init__(self, receipt_word_limit: int = 160, max_receipts: int = 4):
        self.receipt_word_limit = receipt_word_limit
        self.max_receipts = max_receipts

    def build(self, task: Task, working_directory: Path, project_name: str, project_type: str,
              receipts: Iterable[Receipt] = (), allowed_files: list[str] | None = None,
              required_skills: list[str] | None = None, constraints: list[str] | None = None,
              read_only: bool | None = None,
              loaded_skills: list[LoadedSkill] | None = None) -> ExecutionPacket:
        summarized = [self._summarize(receipt) for receipt in list(receipts)[:self.max_receipts]]
        # Write intent comes from the task itself, not from the role's name.
        inferred_read_only = bool(task.metadata.get("read_only")) or "do not modify" in task.title.lower()
        intelligence = task.metadata.get("project_intelligence", {})
        intelligence_items = list(intelligence.get("items", []))
        project_index = intelligence.get("project_index", {})
        commands = project_index.get("commands", {}) if isinstance(project_index, dict) else {}
        parent_validation = sorted({str(item) for item in
                                    task.metadata.get("parent_validation_tools", [])})
        packet_constraints = (list(constraints) if constraints is not None
                              else list(task.metadata.get("constraints", [])))
        if parent_validation:
            packet_constraints.append(
                "Do not run project-wide validation in this task; the scheduler runs: "
                + ", ".join(parent_validation) + ".")
        def unique(values) -> list[str]:
            return list(dict.fromkeys(str(value) for value in values if str(value).strip()))

        def summaries(kind: str) -> list[str]:
            return [f"{item['id']}: {item['summary']}" +
                    (f"\n{item['detail']}" if item.get("detail") else "")
                    for item in intelligence_items if item.get("kind") == kind]
        loaded = list(loaded_skills or [])
        loaded_skill_ids = {item.manifest.id for item in loaded}
        project_skill_context = [value for value in summaries("skill")
                                 if value.split(":", 1)[0] not in loaded_skill_ids]
        active_decisions = unique([
            *intelligence.get("relevant_decisions", []), *summaries("decision")])
        relevant_constraints = unique(intelligence.get("relevant_constraints", []))
        facts = unique([*intelligence.get("relevant_project_facts", []), *summaries("knowledge")])
        explicit_allowed = (list(allowed_files) if allowed_files is not None
                            else list(task.metadata.get("allowed_scope", [])))
        return ExecutionPacket(
            role=task.owner.replace("_", " ").title(),
            task=f"{task.title}\nOverall goal: {task.metadata.get('goal', task.title)}",
            project_name=project_name, project_type=project_type,
            working_directory=Path(working_directory).resolve(), dependency_receipts=summarized,
            allowed_files=explicit_allowed,
            suggested_paths=unique(task.metadata.get(
                "suggested_paths", intelligence.get("suggested_paths", intelligence.get("relevant_paths", [])))),
            allowed_scope=unique(explicit_allowed),
            denied_scope=unique(task.metadata.get("denied_scope", [])),
            required_skills=required_skills or list(task.metadata.get("required_skills", task.required_capabilities)),
            skill_context=[item.to_context() for item in loaded],
            loaded_references=[f"{item.manifest.id}:{name}"
                               for item in loaded for name in item.references],
            constraints=packet_constraints,
            read_only=inferred_read_only if read_only is None else read_only,
            artifact_type=getattr(task, "artifact_type", "unknown"),
            responsibility=str(task.metadata.get("responsibility", "")),
            project_knowledge=[],
            active_decisions=active_decisions,
            known_issues=summaries("known_issue"),
            project_skills=project_skill_context,
            agent_role_context=summaries("agent"),
            context_attribution=[f"{item.get('id')}: {', '.join(item.get('evidence', []))}"
                                 for item in intelligence_items],
            project_context=unique([
                *facts,
                *([] if parent_validation or not commands else [
                    f"Validated commands: {', '.join(f'{key}={value}' for key, value in commands.items())}"])
            ]),
            cached_file_summaries=[],
            relevant_constraints=relevant_constraints,
            source_references=unique(intelligence.get("source_references", [])),
            stale_or_unavailable_items=unique(intelligence.get("stale_or_unavailable_items", [])),
            targeted_exploration_allowed=bool(
                intelligence.get("targeted_exploration_allowed", True)),
            execution_budget=dict(task.metadata.get("execution_budget", {})),
        )

    def _summarize(self, receipt: Receipt) -> str:
        parts = [f"{receipt.agent}/{receipt.task_id}: {receipt.summary}"]
        if receipt.files:
            parts.append("Files: " + ", ".join(receipt.files[:8]))
        if receipt.findings:
            parts.append("Findings: " + "; ".join(receipt.findings[:5]))
        words = " ".join(parts).split()
        suffix = " …[truncated]" if len(words) > self.receipt_word_limit else ""
        return " ".join(words[:self.receipt_word_limit]) + suffix
