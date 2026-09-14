# 全新使用者跨領域工具預算驗證

日期：2026-09-14  
模型：`gpt-5.6-luna`，reasoning `low`  
對照：固定 8 次 provider tool call vs 候選 6 次  
有效樣本：6 個領域、12 個全新 Codex session

## 問題與產物

| 領域 | 問題 | 實際產物 | 外部驗收重點 |
|---|---|---|---|
| 產品策略 | 依訪談數、嚴重度、策略契合度選問題並排 roadmap | `deliverable.json` | 計分、排序、指標、風險 |
| 研究綜整 | 從四張來源卡選擇值得擴大試驗的介入 | `deliverable.json` | 建議、效益、風險、引用、樣本數 |
| UI/UX | 設計照護者用藥規劃介面 | `prototype.html` | 語意結構、ARIA、responsive、focus、design tokens |
| 3D 設計 | 製作資訊 kiosk | `kiosk.obj`、`kiosk.mtl` | 幾何邊界、頂點、面、群組、材質、索引 |
| 平面設計 | 製作 Night Harbor 活動海報 | `poster.svg` | SVG、文案、palette、圖層、資訊層級、無外部資源 |
| 室內照明 | 依空間、照度與燈具規格做配置 | `deliverable.json` | 燈數、瓦數、迴路、設計備註 |

## 全新使用者隔離條件

每一個 arm 都從新的 fixture 複製到新的 Git repository。執行前不存在 `.agent`、
project index、adaptive-budget SQLite 或任何 UAP 專案記憶；每個 arm 建立新的 provider
instance 與 Codex session。兩組唯一的實驗差異是 provider tool-call 上限 8 或 6。

這項實驗測的是「已在軟體任務觀察到的 6-tool envelope，能否安全轉移給未見過的使用者
與領域」，不是聲稱全新使用者已經擁有專案特定學習。

## 最終結果

平面設計採用固定 v3 驗收契約下的獨立重跑 pair；其餘五組來自原始 cross-domain run。
所有 12 份產物均以相同 v3 契約重新驗收通過。

| 領域 | 固定品質 | 候選品質 | 固定總 Token | 候選總 Token | 固定未快取 | 候選未快取 | 工具 8→6 | 秒 8→6 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 產品策略 | PASS | PASS | 82,388 | 80,836 | 6,868 | 19,396 | 5→3 | 56.853→42.586 |
| 研究綜整 | PASS | PASS | 80,224 | 80,801 | 19,808 | 19,361 | 3→3 | 40.089→40.926 |
| UI/UX | PASS | PASS | 92,056 | 89,723 | 26,520 | 41,339 | 5→3 | 109.387→92.994 |
| 3D 設計 | PASS | PASS | 163,129 | 105,573 | 45,113 | 23,909 | 5→4 | 118.520→78.497 |
| 平面設計 | PASS | PASS | 84,828 | 84,893 | 10,332 | 25,501 | 3→4 | 71.627→73.649 |
| 室內照明 | PASS | PASS | 83,830 | 81,567 | 10,358 | 20,127 | 3→3 | 51.610→52.053 |
| **合計** | **6/6** | **6/6** | **586,455** | **523,393** | **118,999** | **149,633** | **24→20** | **448.086→380.705** |

合計變化：

- 決定性品質：兩組皆 6/6，沒有觀察到品質退步。
- 總 Token：候選少 10.75%。
- 未快取 Token：候選多 25.74%。
- Provider tool calls：候選少 16.67%。
- Assistant messages：兩組皆 11，沒有下降。
- 執行時間：候選少 15.04%。
- 六個領域中，候選在四個領域使用較少總 Token。

## 三種設計工作

UI/UX、3D、平面設計合計：

- 品質：兩組皆 3/3。
- 總 Token：少 17.59%。
- 未快取 Token：多 10.72%。
- Provider tool calls：13→11，少 15.38%。
- Assistant messages：7→5，少 28.57%。
- 執行時間：少 18.16%。

3D 是最明顯正向樣本；平面設計重跑則沒有成本優勢，且候選多使用一次工具。固定上限
是 guardrail，不會強迫模型一定用滿，也不能保證每一個 task 都更省。

## 驗收器修正紀錄

首次平面設計 pair 的兩份 SVG 都被 v1 錯誤拒絕。只讀檢查顯示，模型把活動名稱分成
多個可見文字行並把地點轉為大寫；視覺內容正確，但 v1 要求單一連續 `<text>`。

v2 允許分行，重跑時又發現候選把標題放在 `information` group；題目只要求標題字級
大於日期與地點，並未要求標題必須位於 `hero` group。v3 因此直接依可見文字辨認標題、
日期與地點，再比較字級，不再猜測 layer 位置。v3 有回歸測試，且對兩次 pair 的四份
未修改 SVG 全部對稱判定通過。原始 v1 與 v2 報告保留，不覆寫。

## 結論

決策：**保持 opt-in，不升為全新使用者的通用預設。**

這輪支持兩個較窄的結論：6-tool envelope 在六個跨領域全新專案中維持了決定性品質，
並減少工具往返與執行時間；它也降低 provider 回報的總 Token。但較接近「新投入內容」
的未快取 Token 反而增加 25.74%，而且個別領域方向不一致，因此目前不能宣稱它會降低
Codex Pro 訂閱額度消耗。

下一步不應繼續盲目收緊成 4 或 3。應先讓 UAP 的自適應決策同時看 task complexity、
artifact type 與近期 cached/uncached 比率：3D 類可保留 6，平面設計與簡短分析則維持正常
上限；只有同一 task family 的外部驗收與未快取成本都連續改善時才收緊。

## 證據

- 原始六領域結果：`benchmark-results/cross-domain-fresh-real-20260914.json`
- 原始六領域報告：`docs/cross-domain-fresh-real-20260914.md`
- 平面設計 v2 重跑：`benchmark-results/cross-domain-graphic-v2-real-20260914.json`
- 平面設計 v2 報告：`docs/cross-domain-graphic-v2-real-20260914.md`
- Benchmark：`scripts/cross_domain_budget_benchmark.py`
- Acceptance：`benchmark-fixtures/cross-domain/acceptance.py`

限制：每個領域只有一個有效 pair，尚不足以估計統計穩定性；決定性規格驗收不能代替
人類對美感、舒適度或策略洞察的主觀評分；provider Token 也不能直接換算訂閱 quota。
