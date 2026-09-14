"""One tiny real Codex check proving live provider-event cancellation."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adaptive_agent.core.models import Task
from adaptive_agent.providers.codex.provider import CodexProvider


async def run(args: argparse.Namespace) -> dict:
    provider = CodexProvider(timeout=args.timeout)
    if not provider.probe().ready:
        raise SystemExit("Codex is unavailable")
    tool_mode = args.limit == "tool"
    budget = ({"max_provider_tool_calls": 0, "max_provider_messages": None}
              if tool_mode else {"max_provider_tool_calls": None,
                                 "max_provider_messages": 1})
    instruction = ("Use a shell command to read pyproject.toml, then report the package name."
                   if tool_mode else "Explain briefly how you would inspect pyproject.toml.")
    working_directory = (ROOT / "benchmark-fixtures" / "live-budget"
                         if tool_mode else ROOT)
    task = Task("LIVE-BUDGET", "LIVE-BUDGET-RUN", instruction, "budget_tester",
                ["filesystem", "repository_access"], metadata={
                    "working_directory": str(working_directory),
                    "read_only": not tool_mode,
                    "model": args.model,
                    "execution_budget": budget,
                }, reasoning="low")
    started = time.monotonic()
    receipt = await provider.execute(task)
    report = {
        "experiment": f"live_codex_{args.limit}_budget",
        "model": args.model,
        "timeout_seconds": args.timeout,
        "budget": budget,
        "status": receipt.status,
        "error_code": receipt.error_code,
        "summary": receipt.summary,
        "duration_seconds": round(time.monotonic() - started, 3),
        "usage": receipt.token_usage,
        "passed": (receipt.error_code == "BUDGET_EXHAUSTED" and
                   ("provider tool-call budget" if tool_mode
                    else "provider assistant-message budget") in receipt.summary),
        "expected": ("The first attempted provider tool is rejected and the child is terminated."
                     if tool_mode else
                     "The second assistant message exceeds the one-message budget and terminates the child."),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--limit", choices=("tool", "message"), default="tool")
    result = asyncio.run(run(parser.parse_args()))
    raise SystemExit(0 if result["passed"] else 1)
