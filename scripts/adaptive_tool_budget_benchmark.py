"""Six-round real-provider benchmark for conservative adaptive tool budgets."""
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

from adaptive_agent.core.goal_analyzer import GoalAnalyzer
from adaptive_agent.project.adaptive_budget import AdaptiveToolBudgetStore
from adaptive_agent.project.direct import prepare
from budget_benchmark import _totals
from context_cache_benchmark import ACCEPTANCE, FIXTURE, GOAL, acceptance, source_hash, task
from direct_benchmark import MeteredCodex, Packet


ARMS = ("fixed_8", "adaptive")
BASELINE_CAP = 8
MESSAGE_CAP = 12


class AdaptivePacket(Packet):
    def __init__(self, root: Path, context: dict, cap: int):
        super().__init__(root, GOAL, context)
        self.text += (
            "\nBOUNDED EXECUTION:\n"
            f"- Hard envelope: {cap} provider tool calls and {MESSAGE_CAP} assistant messages.\n"
            "- Batch independent inspection and edits; validate once after implementation.\n"
            "- Do not repeat successful commands or add a final repository-status pass.\n"
            "- Keep the final response under 250 words.\n"
        )


def _percent(before: float, after: float) -> float | None:
    return round((before - after) / before * 100, 2) if before else None


def selected_cap(store: AdaptiveToolBudgetStore, analysis) -> tuple[int, dict]:
    decision = store.decide(analysis)
    return decision.provider_tool_cap or BASELINE_CAP, decision.to_dict()


def _aggregate(rounds: list[dict], start: int = 1) -> dict:
    selected = [item for item in rounds if item["round"] >= start]
    pooled = {
        arm: {key: sum(_totals(item["results"][arm])[key] for item in selected)
              for key in ("tokens", "uncached_tokens", "tool_calls", "assistant_messages")}
        for arm in ARMS
    }
    for arm in ARMS:
        pooled[arm]["seconds"] = round(sum(
            item["results"][arm]["duration_seconds"] for item in selected), 3)
    return {
        "rounds": len(selected), "pooled": pooled,
        "fixed_quality": sum(item["results"]["fixed_8"]["quality"]["passed"] for item in selected),
        "adaptive_quality": sum(item["results"]["adaptive"]["quality"]["passed"] for item in selected),
        "total_token_reduction_percent": _percent(pooled["fixed_8"]["tokens"], pooled["adaptive"]["tokens"]),
        "uncached_token_reduction_percent": _percent(
            pooled["fixed_8"]["uncached_tokens"], pooled["adaptive"]["uncached_tokens"]),
        "tool_reduction_percent": _percent(pooled["fixed_8"]["tool_calls"], pooled["adaptive"]["tool_calls"]),
        "message_reduction_percent": _percent(
            pooled["fixed_8"]["assistant_messages"], pooled["adaptive"]["assistant_messages"]),
        "time_reduction_percent": _percent(pooled["fixed_8"]["seconds"], pooled["adaptive"]["seconds"]),
    }


def summarize(rounds: list[dict]) -> dict:
    return {"cumulative": _aggregate(rounds),
            "post_learning": _aggregate(rounds, 4) if len(rounds) >= 4 else None}


