# 操作診斷 benchmark — 2026-09-11

## 結果

這是一組診斷，不是新的最佳化方案驗證。執行提示沿用上一版，只增加
不傳回模型的操作事件統計。模型為 Codex `gpt-5.6-luna`、low reasoning。

| 指標 | Baseline | UAP |
|---|---:|---:|
| 固定外部驗收 | PASS | PASS |
| Input tokens | 161,071 | 158,641 |
| Output tokens | 3,083 | 3,471 |
| Cached input（已含在 input） | 136,192 | 145,408 |
| Non-cached input | 24,879 | 13,233 |
| Total tokens | 164,154 | 162,112 |
| Provider 秒數 | 124.803 | 142.951 |
| 工具呼叫 | 7 | 6 |
| Assistant 訊息數 | 4 | 4 |
| Assistant 字元數 | 1,876 | 1,807 |
| 帶 validation 標籤且非零退出的呼叫 | 1 | 3 |

本組總 tokens 少 1.24%，但執行較慢、訊息數不變。與上一組工具呼叫
5 對 9 的方向不同，不能推論穩定改善或訂閱扣打節省。

## 可觀察的問題

- Baseline：兩次 inspection 呼叫，修改後一次帶 missing_dependency 線索的
  驗證失敗，下一次驗證成功，其後有 repository_status 類呼叫。
- UAP：一次未分類呼叫、一次 inspection、修改；接著兩次帶
  missing_dependency 線索的驗證失敗，以及一次帶 permission/test_failure
  線索的失敗；再次修改後，validation/repository_status 呼叫成功。
- 兩組都沒有完全相同命令的重複。這不代表没有語意重複讀檔。
- 標籤可重疊，且來自字詞匹配；不能把每次呼叫直接判為必要或浪費。
  原始命令與輸出沒有保存，因此不能追溯每一個錯誤的精確原因。

## 額外的離線重現

在這次 Baseline 工作目錄中，benchmark 完成後執行：

```text
pytest --collect-only -q
  ERROR: ModuleNotFoundError: No module named 'app'

python -m pytest --collect-only -q
  1 test collected
```

這證明此環境存在一個可避免的 Python import-path 問題；並不證明歷史
trace 的每個 missing_dependency 都是同一原因。收集測試也不等同測試通過。

可重用的精簡配方：在此 fixture 的專案根目錄，用同一個已安裝依賴的
Python 執行 `python -m pytest`。不要把這個 fixture 專用結論升格成所有
語言與專案的全域規則。先以收集測試確認環境，再執行相關測試；來源、
依賴或環境改變後重新確認。此次沒有修改 fixture、驗收器或正式路由。

## 下一步

優先讓跨 task 記憶保存「工作目錄、已驗證命令、適用環境、失效條件」，
而不是擴充架構摘要。下一次有實際任務時驗證這份配方是否消除排錯；
本次不追加付費對照試驗，也不宣稱已證明配方的節省幅度。

## 證據與限制

原始結構化結果：[direct-diagnostic-20260911.json](../benchmark-results/direct-diagnostic-20260911.json)。
基底 commit 為 `639d0f5`，當時有未提交的診斷補丁；精確腳本 SHA-256
記錄在結果內。两側初始 source hash 相同，驗收檔 hash 執行前後不變。
共兩次真實 provider 呼叫，沒有自動重試。新增診斷與直接執行相關測試
9 項通過，腳本 compileall 與 git diff --check 通過；未重跑完整套件。

單一順序配對無統計效力，不能觀察內部推理輪數或訂閱折算。前端驗收
只檢查整合原始碼，非瀏覽器渲染；本次不測量跨 task 的 AI 知識攤提。
