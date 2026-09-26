# 多格式工程資料分析驗證紀錄

## Baseline

- 原有測試：100；初次可完整執行的 baseline 為 96 passed、4 failed。
- 使用原有 `.venv`；系統 Python 沒有 pytest。sandbox 首次執行受到暫存目錄權限限制，因此完整 CAD/GUI 測試在允許本機 AutoCAD 子程序及測試暫存資料的環境執行。
- 四項失敗：`test_full_pipeline_chinese_paths_and_error_isolation`、`test_option_toggles`、`test_stop_during_accoreconsole`、`test_gui_smoke`。
- 根因：中文/空白輸出路徑導致使用 C 槽暫存 DXF，`os.replace` 搬至 D 槽發生 WinError 17，並殘留共用暫存檔。新增跨磁碟安全發布及依輸出路徑隔離的暫存目錄後，原有 100 項全部通過。沒有修改原有測試或 SCADA matcher。
- 原始結果：`baseline_results.txt`。

## 實作

新增程式：

- `scripts/engineering_data.py`：normalized schema、來源證據、SQLite、CSV、parser CLI。
- `scripts/name_normalizer.py`。
- `scripts/analyze_excel.py`、`analyze_pdf.py`、`analyze_docx.py`、`analyze_ifc.py`、`analyze_navisworks.py`。
- `scripts/cross_reference.py`、`scripts/demo_multiformat.py`。
- `requirements-ifc.txt`、本驗證紀錄。
- 八個要求的新測試模組，以及共用 `tests/conftest.py`。

修改程式：

- `scripts/pipeline.py`：獨立 mixed-format routing、逐檔交易及錯誤隔離、明確 BOQ 版本比對。
- `app.py`：資料分析區、檔案選取、背景 pipeline 呼叫、進度/摘要、六個輸出按鈕、表單捲動。
- `config.json`：Excel 標頭別名、文件工程關鍵字、Navisworks HTML 欄位別名。
- `requirements.txt`、`README.md`。
- `scripts/convert_single.py`、`convert_batch.py`：修正已由 baseline 證實的跨磁碟發布問題。

Dependencies：已安裝 openpyxl 3.1.5、pandas 3.0.6、PyMuPDF 1.28.2、python-docx 1.2.0、ifcopenshell 0.8.5，保留既有 ezdxf。IFC 仍為 optional dependency；缺少套件的隔離行為另有測試。未引入大型 framework，也未加入不需要的 pdfplumber。

## Parser 狀態

| Parser | 狀態 | 實際驗證 |
| --- | --- | --- |
| CAD | PASS | 真實 AutoCAD DWG→DXF、DXF entities、舊有 100 項回歸、跨磁碟輸出 |
| IFC | PASS | 實際 IFC4、GlobalId、缺失 property、system/space 報表 |
| Excel | PASS | XLSX merged cell、CSV、中文 alias、Qty、原始列、general table、明確 revision comparison |
| PDF | PASS | 文字層、頁碼、keyword excerpt、掃描影像頁 OCR_REQUIRED |
| DOCX | PASS | Heading hierarchy、paragraph/table 順序、verbatim requirement candidates |
| Navisworks | PASS | Clash XML、canonical Clash CSV、明確欄位 HTML、不支援格式拒絕、DTD 拒絕 |

PASS 指上述已測範圍，不代表所有廠商匯出變體都可解析。

## 新增輸出

實際輸出位於 `demo_multiformat/output/`：

- `cad/`：attribs.csv、blocks.csv、block_summary.csv、dimensions.csv、file_index.csv、layers.csv、object_hits.csv、scada_excluded.csv、scada_hits.csv、texts.csv；另有 JSON 及 DWG 衍生 DXF。
- `ifc/`：ifc_objects.csv、ifc_systems.csv、ifc_spaces.csv、ifc_summary.csv。
- `excel/`：excel_sheets.csv、excel_tables.csv、boq_items.csv、boq_summary.csv、boq_compare.csv。
- `pdf/`：pdf_pages.csv、pdf_sections.csv、pdf_hits.csv、pdf_summary.csv。
- `docx/`：docx_sections.csv、docx_tables.csv、requirements.csv。
- `navisworks/`：navis_clashes.csv、navis_summary.csv。
- `cross_reference/`：cross_reference.csv。
- `database/`：project.db，以及 project_files.csv、engineering_objects.csv、requirements.csv、boq_items.csv、documents.csv、document_sections.csv、clashes.csv、cross_reference_results.csv。

共 37 份 CSV 與 1 份 SQLite DB；無資料的標準報表保留表頭。所有解析報表帶來源證據欄位，跨來源/版本比對為 DERIVED。

## Tests

- 原有：100。
- 新增：27。
- 總數：127。
- Passed：127。
- Failed：0。
- 完整回歸紀錄：`regression_results.txt`。

涵蓋來源不變、缺依賴、混合格式、失敗 CSV、失敗 XML transaction rollback、重跑清空舊資料、revision 排除舊版、名稱正規化、缺失/不確定比對、GUI 無 AutoCAD 執行非 CAD 分析等。

## End-to-End

已執行：

```powershell
.venv\Scripts\python scripts\demo_multiformat.py --output demo_multiformat --with-dwg
.venv\Scripts\python scripts\pipeline.py demo_multiformat\input --compare demo_multiformat\old_boq.xlsx --output demo_multiformat\output
```

八個來源：DWG、DXF、IFC、XLSX、PDF、DOCX、Clash XML 與舊版 XLSX，8 success、0 failed。示範為明確合成資料，DWG 使用原專案測試 fixture。SHA-256 驗證所有示範 input 原檔未變。

BOQ 實際產生 `QUANTITY_CHANGED`（RTU 數量 2→3）與 `UNCHANGED`。CAD/IFC 名稱對應、requirement keyword 與 clash identifier 證據已進入 SQLite 及 cross_reference.csv。舊版 BOQ 保留在 DB，但不影響目前名稱對照。

另由自動測試實跑混合資料夾中 5 個成功檔加 1 個損壞 PDF，確認其餘完成、CLI summary exit_code=1、errors.log 保留失敗來源。

## GUI

- Automated：既有 GUI smoke + 新增 tkinter smoke；背景分析、非 CAD 不需 AutoCAD、檔案不存在時輸出按鈕 disabled、完成後啟用、760×620 表單可捲動。原有 CAD GUI 工作流程亦實跑通過。
- Manual：未做使用者人工點選驗收。自動化建立及操作真實 tkinter 控制項，不把它宣稱為人工測試。

## 尚存限制

- 尚未用公司實際文件及大型專案做容量驗證；cross-reference 仍需要物件/BOQ 索引記憶體。重複 keyword 對超過 20 份 requirement 時輸出 UNCERTAIN 與候選數，避免無界的全配對輸出。
- 名稱相符只代表文字證據，未驗證工程數量、設計合規、施工正確性或跨格式單位換算。
- IFC 未進行 geometry tessellation；尺寸僅取現有 property，座標保留專案單位。
- PDF 不執行 OCR；表格是候選，未重建複雜表格。DOCX 目前處理本文，未處理頁首頁尾/批註，也不推測頁碼。
- Excel merged cell 保留來源錨點與空白，不補值；公式使用已儲存快取，未重算；未另造含 VBA 巨集的 XLSM fixture 驗證巨集檔，但讀取路徑不執行任何巨集。
- Navisworks 只接受 README 列出的 XML/CSV/HTML 結構；不支援 NWD binary。
- 每次 DB/CSV 代表本次輸入快照；歷次 CAD 衍生 DXF/JSON 檔保留，以 project_files 辨識本次来源。
