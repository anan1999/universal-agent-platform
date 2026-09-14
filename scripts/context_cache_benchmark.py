"""Reusable small-to-large experiment isolating compact Project Context value."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from adaptive_agent import __version__
from adaptive_agent.core.execution_packet import ExecutionPacketBuilder
from adaptive_agent.core.models import TaskKind
from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.project.context_index import ProjectContextIndex
from adaptive_agent.providers.registry import providers
from adaptive_agent.storage.database import Database
from scripts.benchmark_harness import Checkpoints, PreparedFixture, experiment_signature, tree_hash

FIXTURE_ROOT = ROOT / "benchmark-fixtures" / "context-cache"
FIXTURE = FIXTURE_ROOT / "base"
ACCEPTANCE = FIXTURE_ROOT / "acceptance.py"
SUITE = json.loads((FIXTURE_ROOT / "suite.json").read_text(encoding="utf-8"))
TASKS = {item["id"]: item for item in SUITE["tasks"]}
GOAL = TASKS["large"]["goal"]


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UAP reusable context scale benchmark")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true",
                        help="confirm real provider calls (two calls per selected task)")
    parser.add_argument("--task", choices=(*TASKS, "all"), default="large")
    parser.add_argument("--resume", action="store_true",
                        help="reuse matching, acceptance-passing arm checkpoints")
    parser.add_argument("--provider", default="codex")
    parser.add_argument("--model")
    parser.add_argument("--reasoning", default="low", choices=("low", "medium", "high", "xhigh"))
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--workspace", type=Path, default=Path("build/context-cache-benchmark"))
    parser.add_argument("--output", type=Path, default=Path("benchmark-results/context-cache-suite.json"))
    parser.add_argument("--report", type=Path, default=Path("docs/context-cache-suite-results.md"))
    return parser.parse_args()


def selected_tasks(args: argparse.Namespace) -> list[dict[str, Any]]:
    task_id = getattr(args, "task", "large")
    return list(SUITE["tasks"]) if task_id == "all" else [TASKS[task_id]]


def source_hash(root: Path) -> str:
    return tree_hash(root)


def seed(destination: Path) -> None:
    """Compatibility helper; real runs use the workspace's prepared fixture."""
    fixture = PreparedFixture(FIXTURE, destination.parent / ".prepared-fixture")
    fixture.prepare()
    fixture._replace_tree(fixture.prepared, destination)


def initialize_context_only(root: Path) -> None:
    (root / ".agent").mkdir(parents=True, exist_ok=True)
    ProjectContextIndex(root).initialize()


def receipt_metrics(receipt, duration: float) -> dict[str, Any]:
    usage = receipt.token_usage
    input_tokens = int(usage.get("input", 0) or 0)
    cached = int(usage.get("cached", 0) or 0)
    output = int(usage.get("output", 0) or 0)
    return {
        "provider_status": receipt.status, "provider": receipt.provider, "model": receipt.model,
        "input_tokens": input_tokens, "cached_input_tokens": cached,
        "non_cached_input_tokens": max(0, input_tokens - cached), "output_tokens": output,
        "total_tokens": input_tokens + output, "token_source": usage.get("source", "unavailable"),
        "usage_complete": usage.get("source") == "measured",
        "duration_seconds": round(duration, 3),
        "ai_invocations": int(usage.get("invocation_count", 1) or 1),
        "provider_tool_calls": usage.get("provider_tool_calls"),
        "provider_messages": usage.get("provider_messages"),
        "files_read": "UNAVAILABLE", "files_changed": receipt.files,
        "error": receipt.error_code or receipt.uncertainty_reason or None,
    }


def acceptance(root: Path, task_id: str = "large") -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(ACCEPTANCE), "--project", str(root), "--task", task_id],
        cwd=ROOT, capture_output=True, text=True, timeout=90, check=False)
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        payload = {"passed": False, "contract": TASKS[task_id]["acceptance_contract"],
                   "error": (result.stdout + result.stderr).strip() or "acceptance produced no JSON"}
    payload["returncode"] = result.returncode
    return payload


