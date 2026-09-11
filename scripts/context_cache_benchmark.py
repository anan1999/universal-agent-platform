"""One-pair experiment isolating compact Project Context value."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
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
from adaptive_agent.core.models import Task, TaskKind, new_id
from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.project.context_index import ProjectContextIndex
from adaptive_agent.providers.registry import providers
from adaptive_agent.storage.database import Database


GOAL = (
    "Add a GET /reports/monthly/{month} API endpoint that returns the selected month, total "
    "spending, and totals by category, then display that monthly total and category breakdown "
    "in the existing React dashboard. Preserve existing expense behavior and validate the work."
)
FIXTURE = ROOT / "benchmark-fixtures" / "context-cache" / "base"
ACCEPTANCE = ROOT / "benchmark-fixtures" / "context-cache" / "acceptance.py"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UAP compact context one-pair benchmark")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true",
                        help="confirm that exactly two real provider calls may be used")
    parser.add_argument("--provider", default="codex")
    parser.add_argument("--model")
    parser.add_argument("--reasoning", default="low", choices=("low", "medium", "high", "xhigh"))
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--workspace", type=Path, default=Path("build/context-cache-benchmark"))
    parser.add_argument("--output", type=Path, default=Path("benchmark-results/context-cache-pair.json"))
    parser.add_argument("--report", type=Path, default=Path("docs/context-cache-pair-results.md"))
    return parser.parse_args()


def source_hash(root: Path) -> str:
    digest = hashlib.sha256()
    ignored = {".agent", ".git", "__pycache__", ".pytest_cache", "node_modules", "expenses.sqlite3"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in ignored for part in path.relative_to(root).parts):
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def seed(destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(FIXTURE, destination)


def initialize_context_only(root: Path) -> None:
    """Create only the treatment under test; do not alter shared source."""
    (root / ".agent").mkdir(parents=True, exist_ok=True)
    ProjectContextIndex(root).initialize()


def task(root: Path, model: str | None, reasoning: str) -> Task:
    return Task(new_id("TASK"), new_id("RUN"), GOAL, "single_executor",
                ["coding", "frontend_implementation", "testing"], reasoning=reasoning,
                metadata={"goal": GOAL, "working_directory": str(root), "model": model,
                          "read_only": False}, kind=TaskKind.AGENT)


def receipt_metrics(receipt, duration: float) -> dict[str, Any]:
    usage = receipt.token_usage
    input_tokens = int(usage.get("input", 0) or 0)
    cached = int(usage.get("cached", 0) or 0)
    output = int(usage.get("output", 0) or 0)
    return {"status": receipt.status, "provider": receipt.provider, "model": receipt.model,
            "input_tokens": input_tokens, "cached_input_tokens": cached,
            "non_cached_input_tokens": max(0, input_tokens - cached),
            "output_tokens": output, "total_tokens": input_tokens + output,
            "token_source": usage.get("source", "unavailable"), "duration_seconds": round(duration, 3),
            "ai_invocations": 1, "files_read": "UNAVAILABLE", "files_changed": receipt.files,
            "error": receipt.error_code or receipt.uncertainty_reason or None}


def acceptance(root: Path) -> dict[str, Any]:
    result = subprocess.run([sys.executable, str(ACCEPTANCE), "--project", str(root)],
                            cwd=ROOT, capture_output=True, text=True, timeout=90, check=False)
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        payload = {"passed": False, "contract": "context-cache-monthly-v1",
                   "error": (result.stdout + result.stderr).strip() or "acceptance produced no JSON"}
    payload["returncode"] = result.returncode
    return payload


def dry_run(args: argparse.Namespace) -> dict[str, Any]:
    workspace = args.workspace.resolve()
    baseline, uap = workspace / "baseline", workspace / "uap"
    seed(baseline)
    seed(uap)
    initialize_context_only(uap)
    context = ProjectContextIndex(uap).select(GOAL)
    payload = {"ready": source_hash(baseline) == source_hash(uap),
               "same_source_hash": source_hash(baseline),
               "pre_task_ai_calls": context.pre_task_ai_calls,
               "project_context_chars": context.context_chars,
               "relevant_paths": context.relevant_paths,
               "baseline_has_index": False, "uap_has_index": True,
               "provider_calls": 0}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    registry = providers()
    if args.provider == "mock" or args.provider not in registry or not registry.get(args.provider).implemented:
        raise SystemExit("A registered real provider is required; Mock is forbidden.")
    baseline_provider = registry.create(args.provider, timeout=args.timeout)
    probe = baseline_provider.probe()
    if not probe.ready or not baseline_provider.capabilities().supports("filesystem", allow_uncertain=False):
        raise SystemExit(f"Provider is not ready for repository work: {probe.detail}")
    # Separate provider instances make the two executions fresh sessions even
    # when an adapter later gains process-local state.
    uap_provider = registry.create(args.provider, timeout=args.timeout)

    workspace = args.workspace.resolve()
    baseline, uap = workspace / "baseline", workspace / "uap"
    seed(baseline)
    seed(uap)
    initialize_context_only(uap)
    baseline_hash, uap_hash = source_hash(baseline), source_hash(uap)
    if baseline_hash != uap_hash:
        raise SystemExit("Baseline and UAP application source differ before execution.")

    baseline_task = task(baseline, args.model, args.reasoning)
    baseline_packet = ExecutionPacketBuilder().build(
        baseline_task, baseline, "Pocket Expense", "benchmark")
    started = time.monotonic()
    baseline_receipt = await baseline_provider.execute(baseline_task, packet=baseline_packet)
    baseline_metrics = receipt_metrics(baseline_receipt, time.monotonic() - started)

    db = Database(workspace / "uap-plan.db")
    composition = Orchestrator(db, uap_provider, provider_name=args.provider).compose(
        "RUN-CONTEXT-PAIR", GOAL, str(uap), "Pocket Expense", "benchmark")
    agent_tasks = [item for item in composition.graph.tasks.values() if item.kind is TaskKind.AGENT]
    if len(agent_tasks) != 1:
        raise SystemExit(f"Simplified UAP must produce exactly one AI task, got {len(agent_tasks)}")
    uap_task = agent_tasks[0]
    uap_task.metadata["model"] = args.model
    uap_task.reasoning = args.reasoning
    uap_packet = ExecutionPacketBuilder().build(
        uap_task, uap, "Pocket Expense", "benchmark",
        allowed_files=list(composition.project_intelligence.get("relevant_paths", [])))
    started = time.monotonic()
    uap_receipt = await uap_provider.execute(uap_task, packet=uap_packet)
    uap_metrics = receipt_metrics(uap_receipt, time.monotonic() - started)

    baseline_quality, uap_quality = acceptance(baseline), acceptance(uap)
    equal_quality = bool(baseline_quality["passed"] and uap_quality["passed"])
    context_chars = int(composition.project_intelligence.get("context_chars", 0))
    measured = (baseline_metrics["token_source"] == "measured"
                and uap_metrics["token_source"] == "measured")
    fewer_tokens = measured and uap_metrics["total_tokens"] < baseline_metrics["total_tokens"]
    equal_tokens = measured and uap_metrics["total_tokens"] == baseline_metrics["total_tokens"]
    materially_faster = (baseline_metrics["duration_seconds"] > 0
                         and uap_metrics["duration_seconds"]
                         <= baseline_metrics["duration_seconds"] * 0.9)
    less_repeated_work = fewer_tokens or (equal_tokens and materially_faster)
    conclusion = ("YES" if equal_quality and less_repeated_work else
                  ("NO" if equal_quality and measured else "INCONCLUSIVE"))
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True, check=False).stdout.strip() or "unknown"
    payload = {
        "environment": {"uap": __version__, "commit": commit, "provider": args.provider,
                        "model": args.model, "reasoning": args.reasoning,
                        "task": GOAL, "source_hash": baseline_hash},
        "baseline": {**baseline_metrics, "quality": baseline_quality},
        "uap": {**uap_metrics, "quality": uap_quality,
                "project_context_chars": context_chars,
                "relevant_paths": composition.project_intelligence.get("relevant_paths", []),
                "pre_task_ai_calls": composition.project_intelligence.get("pre_task_ai_calls", 0),
                "orchestration_wall_ms": composition.project_intelligence.get("orchestration_wall_ms")},
        "equal_quality": equal_quality,
        "decision_evidence": {"measured_tokens": measured, "fewer_tokens": fewer_tokens,
                              "equal_tokens": equal_tokens,
                              "materially_faster_10_percent": materially_faster},
        "conclusion": conclusion,
        "claim": ("compact context helped at equal quality" if conclusion == "YES" else
                  "no benefit claim is supported by this pair"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.report.write_text(render(payload), encoding="utf-8")
    return payload


def render(payload: dict[str, Any]) -> str:
    baseline, uap = payload["baseline"], payload["uap"]
    return "\n".join([
        "# Compact Project Context benchmark", "", f"Task: {payload['environment']['task']}", "",
        "| Metric | Baseline | UAP |", "|---|---:|---:|",
        f"| Acceptance | {'PASS' if baseline['quality']['passed'] else 'FAIL'} | {'PASS' if uap['quality']['passed'] else 'FAIL'} |",
        f"| Input tokens | {baseline['input_tokens']} | {uap['input_tokens']} |",
        f"| Cached input | {baseline['cached_input_tokens']} | {uap['cached_input_tokens']} |",
        f"| Output tokens | {baseline['output_tokens']} | {uap['output_tokens']} |",
        f"| Total tokens | {baseline['total_tokens']} | {uap['total_tokens']} |",
        f"| Duration seconds | {baseline['duration_seconds']} | {uap['duration_seconds']} |",
        f"| AI invocations | {baseline['ai_invocations']} | {uap['ai_invocations']} |", "",
        f"Project context: {uap['project_context_chars']} chars; paths: {', '.join(uap['relevant_paths'])}.",
        f"Pre-task AI calls: {uap['pre_task_ai_calls']}.",
        f"Conclusion: **{payload['conclusion']}** — {payload['claim']}.", "",
        "This is one ordered pair. Provider-side caching and unavailable file-read telemetry remain limitations.",
    ]) + "\n"


def main() -> int:
    args = arguments()
    if args.dry_run:
        print(json.dumps(dry_run(args), indent=2))
        return 0
    if not args.execute:
        raise SystemExit("Use --dry-run or explicitly pass --execute for the two real provider calls.")
    print(json.dumps(asyncio.run(execute(args)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
