"""Programming cost-to-contract benchmark with own-arm state and repair accounting."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

try:
    from scripts import pocketflow_longitudinal_benchmark as programming
    from scripts.quality_completion_benchmark import Ledger, MODEL, converge
except ModuleNotFoundError:
    import pocketflow_longitudinal_benchmark as programming
    from quality_completion_benchmark import Ledger, MODEL, converge


async def execute(args: argparse.Namespace) -> dict:
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit("Use a new workspace; prior attempts are immutable evidence.")
    if args.token_ceiling <= 0 or args.seconds_ceiling <= 0:
        raise SystemExit("Safety ceilings must be positive.")
    provider = programming.providers().create("codex", timeout=min(600, args.seconds_ceiling))
    if not provider.probe().ready:
        raise SystemExit("Codex unavailable; no benchmark started.")

    workspace.mkdir(parents=True)
    roots = {arm: workspace / arm for arm in ("baseline", "uap")}
    for root in roots.values():
        programming.seed(root)
    programming.initialize_project(
        roots["uap"], programming.RESOURCE_ROOT / "templates", auto=True)
    database = programming.Database(workspace / "uap-history.db")
    ledger = Ledger(workspace / "attempts.sqlite3")
    report: dict = {
        "method": "programming_cost_to_contract_acceptance_v1",
        "model": MODEL,
        "suite": "pocketflow-expenses",
        "quality": "pytest_and_external_api_contracts",
        "tasks": [],
        "limits": {
            "tokens_per_arm_task": args.token_ceiling,
            "seconds_per_arm_task": args.seconds_ceiling,
        },
    }

    for number, goal in enumerate(programming.TASKS, 1):
        row = {"task": number, "goal": goal, "arms": {}}
        order = ("baseline", "uap") if number % 2 else ("uap", "baseline")
        for arm in order:
            root = roots[arm]

            async def invoke(prompt: str, arm=arm, root=root) -> dict:
                if arm == "baseline":
                    return await programming.baseline_run(
                        provider, root, prompt, MODEL, "low", number)
                return await programming.uap_run(
                    provider, root, prompt, database, "codex", number, MODEL)

            row["arms"][arm] = await converge(
                ledger, "programming", number, arm, goal, invoke,
                lambda root=root, number=number: programming.evaluate(root, number),
                token_ceiling=args.token_ceiling,
                seconds_ceiling=args.seconds_ceiling,
            )
        report["tasks"].append(row)
        report["observed_tokens"] = {
            arm: sum(item["arms"][arm]["observed_tokens"] for item in report["tasks"])
            for arm in ("baseline", "uap")
        }
        (workspace / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(row), flush=True)
        if any(value["outcome"] != "contract_passed" for value in row["arms"].values()):
            break
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--token-ceiling", type=int, default=500000)
    parser.add_argument("--seconds-ceiling", type=float, default=900)
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required for real quota use")
    asyncio.run(execute(args))


if __name__ == "__main__":
    main()