def dry_run(args: argparse.Namespace) -> dict[str, Any]:
    workspace = args.workspace.resolve()
    fixture = PreparedFixture(FIXTURE, workspace)
    prepared = fixture.prepare()
    rows: list[dict[str, Any]] = []
    total_creation = 0.0
    for spec in selected_tasks(args):
        baseline = fixture.materialize(spec["id"], "disabled")
        uap = fixture.materialize(spec["id"], "enabled")
        initialize_context_only(baseline)
        started = time.monotonic()
        initialize_context_only(uap)
        creation_seconds = time.monotonic() - started
        total_creation += creation_seconds
        context = ProjectContextIndex(uap).select(spec["goal"])
        rows.append({
            "task_id": spec["id"], "scale": spec["scale"], "goal": spec["goal"],
            "ready": tree_hash(baseline) == tree_hash(uap) == prepared["source_hash"],
            "source_hash": prepared["source_hash"], "pre_task_ai_calls": context.pre_task_ai_calls,
            "project_context_chars": context.context_chars, "relevant_paths": context.relevant_paths,
            "acceptance_contract": spec["acceptance_contract"],
            "expected_surfaces": spec["expected_surfaces"],
            "asset_creation": {"ai_invocations": 0, "duration_seconds": round(creation_seconds, 6)},
        })
    payload: dict[str, Any] = {
        "suite": SUITE["suite"], "schema_version": SUITE["schema_version"],
        "prepared_fixture": prepared, "tasks": rows, "same_uap_execution_path": True,
        "only_variable": "reusable_context_enabled",
        "disabled": {"reusable_context_enabled": False},
        "enabled": {"reusable_context_enabled": True},
        "asset_creation": {"ai_invocations": 0, "duration_seconds": round(total_creation, 6)},
        "provider_calls": 0,
    }
    if len(rows) == 1:
        row = rows[0]
        payload.update({"ready": row["ready"], "same_source_hash": row["source_hash"],
                        "pre_task_ai_calls": row["pre_task_ai_calls"],
                        "project_context_chars": row["project_context_chars"],
                        "relevant_paths": row["relevant_paths"],
                        "baseline_has_index": True, "uap_has_index": True})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _signature(args: argparse.Namespace, spec: dict[str, Any], source: str, arm: str) -> str:
    return experiment_signature({
        "harness_schema": 1, "uap": __version__, "source_hash": source,
        "task_id": spec["id"], "goal": spec["goal"], "arm": arm,
        "reuse_context_enabled": arm == "enabled", "provider": args.provider,
        "model": args.model, "reasoning": args.reasoning, "timeout": args.timeout,
    })


async def _run_arm(args: argparse.Namespace, spec: dict[str, Any], fixture: PreparedFixture,
                   prepared: dict[str, Any], checkpoints: Checkpoints, arm: str) -> dict[str, Any]:
    signature = _signature(args, spec, prepared["source_hash"], arm)
    root = fixture.workspace / "runs" / spec["id"] / arm
    if getattr(args, "resume", False):
        cached = checkpoints.completed(spec["id"], arm, signature)
        if cached is not None and root.is_dir() and acceptance(root, spec["id"])["passed"]:
            print(f"[{spec['id']}/{arm}] resumed verified checkpoint", flush=True)
            return {**cached, "resumed": True}

    root = fixture.materialize(spec["id"], arm)
    initialize_context_only(root)
    provider = providers().create(args.provider, timeout=args.timeout)
    plan_dir = fixture.workspace / "plans" / spec["id"]
    plan_dir.mkdir(parents=True, exist_ok=True)
    composition = Orchestrator(
        Database(plan_dir / f"{arm}.db"), provider, provider_name=args.provider,
        reuse_context=arm == "enabled").compose(
            f"RUN-{spec['id'].upper()}-{arm.upper()}", spec["goal"], str(root),
            "Pocket Expense", "benchmark")
    agent_tasks = [item for item in composition.graph.tasks.values() if item.kind is TaskKind.AGENT]
    if len(agent_tasks) != 1:
        raise RuntimeError(f"{spec['id']}/{arm} expected one AI task, got {len(agent_tasks)}")
    task = agent_tasks[0]
    task.metadata["model"] = args.model
    task.reasoning = args.reasoning
    packet = ExecutionPacketBuilder().build(task, root, "Pocket Expense", "benchmark")
    print(f"[{spec['id']}/{arm}] provider call started (timeout={args.timeout:g}s)", flush=True)
    started = time.monotonic()
    receipt = await provider.execute(task, packet=packet)
    metrics = receipt_metrics(receipt, time.monotonic() - started)
    quality = acceptance(root, spec["id"])
    result = {
        **metrics,
        "status": "completed" if receipt.status == "completed" and quality["passed"] else "failed",
        "quality": quality, "post_source_hash": tree_hash(root), "resumed": False,
        "project_context_chars": int(composition.project_intelligence.get("context_chars", 0)),
        "relevant_paths": composition.project_intelligence.get("relevant_paths", []),
        "pre_task_ai_calls": composition.project_intelligence.get("pre_task_ai_calls", 0),
        "orchestration_wall_ms": composition.project_intelligence.get("orchestration_wall_ms"),
    }
    checkpoints.save(spec["id"], arm, signature, result)
    print(f"[{spec['id']}/{arm}] {result['status']}; acceptance="
          f"{'PASS' if quality['passed'] else 'FAIL'}; usage={metrics['token_source']}", flush=True)
    return result


