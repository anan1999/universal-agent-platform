"""Paired test: generic validation advice vs one exact in-session command."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from budget_benchmark import _totals
from context_cache_benchmark import ACCEPTANCE, FIXTURE, GOAL, acceptance, source_hash, task
from direct_benchmark import MeteredCodex
from pi_budget_benchmark import PiBudgetPacket
from adaptive_agent.project.direct import prepare


ARMS = ("generic_validation", "declared_validation")
VALIDATION_COMMAND = "python .agent/acceptance.py --project ."


class DeclaredValidationPacket(PiBudgetPacket):
    def __init__(self, root: Path, goal: str, context: dict):
        super().__init__(root, goal, context)
        self.text += (
            "DETERMINISTIC VALIDATION:\n"
            f"- Run exactly: {VALIDATION_COMMAND}\n"
            "- Reserve one tool call for it before returning.\n"
            "- If it fails because of your implementation, make one focused repair and rerun "
            "the same command once. Do not substitute pytest, npm, or environment setup.\n"
        )


def _percent(before: float, after: float) -> float | None:
    return round((before - after) / before * 100, 2) if before else None


def summarize(rounds: list[dict]) -> dict:
    rows = []
    for current in rounds:
        generic = _totals(current["results"]["generic_validation"])
        declared = _totals(current["results"]["declared_validation"])
        rows.append({
            "round": current["round"], "order": current["order"],
            "generic_quality": current["results"]["generic_validation"]["quality"]["passed"],
            "declared_quality": current["results"]["declared_validation"]["quality"]["passed"],
            "total_token_reduction_percent": _percent(generic["tokens"], declared["tokens"]),
            "uncached_token_reduction_percent": _percent(
                generic["uncached_tokens"], declared["uncached_tokens"]),
            "tool_call_delta": generic["tool_calls"] - declared["tool_calls"],
            "message_delta": generic["assistant_messages"] - declared["assistant_messages"],
            "time_reduction_percent": _percent(
                current["results"]["generic_validation"]["duration_seconds"],
                current["results"]["declared_validation"]["duration_seconds"]),
            "generic_validation": generic, "declared_validation": declared,
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
    def median(key: str) -> float | None:
        values = [row[key] for row in rows if row[key] is not None]
        return round(statistics.median(values), 2) if values else None
    return {
        "rounds_completed": len(rows),
        "generic_quality_passes": sum(row["generic_quality"] for row in rows),
        "declared_quality_passes": sum(row["declared_quality"] for row in rows),
        "declared_quality_regressions": sum(
            row["generic_quality"] and not row["declared_quality"] for row in rows),
        "declared_quality_repairs": sum(
            not row["generic_quality"] and row["declared_quality"] for row in rows),
        "median_total_token_reduction_percent": median("total_token_reduction_percent"),
        "median_uncached_token_reduction_percent": median("uncached_token_reduction_percent"),
        "median_time_reduction_percent": median("time_reduction_percent"),
        "pooled": pooled,
        "pooled_total_token_reduction_percent": _percent(
            pooled["generic_validation"]["tokens"], pooled["declared_validation"]["tokens"]),
        "pooled_uncached_token_reduction_percent": _percent(
            pooled["generic_validation"]["uncached_tokens"],
            pooled["declared_validation"]["uncached_tokens"]),
        "pooled_tool_call_reduction_percent": _percent(
            pooled["generic_validation"]["tool_calls"], pooled["declared_validation"]["tool_calls"]),
        "pooled_message_reduction_percent": _percent(
            pooled["generic_validation"]["assistant_messages"],
            pooled["declared_validation"]["assistant_messages"]),
        "pooled_time_reduction_percent": _percent(
            pooled["generic_validation"]["seconds"], pooled["declared_validation"]["seconds"]),
        "rows": rows,
    }


def render(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# Exact in-session validation benchmark", "",
        f"Treatment command: `{VALIDATION_COMMAND}`", "",
        "| Round | Order | Generic quality | Declared quality | Total token reduction | Uncached reduction | Tool delta | Message delta | Time reduction |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["rows"]:
        lines.append(
            f"| {row['round']} | {' → '.join(row['order'])} | "
            f"{'PASS' if row['generic_quality'] else 'FAIL'} | "
            f"{'PASS' if row['declared_quality'] else 'FAIL'} | "
            f"{row['total_token_reduction_percent']}% | "
            f"{row['uncached_token_reduction_percent']}% | {row['tool_call_delta']:+d} | "
            f"{row['message_delta']:+d} | {row['time_reduction_percent']}% |"
        )
    lines.extend(["", "## Aggregate", "",
                  f"- Generic quality: {summary['generic_quality_passes']}/{summary['rounds_completed']}",
                  f"- Declared-command quality: {summary['declared_quality_passes']}/{summary['rounds_completed']}",
                  f"- Quality repairs: {summary['declared_quality_repairs']}",
                  f"- Quality regressions: {summary['declared_quality_regressions']}",
                  f"- Pooled total-token reduction: {summary['pooled_total_token_reduction_percent']}%",
                  f"- Pooled uncached-token reduction: {summary['pooled_uncached_token_reduction_percent']}%",
                  f"- Pooled tool-call reduction: {summary['pooled_tool_call_reduction_percent']}%",
                  f"- Pooled assistant-message reduction: {summary['pooled_message_reduction_percent']}%",
                  f"- Pooled time reduction: {summary['pooled_time_reduction_percent']}%", "",
                  "Positive reductions favor the exact declared validation command. This small run is a screening test, not sufficient evidence for a default policy."])
    return "\n".join(lines) + "\n"


def save(rounds: list[dict], args: argparse.Namespace) -> dict:
    report = {
        "experiment": "generic_vs_exact_inline_validation", "goal": GOAL,
        "model": args.model, "reasoning": "low", "validation_command": VALIDATION_COMMAND,
        "summary": summarize(rounds), "rounds": rounds,
        "limitations": ["Small screening run on one implementation task family.",
                        "Subscription quota and hidden reasoning rounds are unavailable."],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render(report), encoding="utf-8")
    return report


def _measurable_pair(item: dict) -> bool:
    return all(item.get("results", {}).get(arm, {}).get("usage", {}).get("source") != "unavailable"
               and "input" in item.get("results", {}).get(arm, {}).get("usage", {})
               for arm in ARMS)


async def run(args: argparse.Namespace) -> dict:
    workspace = args.workspace.resolve()
    rounds: list[dict] = []
    if workspace.exists():
        if not args.resume or not args.output.exists():
            raise SystemExit("Use a new workspace, or --resume with saved evidence.")
        old = json.loads(args.output.read_text(encoding="utf-8"))
        if old.get("model") != args.model or old.get("validation_command") != VALIDATION_COMMAND:
            raise SystemExit("Resume parameters do not match saved evidence.")
        rounds = [item for item in old.get("rounds", []) if _measurable_pair(item)]
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
            agent = root / ".agent"
            agent.mkdir()
            shutil.copy2(ACCEPTANCE, agent / "acceptance.py")
            (agent / "commands.yaml").write_text(
                "commands:\n  acceptance:\n    command: [python, .agent/acceptance.py, --project, .]\n    timeout: 90\n",
                encoding="utf-8")
            prepare(root, GOAL)
        hashes = {arm: source_hash(root) for arm, root in roots.items()}
        if len(set(hashes.values())) != 1:
            raise RuntimeError("Application sources differ before execution.")
        context = prepare(roots["declared_validation"], GOAL, read_sources=True,
                          context_budget=4000, value_gated=True)["context"]
        current = {"round": number, "order": order, "source_hashes": hashes, "results": {}}
        for arm in order:
            provider = MeteredCodex(timeout=args.timeout)
            if not provider.probe().ready:
                raise SystemExit("Codex is not available")
            work = task(roots[arm], args.model, "low")
            work.metadata["execution_budget"] = {
                "max_provider_tool_calls": 8, "max_provider_messages": 5,
            }
            packet = (DeclaredValidationPacket(roots[arm], GOAL, context)
                      if arm == "declared_validation" else PiBudgetPacket(roots[arm], GOAL, context))
            started = time.perf_counter()
            receipt = await provider.execute(work, packet=packet)
            result = {
                "status": receipt.status, "usage": receipt.token_usage,
                "duration_seconds": round(time.perf_counter() - started, 3),
                "quality": acceptance(roots[arm]), "error": receipt.error_code,
                "telemetry": getattr(provider, "telemetry", {}), "packet_chars": len(packet.render()),
                "actual_source_changed": source_hash(roots[arm]) != hashes[arm],
            }
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
        raise RuntimeError("External acceptance contract changed during benchmark.")
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
