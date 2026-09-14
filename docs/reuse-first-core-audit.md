# Reuse-First Core — Baseline Data Flow Audit

Baseline: `feature/v2.3.1-adaptive-budget-v0` at `f976f9b`.

## Current flow

```text
original goal + project signals + explicit constraints/approvals
  -> GoalAnalyzer (classification and recommendations)
  -> ProjectContextIndex.select (index + relevant_paths + valid file summaries)
  -> optional legacy ProjectIntelligenceStore.select
  -> SkillResolver / ExecutionPlanner / TeamComposer / UniversalPlanner
  -> provider and model routing
  -> task metadata
  -> ExecutionPacketBuilder (independently decomposes metadata again)
  -> provider -> Receipt
  -> ArtifactEvaluator / project-command acceptance
  -> file cache + stable index update + optional legacy intelligence distillation
```

## Boundary defects found

1. `ProjectContextIndex.select` returns retrieval hints as `relevant_paths`, and Orchestrator copies
   them into `task.metadata.allowed_files`. Navigation is therefore represented as permission.
2. Compact-index `constraints` and `decisions` are persisted but omitted from the normal
   `ExecutionPacket`; only architecture, important paths, and commands are rendered.
3. `ExecutionPacketBuilder` reconstructs context from raw dictionaries, so selection and packet
   assembly do not share one explicit asset-selection contract.
4. The configured `Orchestrator.execution_budget` is replaced after a REDUCED decision. A later
   NORMAL run on the same instance can inherit the reduced value.
5. Runs without artifact evaluation are passed to legacy intelligence history as successful
   evaluation (`evaluation_passed=success`), which conflates provider completion and verification.
6. Required document sections are searched in provider summary/findings rather than the actual
   declared file content.
7. A corrupt compact index is rebuilt safely, but its fallback/reuse state and stale/unavailable
   assets are not expressed as a single packet-facing selection result.

## Minimal refactor boundary

```text
ProjectContextIndex.select
  -> ProjectContext selection
       suggested_paths                  navigation only
       relevant_project_facts           reusable facts
       relevant_constraints             explicit/project policy
       relevant_decisions               approved decisions
       selected_skills/references        one skill-selection input
       source_references                 provenance
       stale_or_unavailable_items        targeted revalidation cues
  -> Orchestrator attaches selection + separate allowed_scope
  -> ExecutionPacketBuilder renders that selection once
  -> existing Provider / Scheduler
  -> separate completion, artifact, and acceptance outcomes
  -> bounded evidence-backed index update
```

`allowed_scope` will come only from explicit constraints or a migrated legacy permission marker;
`suggested_paths` will never narrow it. Missing/stale retrieval context will permit targeted
exploration inside the existing authorized scope. Safety-policy parse failures will not expand
scope.

Adaptive Budget remains opt-in. Each composition will derive an effective run-local budget from
the immutable configured/base budget. Multi-agent composition and Skill/Agent synthesis remain
optional paths and receive no new default AI invocation.
