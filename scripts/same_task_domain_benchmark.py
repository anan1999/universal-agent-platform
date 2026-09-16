"""Paired ten-turn persistent Codex tasks for programming or 3D animation.

Each arm receives the same scripted user follow-ups, owns one real Codex thread,
and is checked against cumulative executable acceptance after each turn.
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
    from scripts.same_task_dialogue_benchmark import CodexProvider, Dialogue, MODEL
    from scripts.same_task_domain_quality import GOALS, EVALUATORS
except ModuleNotFoundError:
    from same_task_dialogue_benchmark import CodexProvider, Dialogue, MODEL
    from same_task_domain_quality import GOALS, EVALUATORS

from adaptive_agent.core.execution_packet import ExecutionPacketBuilder
from adaptive_agent.core.models import Task, new_id
from adaptive_agent.project.adapter import initialize_project
from adaptive_agent.runtime import RESOURCE_ROOT

ROOT = Path(__file__).resolve().parents[1]
CONFIG = {
    "programming": {"fixture": "same-task-programming", "artifact": "tracker.py",
                    "role": "developer", "project_type": "python", "profile": "software-engineering",
                    "capabilities": ["coding", "filesystem", "write_access", "repository_access"]},
    "animation": {"fixture": "same-task-animation", "artifact": "animation.py",
                  "role": "3d-animator", "project_type": "3d-animation", "profile": "design",
                  "capabilities": ["design", "filesystem", "write_access", "repository_access"]},
}


def prompt_for(arm: str, domain: str, root: Path, goal: str) -> str:
    if arm == "baseline":
        return (goal + " Work in this project and preserve earlier accepted behavior. "
                "Run the smallest useful validation; return the structured receipt.")
    config = CONFIG[domain]
    task = Task(new_id("DIALOGUE"), "DIALOGUE", goal, config["role"],
                config["capabilities"], reasoning="low",
                metadata={"working_directory": str(root), "model": MODEL})
    return ExecutionPacketBuilder().build(
        task, root, f"same-task-{domain}", config["project_type"]).render()


def summarize(rows: list[dict], planned: int) -> dict:
    return {"turns": len(rows), "planned": planned,
            "total_tokens": sum(row["usage"]["total_tokens"] for row in rows),
            "uncached_tokens": sum(row["usage"]["uncached_tokens"] for row in rows),
            "cached_input_tokens": sum(row["usage"]["cached_input_tokens"] for row in rows),
            "seconds": round(sum(row["seconds"] for row in rows), 2),
            "quality_passes": sum(row["quality"]["passed"] for row in rows),
            "final_contract_passed": len(rows) == planned and bool(rows[-1]["quality"]["passed"])}


def save(report: dict, workspace: Path) -> None:
    (workspace / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


async def run(args: argparse.Namespace) -> dict:
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit("Choose a new workspace; benchmark evidence is immutable.")
    if args.max_tokens_per_arm <= 0 or args.max_seconds_per_arm <= 0 or args.timeout <= 0:
        raise SystemExit("Safety limits must be positive.")
    if not CodexProvider().probe().ready:
        raise SystemExit("Codex provider is unavailable")
    domain = args.domain
    goals = GOALS[domain]
    config = CONFIG[domain]
    workspace.mkdir(parents=True)
    report: dict[str, Any] = {
        "method": "paired_persistent_task_domain_v1", "domain": domain,
        "model": MODEL, "reasoning": "low", "prompts": goals,
        "quality": "independent cumulative runtime contracts",
        "arms": {}, "order": args.order,
        "limitations": ["one pair with no blinded human quality rating",
                        "UAP arm uses initialized project and packet, not full Orchestrator",
                        "provider tokens are not subscription quota units"],
        "safety": {"pre_turn_token_threshold": args.max_tokens_per_arm,
                   "seconds_per_arm": args.max_seconds_per_arm,
                   "note": "A single in-flight turn may exceed the token threshold."}}
    for arm in args.order:
        root = workspace / arm
        shutil.copytree(ROOT / "benchmark-fixtures" / config["fixture"], root)
        if arm == "uap":
            initialize_project(root, RESOURCE_ROOT / "templates", auto=True)
        rows: list[dict] = []
        started = time.monotonic()
        report["arms"][arm] = {"turns": rows, "outcome": "running"}
        save(report, workspace)
        try:
            async with Dialogue(root, args.timeout) as dialogue:
                report["arms"][arm]["thread_id"] = dialogue.thread_id
                for number, goal in enumerate(goals, 1):
                    if (summarize(rows, len(goals))["total_tokens"] >= args.max_tokens_per_arm
                            or time.monotonic() - started >= args.max_seconds_per_arm):
                        report["arms"][arm]["outcome"] = "safety_threshold_unfinished"
                        break
                    prompt = prompt_for(arm, domain, root, goal)
                    remaining = args.max_seconds_per_arm - (time.monotonic() - started)
                    dialogue.timeout = min(args.timeout, max(1, remaining))
                    result = await dialogue.turn(prompt)
                    result["number"] = number
                    result["prompt"] = goal
                    result["prompt_chars_sent"] = len(prompt)
                    result["quality"] = EVALUATORS[domain](root, number)
                    artifact = root / config["artifact"]
                    if artifact.is_file():
                        evidence = workspace / "snapshots" / arm
                        evidence.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(artifact, evidence / f"turn-{number:02d}.py")
                        result["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
                    if domain == "animation":
                        generated = root / ".quality-animation.gif"
                        if generated.is_file():
                            evidence = workspace / "snapshots" / arm
                            evidence.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(generated, evidence / f"turn-{number:02d}.gif")
                    rows.append(result)
                    report["arms"][arm]["summary"] = summarize(rows, len(goals))
                    save(report, workspace)
                    print(f"{domain} {arm} {number}/{len(goals)}: "
                          f"{result['usage']['total_tokens']} total, "
                          f"{result['usage']['uncached_tokens']} uncached, "
                          f"quality={'PASS' if result['quality']['passed'] else 'FAIL'} "
                          f"{result['quality']['errors']}", flush=True)
                    if result["status"] != "completed":
                        report["arms"][arm]["outcome"] = "provider_turn_unfinished"
                        break
                else:
                    report["arms"][arm]["outcome"] = "script_complete"
        except Exception as error:
            report["arms"][arm]["outcome"] = "measurement_incomplete"
            report["arms"][arm]["error"] = type(error).__name__ + ": " + str(error)
            save(report, workspace)
            raise
        report["arms"][arm]["summary"] = summarize(rows, len(goals))
        save(report, workspace)
    report["comparison_valid"] = all(
        report["arms"][arm]["outcome"] == "script_complete"
        and report["arms"][arm]["summary"]["final_contract_passed"]
        for arm in ("baseline", "uap"))
    save(report, workspace)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", choices=tuple(CONFIG), required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="authorize real provider use")
    parser.add_argument("--order", nargs=2, default=("baseline", "uap"))
    parser.add_argument("--timeout", type=float, default=360)
    parser.add_argument("--max-tokens-per-arm", type=int, default=2_000_000)
    parser.add_argument("--max-seconds-per-arm", type=float, default=3600)
    args = parser.parse_args()
    if set(args.order) != {"baseline", "uap"}:
        raise SystemExit("--order must contain baseline and uap once each")
    if not args.execute:
        print(json.dumps({"ready": True, "domain": args.domain,
                          "turns_per_arm": len(GOALS[args.domain]),
                          "provider_calls": 0, "prompts": GOALS[args.domain]}, indent=2))
        return
    result = asyncio.run(run(args))
    print(json.dumps({"comparison_valid": result["comparison_valid"],
                      "arms": {arm: {"outcome": item["outcome"],
                                     "summary": item["summary"]}
                               for arm, item in result["arms"].items()},
                      "report": str(args.workspace.resolve() / "report.json")}, indent=2))


if __name__ == "__main__":
    main()
