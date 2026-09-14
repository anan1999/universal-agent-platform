# 自然語言、多證據 benchmark：格式驗收失敗

原始結果：[semantic-retrieval-real-20260911.json](../benchmark-results/semantic-retrieval-real-20260911.json)。
Codex gpt-5.6-luna、low reasoning、唯讀、零工具呼叫。計畫三題兩組共六次；
第二題兩組驗收失敗後依規則停止，實際四次，沒有重試。共測量 67,190 raw
tokens；品質不一致／不通過時不計算節省結論。

## 題目內容

### 1. Android production release

問題：`For an Android production release, report the required approver, target API,
crash-log retention days, and storage region.`

需要合併兩段證據：production Android artifact 的 approver/target API，以及
production crash log 的保存天數/region。標準答案：
`security|35|21|eu-west-1`。第一輪兩組均讀完整 13,542 字元 corpus，均通過。

### 2. Customer onboarding survey

問題：`For the customer onboarding survey, report sample size, response percentage,
stable source ID, and whether it establishes causation.`

需要合併 survey sample/response/source 與 observational/causation 限制。
標準答案：`240|62|SURV-24|no`。Lexical selector 從 96 段中選出兩段，
322 字元，且包含全部必要證據；完整 corpus 組與 retrieval 組都完成模型回合，
但都未符合完全相同字串驗收，因此兩組都判定失敗。

### 3. Revenue aggregation

問題：`For revenue aggregation, report included invoice status, whether approved
zero values count, excluded statuses, FX timing, and rounding stage.`

需要合併 invoice filter 與 FX/rounding 兩段；標準答案：
`approved|yes|pending+refunded|transaction-date-close|after-category-aggregation`。
因第二題停止規則，本題沒有呼叫模型、沒有消耗。

## 可觀察結果

| 輪次／組別 | Context 字元 | Total tokens | 驗收 |
|---|---:|---:|---|
| Android full | 13,542 | 16,894 | PASS |
| Android retrieval arm（首輪仍 full） | 13,542 | 16,890 | PASS |
| Survey retrieved | 322 | 13,517 | FAIL |
| Survey full | 13,542 | 16,889 | FAIL |

Survey retrieval 呼叫比 full 少 3,372 raw tokens，但兩組都未通過，不能宣稱
品質相同下的節省。Selector 的 evidence index 為 2、3，SHA-256 與 matched
terms 已保存在 JSON；選取層找到正確資料，但端到端答案契約未通過。

## 問題與修正

舊 prompt 只要求 pipe-delimited answer，沒有定義 percentage 是否帶 `%`、
布林值允許哪些字串等。舊報表為避免保留內容只存答案 hash，現在無法知道
模型實際使用 `62%`、`cannot-establish` 或其他格式；不能事後修改 evaluator
把結果變成通過，也不能聲稱確切失敗原因。

後續腳本已為每題新增明確 `format`，例如 survey 是
`integer sample|integer percentage without percent sign|source ID|yes-or-no`；
也會在這些 bundled synthetic fixtures 中保存最多 300 字元的 observed answer。
這個修改只改善下一次診斷，沒有回頭改動本次 JSON、驗收或結論。

## 第一性原理結論

這次把問題再拆成兩層：retrieval 層成功找齊證據；generation/contract 層
失敗。上下文縮小可能降低 input，但只有輸出契約也穩定通過時才有產品價值。
下一個 benchmark 必須先凍結無歧義的輸出 schema，再執行一次全新樣本；
本次不重跑挑結果。

新增 benchmark 自測七項通過，涵蓋 answer-blind selection、必要證據、問題不含
內部 ID、預算上限、三輪累積與 unavailable usage。修改格式/診斷後再跑同一
七項離線測試；不額外呼叫模型。
