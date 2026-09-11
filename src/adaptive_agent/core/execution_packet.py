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
    allowed_files: list[str] = field(default_factory=list)
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

    def render(self) -> str:
        def section(name: str, values: list[str], fallback: str = "None") -> str:
            body = "\n".join(f"- {value}" for value in values) if values else fallback
            return f"{name}:\n{body}"

        constraints = list(self.constraints)
        constraints.extend([
            "You are a bounded child executor, not the top-level orchestrator.",
            "Do not invoke agentctl or any other agent-orchestration framework.",
            "Use only this packet and the workspace content the task actually needs.",
            "Do not inspect unrelated directories or include full logs in the response.",
            f"Keep the final structured response within {self.max_output_words} words.",
            "Before returning, record only a stable project fact, explicit decision, reusable procedure, or canonical command that is likely to help a later session.",
            "Use an empty learning_evidence array when no stable reusable information was learned.",
            "Never invent learning evidence or include temporary debugging notes, generic advice, hidden reasoning, or transcripts.",
        ])
        if self.read_only:
            constraints.append("Do not modify anything in the workspace.")
        sections = [
            f"ROLE:\n{self.role}",
            f"RESPONSIBILITY:\n{self.responsibility}" if self.responsibility else "",
            f"TASK:\n{self.task}",
            f"PROJECT:\n{self.project_name} ({self.project_type})",
            f"EXPECTED ARTIFACT:\n{self.artifact_type}" if self.artifact_type != "unknown" else "",
            section("COMPACT PROJECT INDEX", self.project_context),
            section("VALID CACHED FILE SUMMARIES", self.cached_file_summaries),
            section("DEPENDENCY RECEIPTS", self.dependency_receipts),
            section("ALLOWED SCOPE", self.allowed_files, "Minimize the workspace scope required by the task."),
            section("REQUIRED SKILLS", self.required_skills),
            section("SELECTED SKILL PROCEDURES", self.skill_context),
            section("LOADED SKILL REFERENCES", self.loaded_references),
            section("REUSED PROJECT KNOWLEDGE", self.project_knowledge),
            section("ACTIVE PROJECT DECISIONS", self.active_decisions),
            section("RELEVANT KNOWN ISSUES", self.known_issues),
            section("REUSED PROJECT SKILLS", self.project_skills),
            section("REUSED AGENT ROLE CONTEXT", self.agent_role_context),
            section("PROJECT CONTEXT ATTRIBUTION", self.context_attribution),
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
        architecture = project_index.get("architecture", {}) if isinstance(project_index, dict) else {}
        commands = project_index.get("commands", {}) if isinstance(project_index, dict) else {}
        important_paths = project_index.get("important_paths", {}) if isinstance(project_index, dict) else {}
        def summaries(kind: str) -> list[str]:
            return [f"{item['id']}: {item['summary']}" +
                    (f"\n{item['detail']}" if item.get("detail") else "")
                    for item in intelligence_items if item.get("kind") == kind]
        return ExecutionPacket(
            role=task.owner.replace("_", " ").title(),
            task=f"{task.title}\nOverall goal: {task.metadata.get('goal', task.title)}",
            project_name=project_name, project_type=project_type,
            working_directory=Path(working_directory).resolve(), dependency_receipts=summarized,
            allowed_files=allowed_files or list(task.metadata.get("allowed_files", [])),
            required_skills=required_skills or list(task.metadata.get("required_skills", task.required_capabilities)),
            skill_context=[item.to_context() for item in (loaded_skills or [])],
            loaded_references=[f"{item.manifest.id}:{name}"
                               for item in (loaded_skills or []) for name in item.references],
            constraints=constraints or list(task.metadata.get("constraints", [])),
            read_only=inferred_read_only if read_only is None else read_only,
            artifact_type=getattr(task, "artifact_type", "unknown"),
            responsibility=str(task.metadata.get("responsibility", "")),
            project_knowledge=summaries("knowledge"),
            active_decisions=summaries("decision"),
            known_issues=summaries("known_issue"),
            project_skills=summaries("skill"),
            agent_role_context=summaries("agent"),
            context_attribution=[f"{item.get('id')}: {', '.join(item.get('evidence', []))}"
                                 for item in intelligence_items],
            project_context=[
                f"Architecture: {', '.join(f'{key}={value}' for key, value in architecture.items()) or 'unknown'}",
                f"Important paths: {', '.join(f'{key}={value}' for key, value in important_paths.items()) or 'none'}",
                f"Validated commands: {', '.join(f'{key}={value}' for key, value in commands.items()) or 'none'}",
            ] if project_index else [],
            cached_file_summaries=[
                f"{item.get('path')}: {item.get('summary')}"
                for item in intelligence.get("cached_files", [])
            ],
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
