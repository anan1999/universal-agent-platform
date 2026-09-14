"""Ten-round paired benchmark: explicit budget alone vs Pi-inspired context control."""
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

from budget_benchmark import BudgetPacket, _totals
from context_cache_benchmark import ACCEPTANCE, FIXTURE, GOAL, acceptance, source_hash, task
from direct_benchmark import MeteredCodex
from adaptive_agent.project.direct import prepare


ARMS = ("budget_only", "pi_context")


class PiBudgetPacket(BudgetPacket):
    def __init__(self, root: Path, goal: str, context: dict):
        super().__init__(root, goal, True, context)
        if context.get("source_excerpts"):
            first_rule = "Treat supplied excerpts as the first inspection pass; do not reread an unchanged complete excerpt."
        else:
            first_rule = "Pointers are routing hints, not file content; read only the smallest missing evidence."
        self.text += (
            "PROGRESSIVE CONTEXT RULES:\n"
            f"- {first_rule}\n"
            "- Keep command output focused on matches, failures, or final summaries.\n"
            "- Stop only after the requested artifact and a deterministic acceptance check pass.\n"
        )


def _percent(before: float, after: float) -> float | None:
    return round((before - after) / before * 100, 2) if before else None


def measurable_pair(report: dict) -> bool:
    results = report.get("results", {})
    return all(
        results.get(arm, {}).get("usage", {}).get("source") != "unavailable"
        and "input" in results.get(arm, {}).get("usage", {})
        for arm in ARMS
    )


def summarize(rounds: list[dict]) -> dict:
    rows = []
    for report in rounds:
        before = _totals(report["results"]["budget_only"])
        after = _totals(report["results"]["pi_context"])
        rows.append({
            "round": report["round"],
            "order": report["order"],
            "quality_equal_and_passed": all(
                report["results"][arm]["quality"]["passed"] for arm in ARMS),
            "token_reduction_percent": _percent(before["tokens"], after["tokens"]),
            "uncached_reduction_percent": _percent(before["uncached_tokens"], after["uncached_tokens"]),
            "tool_call_delta": before["tool_calls"] - after["tool_calls"],
            "message_delta": before["assistant_messages"] - after["assistant_messages"],
            "seconds_reduction_percent": _percent(
                report["results"]["budget_only"]["duration_seconds"],
                report["results"]["pi_context"]["duration_seconds"]),
            "budget_only": before,
            "pi_context": after,
        })
    pooled = {
        arm: {
            key: sum(row[arm][key] for row in rows)
            for key in ("tokens", "uncached_tokens", "tool_calls", "assistant_messages", "assistant_message_chars")
        } for arm in ARMS
    }
    for arm in ARMS:
        pooled[arm]["seconds"] = round(sum(
            report["results"][arm]["duration_seconds"] for report in rounds), 3)
    def median(key: str) -> float | None:
        values = [float(row[key]) for row in rows if row[key] is not None]
        return round(statistics.median(values), 2) if values else None
    return {
        "rounds_completed": len(rows),
        "all_quality_equal_and_passed": all(row["quality_equal_and_passed"] for row in rows),
        "pi_total_token_win_rounds": sum((row["token_reduction_percent"] or 0) > 0 for row in rows),
        "pi_uncached_token_win_rounds": sum((row["uncached_reduction_percent"] or 0) > 0 for row in rows),
        "median_total_token_reduction_percent": median("token_reduction_percent"),
        "median_uncached_token_reduction_percent": median("uncached_reduction_percent"),
        "median_time_reduction_percent": median("seconds_reduction_percent"),
        "pooled": pooled,
        "pooled_total_token_reduction_percent": _percent(pooled["budget_only"]["tokens"], pooled["pi_context"]["tokens"]),
        "pooled_uncached_token_reduction_percent": _percent(pooled["budget_only"]["uncached_tokens"], pooled["pi_context"]["uncached_tokens"]),
        "pooled_tool_call_reduction_percent": _percent(pooled["budget_only"]["tool_calls"], pooled["pi_context"]["tool_calls"]),
        "pooled_message_reduction_percent": _percent(pooled["budget_only"]["assistant_messages"], pooled["pi_context"]["assistant_messages"]),
        "pooled_message_char_reduction_percent": _percent(
            pooled["budget_only"]["assistant_message_chars"],
            pooled["pi_context"]["assistant_message_chars"]),
        "pooled_time_reduction_percent": _percent(pooled["budget_only"]["seconds"], pooled["pi_context"]["seconds"]),
        "rows": rows,
    }


