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
from adaptive_agent.observability.benchmark_quality import assess_implementation_quality
from adaptive_agent.project.adapter import initialize_project
from adaptive_agent.project.discovery import discover
from adaptive_agent.providers.registry import providers
from adaptive_agent.runtime import RESOURCE_ROOT
from adaptive_agent.storage.database import Database


TASKS = [
    "Implement the backend foundation for a personal expense app: FastAPI, SQLite, an Expense model, CRUD API, and backend tests.",
    "Implement a compact React expense dashboard that calls the existing API and handles loading and error states.",
    "Add GET /exports/expenses.csv with columns id,amount,category,description,date, add a dashboard download link to that exact endpoint, and add deterministic tests.",
    "Add GET /reports/monthly/{month} returning exactly month, total, and by_category, with money represented as two-decimal strings; include only dates inside that calendar month and add boundary regression tests.",
    "Add a dashboard month input that calls /reports/monthly/{month} and renders the returned total and by_category breakdown, with deterministic tests.",
]

QUALITY_CONTRACTS = {
    1: {"checks": ["backend"],
        "prefixes": ["app/", "backend/", "pocketflow/", "src/", "tests/", "pyproject.toml", "README.md"],
        "tests": True},
    2: {"checks": ["react dashboard"], "prefixes": ["frontend/", "README.md", ".gitignore"],
        "tests": False},
    3: {"checks": ["csv export", "csv download link"],
        "prefixes": ["app/", "tests/", "frontend/"], "tests": True},
    4: {"checks": ["monthly boundary contract"], "prefixes": ["app/", "tests/"],
        "tests": True},
    5: {"checks": ["monthly dashboard request", "month input", "category breakdown"],
        "prefixes": ["frontend/"], "tests": True},
}


class CompletionProbedProvider:
    """Benchmark-only provider view that preserves exact Codex usage on acceptance."""

    def __init__(self, delegate: Any, completion_probe: Any,
                 model_override: str | None = None):
        self.delegate = delegate
        self.completion_probe = completion_probe
        self.model_override = model_override

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    async def execute(self, task: Task, progress: Any = None, packet: Any = None,
                      completion_probe: Any = None) -> Any:
        probe = completion_probe or self.completion_probe
        if self.model_override:
            task.metadata["model"] = self.model_override
        if getattr(self.delegate, "id", None) == "codex":
            task.metadata["codex_live_usage"] = True
            task.metadata.setdefault("execution_budget", {}).update({
                "completion_probe_passes": 2,
                "completion_probe_grace_seconds": 1.0,
                "completion_steer_grace_seconds": 20.0,
                "completion_interrupt_grace_seconds": 15.0,
            })
        return await self.delegate.execute(task, progress, packet, completion_probe=probe)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PocketFlow real-provider longitudinal benchmark")
    parser.add_argument("--execute", action="store_true", help="confirm that real provider quota may be used")
    parser.add_argument("--dry-run", action="store_true", help="validate all task plans without provider execution")
    parser.add_argument("--audit-existing", action="store_true",
                        help="re-score retained paired artifacts without provider execution")
    parser.add_argument("--resume", action="store_true", help="continue from a retained paired-task checkpoint")
    parser.add_argument("--provider", required=True, help="explicit real provider id (Mock is forbidden)")
    parser.add_argument("--model", help="provider model override when supported")
    parser.add_argument("--reasoning", default="medium", choices=("low", "medium", "high", "xhigh"))
    parser.add_argument("--canonical-source", default="baseline", choices=("baseline", "uap"),
                        help="fixed passing implementation used as the next paired checkpoint")
    parser.add_argument("--rounds", type=int, choices=range(1, len(TASKS) + 1), default=len(TASKS))
    parser.add_argument("--max-provider-calls", type=int, default=len(TASKS) * 2)
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


def reset_source(source: Path, destination: Path, preserve_agent: bool = False) -> None:
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
    shutil.copytree(source, destination, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".agent", ".git", "__pycache__", ".pytest_cache"))
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


def frontend_source_files(path: Path) -> list[Path]:
    """Find React source regardless of whether it is bundled or server-served."""
    ignored = {".agent", ".git", ".pytest_cache", "__pycache__", "node_modules", "tests"}
    candidates = [item for pattern in ("*.js", "*.jsx", "*.ts", "*.tsx")
                  for item in path.rglob(pattern)
                  if not ignored.intersection(item.relative_to(path).parts)
                  and ".test." not in item.name and ".spec." not in item.name]
    return [item for item in candidates
            if "react" in item.read_text(encoding="utf-8", errors="replace").lower()]


