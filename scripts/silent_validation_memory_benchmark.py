"""Paired benchmark for silent, amortized validation-command selection."""
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

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from budget_benchmark import _totals
from context_cache_benchmark import ACCEPTANCE, FIXTURE, GOAL, acceptance, source_hash, task
from direct_benchmark import MeteredCodex
from pi_budget_benchmark import PiBudgetPacket
from adaptive_agent.core.tools import ToolExecutor, ToolRegistry
from adaptive_agent.project.direct import prepare
from adaptive_agent.project.experience import OperationExperience


ARMS = ("cold_candidates", "silent_memory")


def _percent(before: float, after: float) -> float | None:
    return round((before - after) / before * 100, 2) if before else None


def summarize(rounds: list[dict]) -> dict:
    rows = []
    for current in rounds:
        cold = _totals(current["results"]["cold_candidates"])
        warm = _totals(current["results"]["silent_memory"])
        rows.append({
            "round": current["round"], "order": current["order"],
            "cold_quality": current["results"]["cold_candidates"]["quality"]["passed"],
            "warm_quality": current["results"]["silent_memory"]["quality"]["passed"],
            "total_token_reduction_percent": _percent(cold["tokens"], warm["tokens"]),
            "uncached_token_reduction_percent": _percent(
                cold["uncached_tokens"], warm["uncached_tokens"]),
            "tool_call_delta": cold["tool_calls"] - warm["tool_calls"],
            "message_delta": cold["assistant_messages"] - warm["assistant_messages"],
            "time_reduction_percent": _percent(
                current["results"]["cold_candidates"]["duration_seconds"],
                current["results"]["silent_memory"]["duration_seconds"]),
            "cold_candidates": cold, "silent_memory": warm,
        })
    pooled = {
        arm: {key: sum(row[arm][key] for row in rows)
              for key in ("tokens", "uncached_tokens", "tool_calls", "assistant_messages",
                          "assistant_message_chars")}
        for arm in ARMS
    }
    for arm in ARMS:
        pooled[arm]["seconds"] = round(sum(
            item["results"][arm]["duration_seconds"] for item in rounds), 3)
    return {
        "rounds_completed": len(rows),
        "cold_quality_passes": sum(row["cold_quality"] for row in rows),
        "warm_quality_passes": sum(row["warm_quality"] for row in rows),
        "pooled": pooled,
        "pooled_total_token_reduction_percent": _percent(
            pooled["cold_candidates"]["tokens"], pooled["silent_memory"]["tokens"]),
        "pooled_uncached_token_reduction_percent": _percent(
            pooled["cold_candidates"]["uncached_tokens"], pooled["silent_memory"]["uncached_tokens"]),
        "pooled_tool_call_reduction_percent": _percent(
            pooled["cold_candidates"]["tool_calls"], pooled["silent_memory"]["tool_calls"]),
        "pooled_message_reduction_percent": _percent(
            pooled["cold_candidates"]["assistant_messages"], pooled["silent_memory"]["assistant_messages"]),
        "pooled_time_reduction_percent": _percent(
            pooled["cold_candidates"]["seconds"], pooled["silent_memory"]["seconds"]),
        "rows": rows,
    }


