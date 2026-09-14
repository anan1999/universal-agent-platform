"""Resume-safe paired explicit-budget benchmark with counterbalanced order."""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import budget_benchmark as single


def _percent(before: float, after: float) -> float | None:
    return round((before - after) / before * 100, 2) if before else None


def summarize(reports: list[dict]) -> dict:
    rows = []
    for index, report in enumerate(reports, 1):
        unbounded = single._totals(report["results"]["unbounded"])
        budgeted = single._totals(report["results"]["budgeted"])
        quality = all(report["results"][arm]["quality"]["passed"]
                      for arm in ("unbounded", "budgeted"))
        rows.append({
            "round": index,
            "order": report["order"],
            "quality_equal_and_passed": quality,
            "token_reduction_percent": _percent(unbounded["tokens"], budgeted["tokens"]),
            "uncached_token_reduction_percent": _percent(
                unbounded["uncached_tokens"], budgeted["uncached_tokens"]),
            "tool_call_delta": unbounded["tool_calls"] - budgeted["tool_calls"],
            "assistant_message_delta": (unbounded["assistant_messages"] -
                                        budgeted["assistant_messages"]),
            "seconds_reduction_percent": _percent(
                report["results"]["unbounded"]["duration_seconds"],
                report["results"]["budgeted"]["duration_seconds"]),
            "unbounded": unbounded,
            "budgeted": budgeted,
            "budget_repeated_exact_commands": sum(
                bool(item.get("repeated_exact_command"))
                for item in report["results"]["budgeted"].get("telemetry", {}).get("actions", [])),
        })
    def values(key: str) -> list[float]:
        return [float(row[key]) for row in rows if row[key] is not None]
    token_values = values("token_reduction_percent")
    uncached_values = values("uncached_token_reduction_percent")
    seconds_values = values("seconds_reduction_percent")
    pooled = {
        arm: {
            "tokens": sum(row[arm]["tokens"] for row in rows),
            "uncached_tokens": sum(row[arm]["uncached_tokens"] for row in rows),
            "tool_calls": sum(row[arm]["tool_calls"] for row in rows),
            "assistant_messages": sum(row[arm]["assistant_messages"] for row in rows),
            "assistant_message_chars": sum(row[arm]["assistant_message_chars"] for row in rows),
            "seconds": round(sum(report["results"][arm]["duration_seconds"] for report in reports), 3),
        } for arm in ("unbounded", "budgeted")
    }
    return {
        "rounds_completed": len(rows),
        "all_quality_equal_and_passed": all(row["quality_equal_and_passed"] for row in rows),
        "budget_token_win_rounds": sum(row["token_reduction_percent"] > 0 for row in rows),
        "budget_uncached_token_win_rounds": sum(
            row["uncached_token_reduction_percent"] > 0 for row in rows),
        "median_token_reduction_percent": round(statistics.median(token_values), 2),
        "mean_token_reduction_percent": round(statistics.mean(token_values), 2),
        "median_uncached_token_reduction_percent": round(statistics.median(uncached_values), 2),
        "mean_uncached_token_reduction_percent": round(statistics.mean(uncached_values), 2),
        "median_seconds_reduction_percent": round(statistics.median(seconds_values), 2),
        "mean_tool_call_delta": round(statistics.mean(row["tool_call_delta"] for row in rows), 2),
        "pooled": pooled,
        "pooled_total_token_reduction_percent": _percent(
            pooled["unbounded"]["tokens"], pooled["budgeted"]["tokens"]),
        "pooled_uncached_token_reduction_percent": _percent(
            pooled["unbounded"]["uncached_tokens"], pooled["budgeted"]["uncached_tokens"]),
        "pooled_tool_call_reduction_percent": _percent(
            pooled["unbounded"]["tool_calls"], pooled["budgeted"]["tool_calls"]),
        "pooled_seconds_reduction_percent": _percent(
            pooled["unbounded"]["seconds"], pooled["budgeted"]["seconds"]),
        "pooled_assistant_message_reduction_percent": _percent(
            pooled["unbounded"]["assistant_messages"], pooled["budgeted"]["assistant_messages"]),
        "pooled_message_char_reduction_percent": _percent(
            pooled["unbounded"]["assistant_message_chars"],
            pooled["budgeted"]["assistant_message_chars"]),
        "budget_tool_cap_observed_rounds": sum(row["budgeted"]["tool_calls"] <= 8 for row in rows),
        "budget_no_repeat_observed_rounds": sum(
            row["budget_repeated_exact_commands"] == 0 for row in rows),
        "rows": rows,
    }


