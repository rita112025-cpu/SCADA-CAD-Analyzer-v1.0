# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

(Actually a Windows desktop app built with Python Tkinter/ttk, launched via `app.bat`; `web` is recorded only because it is the closest allowed value. Do not assume a browser, CSS or a dev server.)

## Users
The author and colleagues working on SCADA / metro engineering drawings. They use two workflows about equally often:
- A: batch convert DWG to DXF with AutoCAD's accoreconsole, then parse and search for SCADA keywords.
- B: analyze engineering data directly (DXF, IFC, Excel/CSV, PDF, DOCX, Navisworks), with no AutoCAD needed except for stray .dwg files.

## Product Purpose
Turn a folder of engineering files into CSV/JSON reports and keyword hits, so SCADA-related items can be found and counted without opening each file.

## Capabilities and Constraints
- Inputs: an input folder (recursive option) or a multi-file selection. Output: an output folder with CSV/JSON.
- Needs Python 3.12 and ezdxf; AutoCAD / accoreconsole only for DWG conversion.
- Shared SCADA keyword list, one per line, saved to config.
- Stop button, progress bar, log, result buttons.
- UI text is bilingual (Traditional Chinese with English labels); keep that terminology.
- Launch: `app.bat` keeps a black console window open (close it to quit), like the author's Qingxiu tool.

## Product Principles
- The two workflows must be equally easy to find and start.
- Environment status is background information, not the first thing read.
- Everything reachable without hidden dialogs; no feature removal.

## Open Decisions
- UI simplification level chosen: medium. Keep both workflow sections, collapse environment info to one status line, remove explanatory paragraphs.