def render(report: dict) -> str:
    summary = report["summary"]
    lines = ["# Silent validation-memory benchmark", "",
             "The cold arm receives three validation candidates. After one zero-AI successful check, the warm arm receives the same context shape with only the proven candidate.", "",
             "| Round | Order | Cold quality | Warm quality | Total reduction | Uncached reduction | Tool delta | Message delta | Time reduction |",
             "|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in summary["rows"]:
        lines.append(
            f"| {row['round']} | {' → '.join(row['order'])} | "
            f"{'PASS' if row['cold_quality'] else 'FAIL'} | {'PASS' if row['warm_quality'] else 'FAIL'} | "
            f"{row['total_token_reduction_percent']}% | {row['uncached_token_reduction_percent']}% | "
            f"{row['tool_call_delta']:+d} | {row['message_delta']:+d} | {row['time_reduction_percent']}% |")
    lines.extend(["", "## Aggregate", "",
                  f"- Cold quality: {summary['cold_quality_passes']}/{summary['rounds_completed']}",
                  f"- Silent-memory quality: {summary['warm_quality_passes']}/{summary['rounds_completed']}",
                  f"- Pooled total-token reduction: {summary['pooled_total_token_reduction_percent']}%",
                  f"- Pooled uncached-token reduction: {summary['pooled_uncached_token_reduction_percent']}%",
                  f"- Pooled tool-call reduction: {summary['pooled_tool_call_reduction_percent']}%",
                  f"- Pooled assistant-message reduction: {summary['pooled_message_reduction_percent']}%",
                  f"- Pooled time reduction: {summary['pooled_time_reduction_percent']}%", "",
                  "Positive values favor silent validation memory. Quality remains a hard gate."])
    return "\n".join(lines) + "\n"


def save(rounds: list[dict], args: argparse.Namespace) -> dict:
    report = {"experiment": "cold_candidates_vs_silent_validation_memory",
              "goal": GOAL, "model": args.model, "reasoning": "low",
              "summary": summarize(rounds), "rounds": rounds,
              "limitations": ["Three-round screening on one task family.",
                              "Training checks are zero-AI but still consume local wall time.",
                              "Subscription quota and hidden reasoning are unavailable."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render(report), encoding="utf-8")
    return report


def _configure(root: Path) -> None:
    agent = root / ".agent"
    agent.mkdir()
    commands = {"commands": {
        "test": {"command": [sys.executable, "-m", "pytest", "-q",
                             "--basetemp=.agent/pytest-tmp"], "timeout": 90},
        "build": {"command": [sys.executable, "-m", "compileall", "-q", "app"], "timeout": 90},
        "frontend_build": {"command": [sys.executable, "-c",
                                         "from pathlib import Path; assert Path('frontend/src/App.jsx').is_file()"],
                           "timeout": 30},
    }}
    (agent / "commands.yaml").write_text(yaml.safe_dump(commands, sort_keys=False), encoding="utf-8")


def _train_pair(roots: dict[str, Path]) -> dict:
    evidence = {}
    for arm, root in roots.items():
        store = OperationExperience(root)
        before = store.fingerprint()
        started = time.perf_counter()
        result = ToolExecutor(ToolRegistry.default(), root).run("project_test")
        if result.status != "completed" or result.exit_code != 0:
            raise RuntimeError(f"{arm} training check failed: {result.summary}")
        saved = store.record(result, before) if arm == "silent_memory" else False
        evidence[arm] = {"seconds": round(time.perf_counter() - started, 3),
                         "saved": saved, "ai_calls": 0}
    return evidence


def _measurable(item: dict) -> bool:
    return all(item.get("results", {}).get(arm, {}).get("usage", {}).get("source") != "unavailable"
               and "input" in item.get("results", {}).get(arm, {}).get("usage", {}) for arm in ARMS)


async def run(args: argparse.Namespace) -> dict:
    workspace = args.workspace.resolve()
    rounds: list[dict] = []
    if workspace.exists():
        if not args.resume or not args.output.exists():
            raise SystemExit("Use a new workspace, or --resume with saved evidence.")
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        if previous.get("model") != args.model:
            raise SystemExit("Resume model does not match saved evidence.")
        rounds = [item for item in previous.get("rounds", []) if _measurable(item)]
    else:
        if args.resume:
            raise SystemExit("Cannot resume a missing workspace.")
        workspace.mkdir(parents=True)
    contract_hash = hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest()
    for number in range(len(rounds) + 1, args.rounds + 1):
        order = list(ARMS if number % 2 else reversed(ARMS))
        roots = {arm: workspace / f"round-{number}" / arm for arm in ARMS}
        if any(path.exists() for path in roots.values()):
            raise SystemExit(f"Archive interrupted round {number} before resuming.")
        for root in roots.values():
            shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            _configure(root)
            prepare(root, GOAL)
        hashes = {arm: source_hash(root) for arm, root in roots.items()}
        if len(set(hashes.values())) != 1:
            raise RuntimeError("Application sources differ before execution.")
        training = _train_pair(roots)
        contexts = {
            arm: prepare(root, GOAL, read_sources=True, value_gated=True,
                         use_experience=arm == "silent_memory")
            for arm, root in roots.items()
        }
        cold_commands = contexts["cold_candidates"]["context"]["commands_to_verify"]
        warm_commands = contexts["silent_memory"]["context"]["commands_to_verify"]
        if set(cold_commands) != {"test", "build", "frontend_build"} or set(warm_commands) != {"test"}:
            raise RuntimeError("Validation memory did not produce the intended isolated treatment.")
        current = {"round": number, "order": order, "source_hashes": hashes,
                   "training": training,
                   "context_chars": {arm: item["context_chars"] for arm, item in contexts.items()},
                   "commands": {arm: list(item["context"]["commands_to_verify"]) for arm, item in contexts.items()},
                   "results": {}}
        for arm in order:
            provider = MeteredCodex(timeout=args.timeout)
            if not provider.probe().ready:
                raise SystemExit("Codex is not available")
            work = task(roots[arm], args.model, "low")
            work.metadata["execution_budget"] = {
                "max_provider_tool_calls": 8, "max_provider_messages": 5,
            }
            packet = PiBudgetPacket(roots[arm], GOAL, contexts[arm]["context"])
            started = time.perf_counter()
            receipt = await provider.execute(work, packet=packet)
            result = {"status": receipt.status, "usage": receipt.token_usage,
                      "duration_seconds": round(time.perf_counter() - started, 3),
                      "quality": acceptance(roots[arm]), "error": receipt.error_code,
                      "telemetry": getattr(provider, "telemetry", {}),
                      "packet_chars": len(packet.render()),
                      "actual_source_changed": source_hash(roots[arm]) != hashes[arm]}
            current["results"][arm] = result
            print(f"round {number} {arm}: " + json.dumps(result), flush=True)
            if result["usage"].get("source") == "unavailable":
                (workspace / f"round-{number}-infrastructure-failure.json").write_text(
                    json.dumps(current, indent=2), encoding="utf-8")
                save(rounds, args)
                raise SystemExit("Provider usage unavailable; pair excluded.")
        rounds.append(current)
        save(rounds, args)
    if hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest() != contract_hash:
        raise RuntimeError("Acceptance contract changed during benchmark.")
    return save(rounds, args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--timeout", type=float, default=300)
    asyncio.run(run(parser.parse_args()))
