# 六輪確定性上下文選擇實測

原始結果：[context-selection-six-real-20260911.json](../benchmark-results/context-selection-six-real-20260911.json)。
Codex gpt-5.6-luna、low reasoning、12 個獨立 ephemeral session。六輪兩組
全部通過精確答案驗收，零工具呼叫；執行順序每輪交替。

| 累積至輪次 | Cold tokens | Selected tokens | 累積節省 |
|---:|---:|---:|---:|
| 1 | 16,713 | 16,710 | 3 |
| 2 | 33,428 | 30,151 | 3,277 |
| 3 | 50,120 | 43,590 | 6,530 |
| 4 | 66,812 | 57,029 | 9,783 |
| 5 | 83,504 | 70,468 | 13,036 |
| 6 | 100,214 | 83,909 | 16,305 |

六輪累積少 16,305 raw tokens（16.27%）。第一輪兩組都收到完整 10,002
字元 catalog；後五輪 cold 仍收到完整 catalog，selected 每輪收到 79–85
字元的精確規則。排除第一輪後，五個後續 task 共少 16,302 tokens，
相對 cold 的 83,501 tokens 少 19.52%。

Cold 六輪 packet 合計 62,634 字元，Selected 合計 13,035 字元。兩組各有
6 則 assistant message、零工具呼叫。Cold 累積 42.56 秒，Selected 38.38 秒；
單輪時間仍有波動，不用來宣稱穩定速度提升。本次總共測量 184,123 raw
tokens；cached input 在不同輪次为 0、9,984 或 12,032，已包含於 input，
沒有重複加總，也不能直接折算訂閱扣打。

## 結論

六輪結果重現並擴大了兩輪訊號：在品質與輸出固定、沒有工具變因時，模型前
的確定性 relevance selection 能降低後續 task 成本。節省是近似線性累積，
不是每次無限變便宜：第一輪約 16.7k，後續 Selected 穩定約 13.44k，接近
本測試的固定模型/結構化輸出下限。所謂「越用越少」應解讀為首次建立索引
後，每個相近 task 落到較低平台，累積平均成本逐步下降，而不是趨近零。

這仍是合成的精確 key lookup。Selector 直接知道 RULE key，沒有證明任意
自然語言、跨檔依賴、修改程式與驗證流程能達到相同數字。下一個產品步驟
應是受限、可回退的通用 lexical/identifier passage selector：只有高信心時
提供少量帶來源 hash 的片段；低信心時擴大範圍。不要把完整摘要與所有歷史
重新塞入 prompt，也不要把這組 16.27% 當成 UAP 全場景節省率。

## 可重現性

腳本記錄 SHA-256 `72fc09785bcc669534febe493bc26789d0e3667ebdc95ca1f2231a92008a527b`。
執行前，六輪預算、交替順序、第一輪等成本、後五輪選取、累積算法、未知
用量與覆寫保護的離線測試 5 項通過。此前 context-selection 與 amortized
相關測試 13 項通過。沒有因結果好壞重跑本次六輪。
