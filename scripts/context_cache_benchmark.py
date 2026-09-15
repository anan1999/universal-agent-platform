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
from adaptive_agent.core.models import Task, TaskKind, new_id
from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.project.context_index import ProjectContextIndex
from adaptive_agent.providers.registry import providers
from adaptive_agent.storage.database import Database
from scripts.benchmark_harness import (
    Checkpoints, PreparedFixture, changed_files, experiment_signature, tree_hash,
)

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
    parser.add_argument("--reanalyze", action="store_true",
                        help="rerun acceptance and reports from checkpoints with zero provider calls")
    parser.add_argument("--task", choices=(*TASKS, "all"), default="large")
    parser.add_argument("--resume", action="store_true",
                        help="reuse matching, acceptance-passing arm checkpoints")
    parser.add_argument("--early-completion", action="store_true",
                        help="latency experiment only: stop after two acceptance passes; incompatible with exact-token mode")
    parser.add_argument("--metric", choices=("exact-tokens", "latency"), default="exact-tokens",
                        help="primary measurement; exact-tokens rejects runs without provider-reported usage")
    parser.add_argument("--rounds", type=int, default=1,
                        help="paired repetitions; arm order alternates each round")
    parser.add_argument("--max-provider-calls", type=int, default=2,
                        help="hard authorization ceiling checked before setup")
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


def round_plan(args: argparse.Namespace) -> list[tuple[dict[str, Any], int, str, tuple[str, str]]]:
    rounds = int(getattr(args, "rounds", 1))
    if not 1 <= rounds <= 10:
        raise SystemExit("--rounds must be between 1 and 10.")
    plan = []
    for spec in selected_tasks(args):
        for number in range(1, rounds + 1):
            run_key = spec["id"] if rounds == 1 else f"{spec['id']}-r{number}"
            order = ("disabled", "enabled") if number % 2 else ("enabled", "disabled")
            plan.append((spec, number, run_key, order))
    return plan


def enforce_call_ceiling(args: argparse.Namespace) -> int:
    if (getattr(args, "metric", "exact-tokens") == "exact-tokens"
            and bool(getattr(args, "early_completion", False))):
        raise SystemExit(
            "--early-completion interrupts Codex before final usage and cannot be used with "
            "--metric exact-tokens. Use normal completion or explicitly select --metric latency.")
    planned = len(round_plan(args)) * 2
    ceiling = int(getattr(args, "max_provider_calls", 2))
    if planned > ceiling:
        raise SystemExit(
            f"Plan requires {planned} provider calls; explicitly set --max-provider-calls {planned}.")
    return planned


def source_hash(root: Path) -> str:
    return tree_hash(root)


def seed(destination: Path) -> None:
    """Compatibility helper; real runs use the workspace's prepared fixture."""
    fixture = PreparedFixture(FIXTURE, destination.parent)
    fixture.prepare()
    fixture._replace_tree(fixture.prepared, destination)


def initialize_context_only(root: Path) -> None:
    (root / ".agent").mkdir(parents=True, exist_ok=True)
    ProjectContextIndex(root).initialize()


def task(root: Path, model: str | None, reasoning: str, goal: str = GOAL) -> Task:
    """Compatibility constructor shared by the older benchmark tools."""
    return Task(
        new_id("TASK"), new_id("RUN"), goal, "single_executor",
        ["coding", "frontend_implementation", "testing"], reasoning=reasoning,
        metadata={"goal": goal, "working_directory": str(root), "model": model,
                  "read_only": False}, kind=TaskKind.AGENT,
    )


