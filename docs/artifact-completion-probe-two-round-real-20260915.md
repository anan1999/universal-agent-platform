# Artifact completion probe：兩輪交替順序實測

本次使用固定 `small` acceptance、Codex `gpt-6-astra`、low reasoning、180 秒單次上限。兩輪從同一 fixture hash 開始，第一輪依序執行 baseline→UAP，第二輪反轉為 UAP→baseline。

| Round | Order | Baseline | UAP | 較快者 | Tool calls | Acceptance |
|---:|---|---:|---:|---|---|---|
| 1 | baseline→UAP | 62.265s | 55.125s | UAP 11.5% | 3 / 3 | PASS / PASS |
| 2 | UAP→baseline | 63.468s | 59.407s | UAP 6.4% | 3 / 3 | PASS / PASS |
| Pooled | alternating | 125.733s | 114.532s | UAP 8.91% | 6 / 6 | 2 accepted pairs |

四次 provider 執行都在 artifact acceptance 連續通過兩次後停止，沒有任何 timeout。每次都是 2 個 provider messages；completion receipt 均記錄 `artifact=completed`、`provider=stopped`。

這支持兩個不同的觀察：

1. Artifact completion probe 在本次四次執行中穩定避免了 provider timeout。
2. Reusable context arm 在兩種執行順序都比較快，但沒有減少 tool/message 次數。

第二點目前只是小任務上的時間觀察，不是 token 節省證明。提早停止發生在 `turn.completed` 之前，因此四次的精確 token usage 都不可得；runner 正確維持 `INCONCLUSIVE`，沒有把 unavailable 當作零。

與先前沒有 early completion 的單輪相比，最明顯的改進是 UAP arm 從 300.093 秒 timeout 變成兩次分別 55.125 與 59.407 秒完成。但這些是不同的隨機模型執行，不能把差值全部歸因於單一機制。

原始證據：

- `benchmark-results/measurement-early-small-2r-20260915.json`
- `docs/measurement-early-small-2r-20260915.md`

下一步應測試 medium 任務一輪，確認 acceptance probe 在較多實作步驟下不會過早停止。若 medium 也穩定，再增加重複輪數；large 應最後執行。
