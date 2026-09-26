# 工程語意修正與 acceptance gate

目前版本定位為 **SCADA Engineering Data Analyzer — Semantic Validation Candidate**。以下為已完成的測試／合成資料驗證紀錄；最新版本狀態與開發暫停條件以 [VERSION_STATUS.md](VERSION_STATUS.md) 為準，真實專案驗收仍為 NOT TESTED。

## 執行範圍

依最新指示，暫停 Retrieval 後續整合及 Ollama/Dify。只完成工程語意修正、反例測試與新輸出驗收。保留 CAD Analyzer、scada_rules.py、run.bat、app.bat、GUI、原始來源及前次輸出。

最新輸出：`regression_semantics/index.html`、`regression_semantics/evidence.json`、`regression_semantics/existing_output/`、`regression_semantics/acceptance_output/`。

## Baseline 與測試契約

- 本次附件開始前原有 127 項：127 passed、0 failed、0 skipped，見 `evidence_baseline_results.txt`。
- 收到「優先修正語意、停止 Retrieval/LLM」指示時，已加入 Evidence schema/builder/SQL/FTS 的 7 項未整合測試；語意修正前 baseline：134 passed、0 failed、0 skipped，見 `semantics_baseline_results.txt`。
- 本次新增工程語意測試 17 項，總數 151。
- 原有 CAD 100 項測試未修改。
- 因使用者明確變更結果分類與缺值契約，更新了 `test_cross_reference.py`、`test_ifc_analyzer.py`、`test_multiformat_pipeline.py` 的相關預期：MATCH 改為 NORMALIZED_MATCH／RELATED；無來源 handle 改 UNCERTAIN；IFC 缺值改 None 並驗證 SQL IS NULL。新增 compliance assertions，沒有刪除案例或放寬為任意結果均可通過。
- 完整結果見 `semantics_regression_results.txt`。

## 已修正

1. **GUID**：獨立索引，保留字元大小寫與所有分隔符。Navisworks XML 保留 GUID/HANDLE/NAME/ELEMENT_ID 類型。GUID 不轉名稱、不做 fuzzy fallback；相同 GUID 才 EXACT_MATCH，多個來源相同 GUID 為 UNCERTAIN。CAD handle 綁定明確 source_file，未指定來源不宣告確定匹配。
2. **DOCX 表格**：以 row 建立 requirement candidate，保留 table index、row、column headers、subject、所有 cell 原文、requirement fragments、水平及垂直 merged-cell origins。不把新組合的句子寫進 original_text；keyword 從完整 row context 抽取，UPS 不再因隔壁 cell 而漏失。
3. **IFC eligibility**：IfcSpace、IfcSystem、IfcDistributionSystem、IfcBuildingStorey 等為 REFERENCE_ONLY，輸出 NOT_APPLICABLE；其餘以實際 IFC inheritance／明確設備類別判斷。未分類 IFC 不自動認定是設備。
4. **結果分類**：EXACT_MATCH／NORMALIZED_MATCH／RELATED／MISMATCH／MISSING_A／MISSING_B／UNCERTAIN／NOT_APPLICABLE，新增 match_basis 及獨立 compliance_status。Keyword 只代表 RELATED，compliance=INSUFFICIENT_EVIDENCE。名稱及 GUID 匹配為 NOT_EVALUATED，不宣告需求已滿足。
5. **NULL**：新解析的 IFC 缺值使用 None → SQL NULL／JSON null；來源明確給空字串仍保留。新欄位以 additive migration 加入，INSERT 指定欄名，不因舊 DB 的欄位順序而寫錯值。舊空字串資料不盲目回填，需重解析確認。
6. **規格衝突**：明確同屬性、同單位、數值不同才 MISMATCH；原始 attribute／BOQ Specification 與衝突欄位保留於 evidence。未做不具證據的單位換算、設計核准或供應完成判斷。

## 九個 acceptance gate

