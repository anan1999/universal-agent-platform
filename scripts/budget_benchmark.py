"""Real A/B check for a task budget on one identical implementation task."""
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

from context_cache_benchmark import ACCEPTANCE, FIXTURE, GOAL, acceptance, source_hash, task
from direct_benchmark import MeteredCodex, Packet


class BudgetPacket(Packet):
    def __init__(self, root: Path, goal: str, budgeted: bool, context: dict | None = None):
        super().__init__(root, goal, context)
        self.budgeted = budgeted
        if budgeted:
            self.text += (
                "\nRESOURCE BUDGET (the parent enforces the provider timeout):\n"
                "- Use at most 8 observable tool calls inside this task.\n"
                "- Use one targeted inspection pass, one edit pass, and one final validation pass.\n"
                "- Do not repeat an identical command or emit progress-only assistant messages.\n"
                "- Keep the final response under 250 words.\n"
                "- Preserve enough time for acceptance validation.\n"
                "- If this is insufficient, stop and report evidence plus remaining work; do not extend it.\n"
            )


def _totals(result: dict) -> dict[str, int]:
    usage = result["usage"]
    return {
        "tokens": int(usage.get("input", 0)) + int(usage.get("output", 0)),
        "uncached_tokens": (int(usage.get("input", 0)) - int(usage.get("cached", 0)) +
                            int(usage.get("output", 0))),
        "tool_calls": int(result["telemetry"].get("tool_calls", 0)),
        "assistant_messages": int(result["telemetry"].get("assistant_messages", 0)),
        "assistant_message_chars": int(result["telemetry"].get("assistant_message_chars", 0)),
    }


def execution_order(budget_first: bool = False) -> list[str]:
    return ["budgeted", "unbounded"] if budget_first else ["unbounded", "budgeted"]


def render_report(report: dict) -> str:
    baseline = report["results"].get("unbounded", {})
    budgeted = report["results"].get("budgeted", {})
    lines = [
        "# UAP explicit-budget benchmark",
        "",
        "## Problem",
        "",
        report["goal"],
        "",
        "Both arms started from the same fixture hash, used the same model/reasoning, and were checked by the same offline acceptance test.",
        "",
        "## Budget under test",
        "",
        "One provider invocation, 8 advisory internal tool calls, no repeated command, one final validation pass, a 250-word final response, and a hard outer timeout.",
        "",
        "## Results",
        "",
        "| Arm | Quality | Tokens | Uncached tokens | Tool calls | Assistant messages | Message chars | Seconds |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in (("Unbounded", baseline), ("Budgeted", budgeted)):
        totals = _totals(item) if item else {}
        lines.append(
            f"| {name} | {'PASS' if item.get('quality', {}).get('passed') else 'FAIL'} | "
            f"{totals.get('tokens', 0)} | {totals.get('uncached_tokens', 0)} | "
            f"{totals.get('tool_calls', 0)} | "
            f"{totals.get('assistant_messages', 0)} | {totals.get('assistant_message_chars', 0)} | "
            f"{item.get('duration_seconds', 0)} |"
        )
    lines.extend(["", "## Conclusion", "", report.get("conclusion", "Incomplete."), "",
                  "## Limits", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> dict:
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit("Use a new workspace; benchmark evidence is never overwritten.")
    workspace.mkdir(parents=True)
    order = execution_order(getattr(args, "budget_first", False))
    roots = {name: workspace / name for name in order}
    for root in roots.values():
        shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    hashes = {name: source_hash(root) for name, root in roots.items()}
    assert len(set(hashes.values())) == 1
    report = {
        "experiment": "unbounded_vs_explicit_budget",
        "goal": GOAL,
        "source_hashes": hashes,
        "acceptance_sha256": hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest(),
        "model": args.model,
        "reasoning": "low",
        "order": order,
        "budget": {"provider_calls": 1, "internal_tool_calls": 8,
                   "final_words": 250, "outer_timeout_seconds": args.timeout},
        "enforcement": {"provider_calls": "hard by harness", "wall_time": "hard by provider",
                        "internal_tool_calls": "advisory; Codex CLI exposes no per-run hard flag here",
                        "final_words": "prompt contract"},
        "limitations": [
            "One ordered pair is evidence for this task, not a universal average.",
            "Subscription quota conversion is unavailable; measured provider tokens are reported when exposed.",
            "The Codex CLI child tool-call limit is advisory, while provider count and timeout are hard.",
            "Tool calls are observable JSONL events; hidden reasoning rounds are not observable.",
        ],
        "results": {},
    }
    for name, root in roots.items():
        provider = MeteredCodex(timeout=args.timeout)
        if not provider.probe().ready:
            raise SystemExit("Codex is not available")
        current = task(root, args.model, "low")
        if name == "budgeted" and getattr(args, "hard_provider_budget", False):
            current.metadata["execution_budget"] = {
                "max_provider_tool_calls": 8,
                "max_provider_messages": 5,
            }
        packet = BudgetPacket(root, GOAL, budgeted=name == "budgeted")
        started = time.perf_counter()
        receipt = await provider.execute(current, packet=packet)
        result = {
            "status": receipt.status,
            "usage": receipt.token_usage,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "quality": acceptance(root),
            "error": receipt.error_code,
            "telemetry": getattr(provider, "telemetry", {}),
            "packet_chars": len(packet.render()),
            "actual_source_changed": source_hash(root) != hashes[name],
        }
        report["results"][name] = result
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(name + ": " + json.dumps(result), flush=True)
    before, after = (_totals(report["results"][name]) for name in ("unbounded", "budgeted"))
    quality_equal = all(report["results"][name]["quality"]["passed"] for name in roots)
    token_delta = before["tokens"] - after["tokens"]
    token_percent = round(token_delta / before["tokens"] * 100, 2) if before["tokens"] else None
    uncached_delta = before["uncached_tokens"] - after["uncached_tokens"]
    uncached_percent = (round(uncached_delta / before["uncached_tokens"] * 100, 2)
                        if before["uncached_tokens"] else None)
    report["comparison"] = {
        "quality_equal_and_passed": quality_equal,
        "token_delta": token_delta,
        "token_reduction_percent": token_percent,
        "uncached_token_delta": uncached_delta,
        "uncached_token_reduction_percent": uncached_percent,
        "tool_call_delta": before["tool_calls"] - after["tool_calls"],
        "assistant_message_delta": before["assistant_messages"] - after["assistant_messages"],
    }
    if not quality_equal:
        report["conclusion"] = "Budget did not preserve acceptance quality; this envelope is too tight or unstable."
    elif token_delta > 0:
        report["conclusion"] = f"Budget preserved quality and reduced measured tokens by {token_percent}%."
    else:
        report["conclusion"] = "Budget preserved quality but did not reduce measured tokens in this pair."
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(report), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--budget-first", action="store_true")
    parser.add_argument("--hard-provider-budget", action="store_true")
    asyncio.run(run(parser.parse_args()))
