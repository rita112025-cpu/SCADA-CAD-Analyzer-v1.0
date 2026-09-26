# Real Project Validation Status

Detailed evidence (source copies, analyzer output, review worksheets) is retained locally and is **not committed**. This file is a summary only.

| Round | Analyzer | Scope | Result |
| --- | --- | --- | --- |
| SB12 Round 1 | `v1.5-semantic-validation-candidate` | 2 DWG, 2 DOCX point-record revisions, 1 requirement PDF | **FAIL** |
| SB12 Round 2 | `v1.5.1` | Same sources; P0 defect regression only | **PASS** |
| SB12 Round 3 | `v1.5.2` (`v1.5.1` + P1 changes) | Same sources; P1 evidence-metadata regression; Round 2 fixes re-checked | **PASS** (17/17 checks) |

Review: Technical SELF-REVIEWED · Engineering semantic SELF-REVIEWED · Independent engineering approval NOT PERFORMED · Production Approval NOT APPROVED.

Not tested (source unavailable): IFC, BOQ, Clash.

## Round 1 gate

| Gate | Result |
| --- | --- |
| A1 Source hashes unchanged | PASS |
| A2 CAD entity/location traceable | PASS |
| A3 DOCX context preserved | PASS WITH LIMITATION (embedded images not extracted) |
| A4 PDF page/section citation traceable | FAIL |
| A5 Missing values not guessed | PASS |
| A5b Missing source semantics | FAIL |
| A6 Revision sources not mixed | PASS |
| A7 RELATED not promoted to COMPLIANT | PASS — NOT TRIGGERED |
| A8 False MATCH = 0 | PASS — NOT TRIGGERED |
| A9 Reviewed results return to evidence | PASS |
| A10 No real source committed/pushed | PASS |
| F1 MTEXT Unicode decoding (HIGH) | FAIL |

## P0 defects fixed in v1.5.1

| ID | Defect | Round 2 evidence |
| --- | --- | --- |
| F1 | MTEXT `\U+XXXX` escapes kept literally (13% of CAD text records in the sampled drawings) | All previously escaped records decoded and equal to AutoCAD's own reading of the DWG; 0 escapes remain |
| F3 | Absent source category (no BOQ, no parsed requirements) reported as `MISSING_B` | 208 → 0 such rows; recorded as NOT_TESTED in `cross_reference/coverage.csv` |
| F4 | PDF `section` was the running page header | Clause-level ids (e.g. `二(三)3`, `四(十五)`) resolve to the correct page and text; annex tables cite the annex |

Round 2 also confirmed H0 = H1 = H2 for all sources and no other output change versus Round 1.

## P1 evidence-metadata changes (v1.5.2)

| ID | Change | Round 3 evidence |
| --- | --- | --- |
| F2 | `hit_source` (TEXT / MTEXT / ATTRIB / BLOCK_NAME / LAYER_NAME) added to `scada_hits` and `object_hits`; `source_type` stays `CAD`; all previous columns kept; also present in SQLite | Hit set identical to Round 2; hit_source agrees with the entity type of every hit handle |
| F5 | `pdf_page`, `printed_page` (read from the page footer/header band, NULL if absent, never computed) and `citation` (`PDF p.9 / Printed <label> / § <clause>`) on PDF pages, hits and clause rows | Printed label of all pages compared with the rendered footers |
| F6 | `revision_label` / `revision_status` / `revision_basis` on `project_files`; formal `revision` stays NULL; only an older/newer order is inferred from filename, mtime, document core modified time; conflicting bases give no label | The two point-record files distinguished as older / newer; other files unknown |

Compatibility note: the standalone `find_scada.py` CSV keeps its old `source_type` values (TEXT / MTEXT ...) and gains `hit_source`; only the multi-format output reports `source_type = CAD`.
