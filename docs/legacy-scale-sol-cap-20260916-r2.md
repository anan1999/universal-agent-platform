# 舊 Benchmark Fixture 重跑：SOL cap8/plain vs cap6/plain

日期：2026-09-16。固定 `gpt-5.6-sol`、low reasoning，重用既有 `context-cache` small／medium／large fixture 與外部驗收。每個規模兩組配對，順序交錯；共 12 次真實執行。全部一次通過，精確 usage 12/12 完整。

| 規模 | cap8 Token | cap6 Token | cap6 差值 | cap6 勝負 | 工具 8→6 |
|---|---:|---:|---:|---:|---:|
| Small：summary API | 172,561 | 218,718 | +46,157（+26.75%） | 1:1 | 5→7 |
| Medium：monthly API | 313,445 | 279,706 | −33,739（−10.76%） | 2:0 | 9→9 |
| Large：monthly API + React | 217,026 | 177,458 | −39,568（−18.23%） | 1:1 | 3→3 |
| 合計 | 703,032 | 675,882 | −27,150（−3.86%） | 4:2 | 17→19 |

逐組 Token（cap8→cap6）：

- Small 1：96,366→77,185；Small 2：76,195→141,533。
- Medium 1：145,535→138,702；Medium 2：167,910→141,004。
- Large 1：137,468→79,921；Large 2：79,558→97,537。

## 解讀

不能把 cap6/plain 設成所有專案的預設。Small 合計反而增加 26.75%；medium 兩組同方向但樣本僅兩組；large 勝負各一。整體只省 3.86%，且 cap6 工具呼叫總數比 cap8 更多。所有單次執行的工具數都沒有超過各自 cap，因此沒有證據指出硬性中斷節省 Token；更可能是提示錨定與模型路徑變異。

前一次同 fixture 的 cap6 + batching 六組測到 −13.58%，但它是不同 prompt treatment，不能與這次的 plain 數據直接合併成「cap6 的效果」。上一個從零建立完整 PocketFlow 的 factorial 實驗也與這次增量修改 fixture 不同。

## 無效 R1 與量測防線

首次跨規模 R1 發現舊 `Packet` 硬編碼 large monthly 回應格式，把錯誤合約塞進 small summary 題。已立即中止並保留原 workspace，不納入任何政策結論。R2 改用 task-neutral packet，新增單元測試防止 monthly 合約再洩漏到 small 題。

## 下一步

先保持現有 normal 預算預設，不因總量 −3.86% 就全域改 cap6。跨 UI/UX、平面、3D 與非軟體任務時，重用舊 fixture 但固定 SOL，並要求外部品質等價與完整成本。政策只應在同一任務族群累積足夠配對證據後啟用。