def evaluate(path: Path, task_number: int) -> dict[str, Any]:
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
    checks: list[tuple[str, bool]] = [("pytest", result.returncode == 0)]
    ignored_python_parts = {".agent", ".git", ".pytest_cache", "__pycache__", "node_modules"}
    python_sources = [item for item in path.rglob("*.py")
                      if not ignored_python_parts.intersection(item.relative_to(path).parts)]
    if task_number >= 1:
        checks.append(("backend", any("FastAPI(" in item.read_text(encoding="utf-8", errors="replace")
                                      for item in python_sources)))
    frontend_sources = frontend_source_files(path)
    if task_number >= 2:
        checks.append(("react dashboard", bool(frontend_sources)))
    source = "\n".join(item.read_text(encoding="utf-8", errors="replace").lower()
                       for item in frontend_sources)
    if task_number >= 3:
        export_probe = subprocess.run([sys.executable, "-c", """
import tempfile
from fastapi.testclient import TestClient
from app.main import create_app
with tempfile.TemporaryDirectory() as directory:
    with TestClient(create_app(directory + '/acceptance.sqlite3')) as client:
        payload = {'amount':'12.34','category':'Food','description':'Lunch','date':'2026-02-10'}
        assert client.post('/expenses', json=payload).status_code == 201
        response = client.get('/exports/expenses.csv')
        assert response.status_code == 200
        assert response.headers.get('content-type','').startswith('text/csv')
        rows = response.text.strip().splitlines()
        assert rows[0] == 'id,amount,category,description,date'
        assert '12.34,Food,Lunch,2026-02-10' in rows[1]
"""], cwd=path, capture_output=True, text=True, timeout=30, check=False)
        checks.append(("csv export", export_probe.returncode == 0))
        checks.append(("csv download link", "/exports/expenses.csv" in source))
    if task_number >= 4:
        monthly_probe = subprocess.run([sys.executable, "-c", """
import tempfile
from fastapi.testclient import TestClient
from app.main import create_app
with tempfile.TemporaryDirectory() as directory:
    with TestClient(create_app(directory + '/acceptance.sqlite3')) as client:
        for amount, category, date in [('99.00','Other','2026-01-31'),('10.00','Food','2026-02-01'),('20.00','Travel','2026-02-28'),('77.00','Other','2026-03-01')]:
            assert client.post('/expenses', json={'amount':amount,'category':category,'description':'x','date':date}).status_code == 201
        response = client.get('/reports/monthly/2026-02')
        assert response.status_code == 200
        assert response.json() == {'month':'2026-02','total':'30.00','by_category':{'Food':'10.00','Travel':'20.00'}}
"""], cwd=path, capture_output=True, text=True, timeout=30, check=False)
        checks.append(("monthly boundary contract", monthly_probe.returncode == 0))
    if task_number >= 5:
        checks.append(("monthly dashboard request", "/reports/monthly/" in source))
        checks.append(("month input", any(fragment in source for fragment in (
            'type="month"', "type='month'", 'type: "month"', "type: 'month'"))))
        checks.append(("category breakdown", "by_category" in source))
    return {"passed": all(value for _, value in checks),
            "checks": [{"name": name, "passed": value} for name, value in checks],
            "duration_seconds": time.monotonic() - started,
            "stdout": result.stdout[-1200:], "stderr": result.stderr[-800:]}


async def baseline_run(provider: Any, root: Path, goal: str, model: str | None,
                       reasoning: str, task_number: int) -> dict[str, Any]:
    task = Task(new_id("BASE"), "BASELINE", goal, "direct_provider",
                ["coding", "filesystem", "write_access", "repository_access"],
                reasoning=reasoning,
                metadata={"working_directory": str(root), "model": model,
                          "goal": goal, "read_only": False})
    packet = ExecutionPacketBuilder().build(task, root, "pocketflow-expenses", "python")
    measured_provider = CompletionProbedProvider(
        provider, lambda: evaluate(root, task_number)["passed"], model)
    receipt = await measured_provider.execute(task, packet=packet)
    usage = receipt.token_usage
    return {"status": receipt.status, "provider": receipt.provider or getattr(provider, "id", "unknown"),
            "model": receipt.model or model, "reasoning": reasoning,
            "input_tokens": int(usage.get("input", 0)), "cached_input": int(usage.get("cached", 0)),
            "output_tokens": int(usage.get("output", 0)), "token_source": usage.get("source", "unavailable"),
            "usage_complete": bool(usage.get("complete", False)),
            "ai_invocations": int(usage.get("invocation_count", 1)),
            "provider_tool_calls": int(usage.get("provider_tool_calls", 0)),
            "provider_messages": int(usage.get("provider_messages", 0)),
            "token_attribution": usage.get("attribution", {}),
            "handoffs": 0, "deterministic_tool_calls": 0,
            "files_explored": {"value": None, "source": "unavailable"},
            "skill_context_tokens": 0, "knowledge_context_tokens": 0,
            "decision_context_items": 0,
            "duration_seconds": receipt.duration_seconds, "retries": receipt.retry_count,
            "files_modified": receipt.files, "error": receipt.error_code,
            "summary": receipt.summary, "findings": receipt.findings,
            "uncertainty_reason": receipt.uncertainty_reason,
            "needs_escalation": receipt.needs_escalation}


