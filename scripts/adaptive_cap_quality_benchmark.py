"""Paired SOL benchmark for cap 8 versus cap 6 with cost-to-quality accounting."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

try:
    from scripts.adaptive_tool_budget_benchmark import _reset
    from scripts.context_cache_benchmark import ACCEPTANCE, FIXTURE, GOAL, TASKS, acceptance, source_hash, task
    from scripts.direct_benchmark import MeteredCodex, Packet
    from scripts.quality_completion_benchmark import Ledger, converge
    from adaptive_agent.project.direct import prepare
except ModuleNotFoundError:
    from adaptive_tool_budget_benchmark import _reset
    from context_cache_benchmark import ACCEPTANCE, FIXTURE, GOAL, TASKS, acceptance, source_hash, task
    from direct_benchmark import MeteredCodex, Packet
    from quality_completion_benchmark import Ledger, converge
    from adaptive_agent.project.direct import prepare

MODEL = "gpt-5.6-sol"
ARMS = {"normal_8": 8, "reduced_6": 6}
MESSAGE_CAP = 12


class CapPacket(Packet):
    def __init__(self, root: Path, goal: str, context: dict, cap: int,
                 batching: bool = True):
        # The legacy Packet hard-codes the large monthly-report contract. A
        # scale benchmark must carry only the selected task's contract.
        self.working_directory = root
        self.text = (
            "Complete this implementation in the current workspace.\n"
            + goal + "\n"
            "Return JSON matching the supplied schema, with a short factual summary. "
            "Report changed files only when actually changed. Do not start other AI agents. "
            "Do not access sibling workspaces. Preserve existing expense behavior.\n"
            + json.dumps(context, ensure_ascii=False) + "\n"
            "\nBOUNDED EXECUTION:\n"
            f"- Hard envelope: {cap} provider tool calls and {MESSAGE_CAP} assistant messages.\n"
            "- Do not repeat successful commands or add a final repository-status pass.\n"
            "- Keep the final response under 250 words.\n"
        )
        if batching:
            self.text += (
                "- Batch independent inspection and edits; validate once after implementation.\n"
            )


def summarize(rows: list[dict]) -> dict:
    totals = {
        arm: {key: sum(int(row["arms"][arm].get(key, 0)) for row in rows)
              for key in ("observed_tokens", "cached_input", "output_tokens",
                          "provider_tool_calls", "provider_messages", "attempts")}
        for arm in ARMS
    }
    normal = totals["normal_8"]["observed_tokens"]
    reduced = totals["reduced_6"]["observed_tokens"]
    totals["reduced_token_delta"] = reduced - normal
    totals["reduced_percent_delta"] = ((reduced - normal) / normal * 100 if normal else None)
    eligible = [row for row in rows if all(
        value["outcome"] == "contract_passed" and value["measurement_complete"]
        for value in row["arms"].values())]
    totals["pair_wins"] = {
        "normal_8": sum(row["arms"]["normal_8"]["observed_tokens"]
                        < row["arms"]["reduced_6"]["observed_tokens"] for row in eligible),
        "reduced_6": sum(row["arms"]["reduced_6"]["observed_tokens"]
                         < row["arms"]["normal_8"]["observed_tokens"] for row in eligible),
        "ties": sum(row["arms"]["reduced_6"]["observed_tokens"]
                    == row["arms"]["normal_8"]["observed_tokens"] for row in eligible),
        "excluded": len(rows) - len(eligible),
    }
    totals["all_contracts_passed"] = all(
        value["outcome"] == "contract_passed" for row in rows for value in row["arms"].values())
    totals["all_measurements_complete"] = all(
        value["measurement_complete"] for row in rows for value in row["arms"].values())
    return totals


async def execute(args: argparse.Namespace) -> dict:
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit("Use a new workspace; prior attempts are immutable evidence.")
    workspace.mkdir(parents=True)
    ledger = Ledger(workspace / "attempts.sqlite3")
    report = {
        "experiment": "paired_cap_8_vs_6_cost_to_quality_v1",
        "tasks": [TASKS[name] for name in args.tasks],
        "model": MODEL,
        "reasoning": "low",
        "prompt_mode": args.prompt_mode,
        "acceptance_sha256": hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest(),
        "pairs": [],
        "limits": {"tokens_per_arm_pair": args.token_ceiling,
                   "seconds_per_arm_pair": args.seconds_ceiling},
    }
    plan = [(task_id, number) for task_id in args.tasks
            for number in range(1, args.pairs + 1)]
    for task_id, number in plan:
        goal = TASKS[task_id]["goal"]
        pair_root = workspace / task_id / f"pair-{number}"
        roots = {arm: pair_root / arm for arm in ARMS}
        for root in roots.values():
            _reset(root, workspace, preserve_learning=False)
        hashes = {arm: source_hash(root) for arm, root in roots.items()}
        if len(set(hashes.values())) != 1:
            raise RuntimeError("Application sources differ before execution")
        contexts = {arm: prepare(root, goal, read_sources=True, value_gated=True)["context"]
                    for arm, root in roots.items()}
        row = {"task_id": task_id, "pair": number,
               "order": (["normal_8", "reduced_6"] if number % 2
                         else ["reduced_6", "normal_8"]),
               "arms": {}}
        for arm in row["order"]:
            root, cap = roots[arm], ARMS[arm]

            async def invoke(prompt: str, root=root, cap=cap, context=contexts[arm],
                             task_id=task_id) -> dict:
                provider = MeteredCodex(timeout=min(600, args.seconds_ceiling))
                if not provider.probe().ready:
                    return {"status": "failed", "model": MODEL, "token_source": "unavailable",
                            "usage_complete": False, "error": "codex_unavailable"}
                current = task(root, MODEL, "low", goal=prompt)
                current.metadata["execution_budget"] = {
                    "max_provider_tool_calls": cap,
                    "max_provider_messages": MESSAGE_CAP,
                    "completion_probe_passes": 2,
                    "completion_probe_grace_seconds": 1.0,
                    "completion_steer_grace_seconds": 20.0,
                    "completion_interrupt_grace_seconds": 15.0,
                }
                # This flag belongs to task metadata, not inside execution_budget.
                # It selects the app-server path that emits a final exact usage update.
                current.metadata["codex_live_usage"] = True
                packet = CapPacket(
                    root, prompt, context, cap,
                    batching=args.prompt_mode == "batch")
                started = time.monotonic()
                receipt = await provider.execute(
                    current, packet=packet,
                    completion_probe=lambda: acceptance(root, task_id)["passed"])
                usage = receipt.token_usage
                telemetry = getattr(provider, "telemetry", {})
                return {
                    "status": receipt.status,
                    "model": receipt.model or MODEL,
                    "input_tokens": int(usage.get("input", 0)),
                    "cached_input": int(usage.get("cached", 0)),
                    "output_tokens": int(usage.get("output", 0)),
                    "token_source": usage.get("source", "unavailable"),
                    "usage_complete": bool(usage.get("complete", False)),
                    "provider_tool_calls": int(usage.get("provider_tool_calls",
                                                          telemetry.get("tool_calls", 0))),
                    "provider_messages": int(usage.get("provider_messages",
                                                        telemetry.get("assistant_messages", 0))),
                    "duration_seconds": time.monotonic() - started,
                    "error": receipt.error_code,
                }

            row["arms"][arm] = await converge(
                ledger, "adaptive-cap-" + task_id, number, arm, goal, invoke,
                lambda root=root, task_id=task_id: acceptance(root, task_id),
                token_ceiling=args.token_ceiling,
                seconds_ceiling=args.seconds_ceiling,
            )
            row["arms"][arm]["cap"] = cap
        report["pairs"].append(row)
        report["summary"] = summarize(report["pairs"])
        (workspace / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(row), flush=True)
        if not all(value["outcome"] == "contract_passed" for value in row["arms"].values()):
            break
    if hashlib.sha256(ACCEPTANCE.read_bytes()).hexdigest() != report["acceptance_sha256"]:
        raise RuntimeError("Acceptance contract changed during benchmark")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=6)
    parser.add_argument("--tasks", nargs="+", choices=tuple(TASKS), default=["large"])
    parser.add_argument("--prompt-mode", choices=("plain", "batch"), default="batch")
    parser.add_argument("--token-ceiling", type=int, default=500000)
    parser.add_argument("--seconds-ceiling", type=float, default=900)
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required for real quota use")
    if args.pairs <= 0:
        parser.error("--pairs must be positive")
    asyncio.run(execute(args))


if __name__ == "__main__":
    main()
