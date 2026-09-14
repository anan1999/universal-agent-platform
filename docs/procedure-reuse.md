# 跨 task 累積操作經驗

實測更新：首組真實對照沒有節省，記憶版總 tokens 多約 83.4%。
見[完整結果與限制](procedure-reuse-real-20260911.md)。以下機制的功能已測試，
但節省效果尚未成立。

目前已改為 opt-in：不帶 `--experience` 時，prepare/check 不讀寫操作記憶，
不做其環境指紋掃描，也不注入配方。已有資料保留，不刪除。這不影響原本的
專案索引與來源筆記。以下操作僅適用明確選用的實驗。

目標是降低同類工作重複摸索的成本，而非保證每個新任務都比前一個便宜。
此次實作把經驗接進既有指令，不新增 AI 規劃層或背景模型呼叫。

1. 專案先在 `.agent/commands.yaml` 設定正確且允許執行的 test/build 命令。
2. 當前 AI 使用 `agentctl check project_test --experience` 或
   `agentctl check project_build --experience`。
3. 只有實際 exit code 0 且執行前後設定指紋一致，才保存成功證據。
4. 新 task 執行 `agentctl prepare "<goal>" --read --json --experience`，取得
   `verified_procedures`；無需額外要求 AI 寫操作摘要。
5. 使用適合當前目標的既有檢查，再驗證本次變更。帶 --experience 的檢查
   失敗會撤銷該操作證據；未選用時不維護這份實驗記憶，可能保留舊證據。

這是「記住怎麼驗證」，不是「記住結果所以不再驗證」。操作仍經過原本的
ToolExecutor 與 allowlist。prepare 不會執行命令，記憶也不會賦予新權限。

`check project_test project_build` 分別回報每個操作的 exit_code，任一失敗
使整體非零退出。請把獨立檢查分開設定；若自行在 allowlist 命令內呼叫
shell 或腳本，該腳本仍需正確傳遞內部失敗。平台不能從外層零退出碼
推斷任意腳本內部是否真的全部通過。

## 一般性與界線

操作可以是程式測試、文件檢查、研究資料驗證、設計交付物檢查等；沒有
硬編碼語言、模型或 provider。此版只支援現有 project_test/project_build
入口；沒有命令可執行的純手工專案仍使用來源筆記，不假裝已驗證操作。
不會自動安裝依賴、猜出正確命令、跨不相干專案複製經驗。

每個專案最多兩筆 SQLite 記錄：`.agent/cache/operations.sqlite3`。
保存工具 ID、設定/環境雜湊、驗證時間與累積成功次數；不保存命令、環境
原文、輸出或秘密。不新增長篇歷史到 prompt；回傳最多兩個固定大小配方。
SQLite 交易處理並行寫入。快取損毀時忽略，不影響檢查結果。

指紋包括專案位置、Python/OS、PATH/虛擬環境/PYTHONPATH、commands.yaml，
以及根目錄 JSON/TOML/YAML/lock/INI/requirements 設定。掃描最多 256
根目錄項目，每個檔最多 1 MiB、總計最多 4 MiB；超限不提供記憶。
七天後過期。普通原始碼修改不使操作方式失效，但仍要重跑測試。

限制：這不是完整依賴快照；巢狀設定、同路徑執行檔更新或未列入的環境變數
可能不被偵測。過期前也不能當成執行保證。資料庫屬本地提示，不是防竄改
驗證憑證；成功次數不代表品質評分、節省額度或完整測試覆蓋率。

## 離線驗證與後續衡量

`tests/unit/test_operation_experience.py` 用六種不同交付物副檔名進行三輪
真實 allowlisted 子程序檢查；每輪用新物件讀取跨 task 經驗，回傳配方大小
保持小於 400 字元。檢查本身是固定斷言，驗證機制跨領域，不宣稱驗證了
六個領域的交付品質。另測失敗撤銷、設定/環境變更、執行中變更、過期、
損毀與不儲存原始日誌。

尚未測得此機制降低真實 AI tokens。下一次真實任務應比較冷啟動與已有
成功配方的相近工作，計入記憶讀寫成本，維持相同驗收，記錄命令探索、
失敗重試、輸入/快取/輸出 tokens。不要用累積成功次數冒充節省幅度。

2026-09-11 完整離線回歸：206 passed，1 項既有 Starlette/httpx 棄用警告。
本輪沒有額外付費模型 benchmark。完整測試期間僅調整提示為有經驗才附加，
其後再跑直接執行與操作經驗測試，以覆蓋最後文字邏輯。