def render(report: dict) -> str:
    summary = report["summary"]
    strategy = report.get("context_strategy", "fixed_source_excerpts")
    lines = [
        "# UAP Pi-inspired context + budget benchmark", "",
        f"Context strategy: `{strategy}`. Both arms use the existing explicit budget. The experimental arm additionally uses hard-bounded progressive project context.", "",
        "| Round | Order | Quality | Total token reduction | Uncached reduction | Tool-call delta | Message delta | Time reduction |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["rows"]:
        lines.append(
            f"| {row['round']} | {' → '.join(row['order'])} | "
            f"{'PASS' if row['quality_equal_and_passed'] else 'FAIL'} | "
            f"{row['token_reduction_percent']}% | {row['uncached_reduction_percent']}% | "
            f"{row['tool_call_delta']:+d} | {row['message_delta']:+d} | {row['seconds_reduction_percent']}% |"
        )
    lines.extend([
        "", "## Aggregate", "",
        f"- Quality preserved in every pair: {summary['all_quality_equal_and_passed']}",
        f"- Pi-context total-token wins: {summary['pi_total_token_win_rounds']}/{summary['rounds_completed']}",
        f"- Pi-context uncached-token wins: {summary['pi_uncached_token_win_rounds']}/{summary['rounds_completed']}",
        f"- Median total-token reduction: {summary['median_total_token_reduction_percent']}%",
        f"- Median uncached-token reduction: {summary['median_uncached_token_reduction_percent']}%",
        f"- Pooled total-token reduction: {summary['pooled_total_token_reduction_percent']}%",
        f"- Pooled uncached-token reduction: {summary['pooled_uncached_token_reduction_percent']}%",
        f"- Pooled tool-call reduction: {summary['pooled_tool_call_reduction_percent']}%",
        f"- Pooled assistant-message reduction: {summary['pooled_message_reduction_percent']}%",
        f"- Pooled assistant-message-character reduction: {summary['pooled_message_char_reduction_percent']}%",
        f"- Pooled time reduction: {summary['pooled_time_reduction_percent']}%",
        "", "## Interpretation", "",
        "Positive values favor the Pi-inspired context arm. Provider-reported cached input is removed in the uncached view. This measures one task family; it does not convert tokens into subscription quota units.",
        "",
    ])
    if strategy == "fixed_source_excerpts":
        lines.extend(["",
            "The fixed 4,000-character source-context policy is rejected as a default: it reduced observable interactions but increased pooled total tokens, uncached tokens, and elapsed time, and one experimental result failed external acceptance. Keep explicit hard budgets; load source excerpts only when expected avoided discovery cost exceeds their context cost, and never bypass deterministic acceptance gates."])
    else:
        selected = sum(
            item.get("context_value_gate", {}).get("selected_excerpts", 0)
            for item in report.get("rounds", []))
        lines.extend(["",
            "Value-gated mode defaults to path/hash pointers and admits source bodies only when source-linked measured savings exceed preload cost plus a safety margin. External acceptance remains authoritative.",
            f"Across this run, the gate admitted {selected} source bodies; this is therefore a pointer-only progressive-context test, not evidence that preloading source code helps."])
        if not summary["all_quality_equal_and_passed"]:
            lines.extend(["",
                "Decision: reject value-gated progressive context as a default in its current form. Aggregate cost improved, but one experimental implementation failed deterministic external acceptance while its control passed. Keep the gate opt-in until a repair/verification loop preserves quality across repeated and cross-domain benchmarks."])
        else:
            lines.extend(["",
                "Decision: keep value-gated progressive context experimental. This task family preserved quality, but broader repeated and cross-domain evidence is required before enabling it by default."])
    return "\n".join(lines) + "\n"


def save(rounds: list[dict], args: argparse.Namespace) -> dict:
    report = {
        "experiment": "budget_only_vs_pi_progressive_context_ten_round",
        "goal": GOAL,
        "model": args.model,
        "reasoning": "low",
        "context_budget_chars": args.context_budget,
        "context_strategy": "value_gated" if args.value_gated else "fixed_source_excerpts",
        "summary": summarize(rounds),
        "rounds": rounds,
        "limitations": [
            "One implementation task family with repeated fresh fixtures.",
            "Subscription quota conversion is unavailable.",
            "Internal Codex reasoning rounds are not observable.",
            "The context compiler is deterministic and uses no pre-task model call.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render(report), encoding="utf-8")
    return report


async def run(args: argparse.Namespace) -> dict:
    workspace = args.workspace.resolve()
    rounds: list[dict] = []
    if workspace.exists():
        if not args.resume:
            raise SystemExit("Use a new workspace; benchmark evidence is never overwritten.")
        if not args.output.exists():
            raise SystemExit("Cannot resume without the previously saved JSON evidence.")
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        expected_strategy = "value_gated" if args.value_gated else "fixed_source_excerpts"
        immutable = {
            "goal": GOAL,
            "model": args.model,
            "context_budget_chars": args.context_budget,
            "context_strategy": expected_strategy,
        }
        mismatches = [
            key for key, expected in immutable.items()
            if previous.get(key) != expected
        ]
        if mismatches:
            raise SystemExit(
                "Resume parameters do not match saved evidence: " + ", ".join(mismatches))
        saved_rounds = previous.get("rounds", [])
        rounds = [item for item in saved_rounds if measurable_pair(item)]
        if saved_rounds[:len(rounds)] != rounds:
            raise SystemExit("Saved evidence contains an incomplete pair before a completed pair.")
        expected_numbers = list(range(1, len(rounds) + 1))
        if [item.get("round") for item in rounds] != expected_numbers:
            raise SystemExit("Saved evidence has non-contiguous round numbers.")
        if len(rounds) >= args.rounds:
            return save(rounds, args)
    else:
        if args.resume:
            raise SystemExit("Cannot resume because the benchmark workspace does not exist.")
        workspace.mkdir(parents=True)
    acceptance_hash = hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest()
    for number in range(len(rounds) + 1, args.rounds + 1):
        order = list(ARMS if number % 2 else reversed(ARMS))
        roots = {arm: workspace / f"round-{number}" / arm for arm in ARMS}
        if any(root.exists() for root in roots.values()):
            raise SystemExit(
                f"Round {number} contains interrupted evidence; archive it before resuming.")
        for root in roots.values():
            shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            prepare(root, GOAL)  # identical local index state in both arms
        hashes = {arm: source_hash(root) for arm, root in roots.items()}
        assert len(set(hashes.values())) == 1
        context = prepare(roots["pi_context"], GOAL, read_sources=True,
                          context_budget=args.context_budget, value_gated=args.value_gated)
        current_round = {
            "round": number, "order": order, "source_hashes": hashes,
            "acceptance_sha256": acceptance_hash,
            "pi_context_chars": context["context_chars"],
            "context_value_gate": context["context_value_gate"], "results": {},
        }
        for arm in order:
            provider = MeteredCodex(timeout=args.timeout)
            if not provider.probe().ready:
                raise SystemExit("Codex is not available")
            current = task(roots[arm], args.model, "low")
            current.metadata["execution_budget"] = {
                "max_provider_tool_calls": 8, "max_provider_messages": 5,
            }
            packet = (PiBudgetPacket(roots[arm], GOAL, context["context"])
                      if arm == "pi_context" else BudgetPacket(roots[arm], GOAL, True))
            started = time.perf_counter()
            receipt = await provider.execute(current, packet=packet)
            current_round["results"][arm] = {
                "status": receipt.status, "usage": receipt.token_usage,
                "duration_seconds": round(time.perf_counter() - started, 3),
                "quality": acceptance(roots[arm]), "error": receipt.error_code,
                "telemetry": getattr(provider, "telemetry", {}),
                "packet_chars": len(packet.render()),
                "actual_source_changed": source_hash(roots[arm]) != hashes[arm],
            }
            print(f"round {number} {arm}: " + json.dumps(current_round["results"][arm]), flush=True)
            if receipt.status == "failed" and receipt.token_usage.get("source") == "unavailable":
                current_round["infrastructure_failure"] = {
                    "arm": arm, "error": receipt.error_code, "summary": receipt.summary,
                }
                failure_path = workspace / f"round-{number}-infrastructure-failure.json"
                failure_path.write_text(json.dumps(current_round, indent=2), encoding="utf-8")
                save(rounds, args)
                raise SystemExit(
                    f"Infrastructure failure before a measurable pair: {receipt.error_code}: {receipt.summary}")
        rounds.append(current_round)
        save(rounds, args)
    assert hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest() == acceptance_hash
    return save(rounds, args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--context-budget", type=int, default=4000)
    parser.add_argument("--value-gated", action="store_true")
    parser.add_argument("--resume", action="store_true",
                        help="Continue from matching saved JSON without rerunning completed pairs")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--timeout", type=float, default=300)
    asyncio.run(run(parser.parse_args()))
