# 累積跨 task 驗證框架

修正後真實執行更新：第一輪 cold 回報 blocked、reuse 通過，但兩組都尚未
重用記憶，依規則停止，沒有有效攤提比較。
見[本次結果](amortized-document-fixed-real-20260911.md)。

後續將工具與寫檔變因移除，完成一組確定性 context selection 微型實測：
四次皆通過，第二輪 tokens 少 19.48%，兩輪累積少 9.74%。這只證明精確
選擇相關上下文的價值，不證明完整開發任務或通用 retrieval。
見[上下文選擇結果](context-selection-real-20260911.md)。

同一微型測試擴充至六輪後，12 次皆通過；六輪累積少 16.27%，後五個
Selected task 合計少 19.52%。見[六輪結果](context-selection-six-real-20260911.md)。

本框架測試「第一個 task 到第 N 個 task 的累積成本」，不是只挑一次較便宜
的執行。入口是 `scripts/amortized_benchmark.py`，預設只跑離線驗收自測。

## 三種不同工作

- 程式：逐次實作 subtotal、count、mean；以隔離 Python 子程序檢查實際函式
  的數值與邊界條件，每輪也重測先前功能。
- 文件：逐次增加決策摘要，檢查段落、來源 ID、數字與明示的因果限制；保留
  舊摘要。只驗證格式與事實出現，不等同完整語意或編輯品質審查。
- 資料：從包含 approved/pending 與零值的 CSV，逐次產出 revenue/count/mean；
  依固定數值驗收 JSON，並確認來源未改動、先前欄位仍正確。

每種專案兩組、三個 task，共 18 次離線執行。real 模式每個 task 都新建
provider instance 並使用 ephemeral session；交替先執行 cold/reuse，降低
固定順序偏差，但不消除隨機性或模型 cache 影響。

## 此次測的記憶是什麼

使用既有 FileSummaryCache 儲存並以來源 hash 驗證一份短 policy 原文；只有
前一個 task 驗收成功才由 controller 保存，下一個 task 加入仍有效的摘錄。
冷組仍可讀同一 policy 檔。這是控制條件下的來源重用，不是一般化 AI 自動
學習、不是操作記憶，也不是完整 UAP 規劃流程。不可把結果擴大解讀。

第一輪讀取與執行成本計入第一輪；來源記憶保存、讀取、验收時間計入各 task。
fixture 建立/Git 初始化按組另列，也加入累積含 setup 秒數。報表寫檔本身
屬測量工具開銷，不算產品執行成本。若未來增加 AI 記憶生成，必須把其模型
用量列入後才可比較；此版本沒有額外 AI 記憶生成。

Input/output/cached 各自累加，cached 已包含在 input，不重複加總。
任一輪用量 unavailable 時，累積 tokens 是 null，不當成零。
只有所有已完成任務通過相同驗收且用量可用，才比較累積總 tokens；這仍
不是訂閱扣打折算。初次優勢可能反轉，不能只報最後一個 task。

## 執行方式與預算

```text
python scripts/amortized_benchmark.py --workspace build/new-smoke --output benchmark-results/new-smoke.json
```

離線由明確標記的 reference oracle 產出文件、程式與資料，再跑實際驗收；
provider 不會被呼叫，tokens 不可用，不會產生省額度結論。

真實執行需 `--execute --domain <code|document|data>`，最多三輪、六次
provider 嘗試；`--max-calls` 可再縮小，每次逾時最多 300 秒。每輪兩組完成
後若有失敗就停止，不重試。現有工作目錄和報表拒絕覆寫。

## 2026-09-11 證據

離線三領域三輪兩組通過；另有回歸測試確保過去成果破壞時不會通過、
未知用量不算零、超額 real 設定在建立 workspace 前就被拒絕。

曾嘗試文件領域兩輪四次上限的真實執行，但第一輪兩組均提前失敗，沒有
模型完成回合或可用用量。報表保留為
[amortized-document-real-20260911.json](../benchmark-results/amortized-document-real-20260911.json)。
其中舊欄位 actual_ai_calls=2 實際是 provider **嘗試數**，不能解讀為兩次
已確認模型計費請求或零額度消耗；後續改為 provider_attempts 並另記完成回合。

程式檢查發現 Packet 使用相對工作目錄，同時作為 subprocess cwd 和 CLI -C，
會使目錄重複解析。已改為絕對路徑並加入回歸測試。舊框架未保存錯誤碼，
因此不能完整還原原始失敗；新框架已保存 provider status/error_code。
此輪遵守不重試規則，修正後只重跑離線測試。**目前還沒有有效的真實跨 task
累積節省結果**，不得將這次提前失敗計為節省或記憶效果。