async def uap_run(provider: Any, root: Path, goal: str, db: Database,
                  provider_id: str, task_number: int,
                  model: str | None = None) -> dict[str, Any]:
    started = time.monotonic()
    info = discover(root)
    project_rows = db.query("SELECT id FROM projects WHERE path=?", (str(root.resolve()),))
    project_id = project_rows[0]["id"] if project_rows else new_id("PRJ")
    if not project_rows:
        db.execute("INSERT INTO projects(id,path,name,type,config_json) VALUES(?,?,?,?,?)",
                   (project_id, str(root.resolve()), info.name, info.type, "{}"))
    measured_provider = CompletionProbedProvider(
        provider, lambda: evaluate(root, task_number)["passed"], model)
    orchestrator = Orchestrator(db, measured_provider, EventBus(db), provider_name=provider_id,
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
                     "SUM(provider_tool_calls) provider_tool_calls,"
                     "SUM(provider_messages) provider_messages,"
                     "SUM(CASE WHEN invocation_count>0 AND token_source!='measured' THEN 1 ELSE 0 END) incomplete,"
                     "CASE WHEN SUM(CASE WHEN token_source='measured' THEN 1 ELSE 0 END)>0 "
                     "THEN 'measured' WHEN SUM(CASE WHEN token_source='estimated' THEN 1 ELSE 0 END)>0 "
                     "THEN 'estimated' ELSE 'unavailable' END source FROM token_usage WHERE run_id=?", (run_id,))[0]
    lifecycle_rows = db.query("SELECT * FROM project_intelligence_runs WHERE run_id=?", (run_id,))
    composition = json.loads(run["composition_json"] or "{}")
    fallback_lifecycle = composition.get("project_intelligence", {})
    lifecycle = lifecycle_rows[0] if lifecycle_rows else None
    tasks = db.query("SELECT data_json FROM tasks WHERE run_id=?", (run_id,))
    task_payloads = [json.loads(row["data_json"]) for row in tasks]
    run_skills = db.query("SELECT context_tokens FROM run_skills WHERE run_id=?", (run_id,))
    files = []
    retries = 0
    errors: list[str] = []
    attributions: list[dict[str, Any]] = []
    for row in db.query("SELECT attribution_json FROM token_usage WHERE run_id=?", (run_id,)):
        attribution = json.loads(row.get("attribution_json") or "{}")
        if attribution:
            attributions.append(attribution)
    for row in db.query("SELECT data_json FROM receipts WHERE task_id IN "
                        "(SELECT id FROM tasks WHERE run_id=?)", (run_id,)):
        receipt = json.loads(row["data_json"])
        files.extend(receipt.get("files", []))
        retries += int(receipt.get("retry_count", 0))
        if receipt.get("error_code"):
            errors.append(str(receipt["error_code"]))
    lifecycle_data = (json.loads(lifecycle["data_json"]) if lifecycle
                      else fallback_lifecycle)
    return {"run_id": run_id, "status": run["status"], "provider": provider_id,
            "model": sorted({json.loads(row["data_json"])["metadata"].get("model") for row in tasks
                             if json.loads(row["data_json"])["metadata"].get("model")}),
            "input_tokens": int(usage["input"] or 0), "cached_input": int(usage["cached"] or 0),
            "output_tokens": int(usage["output"] or 0), "token_source": usage["source"] or "unavailable",
            "usage_complete": bool(int(usage["invocations"] or 0) > 0
                                   and int(usage["incomplete"] or 0) == 0),
            "ai_invocations": int(usage["invocations"] or 0), "retries": retries,
            "provider_tool_calls": int(usage["provider_tool_calls"] or 0),
            "provider_messages": int(usage["provider_messages"] or 0),
            "token_attribution": (attributions[0] if len(attributions) == 1 else
                                  ({"method": "multiple_provider_invocations",
                                    "invocations": attributions} if attributions else {})),
            "duration_seconds": duration_seconds,
            "handoffs": max(0, sum(item.get("kind") == "agent" for item in task_payloads) - 1),
            "deterministic_tool_calls": sum(item.get("kind") == "tool" for item in task_payloads),
            "files_explored": {"value": None, "source": "unavailable"},
            "skill_context_tokens": sum(int(item["context_tokens"] or 0) for item in run_skills),
            "decision_context_items": sum(item.get("kind") == "decision"
                                          for item in lifecycle_data.get("items", [])),
            "files_modified": sorted(set(files)),
            "error": errors[0] if errors else None,
            "temperature": (lifecycle["temperature"] if lifecycle else
                            fallback_lifecycle.get("temperature", "unknown")),
            "reuse_hits": int(lifecycle["reuse_hits"] if lifecycle else
                              fallback_lifecycle.get("reuse_hits", 0)),
            "rediscovery": int(lifecycle["rediscovery_count"] if lifecycle else
                               fallback_lifecycle.get("rediscovery_count", 0)),
            "knowledge_context_chars": int(lifecycle["context_chars"] if lifecycle else
                                           fallback_lifecycle.get("context_chars", 0)),
            "knowledge_context_tokens_estimated": int(
                lifecycle["estimated_tokens"] if lifecycle else
                fallback_lifecycle.get("estimated_tokens", 0))}


