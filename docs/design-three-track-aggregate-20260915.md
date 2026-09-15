# 三軌連續設計 Benchmark 彙整

本報告固定選用 r3 的 UI/UX 軌，以及修正跨 profile 路由後 r4 的平面與 3D 軌。每輪 Baseline/UAP 從相同通過 checkpoint 開始；只有雙方品質、source hash 與精確 Token 通知都通過的配對，才列入 Token 合計。

| 領域 | 輪次 | 任務 | Baseline | UAP | 節省率 | B 品質 | UAP 品質 | 可比較 |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| ui-ux | 1 | Create the responsive and accessible medication-planner prototype described by the local brief and requirements. | 93434 | 90771 | 2.85% | PASS | PASS | True |
| ui-ux | 2 | Extend the existing prototype with a medication status filter, a visible conflict alert, and an aria-live status region. Preserve the established design tokens and responsive layout. | 96968 | 115387 | -18.99% | PASS | PASS | True |
| ui-ux | 3 | Add an accessible Add medication dialog to the existing prototype, including labelled fields, Escape-key close behavior, focus return, and reduced-motion support. Preserve prior behavior. | 102071 | 119813 | -17.38% | PASS | PASS | True |
| graphic-design | 1 | Create the standalone vector event poster described by the local assignment and poster brief. | 123522 | 89488 | 27.55% | FAIL | PASS | False |
| graphic-design | 2 | Extend the existing poster with a sponsor strip labelled exactly SUPPORTED BY HARBOR LAB. Keep the approved palette, hierarchy, and original layers intact. | 88824 | 100137 | -12.74% | PASS | PASS | True |
| graphic-design | 3 | Create a companion square social.svg adaptation with viewBox 0 0 1080 1080. Reuse the poster palette and include the exact event, date, and venue copy with accessible title and description. | 91926 | 90947 | 1.06% | PASS | PASS | True |
| three-d-design | 1 | Create the valid Wavefront information kiosk described by the local assignment and model brief. | 87399 | 88497 | -1.26% | PASS | PASS | True |
| three-d-design | 2 | Extend the kiosk with a distinct keypad group using a new AccentMetal material. Preserve the existing model bounds, groups, and material assignments. | 70278 | 235705 | -235.39% | PASS | PASS | True |
| three-d-design | 3 | Extend the kiosk with a canopy group using a new Canopy material while preserving all earlier geometry and the exact model bounds. Keep every face index valid. | 70067 | 53454 | 23.71% | PASS | PASS | True |

## 分領域結果

- **ui-ux**：有效 3/3；Baseline 292473，UAP 325971；節省率 -11.45%。
- **graphic-design**：有效 2/3；Baseline 180750，UAP 191084；節省率 -5.72%。
- **three-d-design**：有效 3/3；Baseline 227744，UAP 377656；節省率 -65.82%。

## 有效配對總計

- 有效輪：8/9
- Baseline：700967 Token
- UAP：894711 Token
- 差額：UAP 多 193744 Token
- 節省率：-27.64%（負值代表 UAP 較貴）
- 全部輪次品質等價：False
- 可宣稱節省：False

## Token 結構（僅有效配對）

- Baseline：cached input 473856；uncached input 207422；output 19689；tool calls 24；messages 22。
- UAP：cached input 631552；uncached input 240943；output 22216；tool calls 29；messages 23。

## 主要問題

1. UI/UX 三輪皆正確，但 UAP 累計較貴，表示小型單檔案任務的固定封包成本尚未攤平。
2. 平面第 1 輪 Baseline 兩次獨立執行都違反標題層級；這是模型品質變異，該輪未列入 Token 比較。
3. 修正前 follow-up 會漂移到 Documentation Planner；修正後平面與 3D follow-up 已回到 Visual Designer。
4. 3D 第 2 輪雖品質通過，UAP 出現 235705 Token 尖峰；這是總體成本惡化的主因。
5. UAP 第 3 輪在平面與 3D 都低於 Baseline，表示重用可能在後段生效，但目前不穩定且不足以抵銷尖峰。

## 3D 第 2 輪尖峰歸因

- Baseline：4 個 windows、3 tool calls；command 51567 Token，file change 18711 Token。
- UAP：11 個 windows、7 tool calls；command 191570 Token，file change 44135 Token。
- UAP reuse hits：0；rediscovery：0。尖峰主要來自額外命令/驗證往返，並非已驗證知識重用。

## 結論

目前不能宣稱 UAP 在設計任務上『越用越少』。較精確的結論是：路由正確性已改善，後段輪次偶爾省 Token，但固定成本與 3D 工具往返尖峰仍使有效配對總成本高於 Baseline。下一步應針對 3D 第 2 輪的 attribution window 做尖峰消除，再用同一套三軌合約重跑。

品質驗收涵蓋結構、規格與累積功能，不等同於盲測的人類美感評分；Provider Token 也不等同訂閱制 quota 單位。