def receipt_metrics(receipt, duration: float) -> dict[str, Any]:
    usage = receipt.token_usage
    input_tokens = int(usage.get("input", 0) or 0)
    cached = int(usage.get("cached", 0) or 0)
    output = int(usage.get("output", 0) or 0)
    reported_total = usage.get("total")
    total = (int(reported_total) if isinstance(reported_total, (int, float))
             else input_tokens + output)
    return {
        "provider_status": receipt.status, "provider": receipt.provider, "model": receipt.model,
        "input_tokens": input_tokens, "cached_input_tokens": cached,
        "non_cached_input_tokens": max(0, input_tokens - cached), "output_tokens": output,
        "reasoning_output_tokens": int(usage.get("reasoning_output", 0) or 0),
        "cache_write_input_tokens": int(usage.get("cache_write_input", 0) or 0),
        "total_tokens": total, "token_source": usage.get("source", "unavailable"),
        "usage_complete": usage.get("source") == "measured",
        "duration_seconds": round(duration, 3),
        "ai_invocations": int(usage.get("invocation_count", 1) or 1),
        "provider_tool_calls": usage.get("provider_tool_calls"),
        "provider_messages": usage.get("provider_messages"),
        "completion": dict(receipt.completion),
        "provider_protocol_status": receipt.completion.get(
            "provider", "completed" if receipt.status == "completed" else receipt.status),
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


def _signature(args: argparse.Namespace, spec: dict[str, Any], source: str, arm: str,
               run_key: str | None = None) -> str:
    payload = {
        "harness_schema": 1, "uap": __version__, "source_hash": source,
        "task_id": spec["id"], "goal": spec["goal"], "arm": arm,
        "reuse_context_enabled": arm == "enabled", "provider": args.provider,
        "model": args.model, "reasoning": args.reasoning, "timeout": args.timeout,
        "early_completion": bool(getattr(args, "early_completion", False)),
        "metric": getattr(args, "metric", "exact-tokens"),
    }
    if run_key and run_key != spec["id"]:
        payload["round_key"] = run_key
    return experiment_signature(payload)


async def _run_arm(args: argparse.Namespace, spec: dict[str, Any], fixture: PreparedFixture,
                   prepared: dict[str, Any], checkpoints: Checkpoints, arm: str,
                   run_key: str | None = None) -> dict[str, Any]:
    key = run_key or spec["id"]
    signature = _signature(args, spec, prepared["source_hash"], arm, key)
    root = fixture.workspace / "runs" / key / arm
    if getattr(args, "resume", False):
        cached = checkpoints.completed(key, arm, signature)
        if cached is not None and root.is_dir() and acceptance(root, spec["id"])["passed"]:
            print(f"[{key}/{arm}] resumed verified checkpoint", flush=True)
            return {**cached, "resumed": True}

    root = fixture.materialize(key, arm)
    initialize_context_only(root)
    provider = providers().create(args.provider, timeout=args.timeout)
    plan_dir = fixture.workspace / "plans" / key
    plan_dir.mkdir(parents=True, exist_ok=True)
    composition = Orchestrator(
        Database(plan_dir / f"{arm}.db"), provider, provider_name=args.provider,
        reuse_context=arm == "enabled").compose(
            f"RUN-{key.upper()}-{arm.upper()}", spec["goal"], str(root),
            "Pocket Expense", "benchmark")
    agent_tasks = [item for item in composition.graph.tasks.values() if item.kind is TaskKind.AGENT]
    if len(agent_tasks) != 1:
        raise RuntimeError(f"{key}/{arm} expected one AI task, got {len(agent_tasks)}")
    task = agent_tasks[0]
    task.metadata["model"] = args.model
    task.reasoning = args.reasoning
    early_completion = bool(getattr(args, "early_completion", False))
    if early_completion:
        task.metadata.setdefault("execution_budget", {}).update({
            "completion_probe_passes": 2,
            "completion_probe_grace_seconds": 1.0,
        })
    packet = ExecutionPacketBuilder().build(task, root, "Pocket Expense", "benchmark")
    print(f"[{key}/{arm}] provider call started (timeout={args.timeout:g}s)", flush=True)
    started = time.monotonic()
    probe = (lambda: acceptance(root, spec["id"])["passed"]) if early_completion else None
    receipt = await provider.execute(task, packet=packet, completion_probe=probe)
    metrics = receipt_metrics(receipt, time.monotonic() - started)
    quality = acceptance(root, spec["id"])
    exact_required = getattr(args, "metric", "exact-tokens") == "exact-tokens"
    exact_available = metrics["token_source"] == "measured"
    result = {
        **metrics,
        "status": ("completed" if receipt.status == "completed" and quality["passed"]
                   and (exact_available or not exact_required) else
                   "invalid_exact_usage" if receipt.status == "completed" and quality["passed"]
                   else "failed"),
        "quality": quality, "post_source_hash": tree_hash(root), "resumed": False,
        "files_changed": changed_files(fixture.prepared, root),
        "project_context_chars": int(composition.project_intelligence.get("context_chars", 0)),
        "relevant_paths": composition.project_intelligence.get("relevant_paths", []),
        "pre_task_ai_calls": composition.project_intelligence.get("pre_task_ai_calls", 0),
        "orchestration_wall_ms": composition.project_intelligence.get("orchestration_wall_ms"),
    }
    checkpoints.save(key, arm, signature, result)
    print(f"[{key}/{arm}] {result['status']}; acceptance="
          f"{'PASS' if quality['passed'] else 'FAIL'}; usage={metrics['token_source']}", flush=True)
    return result


def _pair(spec: dict[str, Any], baseline: dict[str, Any], uap: dict[str, Any],
          round_number: int = 1, order: tuple[str, str] = ("disabled", "enabled")) -> dict[str, Any]:
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
        "task_id": spec["id"], "scale": spec["scale"], "round": round_number,
        "order": list(order), "goal": spec["goal"],
        "acceptance_contract": spec["acceptance_contract"],
        "baseline": baseline, "uap": uap, "equal_quality": equal_quality,
        "decision_evidence": {"measured_complete_tokens": measured,
                              "fewer_tokens": fewer_tokens, "equal_tokens": equal_tokens,
                              "materially_faster_10_percent": materially_faster},
        "conclusion": conclusion,
        "claim": ("compact context helped at equal quality" if conclusion == "YES" else
                  "no benefit claim is supported by this pair"),
    }


