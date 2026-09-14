"""Replay one failed implementation and measure a single bounded repair call."""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from budget_benchmark import _totals
from context_cache_benchmark import ACCEPTANCE, GOAL, acceptance, source_hash, task
from direct_benchmark import MeteredCodex, Packet
from adaptive_agent.project.quality_closure import compile_repair_evidence


class RepairPacket(Packet):
    def __init__(self, root: Path, goal: str, evidence: dict):
        super().__init__(root, goal)
        self.text = (
            "Repair exactly one externally observed acceptance failure in the current workspace.\n"
            f"Original goal: {goal}\n"
            "Do not redesign working behavior. Use the supplied failure and excerpts first. "
            "Inspect other files only when strictly required. Make one focused edit and run the "
            "smallest relevant validation. Stop after the failure is fixed.\n"
            "REPAIR EVIDENCE:\n" + json.dumps(evidence, ensure_ascii=False) + "\n"
            "RESOURCE BUDGET:\n"
            "- At most 4 observable tool calls and 3 assistant messages.\n"
            "- No progress-only messages and no repeated command.\n"
            "- Return a short factual receipt.\n"
        )


def _add_usage(first: dict, second: dict) -> dict:
    if any(item.get("source") == "unavailable" for item in (first, second)):
        return {"input": 0, "output": 0, "cached": 0, "source": "unavailable"}
    return {
        "input": int(first.get("input", 0)) + int(second.get("input", 0)),
        "output": int(first.get("output", 0)) + int(second.get("output", 0)),
        "cached": int(first.get("cached", 0)) + int(second.get("cached", 0)),
        "source": "measured",
        "invocation_count": int(first.get("invocation_count", 1)) + 1,
    }


def render(report: dict) -> str:
    control = _totals(report["control"])
    combined = _totals(report["combined"])
    comparison = report["comparison"]
    return "\n".join([
        "# Bounded quality-repair replay", "",
        f"Initial failure: `{report['initial_quality']['error']}`", "",
        "| Metric | Original control | Experimental + repair |", "|---|---:|---:|",
        f"| External acceptance | PASS | {'PASS' if report['repair']['quality']['passed'] else 'FAIL'} |",
        f"| Provider calls | 1 | {report['combined']['usage'].get('invocation_count', 0)} |",
        f"| Total tokens | {control['tokens']} | {combined['tokens']} |",
        f"| Uncached tokens | {control['uncached_tokens']} | {combined['uncached_tokens']} |",
        f"| Tool calls | {control['tool_calls']} | {combined['tool_calls']} |",
        f"| Assistant messages | {control['assistant_messages']} | {combined['assistant_messages']} |", "",
        f"Total-token reduction after repair: {comparison['total_token_reduction_percent']}%.",
        f"Uncached-token reduction after repair: {comparison['uncached_token_reduction_percent']}%.",
        f"Decision: **{comparison['decision']}**.", "",
        "This is a replay of one observed failure, not a fresh randomized pair. It tests whether one bounded repair can close quality without erasing the observed saving.",
    ]) + "\n"


async def run(args: argparse.Namespace) -> dict:
    source = args.failed_workspace.resolve()
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit("Use a new workspace; repair evidence is never overwritten.")
    if not source.is_dir():
        raise SystemExit("Failed workspace does not exist.")
    shutil.copytree(source, workspace, ignore=shutil.ignore_patterns(".git", ".agent", "__pycache__", "*.pyc", "expenses.sqlite3"))
    subprocess.run(["git", "init", "--quiet", str(workspace)], check=True)
    initial_quality = acceptance(workspace)
    if initial_quality.get("passed"):
        raise SystemExit("Replay input must fail external acceptance before repair.")

    historical = json.loads(args.baseline_results.read_text(encoding="utf-8"))
    original = next(item for item in historical["rounds"] if item["round"] == args.round)
    control = original["results"]["budget_only"]
    initial = original["results"]["pi_context"]
    evidence = compile_repair_evidence(
        workspace, str(initial_quality.get("error", "validation failed")), args.candidate,
        max_context_chars=args.context_budget, max_excerpt_chars=args.excerpt_budget,
    )
    provider = MeteredCodex(timeout=args.timeout)
    if not provider.probe().ready:
        raise SystemExit("Codex is not available")
    current = task(workspace, args.model, "low")
    current.title = "Repair deterministic acceptance failure"
    current.metadata["execution_budget"] = {
        "max_provider_tool_calls": 4, "max_provider_messages": 3,
    }
    packet = RepairPacket(workspace, GOAL, evidence.to_dict())
    started = time.perf_counter()
    receipt = await provider.execute(current, packet=packet)
    repair = {
        "status": receipt.status, "usage": receipt.token_usage,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "quality": acceptance(workspace), "error": receipt.error_code,
        "telemetry": getattr(provider, "telemetry", {}), "packet_chars": len(packet.render()),
    }
    combined_usage = _add_usage(initial["usage"], repair["usage"])
    combined = {
        "usage": combined_usage,
        "telemetry": {
            key: int(initial.get("telemetry", {}).get(key, 0)) + int(repair["telemetry"].get(key, 0))
            for key in ("tool_calls", "assistant_messages", "assistant_message_chars")
        },
    }
    before, after = _totals(control), _totals(combined)
    def reduction(key: str) -> float | None:
        return round((before[key] - after[key]) / before[key] * 100, 2) if before[key] else None
    quality_closed = bool(repair["quality"].get("passed"))
    measurable = combined_usage.get("source") == "measured"
    decision = ("ACCEPT_BOUNDED_REPAIR" if quality_closed and measurable and after["tokens"] < before["tokens"]
                else "REJECT_COST" if quality_closed and measurable else "REJECT_QUALITY")
    report = {
        "experiment": "single_bounded_quality_repair_replay", "goal": GOAL,
        "failed_source_hash": source_hash(source), "repair_source_hash": source_hash(workspace),
        "model": args.model, "initial_quality": initial_quality,
        "repair_evidence": evidence.to_dict(), "control": control, "initial_experimental": initial,
        "repair": repair, "combined": combined,
        "comparison": {
            "quality_closed": quality_closed,
            "total_token_reduction_percent": reduction("tokens") if measurable else None,
            "uncached_token_reduction_percent": reduction("uncached_tokens") if measurable else None,
            "tool_call_delta": before["tool_calls"] - after["tool_calls"],
            "assistant_message_delta": before["assistant_messages"] - after["assistant_messages"],
            "decision": decision,
        },
        "limitations": ["One observed failure replay; not a fresh randomized pair.",
                        "Subscription quota conversion and hidden reasoning rounds are unavailable."],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render(report), encoding="utf-8")
    print(json.dumps({"repair": repair, "comparison": report["comparison"]}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--failed-workspace", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--baseline-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--round", type=int, default=10)
    parser.add_argument("--candidate", action="append", default=["app/main.py"])
    parser.add_argument("--context-budget", type=int, default=2400)
    parser.add_argument("--excerpt-budget", type=int, default=1600)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--timeout", type=float, default=240)
    asyncio.run(run(parser.parse_args()))
