# 可重用 Benchmark 量測環境

`scripts/context_cache_benchmark.py` 現在使用固定、版本化的題目 catalog，並把量測環境分成三層：

1. `benchmark-fixtures/context-cache/base` 是唯一的原始 fixture。
2. `<workspace>/prepared/base` 是依 source hash 建立的唯讀基準快照；fixture 沒變就直接重用。
3. `<workspace>/runs/<task>/<arm>` 是每個 A/B arm 的隔離工作目錄。它們一定從同一個 prepared snapshot 開始。

這樣不必每次重新設計 fixture 或驗收規則，但仍保留乾淨工作目錄，避免前一次模型修改污染下一次結果。

## 任務尺度

題目定義在 `benchmark-fixtures/context-cache/suite.json`，由小到大固定為：

| 尺度 | ID | 範圍 | 驗收重點 |
|---:|---|---|---|
| 1 | `small` | 單一後端 endpoint | 筆數與總額 |
| 2 | `medium` | 參數化後端報表 | 月份、總額、分類彙總 |
| 3 | `large` | 後端加前端 | API 合約與 React 呈現 |

每題都有 benchmark 自己擁有的 deterministic acceptance。模型聲稱完成不算通過。

## 安全的離線預檢

```bash
python scripts/context_cache_benchmark.py \
  --dry-run --task all \
  --workspace build/context-cache-benchmark \
  --output benchmark-results/context-cache-dry-run.json
```

這會驗證三個尺度、相同 source hash、context selection 與 prepared fixture 重用，AI 呼叫固定為 0。

## 真實量測

先從小題開始，確認 provider telemetry 可用，再逐步放大：

```bash
python scripts/context_cache_benchmark.py --execute --task small --provider codex
python scripts/context_cache_benchmark.py --execute --task medium --provider codex --resume
python scripts/context_cache_benchmark.py --execute --task large --provider codex --resume
```

也可以明確要求六次呼叫跑完整 suite：

```bash
python scripts/context_cache_benchmark.py --execute --task all --provider codex --resume
```

`--resume` 只重用 signature 完全相同、provider 已完成且 acceptance 再次通過的 arm。失敗、規格變更、模型變更、timeout 變更或 fixture hash 變更都不會被誤當成可重用成功結果。

若只修正 acceptance 或報表邏輯，不需要重跑模型。`--reanalyze` 會從 durable checkpoint 重新驗收現有 artifact，本次 provider 呼叫固定為 0；報表另保留建立這些 checkpoint 時的 historical provider call 數：

```bash
python scripts/context_cache_benchmark.py --reanalyze --task small --provider codex --resume
```

## 判讀規則

只有兩個 arm 都通過 acceptance，而且兩邊都是完整的 provider-measured token usage，才允許輸出 `YES` 或 `NO`。超時前收到的用量會以 `partial_measured` 保存，但只能診斷成本，不能證明節省。未知用量永遠不等於 0。

量測報告同時保存 provider/model/reasoning、commit、fixture hash、context chars、relevant paths、wall time、token source、tool/message counts、acceptance 與修改後 source hash。每完成一個 arm 就原子寫入 checkpoint，每完成一組 pair 就更新結果 JSON，因此中斷不會讓已完成的昂貴呼叫消失。
