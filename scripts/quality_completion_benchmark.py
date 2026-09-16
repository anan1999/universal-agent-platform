"""Cost to contract acceptance: persistent attempts, own-arm repair, no turn cap.

Contract acceptance is NOT a visual/usability quality endorsement. Every provider
attempt is retained in SQLite; budget exhaustion is an unfinished outcome.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

try:
    from scripts import design_longitudinal_benchmark as design
except ModuleNotFoundError:
    import design_longitudinal_benchmark as design

MODEL = "gpt-5.6-sol"


class Ledger:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("""CREATE TABLE IF NOT EXISTS attempts(
            id INTEGER PRIMARY KEY, domain TEXT, task INTEGER, arm TEXT,
            prompt TEXT, result TEXT, quality TEXT, state TEXT)""")
        self.connection.commit()

    def start(self, domain: str, task: int, arm: str, prompt: str) -> int:
        cursor = self.connection.execute(
            "INSERT INTO attempts(domain,task,arm,prompt,state) VALUES(?,?,?,?,?)",
            (domain, task, arm, prompt, "started"))
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish(self, attempt: int, result: dict, quality: dict) -> None:
        self.connection.execute(
            "UPDATE attempts SET result=?,quality=?,state='finished' WHERE id=?",
            (json.dumps(result), json.dumps(quality), attempt))
        self.connection.commit()

    def rows(self, domain: str, task: int, arm: str) -> list[dict]:
        return [{"id": row[0], "result": json.loads(row[1]) if row[1] else {},
                 "quality": json.loads(row[2]) if row[2] else {}, "state": row[3]}
                for row in self.connection.execute(
                    "SELECT id,result,quality,state FROM attempts "
                    "WHERE domain=? AND task=? AND arm=? ORDER BY id", (domain, task, arm))]


def cost(rows: list[dict]) -> dict:
    results = [row["result"] for row in rows]
    exact = bool(results) and all(
        row["state"] == "finished" and row["result"].get("token_source") == "measured"
        and row["result"].get("usage_complete") for row in rows)
    return {"attempts": len(rows), "measurement_complete": exact,
            "observed_tokens": sum(design._tokens(result) for result in results),
            "cached_input": sum(int(result.get("cached_input", 0)) for result in results),
            "output_tokens": sum(int(result.get("output_tokens", 0)) for result in results)}


async def converge(ledger: Ledger, domain: str, task: int, arm: str, goal: str,
                   invoke: Any, validate: Any, *, token_ceiling: int,
                   seconds_ceiling: float, clock=time.monotonic) -> dict:
    """Every retry edits its own existing artifact and receives explicit defects."""
    started = clock()
    while True:
        rows = ledger.rows(domain, task, arm)
        totals = cost(rows)
        if rows:
            last = rows[-1]
            if not totals["measurement_complete"]:
                return {**totals, "outcome": "measurement_incomplete"}
            if last["result"].get("model") not in (MODEL, [MODEL]):
                return {**totals, "outcome": "model_mismatch"}
            if last["quality"].get("passed") and last["result"].get("status") == "completed":
                return {**totals, "outcome": "contract_passed",
                        "visual_usability_quality": "not_evaluated"}
        elapsed = clock() - started
        if totals["observed_tokens"] >= token_ceiling or elapsed >= seconds_ceiling:
            return {**totals, "outcome": "budget_exhausted_unfinished"}
        feedback = ("\nIndependent acceptance found these defects: "
                    + json.dumps(rows[-1]["quality"].get("errors", []))
                    + ". Fix them in your existing files. Preserve all previously passing requirements."
                    if rows else "")
        prompt = goal + feedback
        attempt = ledger.start(domain, task, arm, prompt)
        try:
            result = await asyncio.wait_for(invoke(prompt), seconds_ceiling - elapsed)
        except Exception as error:
            # Unknown usage must not become an apparently free retry.
            result = {"status": "failed", "token_source": "unavailable",
                      "usage_complete": False, "error": type(error).__name__}
        try:
            quality = validate()
        except Exception as error:
            quality = {"passed": False, "errors": ["validator:" + type(error).__name__]}
        ledger.finish(attempt, result, quality)


async def execute(args: argparse.Namespace) -> dict:
    workspace = args.workspace.resolve()
    if workspace.exists():
        raise SystemExit("Use a new workspace; prior attempts are immutable evidence.")
    if args.token_ceiling <= 0 or args.seconds_ceiling <= 0:
        raise SystemExit("Safety ceilings must be positive.")
    provider = design.providers().create("codex", timeout=min(600, args.seconds_ceiling))
    if not provider.probe().ready:
        raise SystemExit("Codex unavailable; no benchmark started.")
    workspace.mkdir(parents=True)
    ledger = Ledger(workspace / "attempts.sqlite3")
    report: dict = {"method": "cost_to_contract_acceptance_v1", "model": MODEL,
                   "visual_usability_quality": "not_evaluated",
                   "quality_savings_claimable": False, "tasks": [],
                   "limits": {"tokens_per_arm_task": args.token_ceiling,
                              "seconds_per_arm_task": args.seconds_ceiling}}
    specs = design.contracts()
    for domain in args.domains:
        roots = {arm: workspace / domain / arm for arm in ("baseline", "uap")}
        for root in roots.values():
            design.seed(root, domain)
        design.initialize_project(roots["uap"], design.RESOURCE_ROOT / "templates", auto=True)
        db = design.Database(workspace / domain / "uap-history.db")
        for number, spec in enumerate(specs[domain], 1):
            row = {"domain": domain, "task": number, "goal": spec["goal"], "arms": {}}
            # Alternate order; each arm retains its own prior accepted work.
            for arm in (("baseline", "uap") if number % 2 else ("uap", "baseline")):
                root = roots[arm]

                async def invoke(prompt, arm=arm, root=root):
                    if arm == "baseline":
                        return await design.baseline_run(provider, root, domain, number,
                                                         prompt, MODEL, "low", limit_tools=False)
                    return await design.uap_run(provider, root, domain, number,
                                                prompt, db, "codex", MODEL)

                row["arms"][arm] = await converge(
                    ledger, domain, number, arm, spec["goal"], invoke,
                    lambda: design.evaluate(root, domain, number),
                    token_ceiling=args.token_ceiling, seconds_ceiling=args.seconds_ceiling)
            report["tasks"].append(row)
            report["observed_tokens"] = {
                arm: sum(item["arms"][arm]["observed_tokens"] for item in report["tasks"])
                for arm in ("baseline", "uap")}
            (workspace / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(row), flush=True)
            if any(item["outcome"] != "contract_passed" for item in row["arms"].values()):
                # No free transfer of the other arm's successful implementation.
                break
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--domains", nargs="+", choices=design.DOMAINS, default=list(design.DOMAINS))
    parser.add_argument("--token-ceiling", type=int, default=400000)
    parser.add_argument("--seconds-ceiling", type=float, default=900)
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required for real quota use")
    asyncio.run(execute(args))


if __name__ == "__main__":
    main()
