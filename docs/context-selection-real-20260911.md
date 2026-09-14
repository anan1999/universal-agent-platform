# 確定性上下文選擇：首個有效真實訊號

後續六輪結果也全部通過，累積少 16.27%；見
[六輪實測](context-selection-six-real-20260911.md)。本文件保留原始兩輪結果。

原始結果：[context-selection-real-20260911.json](../benchmark-results/context-selection-real-20260911.json)。
Codex gpt-5.6-luna、low reasoning、四個獨立 ephemeral session。四次皆通過
完全相同的精確答案驗收，沒有工具呼叫，輸出 tokens 均為 62。

| 指標 | Cold | Selected |
|---|---:|---:|
| 第一輪 context 字元 | 10,002 | 10,002 |
| 第一輪總 tokens | 16,690 | 16,690 |
| 第二輪 context 字元 | 10,002 | 83 |
| 第二輪總 tokens | 16,690 | 13,438 |
| 兩輪累積 tokens | 33,380 | 30,128 |
| 兩輪累積秒數 | 15.240 | 12.516 |

第二輪 Selected 少 3,252 tokens（19.48%）；計入兩組相同的第一輪成本後，
兩輪累積少 3,252 tokens（9.74%）。所有 cached input 都是 0，因此這組差異
沒有混入 provider 回報的 cached tokens。確定性選擇耗時 0.0125 ms，已包含
在該 task wall time；沒有額外 AI 記憶生成呼叫。

## 第一性原理解讀

有效的不是「告訴 AI 以前做過什麼」，而是在模型啟動前就移除與本 task
無關的內容。第一輪支付完整 120 條規則；第二輪依明確 key 選出單條規則。
模型不必決定要不要相信記憶，也沒有操作環境或失敗重試的變因。

這支持以下產品方向：建立可驗證索引、用 task 需求做確定性 retrieval、只傳
最小充分證據，並保留來源 hash；不要把整份專案摘要或不相關歷史固定注入。
若選擇錯誤或證據不足，才回退到針對性讀取，而非預載整個 repository。

## 嚴格界線

這是合成的精確規則查找，不是 repository 修改、工具使用、多領域語意品質，
也不是 AI 自動學會通用 Skill。規則 selector 由 benchmark 直接知道 task key，
尚未證明 UAP 能從任意自然語言正確找出同樣的 83 字元。

只有兩輪、單一交替順序，仍受模型和服務變異影響；不能建立統計結論，也
不能把 raw token 差異直接換算為訂閱扣打。系統固定開銷仍約 13k input tokens，
所以相關上下文再縮小也會遇到下限。此次沒有重跑挑數字。

## 與寫檔 benchmark 的關係

此前 nested Codex 寫檔實驗在明確 workspace-write 模式下，兩組仍自述工作區
唯讀且零工具呼叫。這確認該執行邊界不適合拿來判斷記憶效果；本測試改成
完全內聯、唯讀、無工具，隔離出 context selection 本身。它不能取代未來在
可靠執行邊界上的開發任務驗證。

## 驗證

新增測試驗證固定 catalog/答案、四次硬預算、拒絕覆寫、兩輪累積計算、
未知用量不算零，以及 stub provider 下第一輪同成本、第二輪才縮減。
context-selection 與 amortized benchmark 相關測試 13 項通過；腳本 compileall
與 git diff check 通過。未重跑完整套件。
