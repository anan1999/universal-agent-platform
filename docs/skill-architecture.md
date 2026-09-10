# Skill architecture

V2.2 treats a Skill as a versioned, reusable procedure—not as an Agent and not as a provider.
The execution planner follows this order: deterministic tool, reusable Skill, existing reasoning
role, synthesized temporary Skill, and finally a temporary specialist when the work truly needs
an independent reasoning responsibility.

## Package contract

A package is a directory containing `skill.json` and `SKILL.md`. The manifest indexes identity,
version, capabilities, input/output contracts, dependencies, tools, references, evaluation,
security, provenance, trust, lifecycle status, portability, and estimated context cost. Supporting
material may live under `references/` and `examples/`.

Discovery reads manifests only. At task execution, the registry loads `SKILL.md` and only the
reference names selected for that task. The exact Skill version, selected references, and context
estimate are saved in `run_skills`; outcome and attribution are saved in `skill_runs`.

Discovery is provider-independent and ordered: built-in package resources, trusted global Skills
in `$UNIVERSAL_AGENT_HOME/skills`, then project-local Skills in `.agent/skills`. A later source may
replace the same identifier for the current resolution view, but it does not overwrite files or
historical version records.

## Resolution and execution

`SkillResolver` scores candidates deterministically from capability match, trust, portability,
quality history, artifact quality, dependency/provider penalties, and context cost. It records
positive and rejection reasons. Provider selection remains a separate step.

`ExecutionPlanner` chooses one of: `tool_only`, `single_agent`, `single_agent_with_tools`,
`multi_agent_parallel`, `multi_agent_dag`, `human_approval`, or `artifact_only`. Team composition
is invoked only for genuinely multi-role plans. Deterministic validation is attached as a tool;
it is not inflated into a reviewer Agent.

## Compatibility

V2.1 YAML Skill declarations are adapted to manifests at runtime. This preserves existing
profiles and projects while allowing new package-based Skills. No core module imports a specific
provider to resolve Skills.

