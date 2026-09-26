# Real Project Validation Status

Detailed evidence (source copies, analyzer output, review worksheets) is retained locally and is **not committed**. This file is a summary only.

| Round | Analyzer | Scope | Result |
| --- | --- | --- | --- |
| SB12 Round 1 | `v1.5-semantic-validation-candidate` | 2 DWG, 2 DOCX point-record revisions, 1 requirement PDF | **FAIL** |
| SB12 Round 2 | `v1.5.1` | Same sources; P0 defect regression only | **PASS** |

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

## Open (P1, planned for v1.5.2)

- F2 keyword-hit origin (TEXT / MTEXT / ATTRIB / BLOCK_NAME / LAYER_NAME) overwritten by `source_type = CAD` in multi-format output
- F5 PDF physical page vs printed page label
- F6 DOCX revision metadata (revision fields empty; revisions not distinguished)