def aggregate_pairs(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [pair for pair in pairs if pair["equal_quality"]]
    baseline_seconds = sum(pair["baseline"]["duration_seconds"] for pair in accepted)
    uap_seconds = sum(pair["uap"]["duration_seconds"] for pair in accepted)
    duration_reduction = (None if baseline_seconds <= 0 else
                          round((baseline_seconds - uap_seconds) / baseline_seconds * 100, 2))
    all_tools = [pair[arm].get("provider_tool_calls")
                 for pair in accepted for arm in ("baseline", "uap")]
    measured = [pair for pair in accepted
                if pair["decision_evidence"]["measured_complete_tokens"]]
    return {
        "accepted_pairs": len(accepted),
        "uap_faster_pairs": sum(
            pair["uap"]["duration_seconds"] < pair["baseline"]["duration_seconds"]
            for pair in accepted),
        "baseline_duration_seconds": round(baseline_seconds, 3),
        "uap_duration_seconds": round(uap_seconds, 3),
        "uap_duration_reduction_percent": duration_reduction,
        "baseline_tool_calls": (sum(pair["baseline"]["provider_tool_calls"] for pair in accepted)
                                if accepted and all(value is not None for value in all_tools) else None),
        "uap_tool_calls": (sum(pair["uap"]["provider_tool_calls"] for pair in accepted)
                           if accepted and all(value is not None for value in all_tools) else None),
        "artifact_probe_stops": sum(
            pair[arm].get("provider_protocol_status") == "stopped"
            for pair in pairs for arm in ("baseline", "uap")),
        "provider_timeouts": sum(
            pair[arm].get("error") == "CODEX_TIMEOUT"
            for pair in pairs for arm in ("baseline", "uap")),
        "complete_measured_pairs": len(measured),
        "token_comparison_available": len(measured) == len(accepted) and bool(accepted),
    }


def reanalyze(args: argparse.Namespace) -> dict[str, Any]:
    """Re-evaluate durable artifacts after an acceptance/reporting correction."""
    workspace = args.workspace.resolve()
    fixture = PreparedFixture(FIXTURE, workspace)
    prepared = fixture.prepare()
    checkpoints = Checkpoints(workspace)
    try:
        previous_environment = json.loads(args.output.read_text(encoding="utf-8")).get("environment", {})
    except (OSError, ValueError, json.JSONDecodeError):
        previous_environment = {}
    execution_commit = (previous_environment.get("execution_commit")
                        or previous_environment.get("commit"))
    if not execution_commit:
        execution_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
            text=True, check=False).stdout.strip() or "unknown"
    pairs: list[dict[str, Any]] = []
    for spec, round_number, run_key, order in round_plan(args):
        arms: dict[str, dict[str, Any]] = {}
        for arm in ("disabled", "enabled"):
            signature = _signature(args, spec, prepared["source_hash"], arm, run_key)
            result = checkpoints.load(run_key, arm, signature)
            root = workspace / "runs" / run_key / arm
            if result is None or not root.is_dir():
                raise SystemExit(f"No matching checkpoint for {run_key}/{arm}.")
            quality = acceptance(root, spec["id"])
            result = {**result, "quality": quality,
                      "status": ("completed" if result.get("provider_status") == "completed"
                                 and quality["passed"] else "failed"),
                      "files_changed": changed_files(fixture.prepared, root)}
            checkpoints.save(run_key, arm, signature, result)
            arms[arm] = result
        pairs.append(_pair(spec, arms["disabled"], arms["enabled"], round_number, order))
    historical_calls = sum(
        int(pair[arm].get("ai_invocations", 0) or 0)
        for pair in pairs for arm in ("baseline", "uap"))
    payload = {
        "suite": SUITE["suite"], "schema_version": SUITE["schema_version"],
        "environment": {"uap": __version__, "execution_commit": execution_commit,
                        "provider": args.provider, "model": args.model,
                        "reasoning": args.reasoning, "source_hash": prepared["source_hash"]},
        "prepared_fixture": prepared, "same_uap_execution_path": True,
        "only_variable": "reusable_context_enabled", "provider_calls": 0,
        "historical_provider_calls": historical_calls, "pairs": pairs,
        "summary": {"selected_tasks": len(selected_tasks(args)),
                    "rounds": int(getattr(args, "rounds", 1)), "pairs": len(pairs),
                    "reanalyze_provider_calls": 0,
                    "historical_provider_calls": historical_calls,
                    "conclusive_pairs": sum(p["conclusion"] != "INCONCLUSIVE" for p in pairs),
                    "yes": sum(p["conclusion"] == "YES" for p in pairs),
                    "no": sum(p["conclusion"] == "NO" for p in pairs),
                    "inconclusive": sum(p["conclusion"] == "INCONCLUSIVE" for p in pairs),
                    "observed": aggregate_pairs(pairs)},
    }
    if len(pairs) == 1:
        payload.update(pairs[0])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.report.write_text(render(payload), encoding="utf-8")
    return payload


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    planned_calls = enforce_call_ceiling(args)
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
    for spec, round_number, run_key, order in round_plan(args):
        arms: dict[str, dict[str, Any]] = {}
        for arm in order:
            arms[arm] = await _run_arm(
                args, spec, fixture, prepared, checkpoints, arm, run_key)
        pairs.append(_pair(
            spec, arms["disabled"], arms["enabled"], round_number, order))
        partial = {
            "suite": SUITE["suite"], "environment": {"uap": __version__, "commit": commit,
            "execution_commit": commit,
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
        "environment": {"uap": __version__, "commit": commit, "execution_commit": commit,
                        "provider": args.provider,
                        "model": args.model, "reasoning": args.reasoning,
                        "source_hash": prepared["source_hash"]},
        "prepared_fixture": prepared, "same_uap_execution_path": True,
        "only_variable": "reusable_context_enabled", "pairs": pairs,
        "summary": {"selected_tasks": len(selected_tasks(args)), "rounds": int(getattr(args, "rounds", 1)),
                    "pairs": len(pairs), "provider_calls_max": planned_calls,
                    "provider_calls_actual": sum(
                        not pair[arm].get("resumed", False)
                        for pair in pairs for arm in ("baseline", "uap")),
                    "conclusive_pairs": len(conclusive),
                    "yes": sum(pair["conclusion"] == "YES" for pair in pairs),
                    "no": sum(pair["conclusion"] == "NO" for pair in pairs),
                    "inconclusive": sum(pair["conclusion"] == "INCONCLUSIVE" for pair in pairs)},
    }
    payload["summary"]["observed"] = aggregate_pairs(pairs)
    if len(pairs) == 1:
        payload.update(pairs[0])
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render(payload), encoding="utf-8")
    return payload


