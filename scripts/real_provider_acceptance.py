"""Explicit, quota-consuming Codex acceptance for UAP V2.2.

This script is deliberately outside pytest. It uses temporary fixtures, a
Codex-only ProviderRegistry, and the normal Orchestrator -> Scheduler path.
Run it only with ``--execute`` because it performs three bounded successful AI
executions plus one invalid-model failure probe.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adaptive_agent import __version__
from adaptive_agent.core.escalation import EscalationManager, FailureKind
from adaptive_agent.core.execution_packet import ExecutionPacketBuilder
from adaptive_agent.core.models import Task, TaskKind
from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.profiles.registry import profile_registry
from adaptive_agent.providers.base import ProviderKind
from adaptive_agent.providers.codex import CodexErrorCode, CodexProvider
from adaptive_agent.providers.registry import ProviderDescriptor, ProviderRegistry
from adaptive_agent.runtime import RESOURCE_ROOT
from adaptive_agent.skills.manifest import SkillTrust
from adaptive_agent.skills.registry import SkillRegistry
from adaptive_agent.storage.database import Database


SIMPLE_GOAL = "Fix the arithmetic bug and validate the result by running the existing pytest tests."
SKILL_GOAL = (
    "For this small single-file W8A8 fixture, create validation_report.md that validates the "
    "metadata, separates measured evidence from unavailable runtime checks, and run the existing "
    "pytest test suite. Do not claim hardware execution."
)
SELECTED_REFERENCE = "metadata-contract"


class AcceptanceOrchestrator(Orchestrator):
    """Annotate acceptance contracts while retaining the production run path."""

    def __init__(self, *args: Any, required_artifacts: list[str], allowed_files: list[str],
                 generic: bool = False, forced_model: str | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.acceptance_artifacts = required_artifacts
        self.acceptance_files = allowed_files
        self.generic = generic
        self.forced_model = forced_model

    def plan(self, *args: Any, **kwargs: Any):
        composition = super().plan(*args, **kwargs)
        if self.generic and composition.execution_plan:
            composition.execution_plan.selected_skills = []
            composition.execution_plan.rejected_skills = []
            for member in composition.team.members:
                member.skills = []
        for task in composition.graph.tasks.values():
            if task.kind is not TaskKind.AGENT:
                continue
            if self.generic:
                task.metadata["required_skills"] = []
            task.metadata["required_artifacts"] = list(self.acceptance_artifacts)
            task.metadata["allowed_files"] = list(self.acceptance_files)
            if "w8a8-validation" in task.metadata.get("required_skills", []):
                task.metadata["skill_references"] = {
                    "w8a8-validation": [SELECTED_REFERENCE]
                }
            if self.forced_model:
                task.metadata["model"] = self.forced_model
                routing = task.metadata.get("routing")
                if isinstance(routing, dict):
                    routing["model"] = self.forced_model
                    routing.setdefault("reasons", []).append(
                        "Acceptance benchmark pins the model for a fair paired comparison."
                    )
        return composition


def write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def initialize_fixture(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    commands = {"commands": {"test": {"command": [sys.executable, "-m", "pytest", "-q"],
                                          "timeout": 90}}}
    write(path / ".agent" / "commands.yaml", yaml.safe_dump(commands, sort_keys=False))


def create_simple_fixture(path: Path) -> None:
    initialize_fixture(path)
    write(path / "calculator.py", "def add(a, b):\n    return a - b\n")
    write(path / "test_calculator.py",
          "from calculator import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    write(path / "pyproject.toml", "[project]\nname = 'uap-real-simple'\nversion = '0.0.0'\n")


def create_skill_fixture(path: Path) -> None:
    initialize_fixture(path)
    metadata = {
        "format": "fixture-only", "weights_dtype": "int8", "activations_dtype": "int8",
        "input": {"name": "input", "shape": [1, 4], "dtype": "int8", "scale": 0.125,
                  "zero_point": 0},
        "output": {"name": "output", "shape": [1, 2], "dtype": "int8", "scale": 0.25,
                   "zero_point": -3},
        "runtime": None,
    }
    write(path / "model_metadata.json", json.dumps(metadata, indent=2) + "\n")
    write(path / "test_validation_report.py", '''from pathlib import Path


def test_validation_report_contract():
    text = Path("validation_report.md").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "measured evidence" in lowered
    assert "unavailable checks" in lowered
    assert "conclusion" in lowered
    assert "int8" in lowered
    assert "hardware" in lowered or "runtime" in lowered
    assert "qnn execution: observed" not in lowered
''')
    write(path / "README.md",
          "This fixture contains static quantization metadata only. No model binary, runtime, "
          "device, or accelerator result is available.\n")
    write(path / "pyproject.toml", "[project]\nname = 'uap-real-skill'\nversion = '0.0.0'\n")


def codex_registry(timeout: float) -> ProviderRegistry:
    return ProviderRegistry([ProviderDescriptor(
        "codex", "Codex", ProviderKind.CLI,
        lambda **_: CodexProvider(timeout=timeout),
        notes="Only eligible provider in real acceptance.",
    )])


def json_field(row: dict[str, Any], field: str) -> dict[str, Any]:
    value = row.get(field, "{}")
    decoded = json.loads(value) if isinstance(value, str) else value
    return decoded if isinstance(decoded, dict) else {}


def collect_run(db: Database, run_id: str) -> dict[str, Any]:
    run = db.query("SELECT * FROM runs WHERE id=?", (run_id,))[0]
    tasks = db.query("SELECT * FROM tasks WHERE run_id=? ORDER BY priority DESC,id", (run_id,))
    task_data = [json_field(row, "data_json") for row in tasks]
    task_ids = [row["id"] for row in tasks]
    receipts = []
    for task_id in task_ids:
        receipts.extend(json_field(row, "data_json") for row in db.query(
            "SELECT data_json FROM receipts WHERE task_id=? ORDER BY id", (task_id,)))
    usage = db.query("SELECT * FROM token_usage WHERE run_id=? ORDER BY id", (run_id,))
    artifacts = db.query("SELECT * FROM artifact_evaluations WHERE run_id=? ORDER BY id", (run_id,))
    skills = db.query("SELECT * FROM run_skills WHERE run_id=? ORDER BY id", (run_id,))
    composition = json.loads(run.get("composition_json") or "{}")
    agent_receipts = [item for item in receipts if item.get("provider")]
    tool_tasks = [item for item in task_data if item.get("kind") == "tool"]
    models = sorted({str(item.get("model")) for item in agent_receipts if item.get("model")})
    sources = sorted({str(item.get("token_usage", {}).get("source", "unavailable"))
                      for item in agent_receipts})
    input_tokens = sum(int(item.get("token_usage", {}).get("input", 0)) for item in agent_receipts)
    cached = sum(int(item.get("token_usage", {}).get("cached", 0)) for item in agent_receipts)
    output_tokens = sum(int(item.get("token_usage", {}).get("output", 0)) for item in agent_receipts)
    return {
        "run_id": run_id, "status": run["status"], "composition": composition,
        "tasks": task_data, "receipts": receipts, "agent_receipts": agent_receipts,
        "usage_rows": usage, "artifact_rows": artifacts, "skill_rows": skills,
        "provider": sorted({str(item.get("provider")) for item in agent_receipts}),
        "models": models, "usage_sources": sources,
        "ai_invocations": sum(int(row.get("invocation_count", 0)) for row in usage),
        "input_tokens": input_tokens, "cached_tokens": cached,
        "non_cached_tokens": max(0, input_tokens - cached), "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "duration": sum(float(item.get("duration_seconds", 0)) for item in agent_receipts),
        "retries": sum(int(item.get("retry_count", 0)) for item in agent_receipts),
        "escalations": sum(int(bool(item.get("escalated"))) for item in agent_receipts),
        "execution_ids": [str(item.get("token_usage", {}).get("execution_id"))
                          for item in agent_receipts if item.get("token_usage", {}).get("execution_id")],
        "tool_tasks": tool_tasks,
    }


async def run_orchestration(db: Database, provider: CodexProvider, registry: ProviderRegistry,
                            workspace: Path, goal: str, artifacts: list[str], files: list[str],
                            *, generic: bool = False, forced_model: str | None = None) -> dict[str, Any]:
    orchestrator = AcceptanceOrchestrator(
        db, provider, provider_name="codex", providers=registry,
        profiles=profile_registry(refresh=True), provider_preference=("codex",),
        consumption_mode="economy", required_artifacts=artifacts,
        allowed_files=files, generic=generic, forced_model=forced_model,
    )
    run_id = await orchestrator.run_goal(
        goal, working_directory=str(workspace), project_name=workspace.name,
        project_type="python", project_signals=["pyproject.toml", ".git"],
        entry_source="real_provider_acceptance",
    )
    return collect_run(db, run_id)


def assert_real_run(result: dict[str, Any]) -> None:
    assert result["provider"] == ["codex"], f"unexpected providers: {result['provider']}"
    assert all(row.get("provider") != "mock" for row in result["usage_rows"])
    assert result["ai_invocations"] >= 1


def progressive_evidence() -> dict[str, Any]:
    package = RESOURCE_ROOT / "skills" / "w8a8-validation"
    registry = SkillRegistry()
    registry.discover_directory(package.parent, SkillTrust.BUILT_IN)
    manifest = registry.manifest("w8a8-validation")
    loaded = registry.load_selected(manifest.id, [SELECTED_REFERENCE])
    all_files = sorted(str(path.relative_to(package)).replace("\\", "/")
                       for path in package.rglob("*") if path.is_file())
    selected_files = [manifest.entrypoint, manifest.references[SELECTED_REFERENCE]]
    excluded = sorted(set(manifest.references) - {SELECTED_REFERENCE})
    eager_chars = len((package / manifest.entrypoint).read_text(encoding="utf-8")) + sum(
        len((package / relative).read_text(encoding="utf-8"))
        for relative in manifest.references.values())
    return {
        "skill": manifest.id, "version": manifest.version, "all_files": all_files,
        "selected_files": selected_files, "selected_references": [SELECTED_REFERENCE],
        "excluded_references": excluded, "loaded_chars": loaded.context_chars,
        "loaded_estimated_tokens": loaded.estimated_context_tokens,
        "eager_chars": eager_chars, "eager_estimated_tokens": max(1, (eager_chars + 3) // 4),
    }


async def failure_probe(provider: CodexProvider, workspace: Path) -> dict[str, Any]:
    initialize_fixture(workspace)
    task = Task("TASK-FAILURE", "RUN-FAILURE", "Return a tiny status only.", "acceptance_probe",
                metadata={"working_directory": str(workspace), "model": "uap-invalid-model-acceptance",
                          "read_only": True}, reasoning="low")
    packet = ExecutionPacketBuilder(40, 0).build(task, workspace, workspace.name, "python",
                                                   read_only=True)
    receipt = await provider.execute(task, packet=packet)
    decision = EscalationManager(2).decide(task, receipt, 0)
    return {"receipt": receipt.to_dict(), "failure_kind": decision.failure_kind.value,
            "escalate": decision.escalate, "reason": decision.reason}


def label_tokens(result: dict[str, Any]) -> str:
    source = ", ".join(result["usage_sources"]) or "unavailable"
    label = "MEASURED" if result["usage_sources"] == ["measured"] else (
        "ESTIMATED" if result["usage_sources"] == ["estimated"] else "UNAVAILABLE")
    return (f"{result['input_tokens']} input / {result['cached_tokens']} cached / "
            f"{result['non_cached_tokens']} non-cached / {result['output_tokens']} output / "
            f"{result['total_tokens']} total ({label}; provider source: {source})")


def artifact_passed(result: dict[str, Any]) -> bool:
    return bool(result["artifact_rows"]) and all(int(row["passed"]) == 1 for row in result["artifact_rows"])


def pytest_passed(result: dict[str, Any]) -> bool:
    return any(task.get("metadata", {}).get("tool_result", {}).get("exit_code") == 0
               for task in result["tool_tasks"])


def render_report(environment: dict[str, Any], simple: dict[str, Any], generic: dict[str, Any],
                  skill: dict[str, Any], progressive: dict[str, Any], failure: dict[str, Any],
                  checks: dict[str, bool]) -> str:
    strategy = simple["composition"].get("execution_plan", {})
    skill_strategy = skill["composition"].get("execution_plan", {})
    quality_generic = "PASS" if artifact_passed(generic) and pytest_passed(generic) else "FAIL"
    quality_skill = "PASS" if artifact_passed(skill) and pytest_passed(skill) else "FAIL"
    total_delta = skill["total_tokens"] - generic["total_tokens"]
    total_delta_percent = (total_delta / generic["total_tokens"] * 100
                           if generic["total_tokens"] else 0.0)
    context_delta = progressive["loaded_estimated_tokens"]
    quality_improved = quality_skill == "PASS" and quality_generic != "PASS"
    total_reduced = skill["total_tokens"] < generic["total_tokens"]
    lines = [
        "# UAP V2.2 real-provider validation", "", "## Environment", "",
        f"- Codex version: `{environment['codex_version']}`",
        f"- UAP version: `{__version__}`", f"- Branch: `{environment['branch']}`",
        f"- Commit before acceptance changes: `{environment['commit']}`",
        f"- Date: `{date.today().isoformat()}`", f"- Executable: `{environment['executable']}`",
        "- Authentication readiness: validated by successful bounded executions; credentials were not read or logged.",
        "- Non-interactive / structured output / working directory: supported and exercised.",
        f"- Usage reporting: `{environment['usage_reporting']}` after real execution.", "",
        "## Test A — Simple Real Execution", "",
        f"- Provider: `{', '.join(simple['provider'])}`",
        f"- Model: `{', '.join(simple['models'])}`",
        f"- Strategy: `{strategy.get('strategy')}`",
        f"- Agents: `{strategy.get('ai_agents')}`; handoffs: `{strategy.get('expected_handoffs')}`",
        f"- Skills: `{', '.join(item['skill'] for item in strategy.get('selected_skills', [])) or 'none'}`",
        f"- Tools: `{', '.join(strategy.get('tools', []))}`",
        f"- AI invocations: `{simple['ai_invocations']}`",
        f"- Tokens: {label_tokens(simple)}", f"- Duration: `{simple['duration']:.2f}s`",
        f"- pytest: `{'PASS' if pytest_passed(simple) else 'FAIL'}`",
        f"- Artifact evaluation: `{'PASS' if artifact_passed(simple) else 'FAIL'}`",
        "- Source contract: the fixture must change from subtraction to addition.",
        f"- Execution ID(s): `{', '.join(simple['execution_ids']) or 'UNAVAILABLE'}`",
        f"- Result: `{'PASS' if checks['simple'] else 'FAIL'}`", "",
        "## Test B — Real Skill Execution", "",
        f"- Provider: `{', '.join(skill['provider'])}`; model: `{', '.join(skill['models'])}`",
        f"- Skill: `{progressive['skill']}@{progressive['version']}`",
        f"- Strategy: `{skill_strategy.get('strategy')}`; AI invocations: `{skill['ai_invocations']}`",
        f"- Progressive loading: `{'PASS' if checks['progressive'] else 'FAIL'}`",
        f"- Files loaded into context: `{', '.join(progressive['selected_files'])}`",
        f"- References loaded: `{', '.join(progressive['selected_references'])}`",
        f"- References excluded: `{', '.join(progressive['excluded_references'])}`",
        f"- Skill context: `{progressive['loaded_chars']} chars`, approximately "
        f"`{progressive['loaded_estimated_tokens']} UAP-controlled tokens` (ESTIMATED)",
        f"- Tokens: {label_tokens(skill)}", f"- Artifact evaluation: `{quality_skill}`",
        f"- Result: `{'PASS' if checks['skill'] else 'FAIL'}`", "",
        "## Test C — Generic vs Structured Skill", "",
        "| Metric | Generic | UAP Skill |", "|---|---:|---:|",
        f"| Provider | {', '.join(generic['provider'])} | {', '.join(skill['provider'])} |",
        f"| Model | {', '.join(generic['models'])} | {', '.join(skill['models'])} |",
        f"| AI invocations | {generic['ai_invocations']} | {skill['ai_invocations']} |",
        f"| Input tokens | {generic['input_tokens']} | {skill['input_tokens']} |",
        f"| Cached tokens | {generic['cached_tokens']} | {skill['cached_tokens']} |",
        f"| Non-cached tokens | {generic['non_cached_tokens']} | {skill['non_cached_tokens']} |",
        f"| Output tokens | {generic['output_tokens']} | {skill['output_tokens']} |",
        f"| UAP Skill context (estimated tokens) | 0 | {progressive['loaded_estimated_tokens']} |",
        f"| Duration (seconds) | {generic['duration']:.2f} | {skill['duration']:.2f} |",
        f"| Repairs / retries | {generic['retries']} | {skill['retries']} |",
        f"| Deterministic validation | {'PASS' if pytest_passed(generic) else 'FAIL'} | {'PASS' if pytest_passed(skill) else 'FAIL'} |",
        f"| Artifact quality | {quality_generic} | {quality_skill} |", "",
        f"Total-token difference (Skill - Generic): `{total_delta:+d}` / `{total_delta_percent:+.2f}%` "
        f"({'reduced' if total_reduced else 'not reduced'}).",
        f"UAP-controlled Skill-context difference (Skill - Generic): `+{context_delta}` estimated tokens.",
        f"Artifact-quality improvement: `{'YES' if quality_improved else 'NO'}`.",
        "Both variants used the same provider, model, goal, fixture directory, input files, test, and environment. "
        "The generated report was removed between variants; the Generic run was not given degraded instructions.", "",
        "This is one ordered paired sample. Different cached-input totals mean the observed token difference "
        "cannot be attributed causally to the Skill package without repeated counterbalanced runs.", "",
        "## Progressive-loading evidence", "",
        f"- Total available Skill files: `{len(progressive['all_files'])}` — `{', '.join(progressive['all_files'])}`",
        f"- Selected context files: `{len(progressive['selected_files'])}` — `{', '.join(progressive['selected_files'])}`",
        f"- Progressive context: `{progressive['loaded_chars']} chars` / approximately `{progressive['loaded_estimated_tokens']} tokens`.",
        f"- Eager package context: `{progressive['eager_chars']} chars` / approximately `{progressive['eager_estimated_tokens']} tokens`.",
        "- The manifest was read for metadata discovery. Only the entrypoint and explicitly selected reference were placed in the execution packet.", "",
        "## Context Attribution", "",
        f"- Measured: provider-reported input, cached-input, and output tokens for each successful Codex turn ({', '.join(skill['usage_sources'])}).",
        f"- Estimated: UAP Skill context from UTF-8 character count divided by four (`{progressive['loaded_estimated_tokens']}` tokens).",
        "- Unavailable: Codex provider base instructions/tool context and project-context token shares cannot be separated from total input tokens. "
        "Therefore total Codex input is not attributed entirely to UAP.",
        "- Dependency receipt context was empty for the single-Agent runs.", "",
        "## Failure Path", "",
        f"- Invalid model status: `{failure['receipt']['status']}`",
        f"- Error code: `{failure['receipt'].get('error_code')}`",
        f"- Failure kind: `{failure['failure_kind']}`",
        f"- Stronger-model escalation: `{'YES' if failure['escalate'] else 'NO'}`",
        f"- Mock fallback: `NO`",
        f"- Root cause (bounded): `{failure['receipt']['summary']}`", "",
        "## Conclusion", "",
        f"- Did V2.2 execute a real provider? `{'YES' if checks['real'] else 'NO'}`",
        f"- Did one Agent + tools complete the simple bug? `{'YES' if checks['simple'] else 'NO'}`",
        f"- Did SkillResolver participate in a real execution? `{'YES' if checks['skill'] else 'NO'}`",
        f"- Did progressive loading occur? `{'YES' if checks['progressive'] else 'NO'}`",
        f"- Did structured Skill improve deterministic artifact quality? `{'YES' if quality_improved else 'NO'}`",
        f"- Did structured Skill reduce UAP-controlled context versus Generic? `NO` (it added `{context_delta}` estimated targeted tokens).",
        f"- Did it reduce total provider tokens in this observed pair? `{'YES' if total_reduced else 'NO'}`. "
        "This is measured but not yet a causal efficiency claim.",
        "", "This experiment reports the observed paired result without treating estimated context as measured provider usage. "
        "Passing architecture tests and real-provider product acceptance remain separate evidence.", "",
    ]
    return "\n".join(lines)


async def execute(output: Path, keep_fixtures: bool, timeout: float,
                  reuse_simple_db: Path | None = None, reuse_simple_run: str | None = None) -> int:
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    temporary = None if keep_fixtures else tempfile.TemporaryDirectory(
        prefix="uap-real-provider-", dir=build)
    fixture_root = (Path(tempfile.mkdtemp(prefix="uap-real-provider-", dir=build))
                    if keep_fixtures else Path(temporary.name))
    old_home = os.environ.get("UNIVERSAL_AGENT_HOME")
    try:
        os.environ["UNIVERSAL_AGENT_HOME"] = str(fixture_root / "platform-home")
        provider = CodexProvider(timeout=timeout)
        probe = provider.probe()
        capabilities = provider.codex_capabilities
        if not (probe.state.ready and capabilities.supports_noninteractive
                and capabilities.supports_structured_output and capabilities.supports_working_directory):
            raise RuntimeError(f"Codex preflight unavailable: {probe.to_dict()}")
        registry = codex_registry(timeout)
        db = Database(fixture_root / "platform-home" / "data" / "acceptance.db")

        if reuse_simple_db and reuse_simple_run:
            simple = collect_run(Database(reuse_simple_db.resolve()), reuse_simple_run)
            assert_real_run(simple)
            strategy = simple["composition"].get("execution_plan", {})
            simple_ok = (simple["status"] == "completed"
                         and strategy.get("strategy") == "single_agent_with_tools"
                         and strategy.get("ai_agents") == 1
                         and strategy.get("expected_handoffs") == 0
                         and "project_test" in strategy.get("tools", [])
                         and pytest_passed(simple) and artifact_passed(simple))
        else:
            simple_dir = fixture_root / "simple-project"
            create_simple_fixture(simple_dir)
            before = (simple_dir / "calculator.py").read_text(encoding="utf-8")
            simple = await run_orchestration(
                db, provider, registry, simple_dir, SIMPLE_GOAL, ["calculator.py"],
                ["calculator.py", "test_calculator.py", ".agent/commands.yaml"],
            )
            after = (simple_dir / "calculator.py").read_text(encoding="utf-8")
            assert_real_run(simple)
            strategy = simple["composition"].get("execution_plan", {})
            simple_ok = (simple["status"] == "completed"
                         and strategy.get("strategy") == "single_agent_with_tools"
                         and strategy.get("ai_agents") == 1
                         and strategy.get("expected_handoffs") == 0
                         and "project_test" in strategy.get("tools", []) and before != after
                         and "return a + b" in after and pytest_passed(simple)
                         and artifact_passed(simple))
        if not simple_ok:
            raise RuntimeError(
                f"Simple real execution failed; stopping before paired benchmark. run={simple['run_id']} "
                f"status={simple['status']} receipts={simple['agent_receipts']}"
            )

        skill_dir = fixture_root / "skill-project"
        create_skill_fixture(skill_dir)
        generic = await run_orchestration(
            db, provider, registry, skill_dir, SKILL_GOAL, ["validation_report.md"],
            ["model_metadata.json", "validation_report.md", "test_validation_report.py",
             "README.md", ".agent/commands.yaml"], generic=True,
        )
        assert_real_run(generic)
        forced_model = generic["models"][0]
        (skill_dir / "validation_report.md").unlink(missing_ok=True)
        skill = await run_orchestration(
            db, provider, registry, skill_dir, SKILL_GOAL, ["validation_report.md"],
            ["model_metadata.json", "validation_report.md", "test_validation_report.py",
             "README.md", ".agent/commands.yaml"], forced_model=forced_model,
        )
        assert_real_run(skill)
        progressive = progressive_evidence()
        loaded_refs = [json.loads(row["loaded_references_json"]) for row in skill["skill_rows"]
                       if row["skill_id"] == "w8a8-validation"]
        progressive_ok = (loaded_refs == [[SELECTED_REFERENCE]]
                          and bool(progressive["excluded_references"])
                          and progressive["loaded_chars"] < progressive["eager_chars"])
        selected = {item["skill"] for item in
                    skill["composition"].get("execution_plan", {}).get("selected_skills", [])}
        generic_selected = generic["composition"].get("execution_plan", {}).get("selected_skills", [])
        skill_ok = (skill["status"] == "completed" and "w8a8-validation" in selected
                    and pytest_passed(skill) and artifact_passed(skill)
                    and generic["status"] == "completed" and not generic_selected
                    and pytest_passed(generic) and artifact_passed(generic)
                    and generic["models"] == skill["models"] and generic["provider"] == skill["provider"])

        failure = await failure_probe(provider, fixture_root / "failure-project")
        failure_ok = (failure["receipt"].get("error_code") == CodexErrorCode.INVALID_ARGUMENT.value
                      and failure["failure_kind"] == FailureKind.ENVIRONMENT.value
                      and not failure["escalate"])
        checks = {"real": True, "simple": simple_ok, "skill": skill_ok,
                  "progressive": progressive_ok, "failure": failure_ok}
        git_branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT,
                                    capture_output=True, text=True, check=True).stdout.strip()
        git_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                    capture_output=True, text=True, check=True).stdout.strip()
        environment = {
            "codex_version": capabilities.version, "branch": git_branch, "commit": git_commit,
            "executable": capabilities.executable,
            "usage_reporting": "MEASURED" if all(
                item["usage_sources"] == ["measured"] for item in (simple, generic, skill)) else "ESTIMATED/UNAVAILABLE",
        }
        output.write_text(render_report(environment, simple, generic, skill, progressive, failure, checks),
                          encoding="utf-8")
        summary = {"checks": checks, "simple": {key: simple[key] for key in
                   ("run_id", "provider", "models", "ai_invocations", "total_tokens")},
                   "generic": {key: generic[key] for key in
                   ("run_id", "provider", "models", "ai_invocations", "total_tokens")},
                   "skill": {key: skill[key] for key in
                   ("run_id", "provider", "models", "ai_invocations", "total_tokens")},
                   "report": str(output)}
        print(json.dumps(summary, indent=2))
        return 0 if all(checks.values()) else 1
    finally:
        if old_home is None:
            os.environ.pop("UNIVERSAL_AGENT_HOME", None)
        else:
            os.environ["UNIVERSAL_AGENT_HOME"] = old_home
        if keep_fixtures:
            print(f"Fixtures retained at {fixture_root}")
        elif temporary is not None:
            temporary.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="acknowledge that this explicitly consumes real Codex quota")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "docs" / "v2.2-real-provider-validation.md")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--keep-fixtures", action="store_true")
    parser.add_argument("--reuse-simple-db", type=Path,
                        help="reuse a previously retained passing Test A database to avoid quota waste")
    parser.add_argument("--reuse-simple-run",
                        help="run id paired with --reuse-simple-db")
    args = parser.parse_args()
    if not args.execute:
        parser.error("real-provider acceptance is opt-in; pass --execute")
    if bool(args.reuse_simple_db) != bool(args.reuse_simple_run):
        parser.error("--reuse-simple-db and --reuse-simple-run must be supplied together")
    raise SystemExit(asyncio.run(execute(
        args.output.resolve(), args.keep_fixtures, args.timeout,
        args.reuse_simple_db, args.reuse_simple_run,
    )))


if __name__ == "__main__":
    main()
