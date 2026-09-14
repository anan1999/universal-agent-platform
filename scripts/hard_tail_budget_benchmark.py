"""Paired real-provider benchmark for a hard three-tool completion envelope."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from budget_benchmark import _totals
from context_cache_benchmark import ACCEPTANCE, FIXTURE, GOAL, acceptance, source_hash, task
from direct_benchmark import MeteredCodex, Packet
from adaptive_agent.project.direct import prepare


ARMS = ("flexible_8", "hard_3")
LIMITS = {
    "flexible_8": {"max_provider_tool_calls": 8, "max_provider_messages": 12},
    "hard_3": {"max_provider_tool_calls": 3, "max_provider_messages": 12},
}


class TailBudgetPacket(Packet):
    def __init__(self, root: Path, goal: str, context: dict, arm: str):
        super().__init__(root, goal, context)
        limits = LIMITS[arm]
        self.text += (
            "\nBOUNDED EXECUTION:\n"
            f"- Hard envelope: {limits['max_provider_tool_calls']} tool calls and "
            f"{limits['max_provider_messages']} assistant messages.\n"
            "- Use one targeted inspection, one edit, and one validation; batch independent work.\n"
            "- Do not repeat commands or add a repository-status pass after validation succeeds.\n"
            "- Keep the final response under 250 words.\n"
        )


def _percent(before: float, after: float) -> float | None:
    return round((before - after) / before * 100, 2) if before else None


def measurable(result: dict) -> bool:
    usage = result.get("usage", {})
    return usage.get("source") != "unavailable" and "input" in usage and "output" in usage


def summarize(rounds: list[dict]) -> dict:
    rows = []
    for current in rounds:
        flexible = _totals(current["results"]["flexible_8"])
        hard = _totals(current["results"]["hard_3"])
        rows.append({
            "round": current["round"], "order": current["order"],
            "flexible_quality": current["results"]["flexible_8"]["quality"]["passed"],
            "hard_quality": current["results"]["hard_3"]["quality"]["passed"],
            "token_reduction_percent": _percent(flexible["tokens"], hard["tokens"]),
            "uncached_reduction_percent": _percent(
                flexible["uncached_tokens"], hard["uncached_tokens"]),
            "tool_delta": flexible["tool_calls"] - hard["tool_calls"],
            "message_delta": flexible["assistant_messages"] - hard["assistant_messages"],
            "flexible_8": flexible, "hard_3": hard,
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
        "flexible_quality_passes": sum(row["flexible_quality"] for row in rows),
        "hard_quality_passes": sum(row["hard_quality"] for row in rows),
        "pooled": pooled,
        "pooled_total_token_reduction_percent": _percent(
            pooled["flexible_8"]["tokens"], pooled["hard_3"]["tokens"]),
        "pooled_uncached_token_reduction_percent": _percent(
            pooled["flexible_8"]["uncached_tokens"], pooled["hard_3"]["uncached_tokens"]),
        "pooled_tool_reduction_percent": _percent(
            pooled["flexible_8"]["tool_calls"], pooled["hard_3"]["tool_calls"]),
        "pooled_message_reduction_percent": _percent(
            pooled["flexible_8"]["assistant_messages"], pooled["hard_3"]["assistant_messages"]),
        "pooled_time_reduction_percent": _percent(
            pooled["flexible_8"]["seconds"], pooled["hard_3"]["seconds"]),
        "rows": rows,
    }


def render(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# Hard tail-budget benchmark", "",
        "Both arms keep validation inside the agent. The treatment changes only the provider "
        "tool-call limit from eight to three; both arms allow twelve assistant messages.", "",
        "| Round | Order | Flexible quality | Hard quality | Token reduction | Uncached reduction | Tool delta | Message delta |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["rows"]:
        lines.append(
            f"| {row['round']} | {' → '.join(row['order'])} | "
            f"{'PASS' if row['flexible_quality'] else 'FAIL'} | "
            f"{'PASS' if row['hard_quality'] else 'FAIL'} | "
            f"{row['token_reduction_percent']}% | {row['uncached_reduction_percent']}% | "
            f"{row['tool_delta']:+d} | {row['message_delta']:+d} |")
    lines.extend([
        "", "## Aggregate", "",
        f"- Flexible quality: {summary['flexible_quality_passes']}/{summary['rounds_completed']}",
        f"- Hard-budget quality: {summary['hard_quality_passes']}/{summary['rounds_completed']}",
        f"- Pooled total-token reduction: {summary['pooled_total_token_reduction_percent']}%",
        f"- Pooled uncached-token reduction: {summary['pooled_uncached_token_reduction_percent']}%",
        f"- Pooled provider-tool reduction: {summary['pooled_tool_reduction_percent']}%",
        f"- Pooled assistant-message reduction: {summary['pooled_message_reduction_percent']}%",
        f"- Pooled time reduction: {summary['pooled_time_reduction_percent']}%", "",
    ])
    if summary["hard_quality_passes"] < summary["flexible_quality_passes"]:
        lines.append("Decision: **REJECT_QUALITY** — the hard tail budget reduced accepted quality.")
    elif ((summary["pooled_total_token_reduction_percent"] or 0) > 0
          and (summary["pooled_uncached_token_reduction_percent"] or 0) > 0):
        lines.append("Decision: **CANDIDATE** — quality held and both measured token views improved.")
    elif all((summary[key] or 0) < 0 for key in (
            "pooled_total_token_reduction_percent",
            "pooled_uncached_token_reduction_percent")):
        lines.append("Decision: **REJECT_COST** — quality held but both measured token views worsened.")
    else:
        lines.append("Decision: **INCONCLUSIVE** — measured cost signals disagree.")
    return "\n".join(lines) + "\n"


def save(rounds: list[dict], args: argparse.Namespace) -> dict:
    report = {
        "experiment": "flexible_8_vs_hard_3_tail_budget", "goal": GOAL,
        "model": args.model, "reasoning": "low", "limits": LIMITS,
        "summary": summarize(rounds), "rounds": rounds,
        "limitations": [
            "A hard stop before turn completion has no final provider usage report and is rejected.",
            "This screening uses one software task family.",
            "Provider tokens do not map directly to subscription quota units.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render(report), encoding="utf-8")
    return report


async def run(args: argparse.Namespace) -> dict:
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit("Use a new workspace; benchmark evidence is never overwritten.")
    workspace.mkdir(parents=True)
    rounds = []
    contract_hash = hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest()
    for number in range(1, args.rounds + 1):
        order = list(ARMS if number % 2 else reversed(ARMS))
        roots = {arm: workspace / f"round-{number}" / arm for arm in ARMS}
        for root in roots.values():
            shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            prepare(root, GOAL)
        hashes = {arm: source_hash(root) for arm, root in roots.items()}
        if len(set(hashes.values())) != 1:
            raise RuntimeError("Application sources differ before execution.")
        contexts = {arm: prepare(root, GOAL, read_sources=True, value_gated=True)["context"]
                    for arm, root in roots.items()}
        current = {"round": number, "order": order, "source_hashes": hashes, "results": {}}
        for arm in order:
            provider = MeteredCodex(timeout=args.timeout)
            if not provider.probe().ready:
                raise SystemExit("Codex is not available")
            work = task(roots[arm], args.model, "low")
            work.metadata["execution_budget"] = dict(LIMITS[arm])
            packet = TailBudgetPacket(roots[arm], GOAL, contexts[arm], arm)
            started = time.perf_counter()
            receipt = await provider.execute(work, packet=packet)
            result = {
                "status": receipt.status, "usage": receipt.token_usage,
                "duration_seconds": round(time.perf_counter() - started, 3),
                "quality": acceptance(roots[arm]), "error": receipt.error_code,
                "provider_summary": receipt.summary,
                "telemetry": getattr(provider, "telemetry", {}),
                "packet_chars": len(packet.render()),
                "actual_source_changed": source_hash(roots[arm]) != hashes[arm],
            }
            current["results"][arm] = result
            print(f"round {number} {arm}: " + json.dumps(result), flush=True)
            if not measurable(result):
                failure = workspace / f"round-{number}-unmeasurable.json"
                failure.write_text(json.dumps(current, indent=2), encoding="utf-8")
                raise SystemExit(
                    f"Hard stop or provider failure removed usage evidence; pair rejected at {failure}.")
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
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--timeout", type=float, default=300)
    asyncio.run(run(parser.parse_args()))
