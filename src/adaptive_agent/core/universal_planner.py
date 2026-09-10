"""Universal planner: TeamPlan -> Task DAG.

DAG depth follows the assessed complexity, not a fixed template. A trivial goal
gets one node. A critical goal gets specialists, evaluation, and an approval
gate. Nothing here knows what domain the work belongs to.
"""

from __future__ import annotations

from adaptive_agent.core.capabilities import Complexity
from adaptive_agent.core.evaluation import EvaluationKind
from adaptive_agent.core.execution_planner import ExecutionPlan, ExecutionStrategy
from adaptive_agent.core.goal_analyzer import GoalAnalysis
from adaptive_agent.core.models import Task, TaskKind
from adaptive_agent.core.team_composer import TeamPlan
from adaptive_agent.tasks.graph import TaskGraph


class UniversalPlanner:
    def plan(self, run_id: str, goal: str, analysis: GoalAnalysis, team: TeamPlan,
             execution: ExecutionPlan | None = None) -> TaskGraph:
        prefix = run_id.replace("RUN-", "")[:6]
        sequence = 0
        tasks: list[Task] = []

        def add(title: str, owner: str, capabilities: list[str], kind: TaskKind,
                dependencies: list[str], priority: int, **metadata) -> Task:
            nonlocal sequence
            sequence += 1
            task = Task(f"TASK-{prefix}-{sequence:02d}", run_id, title, owner,
                        list(capabilities), list(dependencies), priority, kind=kind)
            task.metadata.update({
                "goal": goal,
                "task_type": capabilities[0] if capabilities else "unknown",
                "risk": analysis.risk.value,
                "complexity": analysis.complexity.value,
                "work_profiles": list(analysis.profiles),
                "capability_signature": analysis.capability_signature,
                "read_only": analysis.read_only,
                **metadata,
            })
            tasks.append(task)
            return task

        if execution and execution.strategy is ExecutionStrategy.TOOL_ONLY:
            for tool in execution.tools:
                task = add(f"Run deterministic tool: {tool}", tool, analysis.capabilities,
                           TaskKind.TOOL, [], 90, tool=tool, required_skills=[],
                           execution_strategy=execution.strategy.value)
                task.artifact_type = "test_result"
            return TaskGraph(tasks)
        if execution and execution.strategy is ExecutionStrategy.HUMAN_APPROVAL:
            for gate in team.approval_gates or analysis.approval_gates:
                add(f"Human approval required: {gate.replace('_', ' ')}", "human", ["approval"],
                    TaskKind.APPROVAL, [], 90, approval_gate=gate, required_skills=[],
                    execution_strategy=execution.strategy.value)
            return TaskGraph(tasks)
        if execution and execution.strategy is ExecutionStrategy.ARTIFACT_ONLY:
            add(goal, "artifact", analysis.capabilities, TaskKind.ARTIFACT, [], 90,
                execution_strategy=execution.strategy.value)
            return TaskGraph(tasks)

        # 1. Agent tasks, ordered by the stage each role declares.
        agent_tasks: list[Task] = []
        previous: list[str] = []
        producers: list[str] = []
        for member in [item for item in team.members if not item.evaluative]:
            task = add(self._title(member, goal), member.role_id, member.capabilities,
                       TaskKind.AGENT, previous, 90 - member.stage // 2,
                       required_skills=list(member.skills), work_profile=member.profile,
                       execution_strategy=(execution.strategy.value if execution else "multi_agent_dag"),
                       role_origin=member.origin, responsibility=member.responsibility,
                       read_only=analysis.read_only or member.read_only)
            task.artifact_type = self._artifact_for(analysis, member.capabilities)
            agent_tasks.append(task)
            producers.append(task.id)
            previous = [task.id]

        if not agent_tasks:
            fallback = add(goal, "analyst", analysis.capabilities or ["goal_analysis"],
                           TaskKind.AGENT, [], 90, required_skills=[],
                           work_profile=(analysis.profiles or ["general"])[0],
                           responsibility="Carry the goal end to end.")
            agent_tasks.append(fallback)
            producers.append(fallback.id)

        # 2. Deterministic tool tasks — cheaper and more reliable than an agent.
        tool_tasks: list[str] = []
        if analysis.complexity is not Complexity.TRIVIAL:
            for strategy in team.evaluation:
                if strategy.kind is EvaluationKind.DETERMINISTIC and strategy.tool:
                    task = add(f"Evaluate: {strategy.name}", strategy.tool, strategy.capabilities,
                               TaskKind.TOOL, producers, 40, tool=strategy.tool,
                               evaluation_strategy=strategy.id, required_skills=[])
                    task.artifact_type = "test_result"
                    tool_tasks.append(task.id)

        # 3. Evaluating agent roles.
        review_dependencies = producers + tool_tasks
        review_tasks: list[str] = []
        agent_reviews = {strategy.id for strategy in team.evaluation
                         if strategy.kind is EvaluationKind.AGENT_REVIEW}
        for member in [item for item in team.members if item.evaluative]:
            task = add(f"{member.name}: {member.responsibility or 'review the result'}",
                       member.role_id, member.capabilities, TaskKind.AGENT,
                       review_dependencies, 20, required_skills=list(member.skills),
                       work_profile=member.profile, read_only=True,
                       responsibility=member.responsibility,
                       context_receipts=review_dependencies,
                       evaluation_strategies=sorted(agent_reviews))
            task.artifact_type = "report"
            review_tasks.append(task.id)

        # 4. Human approval gates, always last and always blocking.
        for gate in team.approval_gates:
            task = add(f"Human approval required: {gate.replace('_', ' ')}", "human",
                       ["approval"], TaskKind.APPROVAL,
                       review_tasks or review_dependencies, 10, approval_gate=gate,
                       required_skills=[])
            task.artifact_type = "unknown"

        return TaskGraph(tasks)

    def _title(self, member, goal: str) -> str:
        if member.origin == "temporary_specialist":
            return f"{member.name}: {member.responsibility}"
        verb = member.responsibility.rstrip(".") if member.responsibility else member.name
        return f"{member.name}: {verb}"

    def _artifact_for(self, analysis: GoalAnalysis, capabilities: list[str]) -> str:
        overlap = [kind for kind in analysis.artifact_types if kind != "unknown"]
        return overlap[0] if overlap else "unknown"
