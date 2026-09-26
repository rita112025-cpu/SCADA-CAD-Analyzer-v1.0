# 輸出品質抽查：暫不通過工程資料驗收

本輪凍結 parser、pipeline、GUI 與既有輸出，僅新增本資料夾內的驗收文件及唯讀抽查工具。這是對現有**合成範例**的逐筆證據審查，不是公司真實專案驗收，也不是使用者人工簽核。

先前 127/127 是程式測試結果，不能替代本次輸出品質判斷。原先提到的 HTML 支援是 Navisworks HTML **輸入**，不是已存在的 HTML 報表。本資料夾新增的 `index.html` 是一次性靜態檢視頁，只呈現已擷取的 SQLite/CSV 證據，不含業務計算或比對 JavaScript。

## 抽查範圍與可重現證據

- 來源：`demo_multiformat/input/` 七份來源與明確指定的 `old_boq.xlsx`；DWG 是既有測試 fixture，其餘是合成範例。
- SQLite 以 `mode=ro` 開啟；沒有重跑 parser 或更改既有 CSV/DB。
- 8/8 原始檔現有 SHA-256 與 project_files 記錄一致。
- 抽查前後，8 個來源及現有 output 全部檔案 SHA-256 不變。
- 8 張 normalized CSV 加 28 張有 exports 紀錄的 parser/比對 CSV，共 36 張逐欄、逐列與 DB 一致；輸出樹另有 1 張空報表，共 37 張 CSV。
- DB：project_files 8、engineering_objects 9、requirements 3、boq_items 4（含新舊版）、documents 5、document_sections 14、clashes 1、cross_reference_results 18。
- 18 筆實際比對只有 MATCH 7、MISSING_B 11。不可把沒有出現的 MISMATCH／MISSING_A／UNCERTAIN 當作已經由此範例驗證。
- 全部原文、DB payload、CSV 核對、GUID 反例及雜湊記錄見 `evidence.json`。可用 `.venv\Scripts\python reports\acceptance_review\audit_outputs.py` 重現唯讀抽查。

## 原始資料 → Parser → Normalized → Cross-reference

| 抽樣 | 原始證據 | 解析／正規化 | 現有比對與判讀 |
| --- | --- | --- | --- |
| CAD Block | drawing.dxf，handle 32，INSERT RTU-01，座標 (1,2,3) | blocks.csv 與 engineering_objects 保留名稱、handle、座標；normalized_name=RTU01 | 對新版 BOQ RTU01 為 MATCH，作為名稱等價證據合理；不證明數量符合 |
| BOQ | boq.xlsx，Equipment!row:3，001 / RTU01 / Remote Terminal Unit / 3 / ea | item_no 的前導零保留，quantity=3.0；SQLite TEXT 欄位儲存文字 3.0，payload_json 保留數字 | 對舊版 quantity=2.0 為 QUANTITY_CHANGED；原文與 sheet/row 可回溯 |
| IFC | model.ifc，#1，IfcCableCarrierSegment，TRAY_X600；沒有系統指派或空間容器 | GlobalId 原樣保留；system、space、level、座標均空白，未從同檔 SCADA system 物件補猜 | 對 BOQ TRAY-X600 為 MATCH，只證明名稱等價 |
| PDF | appendix.pdf 第 1 頁，RTU shall connect to the UPS panel. | pdf_hits 保留頁碼及原句；4 筆 keyword hits | 現有跨來源引擎沒有把此 PDF 的句子作為 requirement 輸入；不能把輸出宣稱為完整 PDF requirement coverage |
| DOCX 段落 | sow.docx，body:3，RTU shall retain source evidence. | requirement_text/original_text 完全相同，status=CANDIDATE | CAD 對此 requirement 為 MATCH，僅代表共用 RTU keyword，不代表需求已滿足 |
| DOCX 表格 | sow.docx，body:5/row:1，兩格為 UPS 與 must be supplied | 表格全列原文有保存；requirement 只有第二格，keyword 空白 | CAD 的 UPS 被列 MISSING_B；原始表格其實提供 UPS 需求關係，屬已確認的漏關聯 |
| Clash | clashes.xml，object_a GUID 與 IFC #1 相同，object_b=RTU-01 | navis_clashes 與 normalized clashes 保留原字串 | 此範例兩側 MATCH 有來源支持；但 GUID 比對實作存在下述反例，不能據此通過一般化驗收 |

## 需要處理的問題

### A1／高：不同 IFC GUID 被判為確定 MATCH

