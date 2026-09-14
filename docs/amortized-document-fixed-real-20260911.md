# 修正路徑後的真實測試：第一輪阻擋，無法比較攤提

原始結果：[amortized-document-fixed-real-20260911.json](../benchmark-results/amortized-document-fixed-real-20260911.json)。
模型 Codex gpt-5.6-luna / low；計畫兩轮兩組、最多四次嘗試。
實際兩次嘗試、兩個觀察到的完成回合；第一輪有失敗，依規則停止，沒有重試。

| 第一輪指標 | cold | reuse |
|---|---:|---:|
| Provider status | blocked | completed |
| 外部驗收 | 未通過 | 通過 |
| 記憶命中 | 否 | 否 |
| Input tokens | 31,176 | 63,456 |
| Output tokens | 515 | 667 |
| Cached input（包含於 input） | 15,104 | 45,312 |
| Total tokens | 31,691 | 64,123 |
| 工具呼叫 | 1 | 2 |
| AI 訊息 | 3 | 2 |
| task wall seconds | 22.3515 | 36.9343 |

共記錄 95,814 tokens；不能換算訂閱扣打。兩邊品質不相同，不能比較哪邊
更省；且都在第一輪，尚未使用記憶，不能歸因於重用效果。

## 阻擋證據的界線

cold 錯誤碼為 CODEX_CAPABILITY_UNAVAILABLE。此碼在 Provider 中可能來自
模型回報 blocked 且 summary/findings 含 sandbox、filesystem access 等詞。
它不等同作業系統已證明拒絕寫入：cold trace 只看到一次成功的 inspection
命令，沒有可見的失敗寫檔事件；工作目錄也沒有 brief-1.md。reuse 則有
file_change 事件且通過相同驗收。

因此能確定的是：修正絕對路徑後模型可以執行，但這次兩個新 task 的產出
不一致。不能確定冷組的阻擋是工具可用性、實際沙箱限制、或模型誤判。
未保留的原始回覆不能靠猜測補回。

## 結論與下一步

沒有有效的跨 task 累積節省結果。本次不改驗收、不延續到第二輪、不追加
模型呼叫。先驗證執行環境的可重現性與阻擋診斷，才能進行記憶效果試驗。
應將「模型自述受阻」與「工具實際拒絕」分別記錄；不要為了通過測試放寬
沙箱或繞過批准。沒有改產品程式碼或重跑整套單元測試。