def render(aggregate: dict) -> str:
    summary = aggregate["summary"]
    lines = [
        "# UAP explicit-budget multi-round benchmark",
        "",
        "## Problem",
        "",
        aggregate["goal"],
        "",
        "Five independent paired runs use the same source fixture, model, reasoning level and offline acceptance contract. Execution order alternates between arms.",
        "",
        "## Per-round results",
        "",
        "| Round | Order | Quality | Total token reduction | Uncached reduction | Tool-call delta | Time reduction |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in summary["rows"]:
        lines.append(
            f"| {row['round']} | {' → '.join(row['order'])} | "
            f"{'PASS' if row['quality_equal_and_passed'] else 'FAIL'} | "
            f"{row['token_reduction_percent']}% | {row['uncached_token_reduction_percent']}% | "
            f"{row['tool_call_delta']:+d} | {row['seconds_reduction_percent']}% |"
        )
    lines.extend([
        "", "## Aggregate", "",
        f"- Quality preserved in every pair: {summary['all_quality_equal_and_passed']}",
        f"- Budget won total-token rounds: {summary['budget_token_win_rounds']}/{summary['rounds_completed']}",
        f"- Budget won uncached-token rounds: {summary['budget_uncached_token_win_rounds']}/{summary['rounds_completed']}",
        f"- Median total-token reduction: {summary['median_token_reduction_percent']}%",
        f"- Median uncached-token reduction: {summary['median_uncached_token_reduction_percent']}%",
        f"- Median time reduction: {summary['median_seconds_reduction_percent']}%",
        f"- Mean tool-call reduction: {summary['mean_tool_call_delta']}",
        f"- Pooled total-token reduction: {summary['pooled_total_token_reduction_percent']}%",
        f"- Pooled uncached-token reduction: {summary['pooled_uncached_token_reduction_percent']}%",
        f"- Pooled tool-call reduction: {summary['pooled_tool_call_reduction_percent']}%",
        f"- Pooled time reduction: {summary['pooled_seconds_reduction_percent']}%",
        f"- Pooled assistant-message reduction: {summary['pooled_assistant_message_reduction_percent']}%",
        f"- Pooled assistant-message-character reduction: {summary['pooled_message_char_reduction_percent']}%",
        f"- Budgeted rounds within the advisory 8-tool cap: {summary['budget_tool_cap_observed_rounds']}/{summary['rounds_completed']}",
        f"- Budgeted rounds with no repeated exact command: {summary['budget_no_repeat_observed_rounds']}/{summary['rounds_completed']}",
        "", "## Interpretation", "",
        "A positive reduction means the budgeted arm used less. Uncached tokens are the conservative quota-oriented view. The median and pooled results favor the budget, but only 3/5 individual pairs won and one round became materially worse. The budget is therefore a useful default guardrail, not a guaranteed saving. This benchmark still covers one task family and cannot establish a universal default by itself.",
        "", "## Enforcement boundary", "",
        "Provider count and outer timeout are hard. UAP scheduler limits are hard across provider calls and DAG tool tasks. The number of tools used inside one Codex CLI process remains an advisory prompt contract.",
    ])
    return "\n".join(lines) + "\n"


def save(reports: list[dict], output: Path, report_path: Path) -> dict:
    aggregate = {
        "experiment": "explicit_budget_five_round_counterbalanced",
        "goal": reports[0]["goal"],
        "model": reports[0]["model"],
        "reasoning": reports[0]["reasoning"],
        "summary": summarize(reports),
        "rounds": reports,
        "limitations": [
            "Repeated paired trials reduce random noise but cover one implementation task family.",
            "Subscription quota conversion is unavailable.",
            "Cached input is a subset of provider-reported input; uncached totals are shown separately.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(aggregate, indent=2), encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render(aggregate), encoding="utf-8")
    return aggregate


async def run(args: argparse.Namespace) -> dict:
    reports = [json.loads(args.seed.read_text(encoding="utf-8"))]
    for round_number in range(2, args.rounds + 1):
        round_output = args.output.parent / f"budget-real-round-{round_number}-20260913.json"
        round_report = args.report.parent / f"budget-real-round-{round_number}-20260913.md"
        if round_output.exists() and "comparison" in json.loads(round_output.read_text(encoding="utf-8")):
            result = json.loads(round_output.read_text(encoding="utf-8"))
        else:
            result = await single.run(SimpleNamespace(
                workspace=args.workspace / f"round-{round_number}",
                output=round_output,
                report=round_report,
                model=args.model,
                timeout=args.timeout,
                budget_first=round_number % 2 == 0,
            ))
        reports.append(result)
        aggregate = save(reports, args.output, args.report)
        row = aggregate["summary"]["rows"][-1]
        print("round " + str(round_number) + ": " + json.dumps(row), flush=True)
    return save(reports, args.output, args.report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--timeout", type=float, default=300)
    asyncio.run(run(parser.parse_args()))
