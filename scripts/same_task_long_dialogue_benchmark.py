"""Run one coherent 10-turn UI/UX conversation in each persistent Codex task.

The user requests are fixed; quality is checked independently after every turn.
Failures remain visible and the next natural follow-up still runs. No retry is
silently free. This is a bounded real-provider experiment, not a quota estimate.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any

try:
    from scripts.design_longitudinal_benchmark import seed
    from scripts.same_task_dialogue_benchmark import CodexProvider, Dialogue, MODEL, prompt_for
    from scripts.same_task_quality import GOALS, evaluate
except ModuleNotFoundError:
    from design_longitudinal_benchmark import seed
    from same_task_dialogue_benchmark import CodexProvider, Dialogue, MODEL, prompt_for
    from same_task_quality import GOALS, evaluate
from adaptive_agent.project.adapter import initialize_project
from adaptive_agent.runtime import RESOURCE_ROOT


def summary(rows: list[dict[str, Any]], requested: int) -> dict[str, Any]:
    return {
        "turns_completed": len(rows), "requested_turns": requested,
        "total_tokens": sum(row["usage"]["total_tokens"] for row in rows),
        "uncached_tokens": sum(row["usage"]["uncached_tokens"] for row in rows),
        "cached_input_tokens": sum(row["usage"]["cached_input_tokens"] for row in rows),
        "wall_seconds": round(sum(row["seconds"] for row in rows), 2),
        "quality_passes": sum(row["quality"]["passed"] for row in rows),
        "final_contract_passed": len(rows) == requested and bool(rows[-1]["quality"]["passed"]),
    }


def save(report: dict, workspace: Path) -> None:
    (workspace / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


async def run(args: argparse.Namespace) -> dict:
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit("Choose a new workspace; prior evidence is immutable.")
    if args.turns != len(GOALS):
        raise SystemExit(f"This coherent scenario contains exactly {len(GOALS)} follow-ups.")
    if args.max_tokens_per_arm <= 0 or args.max_seconds_per_arm <= 0:
        raise SystemExit("Safety ceilings must be positive.")
    if not CodexProvider().probe().ready:
        raise SystemExit("Codex is unavailable")
    workspace.mkdir(parents=True)
    report: dict[str, Any] = {
        "method": "paired_persistent_task_coherent_dialogue_v1",
        "model": MODEL, "reasoning": "low", "scenario": "caregiver medication planner UI/UX",
        "prompts": GOALS, "arms": {}, "quality_contract": "same_task_quality.evaluate",
        "limitations": ["deterministic checks do not prove visual or real-browser quality",
                        "UAP arm uses initialized project + packet, not full Orchestrator",
                        "arm order is not counterbalanced in one pair",
                        "provider tokens are not subscription quota units"],
        "safety_ceiling": {"start_threshold_tokens_per_arm": args.max_tokens_per_arm,
                           "seconds_per_arm": args.max_seconds_per_arm,
                           "note": "Token threshold is checked before each turn; the final turn may exceed it."}}
    for arm in args.order:
        root = workspace / arm
        seed(root, "ui-ux")
        if arm == "uap":
            initialize_project(root, RESOURCE_ROOT / "templates", auto=True)
        rows: list[dict[str, Any]] = []
        started = time.monotonic()
        report["arms"][arm] = {"turns": rows, "outcome": "running"}
        save(report, workspace)
        try:
            async with Dialogue(root, args.timeout) as dialogue:
                report["arms"][arm]["thread_id"] = dialogue.thread_id
                for number, goal in enumerate(GOALS, 1):
                    totals = summary(rows, args.turns)
                    if totals["total_tokens"] >= args.max_tokens_per_arm or (
                            time.monotonic() - started >= args.max_seconds_per_arm):
                        report["arms"][arm]["outcome"] = "safety_ceiling_unfinished"
                        break
                    prompt = prompt_for(arm, root, goal)
                    remaining = args.max_seconds_per_arm - (time.monotonic() - started)
                    dialogue.timeout = min(args.timeout, max(1, remaining))
                    turn = await dialogue.turn(prompt)
                    turn["number"] = number
                    turn["prompt"] = goal
                    turn["prompt_chars_sent"] = len(prompt)
                    turn["quality"] = evaluate(root, number)
                    artifact = root / "prototype.html"
                    if artifact.is_file():
                        snapshots = workspace / "snapshots" / arm
                        snapshots.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(artifact, snapshots / f"turn-{number:02d}.html")
                        turn["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
                    rows.append(turn)
                    report["arms"][arm]["summary"] = summary(rows, args.turns)
                    save(report, workspace)
                    print(f"{arm} {number}/{args.turns}: {turn['usage']['total_tokens']} "
                          f"total, {turn['usage']['uncached_tokens']} uncached, "
                          f"quality={'PASS' if turn['quality']['passed'] else 'FAIL'} "
                          f"{turn['quality']['errors']}", flush=True)
                    if turn["status"] != "completed":
                        report["arms"][arm]["outcome"] = "provider_turn_unfinished"
                        break
                else:
                    report["arms"][arm]["outcome"] = "script_complete"
        except Exception as error:
            report["arms"][arm]["outcome"] = "measurement_incomplete"
            report["arms"][arm]["error"] = type(error).__name__ + ": " + str(error)
            save(report, workspace)
            raise
        report["arms"][arm]["summary"] = summary(rows, args.turns)
        save(report, workspace)
    report["comparison_valid"] = all(
        report["arms"][arm]["outcome"] == "script_complete"
        and report["arms"][arm]["summary"]["final_contract_passed"]
        for arm in ("baseline", "uap"))
    save(report, workspace)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="authorize real model calls")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--turns", type=int, default=10)
    parser.add_argument("--order", nargs=2, choices=("baseline", "uap"),
                        default=("baseline", "uap"))
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--max-tokens-per-arm", type=int, default=2_000_000)
    parser.add_argument("--max-seconds-per-arm", type=float, default=2400)
    args = parser.parse_args()
    if set(args.order) != {"baseline", "uap"}:
        raise SystemExit("--order must include baseline and uap once each")
    if not args.execute:
        print(json.dumps({"ready": True, "turns_per_arm": len(GOALS),
                          "provider_calls": 0, "prompts": GOALS}, indent=2))
        return
    result = asyncio.run(run(args))
    print(json.dumps({"comparison_valid": result["comparison_valid"],
                      "arms": {arm: {"outcome": item["outcome"],
                                     "summary": item["summary"]}
                               for arm, item in result["arms"].items()},
                      "report": str(args.workspace.resolve() / "report.json")}, indent=2))


if __name__ == "__main__":
    main()
