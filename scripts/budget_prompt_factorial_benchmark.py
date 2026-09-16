"""SOL 2x2 benchmark: hard tool cap (8/6) x batching prompt (off/on)."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

try:
    from scripts import pocketflow_longitudinal_benchmark as programming
    from scripts.quality_completion_benchmark import Ledger, MODEL, converge
except ModuleNotFoundError:
    import pocketflow_longitudinal_benchmark as programming
    from quality_completion_benchmark import Ledger, MODEL, converge

from adaptive_agent.core.execution_packet import ExecutionPacketBuilder
from adaptive_agent.core.models import Task, new_id
from adaptive_agent.providers.registry import providers


ARMS = {
    "cap8_plain": {"cap": 8, "batching": False},
    "cap6_plain": {"cap": 6, "batching": False},
    "cap8_batch": {"cap": 8, "batching": True},
    "cap6_batch": {"cap": 6, "batching": True},
}
ORDERS = (
    ("cap8_plain", "cap6_plain", "cap8_batch", "cap6_batch"),
    ("cap6_plain", "cap8_batch", "cap6_batch", "cap8_plain"),
    ("cap8_batch", "cap6_batch", "cap8_plain", "cap6_plain"),
    ("cap6_batch", "cap8_plain", "cap6_plain", "cap8_batch"),
)
GOAL = "\n".join([
    "Build the complete PocketFlow personal expense application in this repository.",
    *[f"{number}. {goal}" for number, goal in enumerate(programming.TASKS, 1)],
    "All backend, API boundary, CSV, monthly-report, React integration, and deterministic test requirements must pass together.",
])
BATCHING_CONSTRAINTS = [
    "Batch independent file inspection into as few tool windows as practical.",
    "Plan the complete cross-stack change before editing; avoid alternating one-file inspection and one-file edits.",
    "Run the smallest complete validation after implementation and do not repeat successful checks.",
]


def summarize(blocks: list[dict]) -> dict:
    cells: dict[str, dict] = {}
    for arm in ARMS:
        values = [block["arms"][arm] for block in blocks]
        cells[arm] = {
            key: sum(int(value.get(key, 0)) for value in values)
            for key in ("observed_tokens", "cached_input", "output_tokens",
                        "provider_tool_calls", "provider_messages", "attempts")
        }
        cells[arm]["contracts_passed"] = sum(
            value.get("outcome") == "contract_passed" for value in values)
        cells[arm]["complete_measurements"] = sum(
            bool(value.get("measurement_complete")) for value in values)

    def pooled(*names: str) -> int:
        return sum(cells[name]["observed_tokens"] for name in names)

    cap8 = pooled("cap8_plain", "cap8_batch")
    cap6 = pooled("cap6_plain", "cap6_batch")
    plain = pooled("cap8_plain", "cap6_plain")
    batch = pooled("cap8_batch", "cap6_batch")
    cap_plain = cells["cap6_plain"]["observed_tokens"] - cells["cap8_plain"]["observed_tokens"]
    cap_batch = cells["cap6_batch"]["observed_tokens"] - cells["cap8_batch"]["observed_tokens"]
    batch_cap8 = cells["cap8_batch"]["observed_tokens"] - cells["cap8_plain"]["observed_tokens"]
    batch_cap6 = cells["cap6_batch"]["observed_tokens"] - cells["cap6_plain"]["observed_tokens"]
    return {
        "cells": cells,
        "main_effects": {
            "cap6_minus_cap8_tokens": cap6 - cap8,
            "cap6_percent": ((cap6 - cap8) / cap8 * 100 if cap8 else None),
            "batch_minus_plain_tokens": batch - plain,
            "batch_percent": ((batch - plain) / plain * 100 if plain else None),
            "cap_effect_with_plain_prompt": cap_plain,
            "cap_effect_with_batch_prompt": cap_batch,
            "batch_effect_at_cap8": batch_cap8,
            "batch_effect_at_cap6": batch_cap6,
            "interaction_difference_of_differences": cap_batch - cap_plain,
        },
        "all_contracts_passed": all(
            value.get("outcome") == "contract_passed"
            for block in blocks for value in block["arms"].values()),
        "all_measurements_complete": all(
            value.get("measurement_complete")
            for block in blocks for value in block["arms"].values()),
    }


async def execute(args: argparse.Namespace) -> dict:
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit("Use a new workspace; prior attempts are immutable evidence.")
    workspace.mkdir(parents=True)
    ledger = Ledger(workspace / "attempts.sqlite3")
    report = {
        "experiment": "tool_cap_x_batching_prompt_factorial_v1",
        "model": MODEL,
        "reasoning": "low",
        "goal": GOAL,
        "arms": ARMS,
        "blocks": [],
        "limits": {"tokens_per_arm_block": args.token_ceiling,
                   "seconds_per_arm_block": args.seconds_ceiling},
    }

    for block_number in range(1, args.blocks + 1):
        block_root = workspace / f"block-{block_number}"
        roots = {arm: block_root / arm for arm in ARMS}
        for root in roots.values():
            programming.seed(root)
        order = list(ORDERS[(block_number - 1) % len(ORDERS)])
        block = {"block": block_number, "order": order, "arms": {}}
        for arm in order:
            root = roots[arm]
            treatment = ARMS[arm]

            async def invoke(prompt: str, *, root=root, treatment=treatment) -> dict:
                provider = providers().create("codex", timeout=min(600, args.seconds_ceiling))
                if not provider.probe().ready:
                    return {"status": "failed", "model": MODEL,
                            "token_source": "unavailable", "usage_complete": False,
                            "error": "codex_unavailable"}
                current = Task(
                    new_id("FACTOR"), "Developer", prompt, "developer",
                    ["coding", "filesystem", "write_access", "repository_access"],
                    reasoning="low", metadata={
                        "working_directory": str(root), "model": MODEL,
                        "goal": prompt, "read_only": False,
                        "codex_live_usage": True,
                        "constraints": (BATCHING_CONSTRAINTS
                                        if treatment["batching"] else []),
                        "execution_budget": {
                            "max_provider_tool_calls": treatment["cap"],
                            "max_provider_messages": 12,
                            "completion_probe_passes": 2,
                            "completion_probe_grace_seconds": 1.0,
                            "completion_steer_grace_seconds": 20.0,
                            "completion_interrupt_grace_seconds": 15.0,
                        },
                    })
                packet = ExecutionPacketBuilder().build(
                    current, root, "pocketflow-expenses", "python")
                started = time.monotonic()
                receipt = await provider.execute(
                    current, packet=packet,
                    completion_probe=lambda: programming.evaluate(root, 5)["passed"])
                usage = receipt.token_usage
                return {
                    "status": receipt.status,
                    "model": receipt.model or MODEL,
                    "input_tokens": int(usage.get("input", 0)),
                    "cached_input": int(usage.get("cached", 0)),
                    "output_tokens": int(usage.get("output", 0)),
                    "token_source": usage.get("source", "unavailable"),
                    "usage_complete": bool(usage.get("complete", False)),
                    "provider_tool_calls": int(usage.get("provider_tool_calls", 0)),
                    "provider_messages": int(usage.get("provider_messages", 0)),
                    "duration_seconds": time.monotonic() - started,
                    "error": receipt.error_code,
                }

            block["arms"][arm] = await converge(
                ledger, "factorial", block_number, arm, GOAL, invoke,
                lambda root=root: programming.evaluate(root, 5),
                token_ceiling=args.token_ceiling,
                seconds_ceiling=args.seconds_ceiling,
            )
            block["arms"][arm].update(treatment)
        report["blocks"].append(block)
        report["summary"] = summarize(report["blocks"])
        (workspace / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(block), flush=True)
        if not all(value["outcome"] == "contract_passed"
                   for value in block["arms"].values()):
            break
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--blocks", type=int, default=2)
    parser.add_argument("--token-ceiling", type=int, default=700000)
    parser.add_argument("--seconds-ceiling", type=float, default=1200)
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required for real quota use")
    if args.blocks <= 0:
        parser.error("--blocks must be positive")
    asyncio.run(execute(args))


if __name__ == "__main__":
    main()