def render_report(payload: dict[str, Any]) -> str:
    def model_label(value: Any) -> str:
        if isinstance(value, list):
            return ", ".join(str(item) for item in value) or "default"
        return str(value or "default")

    def attribution_label(result: dict[str, Any]) -> str:
        attribution = result.get("token_attribution") or {}
        groups = attribution.get("invocations", [attribution])
        totals: dict[str, int] = {}
        windows = 0
        for group in groups:
            for window in group.get("windows", []):
                kind = str(window.get("kind", "unknown"))
                totals[kind] = totals.get(kind, 0) + int(window.get("total_tokens", 0))
                windows += 1
        if not windows:
            return "not collected"
        detail = ", ".join(f"{kind}={value}" for kind, value in sorted(totals.items()))
        return f"{windows} windows ({detail})"

    providers_used = sorted({str(side.get("provider", "unknown"))
                             for task in payload["tasks"] for side in (task["baseline"], task["uap"])})
    provider_note = (f"All paired tasks used the single provider {providers_used[0]}."
                     if len(providers_used) == 1 else
                     f"This is a mixed-provider sequence: {', '.join(providers_used)}.")
    canonical = payload["environment"].get("canonical_source", "baseline")
    lines = ["# PocketFlow longitudinal results", "", "## Method", "",
             "Five implementation tasks were executed sequentially in the same fresh project. "
             "Each task compared direct Codex against UAP from the same accepted source checkpoint; "
             "provider sessions were ephemeral while UAP retained project-local reusable state.", "",
             "## Environment", "",
             f"- UAP: {payload['environment']['uap']}",
             f"- Commit: {payload['environment']['commit']}",
             f"- Provider: {payload['environment']['provider']}",
             f"- Model: {payload['environment']['model'] or 'provider default'}",
             f"- Canonical source: {payload['environment'].get('canonical_source', 'baseline')}",
             f"- Date: {payload['environment']['date']}", ""]
    for task in payload["tasks"]:
        baseline_tokens = int(task["baseline_tokens"])
        uap_tokens = int(task["uap_tokens"])
        reduction = ((baseline_tokens - uap_tokens) / baseline_tokens * 100
                     if baseline_tokens else 0.0)
        baseline_score = task["quality"]["baseline"].get("independent", {}).get("score")
        uap_score = task["quality"]["uap"].get("independent", {}).get("score")
        lines += [f"## Task {task['task_number']}", "",
                  f"- Goal: {task['goal']}",
                  f"- Provider/model: baseline={task['baseline']['provider']}/{model_label(task['baseline'].get('model'))}; "
                  f"UAP={task['uap']['provider']}/{model_label(task['uap'].get('model'))}",
                  f"- Baseline: {task['baseline']['status']}, {task['baseline_tokens']} tokens ({task['baseline']['token_source']})",
                  f"- UAP: {task['uap']['status']}, {task['uap_tokens']} tokens ({task['uap']['token_source']})",
                  f"- Token reduction: {reduction:.2f}%",
                  f"- Quality: baseline={task['quality']['baseline']['passed']}, UAP={task['quality']['uap']['passed']}",
                  f"- Independent quality score: baseline={baseline_score if baseline_score is not None else 'not collected'}; "
                  f"UAP={uap_score if uap_score is not None else 'not collected'}",
                  f"- Provider tool windows: baseline={task['baseline'].get('provider_tool_calls', 'not collected')}; "
                  f"UAP={task['uap'].get('provider_tool_calls', 'not collected')}",
                  f"- Baseline token attribution: {attribution_label(task['baseline'])}",
                  f"- UAP token attribution: {attribution_label(task['uap'])}",
                  f"- State: {task['cold_or_warm'].upper()}",
                  f"- Paired comparison valid: {task['comparison_valid']}",
                  f"- Canonical source: {task.get('canonical_source', 'baseline')}",
                  f"- Reuse hits: {task['reuse_hits']}; rediscovery: {task['rediscovery']}", ""]
    if payload.get("interrupted"):
        stopped = payload["interrupted"]
        lines += ["## Interrupted", "",
                  f"- Task: {stopped['task_number']}",
                  f"- Stage: {stopped['stage']}",
                  f"- Status: {stopped.get('status') or 'unknown'}",
                  f"- Error: {stopped.get('error') or 'none'}",
                  f"- Detail: {stopped.get('summary') or stopped.get('message') or 'unavailable'}", ""]
    if payload.get("posthoc_quality_audit"):
        audit = payload["posthoc_quality_audit"]
        lines += ["## Post-hoc independent quality audit", "",
                  f"- Audited tasks: {', '.join(str(item['task_number']) for item in audit['tasks'])}",
                  f"- Quality equivalent: {audit['quality_equivalent']}",
                  f"- Quality-adjusted savings claimable: "
                  f"{payload['cumulative'].get('quality_adjusted_savings_claimable', False)}"]
        for item in audit["tasks"]:
            lines += [f"- Task {item['task_number']}: baseline={item['baseline']['score']}/100 "
                      f"({'PASS' if item['baseline']['passed'] else 'FAIL'}), "
                      f"UAP={item['uap']['score']}/100 "
                      f"({'PASS' if item['uap']['passed'] else 'FAIL'})"]
        lines += [f"- Limitation: {audit['limitation']}", ""]
    baseline_total = int(payload["cumulative"]["baseline_tokens"])
    uap_total = int(payload["cumulative"]["uap_tokens"])
    total_reduction = ((baseline_total - uap_total) / baseline_total * 100
                       if baseline_total else 0.0)
    lines += ["## Cumulative", "",
              f"- Baseline total: {payload['cumulative']['baseline_tokens']}",
              f"- UAP total: {payload['cumulative']['uap_tokens']}",
              f"- Token reduction: {total_reduction:.2f}%",
              f"- Valid paired tasks: {payload['cumulative']['comparison_valid_tasks']}",
              f"- Paired measurement claimable: {payload['cumulative'].get('paired_measurement_claimable', False)}",
              f"- Savings claimable: {payload['cumulative'].get('savings_claimable', False)}",
              f"- Learning reuse validated: {payload['cumulative'].get('learning_reuse_validated', False)}",
              f"- Learning savings claimable: {payload['cumulative'].get('learning_savings_claimable', False)}",
              f"- Break-even: {payload['cumulative']['break_even_task'] or 'not reached'}", "",
              "## Intelligence ROI", "",
              f"- Final state: `{json.dumps(payload['intelligence'], ensure_ascii=False)}`", "",
              "## Limitations", "",
              "Provider sessions are ephemeral, but provider-side caching may still exist. Files explored are unavailable unless the provider reports them. "
             f"Paired task inputs are reset to the same accepted source checkpoint. When both systems pass, the predeclared canonical source is {canonical}; if only one passes, the passing result is canonical. Token outcomes never choose the checkpoint. {provider_note} A valid paired measurement and validated learning reuse do not imply token savings; break-even must also be reached. UAP alone retains durable `.agent` intelligence.\n"]
    return "\n".join(lines)