def render(report: dict) -> str:
    lines = [
        "# Adaptive provider tool-budget benchmark", "",
        "The control stays at eight provider tool calls. The adaptive arm preserves eight during "
        "three externally accepted learning runs, then follows the production recommendation. "
        "Both arms use twelve assistant messages, identical source, model, reasoning, prompt shape, "
        "and frozen external acceptance.", "",
        "| Round | Order | Adaptive cap | Evidence before | Fixed quality | Adaptive quality |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for item in report["rounds"]:
        decision = item["adaptive_decision"]
        lines.append(
            f"| {item['round']} | {' → '.join(item['order'])} | {item['adaptive_cap']} | "
            f"{decision['accepted_runs']} | "
            f"{'PASS' if item['results']['fixed_8']['quality']['passed'] else 'FAIL'} | "
            f"{'PASS' if item['results']['adaptive']['quality']['passed'] else 'FAIL'} |"
        )
    for title, key in (("Cumulative", "cumulative"), ("Post-learning rounds 4–6", "post_learning")):
        item = report["summary"].get(key)
        if not item:
            continue
        lines.extend([
            "", f"## {title}", "",
            f"- Quality: fixed {item['fixed_quality']}/{item['rounds']}; adaptive {item['adaptive_quality']}/{item['rounds']}",
            f"- Total-token reduction: {item['total_token_reduction_percent']}%",
            f"- Uncached-token reduction: {item['uncached_token_reduction_percent']}%",
            f"- Provider-tool reduction: {item['tool_reduction_percent']}%",
            f"- Assistant-message reduction: {item['message_reduction_percent']}%",
            f"- Time reduction: {item['time_reduction_percent']}%",
        ])
    post = report["summary"].get("post_learning")
    if not post or post["adaptive_quality"] < post["fixed_quality"]:
        decision = "INCOMPLETE_OR_REJECT_QUALITY"
    elif ((post["total_token_reduction_percent"] or 0) > 0
          and (post["uncached_token_reduction_percent"] or 0) > 0):
        decision = "CANDIDATE"
    elif all((post[key] or 0) < 0 for key in (
            "total_token_reduction_percent", "uncached_token_reduction_percent")):
        decision = "REJECT_COST"
    else:
        decision = "INCONCLUSIVE"
    lines.extend(["", f"Decision: **{decision}**.", "",
                  "Provider token measurements do not map directly to subscription quota units. "
                  "This benchmark covers one software task family; cross-domain adoption requires "
                  "separate accepted evidence."])
    return "\n".join(lines) + "\n"


def _reset(root: Path, workspace: Path, preserve_learning: bool) -> None:
    root = root.resolve()
    if not root.is_relative_to(workspace.resolve()):
        raise RuntimeError("Benchmark reset target leaves its dedicated workspace")
    saved = None
    budget_path = root / ".agent/cache/adaptive-budgets.sqlite3"
    if preserve_learning and budget_path.exists():
        saved = budget_path.read_bytes()
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    (root / ".agent").mkdir(parents=True, exist_ok=True)
    command = {"commands": {"test": {
        "command": [sys.executable, str(ACCEPTANCE), "--project", "."],
        "timeout": 90, "acceptance": True,
    }}}
    (root / ".agent/commands.yaml").write_text(yaml.safe_dump(command), encoding="utf-8")
    if saved is not None:
        budget_path.parent.mkdir(parents=True, exist_ok=True)
        budget_path.write_bytes(saved)
    prepare(root, GOAL)


def _save(report: dict, args: argparse.Namespace) -> None:
    report["summary"] = summarize(report["rounds"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render(report), encoding="utf-8")


async def run(args: argparse.Namespace) -> dict:
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit("Use a new workspace; benchmark evidence is never overwritten.")
    workspace.mkdir(parents=True)
    roots = {arm: workspace / arm for arm in ARMS}
    analysis = GoalAnalyzer().analyze(GOAL, active_profiles=("software-engineering",))
    report = {
        "experiment": "fixed_8_vs_conservative_adaptive_tool_budget",
        "goal": GOAL, "model": args.model, "reasoning": "low", "rounds": [],
        "acceptance_sha256": hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest(),
        "limitations": ["one software task family", "subscription quota conversion unavailable"],
    }
    for number in range(1, args.rounds + 1):
        for arm in ARMS:
            _reset(roots[arm], workspace, preserve_learning=arm == "adaptive")
        adaptive_store = AdaptiveToolBudgetStore(roots["adaptive"])
        cap, decision = selected_cap(adaptive_store, analysis)
        order = list(ARMS if number % 2 else reversed(ARMS))
        current = {"round": number, "order": order, "adaptive_cap": cap,
                   "adaptive_decision": decision, "results": {}}
        hashes = {arm: source_hash(root) for arm, root in roots.items()}
        if len(set(hashes.values())) != 1:
            raise RuntimeError("Application sources differ before execution")
        contexts = {arm: prepare(root, GOAL, read_sources=True, value_gated=True)["context"]
                    for arm, root in roots.items()}
        for arm in order:
            provider = MeteredCodex(timeout=args.timeout)
            if not provider.probe().ready:
                raise SystemExit("Codex is not available")
            arm_cap = BASELINE_CAP if arm == "fixed_8" else cap
            current_task = task(roots[arm], args.model, "low")
            current_task.metadata["execution_budget"] = {
                "max_provider_tool_calls": arm_cap, "max_provider_messages": MESSAGE_CAP,
            }
            packet = AdaptivePacket(roots[arm], contexts[arm], arm_cap)
            started = time.perf_counter()
            receipt = await provider.execute(current_task, packet=packet)
            quality = acceptance(roots[arm])
            result = {"status": receipt.status, "usage": receipt.token_usage,
                      "duration_seconds": round(time.perf_counter() - started, 3),
                      "quality": quality, "error": receipt.error_code,
                      "telemetry": getattr(provider, "telemetry", {}),
                      "packet_chars": len(packet.render()),
                      "actual_source_changed": source_hash(roots[arm]) != hashes[arm]}
            current["results"][arm] = result
            print(f"round {number} {arm}: " + json.dumps(result), flush=True)
            if result["usage"].get("source") == "unavailable":
                raise SystemExit("Provider usage unavailable; benchmark pair rejected")
        adaptive_store.record(analysis, current["results"]["adaptive"]["quality"]["passed"])
        report["rounds"].append(current)
        _save(report, args)
    if hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest() != report["acceptance_sha256"]:
        raise RuntimeError("Acceptance contract changed during benchmark")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--timeout", type=float, default=300)
    asyncio.run(run(parser.parse_args()))
