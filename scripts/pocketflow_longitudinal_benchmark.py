"""Explicit real-provider longitudinal benchmark for UAP V2.3.

This file is deliberately not imported by pytest. It performs real provider
calls and therefore requires both --execute and an explicit non-Mock provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import tempfile
import hashlib
from enum import StrEnum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adaptive_agent import __version__
from adaptive_agent.core.execution_packet import ExecutionPacketBuilder
from adaptive_agent.core.models import Task, new_id
from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.intelligence.project import ProjectIntelligenceStore
from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.project.adapter import initialize_project
from adaptive_agent.project.discovery import discover
from adaptive_agent.providers.registry import providers
from adaptive_agent.runtime import RESOURCE_ROOT
from adaptive_agent.storage.database import Database


TASKS = [
    "Implement the backend foundation for a personal expense app: FastAPI, SQLite, an Expense model, CRUD API, and backend tests.",
    "Implement a compact React expense dashboard that calls the existing API and handles loading and error states.",
    "Implement category filtering and a category spending breakdown across the existing API and React dashboard, with tests.",
    "Fix month filtering so YYYY-MM includes records through the selected month's final day and excludes adjacent-month records (including January 31 / February 1), add a regression test, and preserve existing behavior.",
    "Implement a monthly spending report and summary feature across the API and UI, including deterministic tests.",
]


class BenchmarkMode(StrEnum):
    EXECUTION_EFFICIENCY = "execution-efficiency"
    LONGITUDINAL_LEARNING = "longitudinal-learning"


class ResultState(StrEnum):
    VALID = "VALID"
    INVALID_QUALITY = "INVALID_QUALITY"
    INVALID_HARNESS = "INVALID_HARNESS"
    INTERRUPTED_PROVIDER = "INTERRUPTED_PROVIDER"
    QUOTA_LIMIT = "QUOTA_LIMIT"
    NOT_COMPARABLE = "NOT_COMPARABLE"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PocketFlow real-provider longitudinal benchmark")
    parser.add_argument("--execute", action="store_true", help="confirm that real provider quota may be used")
    parser.add_argument("--dry-run", action="store_true", help="validate all task plans without provider execution")
    parser.add_argument("--resume", action="store_true", help="continue from a retained paired-task checkpoint")
    parser.add_argument("--mode", default=BenchmarkMode.LONGITUDINAL_LEARNING.value,
                        choices=tuple(item.value for item in BenchmarkMode),
                        help="measure cold execution strategy or independent longitudinal learning")
    parser.add_argument("--provider", required=True, help="explicit real provider id (Mock is forbidden)")
    parser.add_argument("--model", help="provider model override when supported")
    parser.add_argument("--reasoning", default="medium", choices=("low", "medium", "high", "xhigh"))
    parser.add_argument("--canonical-source", default="baseline", choices=("baseline", "uap"),
                        help="fixed passing implementation used as the next paired checkpoint")
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--workspace", type=Path, default=Path("build/pocketflow-longitudinal"))
    parser.add_argument("--output", type=Path,
                        default=Path("benchmark-results/pocketflow-longitudinal.json"))
    parser.add_argument("--report", type=Path,
                        default=Path("docs/pocketflow-longitudinal-results.md"))
    return parser.parse_args()


def dry_run() -> dict[str, Any]:
    """Offline contract check using the same Orchestrator planner as real runs."""
    from adaptive_agent.core.orchestrator import Orchestrator
    from adaptive_agent.providers.mock import MockProvider
    rows = []
    with tempfile.TemporaryDirectory(prefix="uap-pocketflow-dry-") as directory:
        root = Path(directory)
        seed(root)
        initialize_project(root, RESOURCE_ROOT / "templates", auto=True)
        db = Database(root / "history.db")
        orchestrator = Orchestrator(db, MockProvider(), EventBus(db), provider_name="mock",
                                    active_profiles=["software-engineering"], consumption_mode="economy")
        for number, goal in enumerate(TASKS, 1):
            composition = orchestrator.compose(new_id("DRY"), goal, str(root),
                                               project_name="pocketflow-expenses", project_type="python")
            task_rows = []
            ready = not composition.analysis.read_only
            for task in composition.graph.tasks.values():
                task_data = task.to_dict()
                task_rows.append(task_data)
                if task.kind.value == "agent":
                    routing = task.metadata.get("routing", {})
                    required = set(routing.get("required_capabilities", task.required_capabilities))
                    writable = (not bool(task.metadata.get("read_only", False)) and
                                {"filesystem", "write_access", "repository_access"} <= required)
                    ready = ready and writable
            rows.append({"task_number": number, "goal": goal,
                         "read_only": composition.analysis.read_only,
                         "strategy": composition.execution_plan.strategy.value if composition.execution_plan else None,
                         "agent_count": composition.execution_plan.ai_agents if composition.execution_plan else 0,
                         "selected_tools": composition.execution_plan.tools if composition.execution_plan else [],
                         "approvals": list(composition.team.approval_gates),
                         "selected_skills": [item.manifest.id for item in composition.execution_plan.selected_skills] if composition.execution_plan else [],
                         "provider_requirements": sorted({capability for task in composition.graph.tasks.values()
                                                          for capability in task.metadata.get("routing", {}).get("required_capabilities", [])}),
                         "tasks": task_rows, "ready": ready})
    return {"tasks": rows, "ready_for_real_benchmark": all(row["ready"] for row in rows)}


def seed(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "pyproject.toml").write_text(
        "[project]\nname='pocketflow-expenses'\nversion='0.1.0'\n"
        "requires-python='>=3.11'\ndependencies=['fastapi>=0.110']\n\n"
        "[tool.pytest.ini_options]\ntestpaths=['tests']\npythonpath=['.']\n", encoding="utf-8")
    (path / "README.md").write_text(
        "# PocketFlow Personal Expenses\n\nBuild the application incrementally and keep `python -m pytest -q` green.\n",
        encoding="utf-8")
    (path / "tests").mkdir(exist_ok=True)
    (path / "tests" / "test_seed.py").write_text("def test_seed():\n    assert True\n", encoding="utf-8")
    cursor_rules = path / ".cursor" / "cli.json"
    cursor_rules.parent.mkdir(exist_ok=True)
    cursor_rules.write_text(json.dumps({
        "permissions": {
            "allow": ["Read(**)", "Write(**)", "Shell(python:*)", "Shell(pytest:*)",
                      "Shell(node:*)", "Shell(npm:*)", "Shell(npx:*)"],
            "deny": ["Read(../**)", "Write(../**)", "Read(.env*)", "Read(**/.env*)",
                     "Read(**/*.key)", "Read(**/*.pem)", "Write(.git/**)",
                     "Write(**/.env*)", "Write(**/*.key)", "Write(**/*.pem)",
                     "Shell(curl:*)", "Shell(Invoke-WebRequest:*)", "Shell(Invoke-RestMethod:*)",
                     "Shell(git:push*)", "Shell(git:remote*)", "Shell(rm:*)", "Shell(del:*)",
                     "WebFetch(*)", "Mcp(*:*)"],
        }
    }, indent=2) + "\n", encoding="utf-8")


def reset_source(source: Path, destination: Path, preserve_agent: bool = False,
                 include_agent: bool = False) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    preserved = destination / ".agent"
    saved = destination.parent / f".{destination.name}-agent-memory"
    if preserve_agent and preserved.exists():
        if saved.exists():
            remove_tree(saved)
        shutil.copytree(preserved, saved)
    for child in list(destination.iterdir()):
        if child == saved:
            continue
        if child.is_dir():
            remove_tree(child)
        else:
            child.unlink()
    ignored = [".git", "__pycache__", ".pytest_cache"]
    if not include_agent:
        ignored.append(".agent")
    shutil.copytree(source, destination, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*ignored))
    if preserve_agent and saved.exists():
        shutil.copytree(saved, preserved, dirs_exist_ok=True)
        remove_tree(saved)


def remove_tree(path: Path) -> None:
    """Remove generated trees containing transient or broken pnpm links."""
    target = (Path("\\\\?\\" + str(path.resolve())) if os.name == "nt" else path)
    for _ in range(8):
        if not path.exists():
            return
        shutil.rmtree(target, ignore_errors=True)
    if path.exists():
        def handle_error(function: Any, name: str, error_info: tuple[Any, Any, Any]) -> None:
            error = error_info[1]
            if isinstance(error, FileNotFoundError):
                return
            os.chmod(name, stat.S_IWRITE)
            function(name)
        shutil.rmtree(target, onerror=handle_error)


def evaluate(path: Path, task_number: int) -> dict[str, Any]:
    """Run the immutable benchmark-owned contract; self tests are informational only."""
    path = path.resolve()
    started = time.monotonic()
    pytest_temp = path / ".benchmark-pytest-tmp"
    if pytest_temp.exists():
        remove_tree(pytest_temp)
    try:
        result = subprocess.run([sys.executable, "-m", "pytest", "-q",
                                 f"--basetemp={pytest_temp}"], cwd=path,
                                capture_output=True, text=True, timeout=180, check=False)
    finally:
        if pytest_temp.exists():
            remove_tree(pytest_temp)
    contract = ROOT / "benchmark-fixtures" / "pocketflow" / "acceptance" / "contract.py"
    try:
        accepted = subprocess.run([sys.executable, str(contract), "--project", str(path),
                                   "--task", str(task_number)], cwd=ROOT,
                                  capture_output=True, text=True, timeout=300, check=False)
        payload = json.loads(accepted.stdout.strip().splitlines()[-1])
        harness_error = False
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as error:
        payload = {"contract": "pocketflow-v1", "passed": False, "checks": [],
                   "harness_error": f"{type(error).__name__}: {error}"}
        harness_error = True
    return {**payload, "passed": bool(payload.get("passed")),
            "quality_source": "benchmark_owned_external_acceptance",
            "harness_error": payload.get("harness_error") if harness_error else None,
            "duration_seconds": time.monotonic() - started,
            "self_tests": {"passed": result.returncode == 0,
                           "stdout": result.stdout[-1200:], "stderr": result.stderr[-800:]}}


def source_tree_hash(path: Path) -> str:
    """Hash auditable source lineage while excluding runtime and intelligence state."""
    digest = hashlib.sha256()
    ignored = {".agent", ".git", "node_modules", "__pycache__", ".pytest_cache",
               ".benchmark-pytest-tmp", "dist", "build"}
    for item in sorted((value for value in path.rglob("*") if value.is_file()),
                       key=lambda value: value.relative_to(path).as_posix()):
        relative = item.relative_to(path)
        if any(part in ignored for part in relative.parts) or item.suffix in {".db", ".sqlite", ".sqlite3"}:
            continue
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


async def baseline_run(provider: Any, root: Path, goal: str, model: str | None,
                       reasoning: str) -> dict[str, Any]:
    task = Task(new_id("BASE"), "BASELINE", goal, "direct_provider",
                ["coding", "filesystem", "write_access", "repository_access"],
                reasoning=reasoning,
                metadata={"working_directory": str(root), "model": model,
                          "goal": goal, "read_only": False})
    packet = ExecutionPacketBuilder().build(task, root, "pocketflow-expenses", "python")
    receipt = await provider.execute(task, packet=packet)
    usage = receipt.token_usage
    input_tokens = int(usage.get("input", 0))
    cached_input = int(usage.get("cached", 0))
    return {"status": receipt.status, "provider": receipt.provider or getattr(provider, "id", "unknown"),
            "model": receipt.model or model, "reasoning": reasoning,
            "input_tokens": input_tokens, "cached_input": cached_input,
            "non_cached_input": max(0, input_tokens - cached_input),
            "output_tokens": int(usage.get("output", 0)), "token_source": usage.get("source", "unavailable"),
            "ai_invocations": int(usage.get("invocation_count", 1)),
            "handoffs": 0, "deterministic_tool_calls": 0,
            "files_explored": {"value": None, "source": "unavailable"},
            "skill_context_tokens": 0, "knowledge_context_tokens": 0,
            "decision_context_items": 0,
            "duration_seconds": receipt.duration_seconds, "retries": receipt.retry_count,
            "files_modified": receipt.files, "error": receipt.error_code,
            "summary": receipt.summary, "findings": receipt.findings,
            "uncertainty_reason": receipt.uncertainty_reason,
            "needs_escalation": receipt.needs_escalation,
            "provider_learning_evidence_count": len(receipt.learning_evidence),
            "provider_learning_evidence_types": sorted({str(item.get("type", item.get("kind", "unknown")))
                                                        for item in receipt.learning_evidence})}


async def uap_run(provider: Any, root: Path, goal: str, db: Database,
                  provider_id: str) -> dict[str, Any]:
    started = time.monotonic()
    info = discover(root)
    project_rows = db.query("SELECT id FROM projects WHERE path=?", (str(root.resolve()),))
    project_id = project_rows[0]["id"] if project_rows else new_id("PRJ")
    if not project_rows:
        db.execute("INSERT INTO projects(id,path,name,type,config_json) VALUES(?,?,?,?,?)",
                   (project_id, str(root.resolve()), info.name, info.type, "{}"))
    orchestrator = Orchestrator(db, provider, EventBus(db), provider_name=provider_id,
                                provider_preference=[provider_id], active_profiles=["software-engineering"],
                                consumption_mode="economy")
    run_id = await orchestrator.run_goal(goal, project_id, str(root), project_name=info.name,
                                         project_type=info.type, project_signals=info.signals)
    return summarize_uap_run(db, run_id, provider_id, duration_seconds=time.monotonic() - started)


def summarize_uap_run(db: Database, run_id: str, provider_id: str,
                       *, duration_seconds: float | None = None) -> dict[str, Any]:
    """Rebuild a normalized benchmark row from durable UAP receipts."""
    run = db.query("SELECT status,composition_json FROM runs WHERE id=?", (run_id,))[0]
    usage = db.query("SELECT SUM(input_tokens) input,SUM(output_tokens) output,"
                     "SUM(cached_tokens) cached,SUM(invocation_count) invocations,"
                     "CASE WHEN SUM(CASE WHEN token_source='measured' THEN 1 ELSE 0 END)>0 "
                     "THEN 'measured' WHEN SUM(CASE WHEN token_source='estimated' THEN 1 ELSE 0 END)>0 "
                     "THEN 'estimated' ELSE 'unavailable' END source FROM token_usage WHERE run_id=?", (run_id,))[0]
    lifecycle = db.query("SELECT * FROM project_intelligence_runs WHERE run_id=?", (run_id,))[0]
    tasks = db.query("SELECT data_json FROM tasks WHERE run_id=?", (run_id,))
    task_payloads = [json.loads(row["data_json"]) for row in tasks]
    run_skills = db.query("SELECT context_tokens FROM run_skills WHERE run_id=?", (run_id,))
    lifecycle_data = json.loads(lifecycle["data_json"])
    files = []
    provider_evidence: list[dict[str, Any]] = []
    retries = 0
    for row in db.query("SELECT data_json FROM receipts WHERE task_id IN "
                        "(SELECT id FROM tasks WHERE run_id=?)", (run_id,)):
        receipt = json.loads(row["data_json"])
        files.extend(receipt.get("files", []))
        provider_evidence.extend(item for item in receipt.get("learning_evidence", [])
                                 if isinstance(item, dict))
        retries += int(receipt.get("retry_count", 0))
    input_tokens = int(usage["input"] or 0)
    cached_input = int(usage["cached"] or 0)
    funnel = lifecycle_data.get("learning_funnel", {})
    return {"run_id": run_id, "status": run["status"], "provider": provider_id,
            "model": sorted({json.loads(row["data_json"])["metadata"].get("model") for row in tasks
                             if json.loads(row["data_json"])["metadata"].get("model")}),
            "input_tokens": input_tokens, "cached_input": cached_input,
            "non_cached_input": max(0, input_tokens - cached_input),
            "output_tokens": int(usage["output"] or 0), "token_source": usage["source"] or "unavailable",
            "ai_invocations": int(usage["invocations"] or 0), "retries": retries,
            "duration_seconds": duration_seconds,
            "handoffs": max(0, sum(item.get("kind") == "agent" for item in task_payloads) - 1),
            "deterministic_tool_calls": sum(item.get("kind") == "tool" for item in task_payloads),
            "files_explored": {"value": None, "source": "unavailable"},
            "skill_context_tokens": sum(int(item["context_tokens"] or 0) for item in run_skills),
            "decision_context_items": sum(item.get("kind") == "decision"
                                          for item in lifecycle_data.get("items", [])),
            "files_modified": sorted(set(files)), "temperature": lifecycle["temperature"],
            "reuse_hits": lifecycle["reuse_hits"], "rediscovery": lifecycle["rediscovery_count"],
            "knowledge_context_chars": lifecycle["context_chars"],
            "knowledge_context_tokens_estimated": lifecycle["estimated_tokens"],
            "controlled_context_chars": lifecycle["context_chars"],
            "controlled_context_tokens_estimated": lifecycle["estimated_tokens"],
            "provider_learning_evidence_count": len(provider_evidence),
            "provider_learning_evidence_types": sorted({str(item.get("type", item.get("kind", "unknown")))
                                                        for item in provider_evidence}),
            "learning_funnel": funnel,
            "reuse_funnel": {
                key: lifecycle_data.get(key, 0 if key != "rediscovery_avoidance" else "UNAVAILABLE")
                for key in ("intelligence_candidates_considered", "intelligence_selected",
                            "knowledge_selected", "skills_selected", "decisions_selected",
                            "commands_selected", "successful_selected_items",
                            "validated_context_reuse", "rediscovery_avoidance")
            },
            "stale_intelligence": lifecycle_data.get("stale_reasons", [])}


def render_report(payload: dict[str, Any]) -> str:
    def model_label(value: Any) -> str:
        if isinstance(value, list):
            return ", ".join(str(item) for item in value) or "default"
        return str(value or "default")

    providers_used = sorted({str(side.get("provider", "unknown"))
                             for task in payload["tasks"] for side in (task["baseline"], task["uap"])})
    provider_note = (f"All paired tasks used the single provider {providers_used[0]}."
                     if len(providers_used) == 1 else
                     f"This is a mixed-provider sequence: {', '.join(providers_used)}.")
    mode = payload["environment"].get("mode", BenchmarkMode.LONGITUDINAL_LEARNING.value)
    lines = ["# PocketFlow benchmark results", "", "## Environment", "",
             f"- UAP: {payload['environment']['uap']}",
             f"- Commit: {payload['environment']['commit']}",
             f"- Provider: {payload['environment']['provider']}",
             f"- Model: {payload['environment']['model'] or 'provider default'}",
             f"- Mode: {mode}",
             f"- Hypothesis: {payload['environment'].get('hypothesis', 'unknown')}",
             f"- Source policy: {payload['environment'].get('source_policy', 'unknown')}",
             f"- Date: {payload['environment']['date']}", ""]
    for task in payload["tasks"]:
        funnel = task.get("learning_funnel", {})
        reuse = task.get("reuse_funnel", {})
        lines += [f"## Task {task['task_number']}", "",
                  f"- Provider/model: baseline={task['baseline']['provider']}/{model_label(task['baseline'].get('model'))}; "
                  f"UAP={task['uap']['provider']}/{model_label(task['uap'].get('model'))}",
                  f"- Baseline: {task['baseline']['status']}, {task['baseline_tokens']} tokens ({task['baseline']['token_source']})",
                  f"- UAP: {task['uap']['status']}, {task['uap_tokens']} tokens ({task['uap']['token_source']})",
                  f"- Result state: {task.get('result_state', 'UNKNOWN')}",
                  f"- Quality equivalent: {task.get('quality_equivalent', False)} "
                  f"(external contract={task.get('quality', {}).get('contract', 'unknown')})",
                  f"- State: {task['cold_or_warm'].upper()}",
                  f"- Paired comparison valid: {task['comparison_valid']}",
                  f"- Validated context reuse: {reuse.get('validated_context_reuse', 0)}",
                  f"- Reuse candidate found: {bool(task.get('reuse_hits'))}",
                  f"- Rediscovery avoidance: {task.get('rediscovery_avoidance', 'UNAVAILABLE')}",
                  f"- Source lineage: baseline {task.get('source_lineage', {}).get('baseline', {}).get('starting_hash', 'unknown')[:12]}→"
                  f"{task.get('source_lineage', {}).get('baseline', {}).get('ending_hash', 'unknown')[:12]}; "
                  f"UAP {task.get('source_lineage', {}).get('uap', {}).get('starting_hash', 'unknown')[:12]}→"
                  f"{task.get('source_lineage', {}).get('uap', {}).get('ending_hash', 'unknown')[:12]}", "",
                  "### Learning funnel", "",
                  f"- Provider evidence: {funnel.get('provider_learning_evidence_count', 0)} "
                  f"({', '.join(funnel.get('provider_learning_evidence_types', [])) or 'none'})",
                  f"- Distiller: {funnel.get('distiller_input_count', 0)} input → "
                  f"{funnel.get('distiller_candidate_count', 0)} candidates",
                  f"- Persisted: {funnel.get('persistence_accepted_count', 0)} accepted; "
                  f"{funnel.get('persistence_rejected_count', 0)} rejected",
                  f"- Accepted by kind: {json.dumps(funnel.get('accepted_by_kind', {}), sort_keys=True)}",
                  f"- Rejected by reason: {json.dumps(funnel.get('rejected_by_reason', {}), sort_keys=True)}",
                  f"- Materialized: {', '.join(funnel.get('materialized', [])) or 'none'}", "",
                  "### Reuse funnel", "",
                  f"- Considered: {reuse.get('intelligence_candidates_considered', 0)}; "
                  f"selected: {reuse.get('intelligence_selected', 0)}",
                  f"- Knowledge/Skills/Decisions/Commands: {reuse.get('knowledge_selected', 0)}/"
                  f"{reuse.get('skills_selected', 0)}/{reuse.get('decisions_selected', 0)}/"
                  f"{reuse.get('commands_selected', 0)}",
                  f"- Selected context: {task['uap'].get('controlled_context_chars', 0)} chars / "
                  f"~{task['uap'].get('controlled_context_tokens_estimated', 0)} tokens",
                  f"- Successful selected items: {reuse.get('successful_selected_items', 0)}", ""]
        if task.get("stale_intelligence"):
            lines += ["### Revalidation causes", "",
                      *[f"- {item.get('id')}: {item.get('reason')} — "
                        f"{', '.join(item.get('changed_paths', [])) or 'path unavailable'}"
                        for item in task["stale_intelligence"]], ""]
    if payload.get("interrupted"):
        stopped = payload["interrupted"]
        lines += ["## Interrupted", "",
                  f"- Task: {stopped['task_number']}",
                  f"- Stage: {stopped['stage']}",
                  f"- Status: {stopped.get('status') or 'unknown'}",
                  f"- Error: {stopped.get('error') or 'none'}",
                  f"- Detail: {stopped.get('summary') or stopped.get('message') or 'unavailable'}", ""]
    lines += ["## Cumulative", "",
              f"- Baseline total: {payload['cumulative']['baseline_tokens']}",
              f"- UAP total: {payload['cumulative']['uap_tokens']}",
              f"- Valid paired tasks: {payload['cumulative']['comparison_valid_tasks']}",
              f"- Paired measurement claimable: {payload['cumulative'].get('paired_measurement_claimable', False)}",
              f"- Savings claimable: {payload['cumulative'].get('savings_claimable', False)}",
              f"- Learning reuse validated: {payload['cumulative'].get('learning_reuse_validated', False)}",
              f"- Learning savings claimable: {payload['cumulative'].get('learning_savings_claimable', False)}",
              f"- Learning observation: {payload.get('learning_observation', 'LEARNING_NOT_OBSERVED')}",
              f"- Break-even: {payload['cumulative']['break_even_task'] or 'not reached'}", "",
              "## Intelligence ROI", "",
              f"- Final state: `{json.dumps(payload['intelligence'], ensure_ascii=False)}`", "",
              "## Limitations", "",
              "Provider sessions are ephemeral, but provider-side caching may still exist. Files explored are unavailable unless the provider reports them. "
             + ("Execution-efficiency pairs start from the same checkpoint and UAP Project Intelligence is empty for every pair. "
                if mode == BenchmarkMode.EXECUTION_EFFICIENCY.value else
                "Baseline and UAP preserve independent longitudinal source lines; source trees are never swapped between them. ")
             + f"{provider_note} Provider-side caching may still exist. Repository exploration is not inferred when the provider does not report it. Validated context reuse means selected context plus successful external acceptance; it does not prove semantic reliance or token causality. Break-even requires every preceding pair to remain VALID and quality-equivalent.\n"]
    return "\n".join(lines)


def rollback_invalid_runs(db: Database, intelligence_root: Path,
                          invalid_tasks: list[dict[str, Any]]) -> None:
    """Remove failed benchmark attempts before resuming a valid prefix.

    The benchmark database and project-intelligence file are isolated build
    artifacts.  A provider outage must not become durable project knowledge or
    make later tasks appear warm.
    """
    run_ids = [str(item.get("uap", {}).get("run_id") or "") for item in invalid_tasks]
    run_ids = [run_id for run_id in run_ids if run_id]
    for run_id in run_ids:
        task_ids = [row["id"] for row in db.query("SELECT id FROM tasks WHERE run_id=?", (run_id,))]
        for task_id in task_ids:
            db.execute("DELETE FROM receipts WHERE task_id=?", (task_id,))
        for table in ("token_usage", "events", "messages", "artifacts", "agent_skills",
                      "skill_runs", "run_skills", "artifact_evaluations",
                      "project_intelligence_runs", "agent_instances"):
            db.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
        db.execute("DELETE FROM tasks WHERE run_id=?", (run_id,))
        db.execute("DELETE FROM runs WHERE id=?", (run_id,))

    # Failed performance rows have no run_id in the current schema. This is a
    # dedicated benchmark database, so failed rows cannot belong to user work.
    if run_ids:
        db.execute("DELETE FROM agent_performance WHERE success=0")

    path = intelligence_root / ".agent" / "intelligence.json"
    if not path.exists() or not run_ids:
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    blocked = set(run_ids)
    data["items"] = [item for item in data.get("items", [])
                     if item.get("first_created_task") not in blocked]
    data["runs"] = [item for item in data.get("runs", [])
                    if item.get("run_id") not in blocked]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def write_interruption(args: argparse.Namespace, tasks: list[dict[str, Any]],
                       task_number: int, stage: str, result: dict[str, Any],
                       pending: dict[str, Any] | None = None) -> None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    interruption = {
            "task_number": task_number,
            "stage": stage,
            "status": result.get("status"),
            "error": result.get("error"),
            "summary": result.get("summary"),
            "findings": result.get("findings", []),
            "uncertainty_reason": result.get("uncertainty_reason"),
            "message": "Provider execution stopped early; resolve the provider or task blocker before resuming.",
        }
    cumulative_baseline = sum(int(item.get("baseline_tokens", 0)) for item in tasks)
    cumulative_uap = sum(int(item.get("uap_tokens", 0)) for item in tasks)
    break_even = next((int(item["task_number"]) for item in tasks
                       if item.get("comparison_valid")
                       and int(item.get("cumulative_uap", 0)) <= int(item.get("cumulative_baseline", 0))), None)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                            text=True, check=False).stdout.strip() or "unknown"
    uap_root = args.workspace.resolve() / "uap"
    error_text = " ".join(str(result.get(key) or "")
                          for key in ("error", "summary", "status")).lower()
    stop_state = (ResultState.QUOTA_LIMIT.value if "quota" in error_text or "rate_limit" in error_text
                  or "usage limit" in error_text else ResultState.INTERRUPTED_PROVIDER.value)
    interruption["result_state"] = stop_state
    payload = {
        "environment": {"uap": __version__, "commit": commit, "provider": args.provider,
                        "model": args.model, "reasoning": args.reasoning,
                        "mode": args.mode,
                        "canonical_source": (args.canonical_source if args.mode ==
                                             BenchmarkMode.EXECUTION_EFFICIENCY.value else None),
                        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "tasks": tasks,
        "interrupted": interruption,
        "pending": pending or {},
        "cumulative": {"baseline_tokens": cumulative_baseline, "uap_tokens": cumulative_uap,
                       "break_even_task": "NOT_CLAIMABLE", "observed_break_even_task": break_even,
                       "paired_measurement_claimable": False,
                       "savings_claimable": False,
                       "learning_reuse_validated": False,
                       "learning_savings_claimable": False,
                       "comparison_valid_tasks": sum(bool(item.get("comparison_valid")) for item in tasks)},
        "intelligence": ProjectIntelligenceStore(uap_root).status(),
    }
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(payload), encoding="utf-8")


def repair_react_filename_false_negative(task: dict[str, Any]) -> None:
    """Migrate results created by the former App.jsx-only acceptance check."""
    if int(task.get("task_number", 0)) != 2:
        return
    for side in ("baseline", "uap"):
        modified = task.get(side, {}).get("files_modified", [])
        has_component = any(
            str(name).replace("\\", "/").startswith(("frontend/src/", "src/"))
            and str(name).lower().endswith((".jsx", ".tsx"))
            and ".test." not in str(name).lower() and ".spec." not in str(name).lower()
            for name in modified
        )
        if not has_component:
            continue
        quality = task.get("quality", {}).get(side, {})
        for check in quality.get("checks", []):
            if check.get("name") == "react dashboard":
                check["passed"] = True
        quality["passed"] = all(check.get("passed") for check in quality.get("checks", []))
    task["comparison_valid"] = bool(
        task.get("baseline", {}).get("status") == task.get("uap", {}).get("status") == "completed"
        and task.get("quality", {}).get("baseline", {}).get("passed")
        and task.get("quality", {}).get("uap", {}).get("passed")
        and task.get("baseline", {}).get("token_source") == "measured"
        and task.get("uap", {}).get("token_source") == "measured"
    )
    if task["comparison_valid"] and not task.get("canonical_source"):
        task["canonical_source"] = "uap (legacy evaluator recovery)"


def paired_models_match(task: dict[str, Any]) -> bool:
    """Require an explicit model match when a baseline model was pinned."""
    baseline_model = task.get("baseline", {}).get("model")
    if not baseline_model:
        return True
    uap_model = task.get("uap", {}).get("model")
    models = set(uap_model if isinstance(uap_model, list) else [uap_model])
    return baseline_model in models


def result_state(baseline: dict[str, Any], uap: dict[str, Any],
                 baseline_quality: dict[str, Any], uap_quality: dict[str, Any]) -> str:
    combined_error = " ".join(str(value or "") for value in (
        baseline.get("error"), uap.get("error"), baseline.get("summary"), uap.get("summary"))).lower()
    if "quota" in combined_error or "rate_limit" in combined_error or "usage limit" in combined_error:
        return ResultState.QUOTA_LIMIT.value
    if baseline.get("status") != "completed" or uap.get("status") != "completed":
        return ResultState.INTERRUPTED_PROVIDER.value
    if baseline_quality.get("harness_error") or uap_quality.get("harness_error"):
        return ResultState.INVALID_HARNESS.value
    if not baseline_quality.get("passed") or not uap_quality.get("passed"):
        return ResultState.INVALID_QUALITY.value
    if (not baseline.get("files_modified") or not uap.get("files_modified")
            or not paired_models_match({"baseline": baseline, "uap": uap})
            or baseline.get("token_source") != "measured"
            or uap.get("token_source") != "measured"):
        return ResultState.NOT_COMPARABLE.value
    return ResultState.VALID.value


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    registry = providers()
    if args.provider == "mock" or args.provider not in registry:
        raise SystemExit("A registered real provider is required; Mock fallback is prohibited.")
    descriptor = registry.get(args.provider)
    if not descriptor.implemented:
        raise SystemExit(f"Provider {args.provider!r} is not a real implemented provider.")
    provider = registry.create(args.provider, timeout=args.timeout)
    if provider.execution_mode.value == "mock":
        raise SystemExit(f"Provider {args.provider!r} is not a real implemented provider.")
    probe = provider.probe()
    if not probe.ready:
        raise SystemExit(f"Provider {args.provider!r} is not ready: {probe.detail}")
    if not provider.capabilities().supports("filesystem", allow_uncertain=False):
        raise SystemExit(f"Provider {args.provider!r} cannot perform this repository-writing benchmark.")

    mode = BenchmarkMode(args.mode)
    workspace = args.workspace.resolve()
    resuming = bool(args.resume and workspace.exists() and args.output.exists())
    if workspace.exists() and not resuming:
        remove_tree(workspace)
    baseline, uap = workspace / "baseline", workspace / "uap"
    canonical = workspace / "execution-canonical"
    baseline_checkpoints = workspace / "checkpoints" / "baseline"
    uap_checkpoints = workspace / "checkpoints" / "uap"
    if not resuming:
        seed(baseline)
        seed(uap)
        initialize_project(uap, RESOURCE_ROOT / "templates", auto=True)
        reset_source(baseline, baseline_checkpoints / "task-0")
        reset_source(uap, uap_checkpoints / "task-0", include_agent=True)
        if mode is BenchmarkMode.EXECUTION_EFFICIENCY:
            reset_source(baseline, canonical)
    resume_payload = (json.loads(args.output.read_text(encoding="utf-8")) if resuming else {})
    if resuming and resume_payload.get("environment", {}).get("mode", args.mode) != args.mode:
        raise SystemExit("Resume mode does not match the retained benchmark checkpoint.")
    tasks: list[dict[str, Any]] = list(resume_payload.get("tasks", []))
    db = Database(workspace / "uap-history.db")
    first_invalid = next((index for index, item in enumerate(tasks)
                          if item.get("result_state") != ResultState.VALID.value), None)
    if first_invalid is not None:
        if mode is not BenchmarkMode.LONGITUDINAL_LEARNING:
            raise SystemExit("Execution-efficiency invalid runs must restart from a fresh workspace.")
        baseline_checkpoint = baseline_checkpoints / f"task-{first_invalid}"
        uap_checkpoint = uap_checkpoints / f"task-{first_invalid}"
        if not baseline_checkpoint.exists() or not uap_checkpoint.exists():
            raise SystemExit(f"Cannot safely roll back task {first_invalid + 1}: source checkpoint unavailable.")
        rollback_invalid_runs(db, uap, tasks[first_invalid:])
        tasks = tasks[:first_invalid]
        reset_source(baseline_checkpoint, baseline)
        reset_source(uap_checkpoint, uap, include_agent=True)
        resume_payload = {"tasks": tasks}

    # A provider can modify its source tree and then fail before returning a
    # usable receipt (for example, a CLI timeout after tests completed).  Such
    # a pending result is not a checkpoint.  Restore the failed side from the
    # last VALID pair before retrying so --resume cannot inherit unmeasured
    # work.  A completed baseline is retained when only the UAP side failed.
    pending = resume_payload.get("pending", {})
    expected_pending_task = len(tasks) + 1
    if (resuming and pending.get("task_number") == expected_pending_task
            and mode is BenchmarkMode.LONGITUDINAL_LEARNING):
        baseline_checkpoint = baseline_checkpoints / f"task-{len(tasks)}"
        uap_checkpoint = uap_checkpoints / f"task-{len(tasks)}"
        if not baseline_checkpoint.exists() or not uap_checkpoint.exists():
            raise SystemExit(
                f"Cannot safely restore pending task {expected_pending_task}: source checkpoint unavailable."
            )
        baseline_pending = pending.get("baseline", {})
        uap_pending = pending.get("uap", {})
        if baseline_pending.get("status") != "completed":
            reset_source(baseline_checkpoint, baseline)
            reset_source(uap_checkpoint, uap, include_agent=True)
            rollback_invalid_runs(db, uap, [{"uap": uap_pending}])
            resume_payload = {"tasks": tasks}
        elif uap_pending and uap_pending.get("status") != "completed":
            reset_source(uap_checkpoint, uap, include_agent=True)
            rollback_invalid_runs(db, uap, [{"uap": uap_pending}])
            resume_payload["pending"].pop("uap", None)
    if tasks and mode is BenchmarkMode.LONGITUDINAL_LEARNING and not resume_payload.get("pending"):
        last = tasks[-1]["source_lineage"]
        if (source_tree_hash(baseline) != last["baseline"]["ending_hash"]
                or source_tree_hash(uap) != last["uap"]["ending_hash"]):
            raise SystemExit("Source lineage corruption detected; retained workspace does not match checkpoint.")

    cumulative_baseline = sum(int(item["baseline_tokens"]) for item in tasks)
    cumulative_uap = sum(int(item["uap_tokens"]) for item in tasks)
    break_even = next((item["task_number"] for item in tasks
                       if item["result_state"] == ResultState.VALID.value
                       and item["cumulative_uap"] <= item["cumulative_baseline"]), None)
    for number, goal in enumerate(TASKS, 1):
        if number <= len(tasks):
            continue
        pending = resume_payload.get("pending", {})
        if mode is BenchmarkMode.EXECUTION_EFFICIENCY and pending.get("task_number") != number:
            reset_source(canonical, baseline)
            reset_source(canonical, uap)
            initialize_project(uap, RESOURCE_ROOT / "templates", auto=True)
        task_db = (db if mode is BenchmarkMode.LONGITUDINAL_LEARNING
                   else Database(workspace / f"uap-history-task-{number}.db"))
        starting_hashes = (pending.get("starting_hashes") if pending.get("task_number") == number
                           else {"baseline": source_tree_hash(baseline), "uap": source_tree_hash(uap)})
        baseline_result = (pending.get("baseline") if pending.get("task_number") == number
                           and pending.get("baseline", {}).get("status") == "completed" else None)
        if baseline_result is None:
            baseline_result = await baseline_run(provider, baseline, goal, args.model, args.reasoning)
        if baseline_result["status"] != "completed":
            write_interruption(args, tasks, number, "baseline", baseline_result,
                               {"task_number": number, "goal": goal,
                                "starting_hashes": starting_hashes,
                                "baseline": baseline_result})
            raise SystemExit(f"Provider stopped at task {number} baseline: "
                             f"{baseline_result.get('error') or baseline_result['status']}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        partial_environment = {"mode": args.mode}
        args.output.write_text(json.dumps({"environment": partial_environment, "tasks": tasks,
                                           "pending": {"task_number": number, "goal": goal,
                                                       "starting_hashes": starting_hashes,
                                                       "baseline": baseline_result}}, indent=2), encoding="utf-8")
        if pending.get("task_number") == number and pending.get("uap", {}).get("status") == "completed":
            uap_result = pending["uap"]
        else:
            uap_result = await uap_run(provider, uap, goal, task_db, args.provider)
        if uap_result["status"] != "completed":
            write_interruption(args, tasks, number, "uap", uap_result,
                               {"task_number": number, "goal": goal,
                                "starting_hashes": starting_hashes,
                                "baseline": baseline_result, "uap": uap_result})
            raise SystemExit(f"Provider stopped at task {number} UAP: "
                             f"{uap_result.get('error') or uap_result['status']}")
        args.output.write_text(json.dumps({"environment": partial_environment, "tasks": tasks,
                                           "pending": {"task_number": number, "goal": goal,
                                                       "starting_hashes": starting_hashes,
                                                       "baseline": baseline_result,
                                                       "uap": uap_result}}, indent=2), encoding="utf-8")
        baseline_quality, uap_quality = evaluate(baseline, number), evaluate(uap, number)
        state = result_state(baseline_result, uap_result, baseline_quality, uap_quality)
        quality_equivalent = bool(baseline_quality["passed"] and uap_quality["passed"])
        baseline_tokens = baseline_result["input_tokens"] + baseline_result["output_tokens"]
        uap_tokens = uap_result["input_tokens"] + uap_result["output_tokens"]
        cumulative_baseline += baseline_tokens
        cumulative_uap += uap_tokens
        if (state == ResultState.VALID.value and break_even is None
                and cumulative_uap <= cumulative_baseline
                and all(item["result_state"] == ResultState.VALID.value for item in tasks)):
            break_even = number
        ending_hashes = {"baseline": source_tree_hash(baseline), "uap": source_tree_hash(uap)}
        intelligence_sources = [{"id": item.id, "source_commit": item.source_commit,
                                 "source_hashes": item.source_hashes}
                                for item in ProjectIntelligenceStore(uap).items()
                                if item.kind in {"knowledge", "decision", "skill", "command",
                                                 "evaluation", "known_issue", "agent"}]
        task_result = {
            "task_number": number, "goal": goal, "benchmark_mode": args.mode,
            "result_state": state, "quality_equivalent": quality_equivalent,
            "baseline": baseline_result, "uap": uap_result,
            "baseline_tokens": baseline_tokens, "uap_tokens": uap_tokens,
            "cumulative_baseline": cumulative_baseline, "cumulative_uap": cumulative_uap,
            "quality": {"contract": "pocketflow-v1", "baseline": baseline_quality,
                        "uap": uap_quality},
            "reuse_hits": uap_result["reuse_hits"], "rediscovery": uap_result["rediscovery"],
            "rediscovery_avoidance": "UNAVAILABLE",
            "cold_or_warm": uap_result["temperature"],
            "comparison_valid": state == ResultState.VALID.value,
            "source_lineage": {
                "baseline": {"starting_hash": starting_hashes["baseline"],
                             "ending_hash": ending_hashes["baseline"],
                             "parent_task": number - 1 or None},
                "uap": {"starting_hash": starting_hashes["uap"],
                        "ending_hash": ending_hashes["uap"],
                        "parent_task": number - 1 or None,
                        "intelligence_sources": intelligence_sources},
            },
            "learning_funnel": uap_result.get("learning_funnel", {}),
            "reuse_funnel": uap_result.get("reuse_funnel", {}),
            "stale_intelligence": uap_result.get("stale_intelligence", []),
        }
        tasks.append(task_result)
        if state == ResultState.VALID.value:
            reset_source(baseline, baseline_checkpoints / f"task-{number}")
            reset_source(uap, uap_checkpoints / f"task-{number}", include_agent=True)
            if mode is BenchmarkMode.EXECUTION_EFFICIENCY:
                chosen = baseline if args.canonical_source == "baseline" else uap
                reset_source(chosen, canonical)
        args.output.write_text(json.dumps({"environment": partial_environment, "tasks": tasks}, indent=2),
                               encoding="utf-8")
        if state != ResultState.VALID.value:
            raise SystemExit(f"Benchmark stopped at task {number}: {state}.")

    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                            text=True, check=False).stdout.strip() or "unknown"
    paired_measurement = len(tasks) == len(TASKS) and all(
        item.get("result_state") == ResultState.VALID.value and item.get("quality_equivalent")
        for item in tasks)
    learning_reuse = (mode is BenchmarkMode.LONGITUDINAL_LEARNING and paired_measurement
                      and any(int(item.get("reuse_funnel", {}).get("validated_context_reuse", 0)) > 0
                              for item in tasks))
    observed_savings = paired_measurement and cumulative_uap < cumulative_baseline
    payload = {"environment": {"uap": __version__, "commit": commit,
                                "provider": args.provider, "model": args.model,
                                "reasoning": args.reasoning,
                                "mode": args.mode,
                                "hypothesis": ("execution_efficiency" if mode is BenchmarkMode.EXECUTION_EFFICIENCY
                                               else "amortized_project_intelligence"),
                                "source_policy": ("same paired checkpoint; project intelligence empty"
                                                  if mode is BenchmarkMode.EXECUTION_EFFICIENCY else
                                                  "independent longitudinal baseline and UAP lines"),
                                "canonical_source": (args.canonical_source
                                                     if mode is BenchmarkMode.EXECUTION_EFFICIENCY else None),
                                "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
               "tasks": tasks,
               "cumulative": {"baseline_tokens": cumulative_baseline,
                              "uap_tokens": cumulative_uap, "break_even_task": break_even,
                              "paired_measurement_claimable": paired_measurement,
                              "savings_claimable": observed_savings,
                              "learning_reuse_validated": learning_reuse,
                              "learning_savings_claimable": learning_reuse and observed_savings,
                              "quality_equivalent_tasks": sum(bool(item["quality_equivalent"]) for item in tasks),
                              "comparison_valid_tasks": sum(item["comparison_valid"] for item in tasks)},
               "intelligence": ProjectIntelligenceStore(uap).status(),
               "learning_observation": ("VALIDATED_CONTEXT_REUSE" if learning_reuse
                                        else "LEARNING_NOT_OBSERVED")}
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(payload), encoding="utf-8")
    return payload


def main() -> int:
    args = arguments()
    if args.dry_run:
        payload = dry_run()
        print(json.dumps(payload, indent=2))
        return 0 if payload["ready_for_real_benchmark"] else 1
    if not args.execute:
        print("Refusing to consume real provider quota without --execute.", file=sys.stderr)
        return 2
    payload = asyncio.run(execute(args))
    print(json.dumps(payload["cumulative"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
