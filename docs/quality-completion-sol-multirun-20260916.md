# SOL 多 Run 品質收斂報告（2026-09-16）

## 結論

增加獨立 run 與程式設計 benchmark 後，目前證據**不支持 UAP 已能普遍做到越用越省**。

- 設計 R2 的公平有效部分（UI/UX + 3D）：Baseline 707,890、UAP 708,273；UAP 多 383（+0.05%），實質打平。
- 程式設計 R6（五個累積需求）：Baseline 716,373、UAP 758,761；UAP 多 42,388（+5.92%）。
- 兩組新有效樣本合併：Baseline 1,424,263、UAP 1,467,034；UAP 多 42,771（+3.00%）。

先前設計 R1 的 UAP -18.15% 不能當穩定效果。R1 的總差距主要由 UI/UX Baseline 一次返工造成；
R2 同一 UI/UX 序列反而是 UAP 返工，結果 UAP +3.91%。

## 有效結果

| Run／領域 | Baseline | UAP | UAP 差異 | 品質狀態 |
| --- | ---: | ---: | ---: | --- |
| 設計 R2 — UI/UX | 436,222 | 453,266 | +3.91% | 兩邊最終通過；UAP 2 attempts 完成第三題 |
| 設計 R2 — 3D | 271,668 | 255,007 | -6.13% | 全部一次通過 |
| 設計 R2 — 有效合計 | 707,890 | 708,273 | +0.05% | 打平 |
| 程式 R6 — 五題 | 716,373 | 758,761 | +5.92% | 10 個 arm-task 全部一次通過 |
| **新有效證據合計** | **1,424,263** | **1,467,034** | **+3.00%** | UAP 較高 |

3D 是目前唯一重複兩次仍為相同方向的領域：R1 UAP -5.53%，R2 UAP -6.13%。
UI/UX 不穩定：R1 -39.29%，R2 +3.91%。平面 R1 是 +12.44%；R2 因驗收器隱藏 ID
假設而無效，不能用來支持任何一邊。

## 程式設計 R6

題目是一個獨立的 Personal Expense App，兩臂各自延續自己的程式碼：

1. FastAPI、SQLite、Expense CRUD 與 pytest。
2. React dashboard、loading 與 error state。
3. CSV export API、前端下載連結與 deterministic tests。
4. Monthly report API、金額格式與跨月邊界測試。
5. Dashboard 月份輸入、月報請求、總額與分類 breakdown。

| Task | Baseline | UAP | UAP 差異 | 累積觀察 |
| --- | ---: | ---: | ---: | --- |
| 1 | 108,799 | 103,993 | -4.42% | 冷啟動接近打平 |
| 2 | 109,902 | 115,141 | +4.77% | 累計幾乎打平 |
| 3 | 176,286 | 156,671 | -11.13% | UAP 首次 break-even |
| 4 | 148,406 | 151,310 | +1.96% | UAP 累計仍少 2.99% |
| 5 | 172,980 | 231,646 | +33.91% | UAP 失去 break-even |

Task 5 顯示目前核心問題不是輸出文字太長，而是 UAP 在較大的既有程式碼上重新讀取、探索與操作的
輸入成本仍可能放大。單靠持久 Project Intelligence 沒有保證模型會少探索。

## 為什麼中途重跑很多次

程式 R1–R5 沒有被拿來比較產品效果。它們揭露並修正量測器問題：

- 修復 prompt 曾只讀 `errors`，沒有把 failed named checks 傳給模型。
- React dashboard 曾只接受 `frontend/src`，錯誤拒絕 server-served React。
- API probe 曾固定假設 `app.main`、`date` 欄位與 `create_app(path)`。
- Windows SQLite 檔案鎖曾讓已通過的 probe 在 temporary-directory cleanup 時回傳失敗。
- 平面設計曾硬編碼 `sponsor-strip`，錯誤拒絕合法的 `sponsor_layer`。

所有問題都加入回歸測試並逐次 commit。中止呼叫因沒有完整 receipt，不得視為零成本，也沒有混入
正式 UAP／Baseline 數字。這些浪費屬於 benchmark 開發成本，不是產品效能證據。

## 可支持與不可支持的說法

目前可支持：

- 3D 累積修改連續兩次約省 5–6%，值得擴大樣本。
- UAP 有時能在第三個需求附近達到 break-even。
- UAP 能在相同 deterministic contract 下完成程式工作，不需要降低合約品質換取 Token。

目前不可支持：

- UAP 適用大部分專案且會隨使用次數單調下降。
- 記憶越多就一定越省；程式 Task 5 正好反證。
- 設計 R1 的 18.15% 是穩定效果。
- 機器合約通過等同主觀視覺品質或 UX 等價。

## 下一步

下一個核心開發不應只是再加更多記憶，而是加入 **marginal context gate**：在每次任務前估算每個
reuse item 是否能避免一次具體搜尋、測試或錯誤；不能說明用途的 context 不注入。接著把程式 Task 5
設為主要回歸案例，測量注入項目、讀檔數、provider tool calls 與 exact tokens，目標是在品質不變下
消除該題 33.91% 的負擔。

機器摘要：`benchmark-results/quality-completion-sol-20260916-multirun.json`。
