"""Re-score immutable animation source snapshots after a documented checker fix.

Never overwrites the original run report or snapshots. The new result records
both the original and corrected quality decisions for every provider turn.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.same_task_domain_quality import evaluate_animation
except ModuleNotFoundError:
    from same_task_domain_quality import evaluate_animation


def rescore(workspace: Path) -> dict:
    workspace = workspace.resolve()
    report = json.loads((workspace / "report.json").read_text(encoding="utf-8"))
    if report.get("domain") != "animation":
        raise ValueError("only animation snapshots are supported")
    payload = {"method": "immutable_animation_snapshot_rescore_v1",
               "source_report": str(workspace / "report.json"),
               "reason": "accept both bare xyz tuples and scene nodes with position xyz",
               "arms": {}}
    for arm in ("baseline", "uap"):
        rows = []
        scratch = workspace / "rescore-check" / arm
        scratch.mkdir(parents=True, exist_ok=True)
        for original in report["arms"][arm]["turns"]:
            number = int(original["number"])
            snapshot = workspace / "snapshots" / arm / f"turn-{number:02d}.py"
            if not snapshot.is_file():
                raise FileNotFoundError(snapshot)
            corrected = evaluate_animation(scratch, number, source=snapshot)
            rows.append({"turn": number, "snapshot": str(snapshot),
                         "original_passed": original["quality"]["passed"],
                         "original_errors": original["quality"]["errors"],
                         "corrected": corrected})
        payload["arms"][arm] = {
            "turns": rows, "quality_passes": sum(row["corrected"]["passed"] for row in rows),
            "final_contract_passed": len(rows) == 10 and bool(rows[-1]["corrected"]["passed"]),
            "total_tokens": report["arms"][arm]["summary"]["total_tokens"],
            "uncached_tokens": report["arms"][arm]["summary"]["uncached_tokens"],
        }
    payload["comparison_valid"] = all(
        payload["arms"][arm]["final_contract_passed"] for arm in ("baseline", "uap"))
    (workspace / "rescore.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    result = rescore(args.workspace)
    print(json.dumps({"comparison_valid": result["comparison_valid"],
                      "quality_passes": {arm: result["arms"][arm]["quality_passes"]
                                         for arm in ("baseline", "uap")},
                      "rescore": str(args.workspace.resolve() / "rescore.json")}, indent=2))


if __name__ == "__main__":
    main()