def longitudinal_intelligence(root: Path, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Report reuse-first state instead of presenting the legacy store as truth."""
    index_path = root / ".agent" / "project-index.json"
    index = (json.loads(index_path.read_text(encoding="utf-8"))
             if index_path.exists() else {})
    sources = index.get("sources", [])
    if not sources:
        sources = index.get("project", {}).get("sources", [])
    return {
        "measurement_source": "paired task receipts and project index",
        "project_index_present": bool(index),
        "project_index_sources": len(sources),
        "benchmark_runs": len(tasks),
        "warm_runs": sum(item.get("cold_or_warm") == "warm" for item in tasks),
        "revalidation_runs": sum(item.get("cold_or_warm") == "revalidation" for item in tasks),
        "reuse_hits": sum(int(item.get("reuse_hits", 0)) for item in tasks),
        "rediscovery": sum(int(item.get("rediscovery", 0)) for item in tasks),
        "decision_context_items": sum(
            int(item.get("uap", {}).get("decision_context_items", 0)) for item in tasks),
        "legacy_store": ProjectIntelligenceStore(root).status(),
    }


def audit_existing(args: argparse.Namespace) -> dict[str, Any]:
    """Independently audit source retained by an already completed benchmark."""
    if not args.output.exists() or not args.workspace.exists():
        raise SystemExit("Existing benchmark output and workspace are required for --audit-existing.")
    payload = json.loads(args.output.read_text(encoding="utf-8"))
    tasks = payload.get("tasks", [])
    if not tasks:
        raise SystemExit("Existing benchmark has no completed tasks to audit.")
    latest = tasks[-1]
    number = int(latest["task_number"])
    root = args.workspace.resolve()
    prior = root / "checkpoints" / f"task-{number - 1}"
    if not prior.exists():
        raise SystemExit(f"Task {number - 1} checkpoint is required for the retained-source audit.")
    before = source_snapshot(prior)
    rows: dict[str, Any] = {}
    for side in ("baseline", "uap"):
        quality = evaluate(root / side, number)
        paths = changed_paths(before, source_snapshot(root / side))
        attach_independent_quality(quality, number, paths)
        rows[side] = quality["independent"]
    quality_equivalent = bool(rows["baseline"]["passed"] and rows["uap"]["passed"])
    payload["posthoc_quality_audit"] = {
        "method": "deterministic_external_quality_v1",
        "tasks": [{"task_number": number, **rows}],
        "quality_equivalent": quality_equivalent,
        "limitation": ("Only the latest paired arm artifacts remain available; earlier task arms "
                       "were intentionally replaced by canonical checkpoints."),
    }
    payload.setdefault("cumulative", {})["quality_adjusted_savings_claimable"] = bool(
        payload["cumulative"].get("savings_claimable") and quality_equivalent)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(payload), encoding="utf-8")
    return payload


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
                       task_number: int, stage: str, result: dict[str, Any]) -> None:
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
            "partial_result": result,
        }
    cumulative_baseline = sum(int(item.get("baseline_tokens", 0)) for item in tasks)
    cumulative_uap = sum(int(item.get("uap_tokens", 0)) for item in tasks)
    break_even = next((int(item["task_number"]) for item in tasks
                       if item.get("comparison_valid")
                       and int(item.get("cumulative_uap", 0)) <= int(item.get("cumulative_baseline", 0))), None)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                            text=True, check=False).stdout.strip() or "unknown"
    uap_root = args.workspace.resolve() / "uap"
    payload = {
        "environment": {"uap": __version__, "commit": commit, "provider": args.provider,
                        "model": args.model, "reasoning": args.reasoning,
                        "canonical_source": args.canonical_source,
                        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "tasks": tasks,
        "interrupted": interruption,
        "cumulative": {"baseline_tokens": cumulative_baseline, "uap_tokens": cumulative_uap,
                       "break_even_task": "NOT_CLAIMABLE", "observed_break_even_task": break_even,
                       "paired_measurement_claimable": False,
                       "savings_claimable": False,
                       "learning_reuse_validated": False,
                       "learning_savings_claimable": False,
                       "comparison_valid_tasks": sum(bool(item.get("comparison_valid")) for item in tasks)},
        "intelligence": longitudinal_intelligence(uap_root, tasks),
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


def source_snapshot(path: Path) -> dict[str, str]:
    """Hash product source while excluding benchmark/runtime state."""
    ignored = {".agent", ".git", ".pytest_cache", "__pycache__", "node_modules"}
    paths = [item.relative_to(path).as_posix() for item in path.rglob("*")
             if item.is_file() and not ignored.intersection(item.relative_to(path).parts)
             and item.relative_to(path).as_posix() != "AGENTS.md"
             and item.suffix not in {".db", ".sqlite", ".sqlite3", ".pyc"}]
    return ProjectIntelligenceStore(path).hash_paths(paths)


def changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def attach_independent_quality(quality: dict[str, Any], task_number: int,
                               paths: list[str]) -> None:
    contract = QUALITY_CONTRACTS[task_number]
    quality["independent"] = assess_implementation_quality(
        quality["checks"], paths, required_checks=contract["checks"],
        expected_prefixes=contract["prefixes"], require_test_change=contract["tests"])


def valid_pair(task: dict[str, Any]) -> bool:
    return bool(
        task["baseline"]["status"] == task["uap"]["status"] == "completed"
        and task["baseline"].get("source_changed") is True
        and task["uap"].get("source_changed") is True
        and paired_models_match(task)
        and task["quality"]["baseline"]["passed"]
        and task["quality"]["uap"]["passed"]
        and task["quality"]["baseline"].get("independent", {}).get("passed", True)
        and task["quality"]["uap"].get("independent", {}).get("passed", True)
        and task["baseline"]["token_source"] == "measured"
        and task["uap"]["token_source"] == "measured"
        and task["baseline"].get("usage_complete") is True
        and task["uap"].get("usage_complete") is True)


def valid_arm(result: dict[str, Any], quality: dict[str, Any]) -> bool:
    """Whether one expensive provider arm can be safely reused on resume."""
    return bool(
        result.get("status") == "completed"
        and result.get("source_changed") is True
        and quality.get("passed") is True
        and result.get("token_source") == "measured"
        and result.get("usage_complete") is True)


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    required_calls = args.rounds * 2
    if args.max_provider_calls != required_calls or args.max_provider_calls > len(TASKS) * 2:
        raise SystemExit("max-provider-calls must equal rounds * 2 and cannot exceed 10.")
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
    resuming = bool(args.resume and workspace.exists() and args.output.exists())
    if workspace.exists() and not resuming:
        shutil.rmtree(workspace)
    canonical, baseline, uap = workspace / "canonical", workspace / "baseline", workspace / "uap"
    checkpoints = workspace / "checkpoints"
    if not resuming:
        seed(canonical)
        reset_source(canonical, baseline)
        reset_source(canonical, uap)
        initialize_project(uap, RESOURCE_ROOT / "templates", auto=True)
        reset_source(canonical, checkpoints / "task-0")
    db = Database(workspace / "uap-history.db")
    resume_payload = (json.loads(args.output.read_text(encoding="utf-8")) if resuming else {})
    tasks: list[dict[str, Any]] = list(resume_payload.get("tasks", []))
    for previous in tasks:
        repair_react_filename_false_negative(previous)
        prior = checkpoints / f"task-{int(previous['task_number']) - 1}"
        if prior.exists():
            previous["baseline"]["source_changed"] = source_snapshot(baseline) != source_snapshot(prior)
            previous["uap"]["source_changed"] = source_snapshot(uap) != source_snapshot(prior)
        previous["comparison_valid"] = valid_pair(previous)
    for previous in tasks:
        run_id = previous.get("uap", {}).get("run_id")
        if run_id and previous.get("uap", {}).get("token_source") == "unavailable":
            measured = db.query("SELECT 1 found FROM token_usage WHERE run_id=? AND token_source='measured' LIMIT 1",
                                (run_id,))
            if measured:
                previous["uap"]["token_source"] = "measured"
                previous["comparison_valid"] = bool(
                    previous["baseline"]["status"] == previous["uap"]["status"] == "completed"
                    and previous["quality"]["baseline"]["passed"] and previous["quality"]["uap"]["passed"]
                    and previous["baseline"]["token_source"] == "measured")

    # The acceptance implementation may have been corrected after the latest
    # paired attempt. Re-evaluate only that task against its retained source;
    # earlier checkpoints are no longer present in the active arm directories.
    if tasks and not tasks[-1].get("comparison_valid"):
        latest = tasks[-1]
        number = int(latest["task_number"])
        prior = checkpoints / f"task-{number - 1}"
        if number == len(tasks) and prior.exists():
            latest["baseline"]["source_changed"] = source_snapshot(baseline) != source_snapshot(prior)
            latest["uap"]["source_changed"] = source_snapshot(uap) != source_snapshot(prior)
            latest["quality"] = {
                "baseline": evaluate(baseline, number),
                "uap": evaluate(uap, number),
            }
            latest["comparison_valid"] = valid_pair(latest)

    first_invalid = next((index for index, item in enumerate(tasks)
                          if not item.get("comparison_valid")), None)
    if first_invalid is not None:
        checkpoint = checkpoints / f"task-{first_invalid}"
        if not checkpoint.exists():
            raise SystemExit(
                f"Cannot safely roll back task {first_invalid + 1}: filesystem checkpoint "
                f"{checkpoint} is unavailable. Start a fresh benchmark workspace."
            )
        invalid = tasks[first_invalid]
        saved_baseline = workspace / ".resume-baseline"
        pending: dict[str, Any] = {}
        if (first_invalid == len(tasks) - 1
                and valid_arm(invalid["baseline"], invalid["quality"]["baseline"])):
            if saved_baseline.exists():
                remove_tree(saved_baseline)
            reset_source(baseline, saved_baseline)
            pending = {"task_number": int(invalid["task_number"]),
                       "goal": invalid["goal"], "baseline": invalid["baseline"]}
        rollback_invalid_runs(db, uap, tasks[first_invalid:])
        tasks = tasks[:first_invalid]
        reset_source(checkpoint, canonical)
        reset_source(canonical, baseline)
        reset_source(canonical, uap, preserve_agent=True)
        if pending:
            reset_source(saved_baseline, baseline)
            remove_tree(saved_baseline)
        resume_payload = {"tasks": tasks, **({"pending": pending} if pending else {})}
        args.output.write_text(json.dumps(resume_payload, indent=2), encoding="utf-8")
    cumulative_baseline = sum(int(item["baseline_tokens"]) for item in tasks)
    cumulative_uap = sum(int(item["uap_tokens"]) for item in tasks)
    break_even = None
    for number, goal in enumerate(TASKS[:args.rounds], 1):
        if number <= len(tasks):
            prior = tasks[number - 1]
            if (all(item.get("comparison_valid") for item in tasks[:number])
                    and int(prior["cumulative_uap"]) <= int(prior["cumulative_baseline"])):
                break_even = break_even or number
            continue
        used_run_ids = {str(item.get("uap", {}).get("run_id") or "") for item in tasks}
        if evaluate(canonical, number)["passed"]:
            raise SystemExit(
                f"Benchmark task {number} acceptance already passes before execution; "
                "the task sequence is not independent.")
        recovered_rows = db.query(
            "SELECT id FROM runs WHERE goal=? AND status='completed' ORDER BY created_at DESC", (goal,))
        recovered_run_id = next((row["id"] for row in recovered_rows
                                 if row["id"] not in used_run_ids), None)
        pending = resume_payload.get("pending", {})
        pending_baseline = (pending.get("baseline") if pending.get("task_number") == number
                            and pending.get("baseline", {}).get("status") == "completed" else None)
        if number > 1:
            if pending_baseline is None:
                reset_source(canonical, baseline)
            if recovered_run_id is None:
                reset_source(canonical, uap, preserve_agent=True)
        before_baseline = source_snapshot(canonical)
        baseline_result = pending_baseline
        if baseline_result is None:
            baseline_result = await baseline_run(
                provider, baseline, goal, args.model, args.reasoning, number)
        if baseline_result["status"] != "completed":
            write_interruption(args, tasks, number, "baseline", baseline_result)
            raise SystemExit(
                f"Provider stopped at task {number} baseline: "
                f"{baseline_result.get('error') or baseline_result['status']}"
            )
        args.output.write_text(json.dumps({"tasks": tasks, "pending": {
            "task_number": number, "goal": goal, "baseline": baseline_result,
        }}, indent=2), encoding="utf-8")
        if recovered_run_id is not None:
            uap_result = summarize_uap_run(db, recovered_run_id, args.provider)
            if not paired_models_match({"baseline": baseline_result, "uap": uap_result}):
                recovered_run_id = None
                reset_source(canonical, uap, preserve_agent=True)
                uap_result = await uap_run(
                    provider, uap, goal, db, args.provider, number, args.model)
        elif pending.get("task_number") == number and pending.get("uap", {}).get("status") == "completed":
            uap_result = pending["uap"]
        else:
            uap_result = await uap_run(
                provider, uap, goal, db, args.provider, number, args.model)
        args.output.write_text(json.dumps({"tasks": tasks, "pending": {
            "task_number": number, "goal": goal, "baseline": baseline_result, "uap": uap_result,
        }}, indent=2), encoding="utf-8")
        baseline_quality, uap_quality = evaluate(baseline, number), evaluate(uap, number)
        baseline_paths = changed_paths(before_baseline, source_snapshot(baseline))
        uap_paths = changed_paths(before_baseline, source_snapshot(uap))
        baseline_result["source_changed"] = bool(baseline_paths)
        uap_result["source_changed"] = bool(uap_paths)
        attach_independent_quality(baseline_quality, number, baseline_paths)
        attach_independent_quality(uap_quality, number, uap_paths)
        baseline_tokens = baseline_result["input_tokens"] + baseline_result["output_tokens"]
        uap_tokens = uap_result["input_tokens"] + uap_result["output_tokens"]
        cumulative_baseline += baseline_tokens
        cumulative_uap += uap_tokens
        comparison_valid = valid_pair({"baseline": baseline_result, "uap": uap_result,
                                       "quality": {"baseline": baseline_quality,
                                                   "uap": uap_quality}})
        if comparison_valid and break_even is None and cumulative_uap <= cumulative_baseline:
            break_even = number
        # Fixed, pre-declared checkpoint rule; token outcome never selects it.
        if baseline_quality["passed"] and uap_quality["passed"]:
            chosen_name = args.canonical_source
        else:
            chosen_name = "baseline" if baseline_quality["passed"] else "uap"
        chosen = baseline if chosen_name == "baseline" else uap
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
                       "canonical_source": chosen_name,
                       "paired_source_files": len(before_baseline)}
        tasks.append(task_result)
        reset_source(canonical, checkpoints / f"task-{number}")
        partial = {"tasks": tasks}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(partial, indent=2), encoding="utf-8")
        if not comparison_valid:
            raise SystemExit(f"Quality or measurement gate failed at task {number}; stopping before task {number + 1}.")

    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                            text=True, check=False).stdout.strip() or "unknown"
    paired_measurement = len(tasks) == args.rounds and all(
        item.get("comparison_valid") for item in tasks)
    learning_reuse = paired_measurement and any(int(item.get("reuse_hits", 0)) > 0 for item in tasks)
    observed_savings = paired_measurement and cumulative_uap < cumulative_baseline
    payload = {"environment": {"uap": __version__, "commit": commit,
                                "provider": args.provider, "model": args.model,
                                "reasoning": args.reasoning,
                                "rounds": args.rounds,
                                "max_provider_calls": args.max_provider_calls,
                                "canonical_source": args.canonical_source,
                                "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
               "tasks": tasks,
               "cumulative": {"baseline_tokens": cumulative_baseline,
                              "uap_tokens": cumulative_uap, "break_even_task": break_even,
                              "paired_measurement_claimable": paired_measurement,
                              "savings_claimable": observed_savings,
                              "learning_reuse_validated": learning_reuse,
                              "learning_savings_claimable": learning_reuse and observed_savings,
                              "comparison_valid_tasks": sum(item["comparison_valid"] for item in tasks)},
               "intelligence": longitudinal_intelligence(uap, tasks)}
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(payload), encoding="utf-8")
    return payload


def main() -> int:
    args = arguments()
    if args.audit_existing:
        payload = audit_existing(args)
        print(json.dumps(payload["posthoc_quality_audit"], indent=2))
        return 0
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
