# dwg_batch_tool

## 用途
DWG 批次轉 DXF，再以 Python + ezdxf 解析圖層 / Block / Attribute / Text / MText / Dimension，輸出 CSV / JSON / log，並搜尋 SCADA 相關關鍵字。

```
DWG -> accoreconsole.exe -> DXF -> ezdxf -> CSV / JSON / log
```

## 需求
- Windows、Python 3.10+
- 本機 Autodesk `accoreconsole.exe`（本機實測：`C:\Program Files\Autodesk\AutoCAD 2027\`，該資料夾含 `acad.exe`，為完整版 AutoCAD 2027，**不是 LT**；未找到 LT 2027）
- Python 套件：`ezdxf`（使用者層級 venv，不需管理員權限）

## 安裝
```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```
`config.json` 的 `accoreconsole` 指向實際路徑（找不到時 `run.bat` 直接停止，不會猜路徑）。

## 目錄結構
```
input/        放 DWG（可含子目錄）
output/dxf    轉出的 DXF（保留子目錄結構）
output/csv    file_index / layers / texts / blocks / attribs / dimensions / scada_hits
output/json   每個 DXF 一份 JSON
output/logs   每次轉檔的 stdout/stderr、batch_results.csv/.jsonl、errors.log
scripts/      env_check, convert_single, batch_convert, analyze_dxf, find_scada, summary
tests/        pytest；tests/fixtures/sample.dwg 為本工具用 accoreconsole 產生的測試圖
```

## 環境檢查
```
.venv\Scripts\python scripts\env_check.py      # 寫入 environment_check.txt
```

## 桌面 UI
```
app.bat            （或 .venv\Scripts\python app.py）
```
tkinter 介面：選輸入/輸出資料夾、勾選處理選項、編輯關鍵字（「儲存設定」才寫入 config.json）、掃描、開始/停止、進度條、Log、結果摘要與開啟結果檔案按鈕。
處理在背景 thread 執行，UI 只透過 Queue 更新；「停止」只會終止本程式自己啟動的 accoreconsole。
GUI log 寫入 `output\logs\gui.log`。掃描不會執行 AutoCAD、不修改任何檔案。
「產生 CSV」控制 analyze 的 CSV；`scada_hits.csv` 只要勾選「SCADA 關鍵字搜尋」就會產生。

## SCADA 搜尋規則（單一實作：`scripts\scada_rules.py`）
- 英文關鍵字以「完整 token」比對、不分大小寫：`RACK` 命中 `RACK`、`rack`、`RACK-01`、`RACK_01`；不命中 `TRACK`、`BRACKET`、`RACK01`（字母/數字相連不算邊界）。`PANELBOARD` 不會命中 `PANEL`。
- `_`、`-`、空白、中文字元都視為邊界；含空白的片語（`SCADA PANEL`）中間可為空白、`_` 或 `-`。含中文的關鍵字用子字串比對。
- 信心等級：`high_confidence`（`high_confidence_phrases`：SCADA/CONTROL/PLC/RTU/UPS/DDC/MCC PANEL）、`normal`、`excluded_noise`（`generic_keywords` 中的 PANEL 若落在 `exclude_phrases`：System Panel、Curtain Wall Panel、Curtain Panel、Architectural Panel、Glazed Panel 內）。已被高信心片語涵蓋的單獨 PANEL 不重複列出。三個清單皆可在 `config.json` 調整。
- 同一文字內同一關鍵字重複出現只記一筆。

## 輸出檔（csv）
`file_index / layers / texts（新增 text_quality）/ blocks / block_summary / attribs / dimensions / scada_hits（新增 confidence）/ object_hits / scada_excluded`
- `object_hits.csv`：每個 entity 一列，`matched_keywords` 以 `|` 合併（如 `SCADA|TRAY`）；無 handle 時以「檔案+類型+圖層+座標+文字」為 key。
- `block_summary.csv`：依 file、count（大到小）、block_name 排序；`scada_related` 依 block 名稱或圖層名稱是否命中。`blocks.csv` 仍保留每個 instance。
- `scada_excluded.csv`：被判為雜訊而未列入 `scada_hits.csv` 的命中，供人工抽查。
- `text_quality`：`OK` / `EMPTY` / `SUSPECT_ENCODING`（純 `?`、含 U+FFFD、控制字元、或 `?` 緊鄰中日文字）。文字原樣保留，不影響檔案狀態。
- 統計文字：`Keyword Hits`（scada_hits 列數）與 `Unique Matched Objects`（object_hits 列數）為不同數字，均由實際資料計算。

## 批次轉檔機制（單一 accoreconsole 視窗）
整批 DWG 由**同一個** accoreconsole 程序處理（`scripts\convert_batch.py`）：產生一份 script，對每個 DWG 執行 `_OPEN` → `_SAVEAS DXF`，並用 stdout 標記回報每檔進度。
- 遇到損壞的 DWG，AutoCAD 會跳出訊息框並卡住；程式從 stdout 偵測到後，把該檔標為失敗、只終止自己啟動的那個 accoreconsole，再為剩餘檔案重開一個（此時才會多出一個視窗）。
- 每檔以 `DWGNAME` 標記確認實際開啟的是預期的圖，避免開檔失敗時把上一張圖存成這一檔。
- 路徑可直接以雙引號放進 script（含空白、中文皆已實測）；若檔名含 ANSI 碼頁（此機為 cp950）無法表示的字元（例如 emoji），會先複製唯讀副本到暫存資料夾再開啟（此情況下該圖的外部參考相對路徑可能失效）。
- 視窗因輸出被程式接走而只會顯示空白黑底，屬正常。
- `convert_single.py` 仍為每檔獨立一個程序。

## 單檔測試
```
.venv\Scripts\python scripts\convert_single.py input\a.dwg output\dxf\a.dxf
```
結果為 `DXF_VALID` / `DXF_INVALID`（以 ezdxf 實際讀取判定，不只看 return code）。

## 批次執行
```
run.bat
```
流程：env_check -> batch_convert -> analyze_dxf -> find_scada -> summary。
`config.json`：`overwrite`（預設 false，已存在的 DXF 不覆寫）、`recursive`、`keywords`、`timeout_seconds`。

## 輸出說明
- `file_index.csv`、`layers.csv`、`texts.csv`（含 TEXT/MTEXT/ATTRIB）、`blocks.csv`、`attribs.csv`、`dimensions.csv`、`scada_hits.csv`
- `logs/batch_results.csv`：source / output / status / return_code / file_size / elapsed_seconds / error（每檔轉完即寫入）
- `logs/errors.log`：所有失敗紀錄

## 錯誤排除
- `DXF not produced`：看 `output/logs/<name>_<id>.stdout.log`（accoreconsole 輸出為 UTF-16，已解碼）。
- 測試：`.venv\Scripts\python -m pytest tests -v`

## 限制（皆已實測）
- accoreconsole 讀 script 使用系統 ANSI 碼頁；script 內的非 ASCII 字元（例如中文）會亂碼。因此 SAVEAS 目標使用 ASCII 暫存檔名，轉完再由 Python 改名到含中文/空白的最終路徑。
- SAVEAS DXF 的版本沿用「目前檔案格式」（本機為 2018，`AC1032`）；`config.json` 的 `dxf_version` 目前僅為紀錄，未用來切換版本。
- SAVEAS 檔名提示以空白分隔，故暫存 DXF 放在「純 ASCII、無空白」的資料夾（優先 `output\logs\tmp`，否則 8.3 短路徑、`%TEMP%\dwg_batch_tool`、`C:\Users\Public\dwg_batch_tool`），最終路徑由 Python 移動。輸出資料夾含空白時這點才會出現（GUI 測試中發現並修正）。
- DIMENSION 的 `dimtype` 輸出為 DXF 原始整數碼。
- 尚未測試：路徑超長、檔案被其他程式鎖定、無寫入權限（程式有處理與記錄，但未實測）。
- 測試 DWG 為 AutoCAD 2027 自產，尚未用公司實際專案圖驗證。

## 安全規則
此工具不修改原始 DWG。

所有 DWG 使用唯讀方式處理（`/readonly`，並在轉檔前後比對 SHA-256）。

所有衍生檔案輸出至 output 目錄。

不使用 ODA。

不使用 COM / ActiveX。

不使用外部 API。

DWG -> DXF 由本機 Autodesk accoreconsole.exe 執行（實測為 AutoCAD 2027，非 LT）。
