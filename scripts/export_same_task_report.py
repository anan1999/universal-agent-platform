"""Export privacy-minimized, versionable metrics from local task evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def export(workspace: Path) -> dict:
    workspace = workspace.resolve()
    raw = json.loads((workspace / "report.json").read_text(encoding="utf-8"))
    corrected = None
    if raw["domain"] == "animation":
        corrected = json.loads((workspace / "rescore.json").read_text(encoding="utf-8"))
    payload = {"method": "same_task_domain_public_evidence_v1",
               "domain": raw["domain"], "model": raw["model"],
               "reasoning": raw["reasoning"], "prompts": raw["prompts"],
               "quality_note": ("animation quality uses immutable snapshot rescore after "
                                "a documented tuple-vs-position-node checker fix"
                                if corrected else "original executable contract"),
               "arms": {}, "comparison_valid": bool(corrected["comparison_valid"]
                                                  if corrected else raw["comparison_valid"])}
    for arm in ("baseline", "uap"):
        original_rows = raw["arms"][arm]["turns"]
        corrected_rows = corrected["arms"][arm]["turns"] if corrected else None
        rows = []
        for index, original in enumerate(original_rows):
            quality = (corrected_rows[index]["corrected"] if corrected_rows
                       else original["quality"])
            rows.append({"turn": original["number"], "status": original["status"],
                         "total_tokens": original["usage"]["total_tokens"],
                         "uncached_tokens": original["usage"]["uncached_tokens"],
                         "cached_input_tokens": original["usage"]["cached_input_tokens"],
                         "seconds": original["seconds"],
                         "quality_passed": quality["passed"],
                         "quality_errors": quality["errors"],
                         "artifact_sha256": original.get("artifact_sha256")})
        payload["arms"][arm] = {"turns": rows,
                                "total_tokens": sum(row["total_tokens"] for row in rows),
                                "uncached_tokens": sum(row["uncached_tokens"] for row in rows),
                                "quality_passes": sum(row["quality_passed"] for row in rows)}
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = export(args.workspace)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"domain": result["domain"],
                      "comparison_valid": result["comparison_valid"],
                      "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