def render(payload: dict[str, Any]) -> str:
    lines = ["# Reuse-first scale benchmark", "", f"Suite: `{payload['suite']}`", "",
             "| Scale | Task | Round | Order | Baseline acceptance | UAP acceptance | Baseline tokens | UAP tokens | Result |",
             "|---:|---|---:|---|---:|---:|---:|---:|---|"]
    for pair in payload["pairs"]:
        baseline, uap = pair["baseline"], pair["uap"]
        baseline_tokens = str(baseline["total_tokens"]) if baseline["token_source"] == "measured" else "UNAVAILABLE"
        uap_tokens = str(uap["total_tokens"]) if uap["token_source"] == "measured" else "UNAVAILABLE"
        lines.append(
            f"| {pair['scale']} | {pair['task_id']} | {pair.get('round', 1)} | "
            f"{' → '.join(pair.get('order', ['disabled', 'enabled']))} | "
            f"{'PASS' if baseline['quality']['passed'] else 'FAIL'} | "
            f"{'PASS' if uap['quality']['passed'] else 'FAIL'} | {baseline_tokens} | {uap_tokens} | "
            f"{pair['conclusion']} |")
    for pair in payload["pairs"]:
        lines.extend(["", f"## {pair['task_id']} detail", ""])
        for label, key in (("Baseline", "baseline"), ("UAP", "uap")):
            row = pair[key]
            lines.append(
                f"- {label}: provider `{row['provider_status']}`, acceptance "
                f"`{'PASS' if row['quality']['passed'] else 'FAIL'}`, token source "
                f"`{row['token_source']}`, duration {row['duration_seconds']}s, "
                f"non-cached input {row['non_cached_input_tokens']}, cached input "
                f"{row['cached_input_tokens']}, output {row['output_tokens']}, tools "
                f"{row['provider_tool_calls'] if row['provider_tool_calls'] is not None else 'UNAVAILABLE'}, "
                f"messages {row['provider_messages'] if row['provider_messages'] is not None else 'UNAVAILABLE'}, "
                f"protocol `{row.get('provider_protocol_status', row['provider_status'])}`, "
                f"error `{row['error'] or 'none'}`.")
        lines.append(f"- Conclusion: `{pair['conclusion']}` — {pair['claim']}.")
    observed = payload.get("summary", {}).get("observed", {})
    if observed:
        lines.extend([
            "", "## Pooled observations", "",
            f"- Accepted pairs: {observed['accepted_pairs']}.",
            f"- UAP faster pairs: {observed['uap_faster_pairs']}.",
            f"- Provider duration: baseline {observed['baseline_duration_seconds']}s; "
            f"UAP {observed['uap_duration_seconds']}s; reduction "
            f"{observed['uap_duration_reduction_percent']}%.",
            f"- Tool calls: baseline {observed['baseline_tool_calls']}; UAP {observed['uap_tool_calls']}.",
            f"- Artifact-probe stops: {observed['artifact_probe_stops']}; provider timeouts: "
            f"{observed['provider_timeouts']}.",
            f"- Exact token comparison available: {observed['token_comparison_available']}.",
        ])
    lines.extend(["", "A token comparison is conclusive only when both arms pass acceptance and both "
                  "providers report complete measured usage. Partial timeout telemetry is retained but never "
                  "counted as proof of savings.",
                  "", "Exact formulas: total = input + output; non-cached input = input - cached input. "
                  "Reasoning output is a subset of output and is not added again.", ""])
    return "\n".join(lines)


def main() -> int:
    args = arguments()
    if args.dry_run:
        print(json.dumps(dry_run(args), indent=2))
        return 0
    if args.reanalyze:
        print(json.dumps(reanalyze(args), indent=2))
        return 0
    if not args.execute:
        raise SystemExit("Use --dry-run or explicitly pass --execute for real provider calls.")
    print(json.dumps(asyncio.run(execute(args)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