def _pair(spec: dict[str, Any], baseline: dict[str, Any], uap: dict[str, Any]) -> dict[str, Any]:
    equal_quality = bool(baseline["quality"]["passed"] and uap["quality"]["passed"])
    measured = baseline["token_source"] == "measured" and uap["token_source"] == "measured"
    fewer_tokens = measured and uap["total_tokens"] < baseline["total_tokens"]
    equal_tokens = measured and uap["total_tokens"] == baseline["total_tokens"]
    materially_faster = (baseline["duration_seconds"] > 0
                         and uap["duration_seconds"] <= baseline["duration_seconds"] * 0.9)
    less_repeated_work = fewer_tokens or (equal_tokens and materially_faster)
    conclusion = "YES" if equal_quality and less_repeated_work else (
        "NO" if equal_quality and measured else "INCONCLUSIVE")
    return {
        "task_id": spec["id"], "scale": spec["scale"], "goal": spec["goal"],
        "acceptance_contract": spec["acceptance_contract"],
        "baseline": baseline, "uap": uap, "equal_quality": equal_quality,
        "decision_evidence": {"measured_complete_tokens": measured,
                              "fewer_tokens": fewer_tokens, "equal_tokens": equal_tokens,
                              "materially_faster_10_percent": materially_faster},
        "conclusion": conclusion,
        "claim": ("compact context helped at equal quality" if conclusion == "YES" else
                  "no benefit claim is supported by this pair"),
    }


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    registry = providers()
    if args.provider == "mock" or args.provider not in registry or not registry.get(args.provider).implemented:
        raise SystemExit("A registered real provider is required; Mock is forbidden.")
    probe_provider = registry.create(args.provider, timeout=args.timeout)
    probe = probe_provider.probe()
    if not probe.ready or not probe_provider.capabilities().supports("filesystem", allow_uncertain=False):
        raise SystemExit(f"Provider is not ready for repository work: {probe.detail}")

    workspace = args.workspace.resolve()
    fixture = PreparedFixture(FIXTURE, workspace)
    prepared = fixture.prepare()
    checkpoints = Checkpoints(workspace)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True, check=False).stdout.strip() or "unknown"
    pairs: list[dict[str, Any]] = []
    for spec in selected_tasks(args):
        baseline = await _run_arm(args, spec, fixture, prepared, checkpoints, "disabled")
        uap = await _run_arm(args, spec, fixture, prepared, checkpoints, "enabled")
        pairs.append(_pair(spec, baseline, uap))
        partial = {
            "suite": SUITE["suite"], "environment": {"uap": __version__, "commit": commit,
            "provider": args.provider, "model": args.model, "reasoning": args.reasoning,
            "source_hash": prepared["source_hash"]}, "prepared_fixture": prepared,
            "same_uap_execution_path": True, "only_variable": "reusable_context_enabled",
            "pairs": pairs,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(partial, indent=2), encoding="utf-8")

    conclusive = [pair for pair in pairs if pair["conclusion"] != "INCONCLUSIVE"]
    payload = {
        "suite": SUITE["suite"], "schema_version": SUITE["schema_version"],
        "environment": {"uap": __version__, "commit": commit, "provider": args.provider,
                        "model": args.model, "reasoning": args.reasoning,
                        "source_hash": prepared["source_hash"]},
        "prepared_fixture": prepared, "same_uap_execution_path": True,
        "only_variable": "reusable_context_enabled", "pairs": pairs,
        "summary": {"selected_tasks": len(pairs), "provider_calls_max": len(pairs) * 2,
                    "conclusive_pairs": len(conclusive),
                    "yes": sum(pair["conclusion"] == "YES" for pair in pairs),
                    "no": sum(pair["conclusion"] == "NO" for pair in pairs),
                    "inconclusive": sum(pair["conclusion"] == "INCONCLUSIVE" for pair in pairs)},
    }
    if len(pairs) == 1:
        payload.update(pairs[0])
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render(payload), encoding="utf-8")
    return payload


def render(payload: dict[str, Any]) -> str:
    lines = ["# Reuse-first scale benchmark", "", f"Suite: `{payload['suite']}`", "",
             "| Scale | Task | Baseline acceptance | UAP acceptance | Baseline tokens | UAP tokens | Result |",
             "|---:|---|---:|---:|---:|---:|---|"]
    for pair in payload["pairs"]:
        baseline, uap = pair["baseline"], pair["uap"]
        baseline_tokens = str(baseline["total_tokens"]) if baseline["token_source"] == "measured" else "UNAVAILABLE"
        uap_tokens = str(uap["total_tokens"]) if uap["token_source"] == "measured" else "UNAVAILABLE"
        lines.append(
            f"| {pair['scale']} | {pair['task_id']} | "
            f"{'PASS' if baseline['quality']['passed'] else 'FAIL'} | "
            f"{'PASS' if uap['quality']['passed'] else 'FAIL'} | {baseline_tokens} | {uap_tokens} | "
            f"{pair['conclusion']} |")
    lines.extend(["", "A token comparison is conclusive only when both arms pass acceptance and both "
                  "providers report complete measured usage. Partial timeout telemetry is retained but never "
                  "counted as proof of savings.", ""])
    return "\n".join(lines)


def main() -> int:
    args = arguments()
    if args.dry_run:
        print(json.dumps(dry_run(args), indent=2))
        return 0
    if not args.execute:
        raise SystemExit("Use --dry-run or explicitly pass --execute for real provider calls.")
    print(json.dumps(asyncio.run(execute(args)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