位置：`scripts/cross_reference.py` 的 identifiers 建索引及 clash lookup 共用 `norm()`。

獨立記憶體反例（沒有寫入既有 project.db）：

```text
IFC GUID:   0AbCdEfGhIjKlMnOpQrStU
Clash GUID: 0aBcDeFgHiJkLmNoPqRsTu

IfcOpenShell expand 結果：
0a94c9cea50ad2b54bd6c58cdad5cdde
242e63683ea46c4ee5705f26746f6778

現有結果：MATCH / confidence=1
```

已由同一套 IfcOpenShell 解碼確認兩者是不同識別碼。名稱用的大小寫／分隔符正規化不可套用到 IFC GUID。修正方向應為：依 identifier 類型分開索引，GUID 保留精確值；handle 綁定來源文件；名稱只作名稱候選。此輪僅記錄，未改程式。

### A2／高：DOCX 表格列的主體與要求失去關聯

原文 `UPS | must be supplied` 被拆成單格需求 `must be supplied`，keyword 為空。DB 仍保有完整 table row，因此 evidence 沒有消失，但跨來源比對沒有使用該關係，造成 UPS 的 MISSING_B。

修正時應保留 row/cell 關係及兩格原文，不能把拼接後的新句子冒充原始 requirement_text。

### A3／中：IFC 缺值沒有猜測，但不是 SQL NULL

三筆 IFC 物件的 system、space、level 均為空字串：`typeof(system)='text'`、`system IS NULL=0`、`quote(system)="''"`。

其中 IfcDistributionSystem 名称 SCADA 是來源既有名稱，沒有被指派到其他物件。這符合不補猜原則，但資料庫缺值語意必須明確：目前查缺值需使用 `NULLIF(system, '') IS NULL`，不能只用 `IS NULL`。數值欄位亦為 TEXT，未建立 SQL 型別及 nullability 約束；不要直接以字串排序解讀數量大小。

### A4／中：非設備 IFC 物件進入 BOQ 缺項判斷

IfcDistributionSystem SCADA 與 IfcSpace Equipment Room 均被列為 IFC_OBJECT_VS_BOQ / MISSING_B。原文只證明「所提供 BOQ 沒有同名文字」，不證明有 BOQ 漏項。應先定義可比的物件類別及 BOQ 範圍。

此範例沒有 IFC_SYSTEM_VS_REQUIREMENT 列；不能把這一類比對視為已由 end-to-end 驗證。

### A5／中：狀態與 confidence 的語意仍不夠嚴謹

- 7 筆 MATCH 中 3 筆是 CAD_KEYWORD_VS_REQUIREMENT，共用 RTU keyword，confidence=1。其 note 有註明共用 keyword，仍不能在報告標示「需求滿足」或「工程確認」。
- `UPS-01` 對 `UPS PANEL` 的反例沒有被誤判 MATCH，這點通過。
- `RACK02` 對 `RACK01` 回傳 UNCERTAIN / 0.3，但同一個 BOQ 同時又有 MISSING_A。應區別「沒有已確認對應」與「確定來源缺項」。
- 目前 cross_reference.py 沒有產生 MISMATCH 的分支；狀態名稱列在需求中不等於已有判定規則。工程矛盾仍需可比較的屬性、單位及範圍證據，不能臆造 MISMATCH。
- 同一缺項表內混合「沒有相同 keyword」與「没有同名設備」，只看 result 欄會造成誤讀；應連同 check_type、note 與兩側 evidence 審查。

### A6／低：示範 summary.json 與目前快照不是同一次發布

`demo_multiformat/summary.json` 的 keyword_hits/unique_objects 是早期示範執行留下的 0；後來 CLI 重跑更新 DB/CSV，未同步此示範 summary 檔。目前 CSV 實際有 CAD hits 12、PDF hits 4。這不是原文解析丟失，而是摘要快照與資料快照無版本綁定；檢視頁以本次唯讀 DB/CSV 擷取證據為準。

## 目前驗收結論

**HOLD／暫不通過真實工程資料驗收。**

來源不變、CSV↔SQLite 一致、抽樣原文保留與基本名稱比對可確認；GUID 確定誤判、表格需求漏關聯及狀態語意仍需處理。不得以 127/127 或 8 檔解析成功代替工程輸出品質核准。

這輪未更名產品、未新增 parser、未修改核心行為、未重寫原有輸出。下一批真實資料需由使用者指定同一專案的完整路徑；本機本次 `Test-Path D:\SCADA` 為 False，因此沒有把該路徑當作已驗收資料。人工簽核仍待使用者進行。
