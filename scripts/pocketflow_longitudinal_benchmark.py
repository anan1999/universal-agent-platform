"""Explicit real-provider longitudinal benchmark for UAP V2.3.

This file is deliberately not imported by pytest. It performs real provider
calls and therefore requires both --execute and an explicit non-Mock provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
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
    "Fix a realistic date or monthly-filter boundary bug, add a regression test, and preserve existing behavior.",
    "Implement a monthly spending report and summary feature across the API and UI, including deterministic tests.",
]


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PocketFlow real-provider longitudinal benchmark")
    parser.add_argument("--execute", action="store_true", help="confirm that real provider quota may be used")
    parser.add_argument("--dry-run", action="store_true", help="validate all task plans without provider execution")
    parser.add_argument("--provider", required=True, help="explicit real provider id (Mock is forbidden)")
    parser.add_argument("--model", help="provider model override when supported")
    parser.add_argument("--reasoning", default="medium", choices=("low", "medium", "high", "xhigh"))
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--workspace", type=Path, default=Path("build/pocketflow-longitudinal"))
    parser.add_argument("--output", type=Path,
                        default=Path("benchmark-results/pocketflow-longitudinal.json"))
    return parser.parse_args()


def dry_run() -> dict[str, Any]:
    """Offline contract check for the five write-enabled benchmark tasks."""
    from adaptive_agent.core.goal_analyzer import GoalAnalyzer
    rows = []
    for number, goal in enumerate(TASKS, 1):
        analysis = GoalAnalyzer().analyze(goal)
        required = sorted(set(analysis.capabilities) | {"filesystem", "repository_access", "write_access"})
        rows.append({"task_number": number, "goal": goal, "read_only": False,
                     "required_capabilities": required, "strategy": "implementation/write-enabled",
                     "agent_count": 1, "selected_tools": ["filesystem", "shell"],
                     "approvals": list(analysis.approval_gates), "selected_skills": [],
                     "provider_requirements": required, "ready": not analysis.read_only})
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


def reset_source(source: Path, destination: Path, preserve_agent: bool = False) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    preserved = destination / ".agent"
    saved = destination.parent / f".{destination.name}-agent-memory"
    if preserve_agent and preserved.exists():
        if saved.exists():
            shutil.rmtree(saved)
        shutil.copytree(preserved, saved)
    for child in list(destination.iterdir()):
        if child == saved:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    shutil.copytree(source, destination, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".agent", ".git", "__pycache__", ".pytest_cache"))
    if preserve_agent and saved.exists():
        shutil.copytree(saved, preserved, dirs_exist_ok=True)
        shutil.rmtree(saved)


def evaluate(path: Path, task_number: int) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=path,
                            capture_output=True, text=True, timeout=180, check=False)
    checks: list[tuple[str, bool]] = [("pytest", result.returncode == 0)]
    python_sources = [item for item in path.rglob("*.py") if ".agent" not in item.parts]
    if task_number >= 1:
        checks.append(("backend", any("FastAPI(" in item.read_text(encoding="utf-8", errors="replace")
                                      for item in python_sources)))
    frontend = next(iter(sorted((path / "frontend").rglob("App.*x"))), None) if (path / "frontend").is_dir() else None
    if task_number >= 2:
        checks.append(("react dashboard", bool(frontend and frontend.is_file())))
    source = frontend.read_text(encoding="utf-8", errors="replace").lower() if frontend else ""
    if task_number >= 3:
        checks.append(("category", "category" in source))
    if task_number >= 4:
        checks.append(("monthly regression", any("month" in item.read_text(encoding="utf-8", errors="replace").lower()
                                                  for item in (path / "tests").glob("*.py"))))
    if task_number >= 5:
        checks.append(("monthly report", "summary" in source or "report" in source))
    return {"passed": all(value for _, value in checks),
            "checks": [{"name": name, "passed": value} for name, value in checks],
            "duration_seconds": time.monotonic() - started,
            "stdout": result.stdout[-1200:], "stderr": result.stderr[-800:]}


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
    return {"status": receipt.status, "provider": receipt.provider or getattr(provider, "id", "unknown"),
            "model": receipt.model or model, "reasoning": reasoning,
            "input_tokens": int(usage.get("input", 0)), "cached_input": int(usage.get("cached", 0)),
            "output_tokens": int(usage.get("output", 0)), "token_source": usage.get("source", "unavailable"),
            "ai_invocations": int(usage.get("invocation_count", 1)),
            "handoffs": 0, "deterministic_tool_calls": 0,
            "files_explored": {"value": None, "source": "unavailable"},
            "skill_context_tokens": 0, "knowledge_context_tokens": 0,
            "decision_context_items": 0,
            "duration_seconds": receipt.duration_seconds, "retries": receipt.retry_count,
            "files_modified": receipt.files, "error": receipt.error_code}


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
    run = db.query("SELECT status,composition_json FROM runs WHERE id=?", (run_id,))[0]
    usage = db.query("SELECT SUM(input_tokens) input,SUM(output_tokens) output,"
                     "SUM(cached_tokens) cached,SUM(invocation_count) invocations,"
                     "MAX(token_source) source FROM token_usage WHERE run_id=?", (run_id,))[0]
    lifecycle = db.query("SELECT * FROM project_intelligence_runs WHERE run_id=?", (run_id,))[0]
    tasks = db.query("SELECT data_json FROM tasks WHERE run_id=?", (run_id,))
    task_payloads = [json.loads(row["data_json"]) for row in tasks]
    run_skills = db.query("SELECT context_tokens FROM run_skills WHERE run_id=?", (run_id,))
    lifecycle_data = json.loads(lifecycle["data_json"])
    files = []
    retries = 0
    for row in db.query("SELECT data_json FROM receipts WHERE task_id IN "
                        "(SELECT id FROM tasks WHERE run_id=?)", (run_id,)):
        receipt = json.loads(row["data_json"])
        files.extend(receipt.get("files", []))
        retries += int(receipt.get("retry_count", 0))
    return {"run_id": run_id, "status": run["status"], "provider": provider_id,
            "model": sorted({json.loads(row["data_json"])["metadata"].get("model") for row in tasks
                             if json.loads(row["data_json"])["metadata"].get("model")}),
            "input_tokens": int(usage["input"] or 0), "cached_input": int(usage["cached"] or 0),
            "output_tokens": int(usage["output"] or 0), "token_source": usage["source"] or "unavailable",
            "ai_invocations": int(usage["invocations"] or 0), "retries": retries,
            "duration_seconds": time.monotonic() - started,
            "handoffs": max(0, sum(item.get("kind") == "agent" for item in task_payloads) - 1),
            "deterministic_tool_calls": sum(item.get("kind") == "tool" for item in task_payloads),
            "files_explored": {"value": None, "source": "unavailable"},
            "skill_context_tokens": sum(int(item["context_tokens"] or 0) for item in run_skills),
            "decision_context_items": sum(item.get("kind") == "decision"
                                          for item in lifecycle_data.get("items", [])),
            "files_modified": sorted(set(files)), "temperature": lifecycle["temperature"],
            "reuse_hits": lifecycle["reuse_hits"], "rediscovery": lifecycle["rediscovery_count"],
            "knowledge_context_chars": lifecycle["context_chars"],
            "knowledge_context_tokens_estimated": lifecycle["estimated_tokens"]}


def render_report(payload: dict[str, Any]) -> str:
    lines = ["# PocketFlow longitudinal results", "", "## Environment", "",
             f"- UAP: {payload['environment']['uap']}",
             f"- Commit: {payload['environment']['commit']}",
             f"- Provider: {payload['environment']['provider']}",
             f"- Model: {payload['environment']['model'] or 'provider default'}",
             f"- Date: {payload['environment']['date']}", ""]
    for task in payload["tasks"]:
        lines += [f"## Task {task['task_number']}", "",
                  f"- Baseline: {task['baseline']['status']}, {task['baseline_tokens']} tokens ({task['baseline']['token_source']})",
                  f"- UAP: {task['uap']['status']}, {task['uap_tokens']} tokens ({task['uap']['token_source']})",
                  f"- Quality: baseline={task['quality']['baseline']['passed']}, UAP={task['quality']['uap']['passed']}",
                  f"- State: {task['cold_or_warm'].upper()}",
                  f"- Paired comparison valid: {task['comparison_valid']}",
                  f"- Reuse hits: {task['reuse_hits']}; rediscovery: {task['rediscovery']}", ""]
    lines += ["## Cumulative", "",
              f"- Baseline total: {payload['cumulative']['baseline_tokens']}",
              f"- UAP total: {payload['cumulative']['uap_tokens']}",
              f"- Valid paired tasks: {payload['cumulative']['comparison_valid_tasks']}",
              f"- Break-even: {payload['cumulative']['break_even_task'] or 'not reached'}", "",
              "## Intelligence ROI", "",
              f"- Final state: `{json.dumps(payload['intelligence'], ensure_ascii=False)}`", "",
              "## Limitations", "",
              "Provider sessions are ephemeral, but provider-side caching may still exist. Files explored are unavailable unless the provider reports them. "
             "Paired task inputs are reset to the same accepted source checkpoint. Canonical checkpoint policy is fixed: if both systems pass, baseline is canonical; if only one passes, the passing result is canonical; token counts never choose the checkpoint. UAP alone retains durable `.agent` intelligence.\n"]
    return "\n".join(lines)


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

    workspace = args.workspace.resolve()
    if workspace.exists():
        shutil.rmtree(workspace)
    canonical, baseline, uap = workspace / "canonical", workspace / "baseline", workspace / "uap"
    seed(canonical)
    reset_source(canonical, baseline)
    reset_source(canonical, uap)
    initialize_project(uap, RESOURCE_ROOT / "templates", auto=True)
    db = Database(workspace / "uap-history.db")
    tasks: list[dict[str, Any]] = []
    cumulative_baseline = cumulative_uap = 0
    break_even = None
    for number, goal in enumerate(TASKS, 1):
        if number > 1:
            reset_source(canonical, baseline)
            reset_source(canonical, uap, preserve_agent=True)
        before_baseline = ProjectIntelligenceStore(canonical).hash_paths(
            path.relative_to(canonical).as_posix() for path in canonical.rglob("*") if path.is_file())
        baseline_result = await baseline_run(provider, baseline, goal, args.model, args.reasoning)
        uap_result = await uap_run(provider, uap, goal, db, args.provider)
        baseline_quality, uap_quality = evaluate(baseline, number), evaluate(uap, number)
        baseline_tokens = baseline_result["input_tokens"] + baseline_result["output_tokens"]
        uap_tokens = uap_result["input_tokens"] + uap_result["output_tokens"]
        cumulative_baseline += baseline_tokens
        cumulative_uap += uap_tokens
        comparison_valid = (baseline_result["status"] == "completed" and
                            uap_result["status"] == "completed" and
                            baseline_quality["passed"] and uap_quality["passed"] and
                            baseline_result["token_source"] == "measured" and
                            uap_result["token_source"] == "measured")
        if comparison_valid and break_even is None and cumulative_uap <= cumulative_baseline:
            break_even = number
        # Fixed, pre-declared checkpoint rule; token outcome never selects it.
        chosen = baseline if baseline_quality["passed"] else uap
        reset_source(chosen, canonical)
        task_result = {"task_number": number, "goal": goal, "baseline": baseline_result,
                       "uap": uap_result, "baseline_tokens": baseline_tokens,
                       "uap_tokens": uap_tokens, "cumulative_baseline": cumulative_baseline,
                       "cumulative_uap": cumulative_uap,
                       "quality": {"baseline": baseline_quality, "uap": uap_quality},
                       "reuse_hits": uap_result["reuse_hits"],
                       "rediscovery": uap_result["rediscovery"],
                       "cold_or_warm": uap_result["temperature"],
                       "comparison_valid": comparison_valid,
                       "paired_source_files": len(before_baseline)}
        tasks.append(task_result)
        partial = {"tasks": tasks}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(partial, indent=2), encoding="utf-8")

    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                            text=True, check=False).stdout.strip() or "unknown"
    payload = {"environment": {"uap": __version__, "commit": commit,
                                "provider": args.provider, "model": args.model,
                                "reasoning": args.reasoning,
                                "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
               "tasks": tasks,
               "cumulative": {"baseline_tokens": cumulative_baseline,
                              "uap_tokens": cumulative_uap, "break_even_task": break_even,
                              "comparison_valid_tasks": sum(item["comparison_valid"] for item in tasks)},
               "intelligence": ProjectIntelligenceStore(uap).status()}
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    report = Path("docs/pocketflow-longitudinal-results.md")
    report.write_text(render_report(payload), encoding="utf-8")
    return payload


def main() -> int:
    args = arguments()
    if args.dry_run:
        print(json.dumps(dry_run(), indent=2))
        return 0 if dry_run()["ready_for_real_benchmark"] else 1
    if not args.execute:
        print("Refusing to consume real provider quota without --execute.", file=sys.stderr)
        return 2
    payload = asyncio.run(execute(args))
    print(json.dumps(payload["cumulative"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