| Case | 實際結果 | Gate |
| --- | --- | --- |
| 不同 IFC GUID、只差大小寫 | MISSING_B，不進入名稱索引 | PASS |
| 完全相同 GUID | EXACT_MATCH；GUID_EXACT | PASS |
| UPS / must be supplied | 一筆 row requirement，subject=UPS，原句及兩格 context 保留 | PASS |
| IfcSpace vs BOQ | NOT_APPLICABLE；REFERENCE_ONLY | PASS |
| IfcDistributionSystem vs BOQ | NOT_APPLICABLE；REFERENCE_ONLY | PASS |
| UPS keyword 對到 UPS-01 | RELATED；INSUFFICIENT_EVIDENCE | PASS |
| 缺 IFC property | SQL IS NULL；不補猜 | PASS |
| 明確 Voltage 220 V vs 110 V | MISMATCH；SPECIFICATION_CONFLICT，原始數值留存 | PASS |
| RACK02 vs RACK01 | UNCERTAIN；不再同時宣稱同一候選 MISSING_A | PASS |

單元測試另涵蓋 IfcSystem、IfcBuildingStorey、exact GUID 不 fallback 名稱、handle 來源範圍、spec 單位不一致、DOCX 水平／垂直合併格、IFC inheritance、來源明確空字串、舊 schema migration。

## 真實 parser 路徑回歸

執行：

```powershell
.venv\Scripts\python reports\semantics_gate\run_acceptance.py --output regression_semantics
```

- 既有八個來源：DWG、DXF、IFC、XLSX、PDF、DOCX、Clash XML、舊版 BOQ；8 success、0 failed。這些是既有測試/合成文件，不冒稱公司正式工程文件。
- 新增五份明確合成的 acceptance source：DXF、CSV、IFC、DOCX、Clash XML；5 success、0 failed。
- CAD 規格衝突確實經 DXF attribute → analyzer → normalized object → BOQ comparison，而非只手工向 DB 塞入結論。
- 原始檔：files checked=13，hashes changed=0。
- 舊 `demo_multiformat/output` 全部檔案雜湊未變。
- 兩批新輸出的 cross_reference CSV 與 SQLite 對應紀錄逐欄逐列一致。
- 新 HTML 只展示已記錄結果與兩側 evidence，無 JavaScript、LLM 或另一套 matching rules。

## 版本狀態

| 項目 | 狀態與範圍 |
| --- | --- |
| Functional Regression | PASS：完整測試與兩批解析流程 |
| Data Integrity | PASS：本次來源／CSV／SQLite 核對範圍 |
| Source Preservation | PASS：13 檔，hash changes=0 |
| Engineering Semantics | PASS：本次九個 acceptance gate，並非所有工程語意均已驗證 |
| Cross Reference Reliability | PASS：已列反例與支援規則範圍，並非全面可靠性認證 |
| Production Approval | NOT APPROVED：沒有真實公司專案資料驗收或人工核准 |

## 尚存限制與暫停項目

- 本次只有測試/合成資料，尚無真實公司工程資料及人工 spot-check 簽核。
- 名稱、識別碼、明確規格衝突均不能直接證明施工、供應或 requirement compliance。SUPPORTED／NOT_SUPPORTED 保留為狀態值，目前不自動產生。
- MISMATCH 目前只支援 README 列出的明確量值語法與同單位比較；自由規格文字、單位換算、數量／位置／容量與完整條文驗證仍未實作。
- DOCX subject 無法從明確欄名或唯一非 requirement context 確認時留空；未處理頁首頁尾、批註與巢狀表格。
- 舊資料與報告保留旧 taxonomy／空字串，未對歷史資料作不具來源依據的回填；新結果在獨立 output。
- Retrieval 僅 Phase 1–4 開發模組及測試已存在，尚未接入 pipeline／GUI。未完成 router/resolver、跨 pipeline 歷史保存；未接 Ollama、embedding、Dify/API。工程語意工作完成不等於原附件全部 v2–v4 功能完成。
