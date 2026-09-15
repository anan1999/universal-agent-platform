"""Aggregate selected tracks from retained longitudinal design benchmark runs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def percent(baseline: int, uap: int) -> float | None:
    return round((baseline - uap) / baseline * 100, 2) if baseline else None


def attribution(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("token_attribution") or {}
    groups = value.get("invocations", [value])
    by_kind: dict[str, int] = {}
    windows = 0
    for group in groups:
        for window in group.get("windows", []):
            kind = str(window.get("kind", "unknown"))
            by_kind[kind] = by_kind.get(kind, 0) + int(window.get("total_tokens", 0))
            windows += 1
    return {"windows": windows, "tokens_by_kind": by_kind,
            "tokens_exact": bool(value.get("token_totals_exact", False))}


def aggregate(selections: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    tracks = []
    valid_rows = []
    all_rows = []
    for domain, source in selections:
        original = next(track for track in source["tracks"] if track["domain"] == domain)
        track = {"domain": domain, "source_environment": source["environment"], "rounds": []}
        for original_row in original["rounds"]:
            row = json.loads(json.dumps(original_row))
            for side in ("baseline", "uap"):
                result = row[side]
                total = int(result.get("input_tokens", 0)) + int(result.get("output_tokens", 0))
                result["total_tokens"] = total
                result["uncached_input"] = max(
                    0, int(result.get("input_tokens", 0)) - int(result.get("cached_input", 0)))
                result["attribution_summary"] = attribution(result)
            row["reduction_percent"] = percent(row["baseline"]["total_tokens"],
                                                row["uap"]["total_tokens"])
            track["rounds"].append(row)
            all_rows.append(row)
            if row.get("comparison_valid"):
                valid_rows.append(row)
        accepted = [row for row in track["rounds"] if row.get("comparison_valid")]
        baseline = sum(row["baseline"]["total_tokens"] for row in accepted)
        uap = sum(row["uap"]["total_tokens"] for row in accepted)
        track["summary"] = {"valid_rounds": len(accepted), "rounds": len(track["rounds"]),
                            "baseline_tokens": baseline, "uap_tokens": uap,
                            "reduction_percent": percent(baseline, uap)}
        tracks.append(track)
    baseline = sum(row["baseline"]["total_tokens"] for row in valid_rows)
    uap = sum(row["uap"]["total_tokens"] for row in valid_rows)
    sides = {}
    for side in ("baseline", "uap"):
        results = [row[side] for row in valid_rows]
        kinds: dict[str, int] = {}
        for result in results:
            for kind, tokens in result["attribution_summary"]["tokens_by_kind"].items():
                kinds[kind] = kinds.get(kind, 0) + int(tokens)
        sides[side] = {
            "input_tokens": sum(int(result.get("input_tokens", 0)) for result in results),
            "cached_input": sum(int(result.get("cached_input", 0)) for result in results),
            "uncached_input": sum(int(result.get("uncached_input", 0)) for result in results),
            "output_tokens": sum(int(result.get("output_tokens", 0)) for result in results),
            "provider_tool_calls": sum(int(result.get("provider_tool_calls", 0)) for result in results),
            "provider_messages": sum(int(result.get("provider_messages", 0)) for result in results),
            "attributed_tokens_by_kind": kinds,
        }
    return {"experiment": "selected_three_track_design_aggregate_v1", "tracks": tracks,
            "summary": {"valid_rounds": len(valid_rows), "total_rounds": len(all_rows),
                        "invalid_rounds": len(all_rows) - len(valid_rows),
                        "baseline_tokens": baseline, "uap_tokens": uap,
                        "token_difference": uap - baseline,
                        "reduction_percent": percent(baseline, uap),
                        "quality_equivalent_all_rounds": len(valid_rows) == len(all_rows),
                        "savings_claimable": len(valid_rows) == len(all_rows) and uap < baseline,
                        "valid_pairs": sides}}


def render(payload: dict[str, Any]) -> str:
    lines = ["# 三軌連續設計 Benchmark 彙整", "",
             "本報告固定選用 r3 的 UI/UX 軌，以及修正跨 profile 路由後 r4 的平面與 3D 軌。"
             "每輪 Baseline/UAP 從相同通過 checkpoint 開始；只有雙方品質、source hash 與精確 Token "
             "通知都通過的配對，才列入 Token 合計。", "",
             "| 領域 | 輪次 | 任務 | Baseline | UAP | 節省率 | B 品質 | UAP 品質 | 可比較 |",
             "|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for track in payload["tracks"]:
        for row in track["rounds"]:
            goal = row["goal"].replace("|", "/")
            lines.append(f"| {track['domain']} | {row['round']} | {goal} | "
                         f"{row['baseline']['total_tokens']} | {row['uap']['total_tokens']} | "
                         f"{row['reduction_percent']}% | "
                         f"{'PASS' if row['quality']['baseline']['passed'] else 'FAIL'} | "
                         f"{'PASS' if row['quality']['uap']['passed'] else 'FAIL'} | "
                         f"{row['comparison_valid']} |")
    lines += ["", "## 分領域結果", ""]
    for track in payload["tracks"]:
        item = track["summary"]
        lines += [f"- **{track['domain']}**：有效 {item['valid_rounds']}/{item['rounds']}；"
                  f"Baseline {item['baseline_tokens']}，UAP {item['uap_tokens']}；"
                  f"節省率 {item['reduction_percent']}%。"]
    summary = payload["summary"]
    baseline, uap = summary["valid_pairs"]["baseline"], summary["valid_pairs"]["uap"]
    lines += ["", "## 有效配對總計", "",
              f"- 有效輪：{summary['valid_rounds']}/{summary['total_rounds']}",
              f"- Baseline：{summary['baseline_tokens']} Token",
              f"- UAP：{summary['uap_tokens']} Token",
              f"- 差額：UAP 多 {summary['token_difference']} Token",
              f"- 節省率：{summary['reduction_percent']}%（負值代表 UAP 較貴）",
              f"- 全部輪次品質等價：{summary['quality_equivalent_all_rounds']}",
              f"- 可宣稱節省：{summary['savings_claimable']}", "",
              "## Token 結構（僅有效配對）", "",
              f"- Baseline：cached input {baseline['cached_input']}；uncached input "
              f"{baseline['uncached_input']}；output {baseline['output_tokens']}；"
              f"tool calls {baseline['provider_tool_calls']}；messages {baseline['provider_messages']}。",
              f"- UAP：cached input {uap['cached_input']}；uncached input "
              f"{uap['uncached_input']}；output {uap['output_tokens']}；"
              f"tool calls {uap['provider_tool_calls']}；messages {uap['provider_messages']}。", "",
              "## 主要問題", "",
              "1. UI/UX 三輪皆正確，但 UAP 累計較貴，表示小型單檔案任務的固定封包成本尚未攤平。",
              "2. 平面第 1 輪 Baseline 兩次獨立執行都違反標題層級；這是模型品質變異，該輪未列入 Token 比較。",
              "3. 修正前 follow-up 會漂移到 Documentation Planner；修正後平面與 3D follow-up 已回到 Visual Designer。",
              "4. 3D 第 2 輪雖品質通過，UAP 出現 235705 Token 尖峰；這是總體成本惡化的主因。",
              "5. UAP 第 3 輪在平面與 3D 都低於 Baseline，表示重用可能在後段生效，但目前不穩定且不足以抵銷尖峰。", "",
              "## 結論", "",
              "目前不能宣稱 UAP 在設計任務上『越用越少』。較精確的結論是：路由正確性已改善，"
              "後段輪次偶爾省 Token，但固定成本與 3D 工具往返尖峰仍使有效配對總成本高於 Baseline。"
              "下一步應針對 3D 第 2 輪的 attribution window 做尖峰消除，再用同一套三軌合約重跑。", "",
              "品質驗收涵蓋結構、規格與累積功能，不等同於盲測的人類美感評分；Provider Token 也不等同訂閱制 quota 單位。", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--track", action="append", required=True,
                        help="domain=benchmark-results/file.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    selections = []
    for value in args.track:
        domain, filename = value.split("=", 1)
        selections.append((domain, json.loads(Path(filename).read_text(encoding="utf-8"))))
    payload = aggregate(selections)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render(payload), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
