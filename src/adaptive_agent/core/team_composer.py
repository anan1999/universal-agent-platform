"""Team Composer.

Decides *what reasoning responsibilities the goal needs*. It never chooses a
provider or a model — that is the router's job, one layer down. The output is a
`TeamPlan` with an explicit rationale and an explicit list of roles that were
deliberately omitted, which presentation clients can render as "Why this team?".

The objective is the minimum sufficient team, not the largest possible one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from adaptive_agent.core.capabilities import Complexity, Level, Requirement, Risk, normalize, signature
from adaptive_agent.core.capability_resolver import CapabilityResolver, ResolutionPlan, Strategy
from adaptive_agent.core.evaluation import EvaluationRegistry, EvaluationStrategy
from adaptive_agent.core.goal_analyzer import GoalAnalysis
from adaptive_agent.core.consumption import ConsumptionPolicy, consumption_policy
from adaptive_agent.profiles.registry import ProfileRole, WorkProfileRegistry


@dataclass(slots=True)
class TeamMember:
    role_id: str
    name: str
    responsibility: str
    capabilities: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    profile: str = ""
    stage: int = 50
    evaluative: bool = False
    read_only: bool = False
    #: How this member came to exist: profile_role | temporary_specialist
    origin: str = "profile_role"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"role_id": self.role_id, "name": self.name, "responsibility": self.responsibility,
                "capabilities": list(self.capabilities), "skills": list(self.skills),
                "profile": self.profile, "stage": self.stage, "evaluative": self.evaluative,
                "read_only": self.read_only, "origin": self.origin, "reason": self.reason}


@dataclass(slots=True)
class TeamPlan:
    members: list[TeamMember] = field(default_factory=list)
    complexity: Complexity = Complexity.NORMAL
    risk: Risk = Risk.LOW
    profiles: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    omitted: list[dict[str, str]] = field(default_factory=list)
    evaluation: list[EvaluationStrategy] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    approval_gates: list[str] = field(default_factory=list)
    resolutions: ResolutionPlan = field(default_factory=ResolutionPlan)
    consumption_mode: str = "balanced"

    @property
    def capability_signature(self) -> str:
        return signature(self.capabilities)

    def to_dict(self) -> dict[str, Any]:
        return {"members": [item.to_dict() for item in self.members],
                "complexity": self.complexity.value, "risk": self.risk.value,
                "profiles": list(self.profiles), "capabilities": list(self.capabilities),
                "capability_signature": self.capability_signature,
                "rationale": list(self.rationale), "omitted": list(self.omitted),
                "evaluation": [item.to_dict() for item in self.evaluation],
                "tools": list(self.tools), "approval_gates": list(self.approval_gates),
                "resolutions": self.resolutions.to_dict(),
                "consumption_mode": self.consumption_mode}


class TeamComposer:
    def __init__(self, profiles: WorkProfileRegistry,
                 evaluations: EvaluationRegistry | None = None,
                 policy: ConsumptionPolicy | None = None):
        self.profiles = profiles
        self.evaluations = evaluations or EvaluationRegistry()
        self.policy = policy or consumption_policy()

    def compose(self, analysis: GoalAnalysis, resolver: CapabilityResolver | None = None,
                run_id: str = "", constraints: Sequence[str] = ()) -> TeamPlan:
        wanted = {normalize(item) for item in analysis.capabilities}
        candidates = self.profiles.roles(analysis.profiles)
        rationale: list[str] = []
        omitted: list[dict[str, str]] = []
        rationale.append(f"Consumption policy: {self.policy.mode.value}.")

        if analysis.inferred:
            rationale.append("The goal matched no known domain, so the team was composed from "
                             "generic capabilities rather than rejected.")
        rationale.append("Goal requires: " + (", ".join(sorted(wanted)[:8]) or "general analysis") + ".")
        rationale.append(f"Assessed {analysis.complexity.value} complexity and {analysis.risk.value} risk "
                         f"across {len(analysis.profiles)} active profile(s): "
                         f"{', '.join(analysis.profiles)}.")

        scored = self._score_roles(candidates, wanted)
        selected, omitted = self._select(scored, analysis, omitted, rationale)

        members = [self._member(role, overlap, wanted) for role, overlap in selected]
        resolutions = ResolutionPlan()
        covered = {capability for member in members for capability in member.capabilities}
        uncovered = sorted(wanted - covered)

        if resolver is not None and uncovered:
            resolutions = resolver.resolve_all(uncovered, run_id)
            members.extend(self._from_resolutions(resolutions, analysis))
            rationale.append(self._resolution_summary(resolutions, uncovered))
        elif uncovered:
            rationale.append("Uncovered capabilities carried by the existing team: "
                             + ", ".join(uncovered[:6]) + ".")

        members = self._enforce_budget(members, analysis, omitted)
        engaged = self._engaged_profiles(analysis, members)
        evaluation = self._evaluation(analysis, members, omitted, rationale, engaged)
        tools = self._tools(analysis, resolutions, engaged)
        gates = sorted(set(analysis.approval_gates) & set(self._profile_gates(analysis.profiles))
                       | {gate for gate in analysis.approval_gates if gate in constraints})

        if gates:
            rationale.append("Approval gate(s) inserted: " + ", ".join(gates) + ".")

        return TeamPlan(members=sorted(members, key=lambda item: (item.stage, item.role_id)),
                        complexity=analysis.complexity, risk=analysis.risk,
                        profiles=list(analysis.profiles), capabilities=sorted(wanted),
                        rationale=rationale, omitted=omitted, evaluation=evaluation,
                        tools=tools, approval_gates=gates, resolutions=resolutions,
                        consumption_mode=self.policy.mode.value)

    # -- selection ---------------------------------------------------------

    def _score_roles(self, roles: Iterable[ProfileRole], wanted: set[str]) -> list[tuple[ProfileRole, set[str]]]:
        scored = [(role, wanted & set(role.capabilities)) for role in roles]
        return sorted(scored, key=lambda item: (-len(item[1]), item[0].stage, item[0].id))

    def _select(self, scored: list[tuple[ProfileRole, set[str]]], analysis: GoalAnalysis,
                omitted: list[dict[str, str]], rationale: list[str]
                ) -> tuple[list[tuple[ProfileRole, set[str]]], list[dict[str, str]]]:
        matched = [(role, overlap) for role, overlap in scored if overlap]
        unmatched = [role for role, overlap in scored if not overlap]

        if not matched:
            fallback: list[tuple[ProfileRole, set[str]]] = [(role, set()) for role, _ in scored[:1]]
            carrier = {role.id for role, _ in fallback}
            for role in unmatched:
                if role.id not in carrier:
                    omitted.append({"role": role.name, "reason": "no capability the goal asked for"})
            if fallback:
                rationale.append(f"No profile role matched the goal directly; "
                                 f"{fallback[0][0].name} carries the work.")
            return fallback, omitted

        for role in unmatched:
            omitted.append({"role": role.name, "reason": "no capability the goal asked for"})

        if analysis.read_only:
            writers = [(role, overlap) for role, overlap in matched if not role.read_only]
            readers = [(role, overlap) for role, overlap in matched if role.read_only]
            if readers:
                for role, _ in writers:
                    omitted.append({"role": role.name, "reason": "the goal is read-only"})
                rationale.append("Goal is read-only, so only non-modifying roles were selected.")
                matched = readers

        limit = self.policy.team_limit(analysis.complexity.max_team_size, analysis.risk)
        essential = [(role, overlap) for role, overlap in matched if not role.optional]
        optional = [(role, overlap) for role, overlap in matched if role.optional]

        if analysis.complexity.rank <= Complexity.SMALL.rank:
            for role, _ in optional:
                omitted.append({"role": role.name,
                                "reason": f"{analysis.complexity.value} work does not justify a separate role"})
            optional = []
            rationale.append(f"Kept the team minimal: {analysis.complexity.value} work needs at most "
                             f"{limit} reasoning role(s).")
        elif analysis.risk is Risk.LOW and analysis.complexity is Complexity.NORMAL:
            keep = optional[:1]
            for role, _ in optional[len(keep):]:
                omitted.append({"role": role.name, "reason": "low-risk work; one evaluation step is enough"})
            optional = keep

        selected = (essential + optional)[:limit]
        for role, _ in (essential + optional)[limit:]:
            omitted.append({"role": role.name, "reason": f"team capped at {limit} for {analysis.complexity.value} work"})
        return selected, omitted

    def _member(self, role: ProfileRole, overlap: set[str], wanted: set[str]) -> TeamMember:
        reason = (f"Covers {', '.join(sorted(overlap))}." if overlap
                  else "Closest available responsibility for this goal.")
        return TeamMember(role_id=role.id, name=role.name, responsibility=role.responsibility,
                          capabilities=sorted(overlap or set(role.capabilities)),
                          skills=list(role.skills), profile=role.profile, stage=role.stage,
                          evaluative=role.evaluative, read_only=role.read_only, reason=reason)

    def _from_resolutions(self, resolutions: ResolutionPlan, analysis: GoalAnalysis) -> list[TeamMember]:
        members = []
        for resolution in resolutions.by_strategy(Strategy.TEMPORARY_SPECIALIST):
            members.append(TeamMember(
                role_id=resolution.target,
                name=resolution.target.replace("_", " ").title(),
                responsibility=f"Temporary specialist for {resolution.capability}.",
                capabilities=[resolution.capability], profile="temporary", stage=45,
                origin="temporary_specialist", reason=resolution.reason))
        return members

    def _resolution_summary(self, resolutions: ResolutionPlan, uncovered: list[str]) -> str:
        parts = []
        for strategy, label in ((Strategy.ATTACH_SKILL, "attached existing skill"),
                                (Strategy.CREATE_SKILL, "created skill"),
                                (Strategy.DETERMINISTIC_TOOL, "used deterministic tool"),
                                (Strategy.EXISTING_AGENT, "reused existing agent"),
                                (Strategy.TEMPORARY_SPECIALIST, "created temporary specialist")):
            items = resolutions.by_strategy(strategy)
            if items:
                parts.append(f"{label} for {', '.join(sorted(item.capability for item in items))}")
        covered = "; ".join(parts) if parts else "no additional resolution needed"
        return f"Capabilities not covered by profile roles ({', '.join(uncovered[:6])}): {covered}."

    def _enforce_budget(self, members: list[TeamMember], analysis: GoalAnalysis,
                        omitted: list[dict[str, str]]) -> list[TeamMember]:
        limit = self.policy.team_limit(analysis.complexity.max_team_size, analysis.risk)
        if len(members) <= limit:
            return members
        ordered = sorted(members, key=lambda item: (item.evaluative, item.stage))
        for member in ordered[limit:]:
            omitted.append({"role": member.name,
                            "reason": f"team capped at {limit} for {analysis.complexity.value} work"})
        return ordered[:limit]

    # -- evaluation and tools ---------------------------------------------

    def _engaged_profiles(self, analysis: GoalAnalysis, members: list[TeamMember]) -> list[str]:
        """Profiles the goal actually drew on, not merely the ones the project activates.

        A Python repository activates software-engineering, but a UI/UX goal in that
        repository should not be validated by running the test suite. Only profiles
        that contributed a team member, or whose own capabilities the goal asked for,
        get to impose an evaluation step.
        """
        contributed = {member.profile for member in members if member.profile}
        engaged = [profile_id for profile_id in analysis.profiles if profile_id in contributed]
        wanted = {normalize(item) for item in analysis.capabilities}
        for profile_id in analysis.profiles:
            profile = self.profiles.get(profile_id)
            if profile_id not in engaged and profile and wanted & set(profile.capabilities):
                engaged.append(profile_id)
        return engaged or list(analysis.profiles)

    def _evaluation(self, analysis: GoalAnalysis, members: list[TeamMember],
                    omitted: list[dict[str, str]], rationale: list[str],
                    engaged: Sequence[str]) -> list[EvaluationStrategy]:
        skipped = [item for item in analysis.profiles if item not in engaged]
        if skipped:
            rationale.append(f"Evaluation drawn from {', '.join(engaged)} only; "
                             f"{', '.join(skipped)} "
                             f"{'is' if len(skipped) == 1 else 'are'} active for this project "
                             f"but the goal did not draw on {'it' if len(skipped) == 1 else 'them'}.")
        declared: list[str] = []
        for profile_id in engaged:
            profile = self.profiles.get(profile_id)
            if profile:
                declared.extend(profile.evaluation)
        strategies = self.evaluations.resolve(dict.fromkeys(declared))

        if analysis.read_only:
            rationale.append("Evaluation limited to goal coverage because the goal is read-only.")
            return [item for item in strategies if not item.blocking] or []
        if analysis.complexity is Complexity.TRIVIAL:
            for item in strategies:
                omitted.append({"role": item.name, "reason": "trivial work; evaluation not warranted"})
            rationale.append("No evaluation step: the work is trivial.")
            return []
        if analysis.risk is Risk.LOW and analysis.complexity.rank <= Complexity.SMALL.rank:
            kept = strategies[:1]
            for item in strategies[1:]:
                omitted.append({"role": item.name, "reason": "low-risk prototype; one check is sufficient"})
            return kept
        return strategies

    def _tools(self, analysis: GoalAnalysis, resolutions: ResolutionPlan,
               engaged: Sequence[str]) -> list[str]:
        tools = set(resolutions.tools)
        if not analysis.read_only:
            for profile_id in engaged:
                profile = self.profiles.get(profile_id)
                if profile:
                    tools.update(profile.tools)
        return sorted(tools)

    def _profile_gates(self, profile_ids: Sequence[str]) -> set[str]:
        gates: set[str] = set()
        for profile_id in profile_ids:
            profile = self.profiles.get(profile_id)
            if profile:
                gates.update(profile.approval_gates)
        return gates
