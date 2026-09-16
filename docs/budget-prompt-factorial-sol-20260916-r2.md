# SOL 工具額度 × Batching Prompt 2×2 Benchmark

日期：2026-09-16  
正式結果：R2  
模型：`gpt-5.6-sol`，reasoning `low`

## 結論

這次結果不支持「把多個省 Token 技巧疊加就會更省」。四個 cell 全部一次通過相同的大型 full-stack 功能合約，且精確 Token usage 完整；但 cap 與 batching prompt 有強烈交互作用：

- plain prompt 下，cap 8→6 減少 157,930 tokens（54.98%）。
- batching prompt 下，cap 8→6 反而增加 8,321 tokens（4.13%）。
- cap 8 下，batching 減少 85,975 tokens（29.93%）。
- cap 6 下，batching 反而增加 80,276 tokens（62.09%）。
- Difference-of-differences 為 +166,251 tokens。

合併主效應顯示 cap 6 減少 30.63%，batching 只減少 1.37%，但主效應會掩蓋上述方向相反的 interaction。現階段最合理的候選預設是「cap 6 + plain」，而不是「cap 6 + batching」。由於只有一個完整 block，還不能直接設為所有專案的全域預設。

## 任務與方法

從空白 fixture 一次完成完整 PocketFlow：

- FastAPI + SQLite expense CRUD
- React dashboard、loading 與 error states
- deterministic CSV export 與下載連結
- 跨月份邊界的 monthly report API
- month input、monthly total 與 category breakdown
- backend、API boundary 與 frontend deterministic tests

四組只改兩個因子：provider tool cap 為 8／6，以及 batching prompt 關閉／開啟。模型、reasoning、初始 fixture、驗收器、完成條件與安全上限相同。不限制固定對話輪數；若驗收失敗，必須在同一成品修正並累計所有成本。

## 正式 R2 結果

| Cell | Token | Cached input | Output | 工具 | 訊息 | 嘗試 | 品質 |
|---|---:|---:|---:|---:|---:|---:|---|
| cap8 / plain | 287,228 | 254,080 | 6,624 | 6 | 4 | 1 | PASS |
| cap6 / plain | 129,298 | 99,328 | 5,486 | 2 | 3 | 1 | PASS |
| cap8 / batch | 201,253 | 175,232 | 6,327 | 5 | 4 | 1 | PASS |
| cap6 / batch | 209,574 | 167,680 | 7,400 | 4 | 4 | 1 | PASS |

聚合後 cap8 為 488,481 tokens，cap6 為 338,872；plain 為 416,526，batch 為 410,827。四組皆為一次通過，因此結果沒有被返工成本或品質失敗扭曲。

沒有 cell 超過工具 cap。這代表目前量到的仍是「額度數字對執行策略的錨定效應」，不是 hard cap 強制中斷的效果。

## R1 量測事故

R1 不可用於政策結論。舊 API probe 只搜尋 `main.py`，因此把使用 `pocketflow/app.py` 且自身 5 個測試全通過的合法 FastAPI 實作錯判為失敗。模型只收到 `csv export` 與 `monthly boundary contract` 兩個模糊名稱，在第一次假陰性後又執行三次 repair，額外消耗 409,079 tokens，仍無法修正驗收器隱藏的檔名假設。

修正內容：

- API probe 支援 `main.py`、`app.py`、`api.py`、`server.py`、`application.py`。
- 失敗 check 會攜帶最後 1,200 字的有界 traceback／probe 診斷。
- budget stop 會正常中斷 app-server 並保存精確 usage，而非遺失成本。

修正後，R1 保留成品立即通過全部 9 項檢查。這證明「驗收器正確性」是 Token 效率的上游條件；錯誤的 quality gate 可以輕易吃掉任何 context 或 cap 節省。

## 第一性原理判斷

總消耗可拆成：

`首次完成成本 + 驗收成本 + 真實缺陷修正成本 + 假陰性造成的無效修正成本`

過去主要優化首次完成成本；R1 顯示假陰性修正成本可以更大。因此 UAP 下一階段應優先：

1. 讓驗收合約對合法專案架構保持中立。
2. 將具體失敗證據直接餵給 focused repair。
3. 禁止同一模糊失敗在沒有新證據時反覆呼叫模型。
4. 在有足夠 paired evidence 前，不疊加 cap 與 batching 政策。

## 限制與下一步

- 目前只有一個正式 block，無法估計各 cell 的變異或順序效應。
- 只涵蓋 SOL 與一個 full-stack 任務。
- 驗收涵蓋功能與 deterministic tests，不含瀏覽器實際視覺品質。
- hard cap 沒有真正中斷任何 R2 cell。

下一輪應補完 Latin-square 的另外三個 block，但先加入「相同失敗簽章沒有新診斷時停止重試」的 no-progress gate。這能避免再次用大量 Token 重複修一個沒有變化的錯誤。
