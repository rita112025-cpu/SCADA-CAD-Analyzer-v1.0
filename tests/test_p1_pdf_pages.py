"""P1-2: physical page + printed page label read from the page, never derived arithmetically."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from analyze_pdf import citation, parse as pdf_parse, printed_page_label  # noqa: E402

H = 800.0


def blk(y0, text):
    return (50, y0, 200, y0 + 12, text, 0, 0)


@pytest.mark.parametrize("blocks,expected", [
    ([blk(760, "附錄C-8")], "附錄C-8"),
    ([blk(760, "C-8")], "C-8"),
    ([blk(760, "- 3 -")], "- 3 -"),
    ([blk(760, "第 12 頁")], "第 12 頁"),
    ([blk(760, "Page 3")], "Page 3"),
    ([blk(760, "12")], "12"),
    ([blk(400, "附錄C-8")], None),                          # mid-page text is not a page label
    ([blk(760, "Section summary of the appendix")], None),   # not a label shape
    ([blk(760, "C-8"), blk(775, "C-9")], None),             # ambiguous footer
    ([blk(20, "Rev 2")], "Rev 2"),                           # header band used only when no footer candidate
    ([blk(20, "H-1"), blk(760, "F-2")], "F-2"),             # footer wins
    ([], None),
])
def test_printed_page_label(blocks, expected):
    assert printed_page_label(blocks, H) == expected


def test_citation_format():
    assert citation(9, "附錄C-8", "四(十五)") == "PDF p.9 / Printed 附錄C-8 / § 四(十五)"
    assert citation(1, None, "") == "PDF p.1"
    assert citation(3, None, "二(三)3") == "PDF p.3 / § 二(三)3"


def _pdf(path, pages):
    """pages: list of (footer_label or None, body_lines)."""
    import fitz
    doc = fitz.open()
    for label, body in pages:
        page = doc.new_page()
        y = 60
        for line in body:
            page.insert_text((40, y), line, fontname="china-t")
            y += 20
        if label:
            page.insert_text((250, page.rect.height - 40), label, fontname="china-t")
    doc.save(path)
    doc.close()


def test_pages_store_both_numbers_and_null_when_absent(tmp_path, data_store, engineering_cfg):
    p = tmp_path / "s.pdf"
    # printed labels are deliberately NOT physical-1: cover has none, then C-7, C-3 (annex-like), none
    _pdf(p, [(None, ["Cover RTU"]), ("C-7", ["一、 甲章", "RTU here"]), ("C-3", ["(二) 甲章第二款", "RACK here"]),
             (None, ["TRAY without footer"])])
    assert pdf_parse(p, data_store, engineering_cfg) == "OK"
    pages = {r["pdf_page"]: r for r in data_store.rows("documents") if r.get("status")}
    assert [pages[i]["printed_page"] for i in (1, 2, 3, 4)] == [None, "C-7", "C-3", None]
    assert all(pages[i]["page"] == i == pages[i]["pdf_page"] for i in pages)
    hits = {(r["pdf_page"], r["keyword"]): r for r in data_store.rows("documents") if r.get("keyword")}
    assert hits[(2, "RTU")]["printed_page"] == "C-7" and hits[(2, "RTU")]["citation"] == "PDF p.2 / Printed C-7 / § 一"
    assert hits[(3, "RACK")]["citation"] == "PDF p.3 / Printed C-3 / § 一(二)"
    assert hits[(4, "TRAY")]["printed_page"] is None and hits[(4, "TRAY")]["citation"].startswith("PDF p.4 / § 一(二)")
    clauses = {r["section"]: r for r in data_store.rows("document_sections") if r.get("kind") == "clause"}
    assert clauses["一(二)"]["printed_page"] == "C-3" and clauses["一(二)"]["pdf_page"] == 3
    # never derived: physical 3 - 1 would have been 2
    assert clauses["一(二)"]["printed_page"] != "C-2"


def test_constant_footer_is_not_a_page_label(tmp_path, data_store, engineering_cfg):
    p = tmp_path / "c.pdf"
    _pdf(p, [("2025", ["RTU a"]), ("2025", ["RTU b"]), ("2025", ["RTU c"])])
    pdf_parse(p, data_store, engineering_cfg)
    pages = [r for r in data_store.rows("documents") if r.get("status")]
    assert [r["printed_page"] for r in pages] == [None, None, None]


def test_sqlite_columns_exist_and_persist(tmp_path, engineering_cfg):
    import sqlite3
    from pipeline import run_multiformat
    p = tmp_path / "in" / "s.pdf"
    p.parent.mkdir()
    _pdf(p, [("C-7", ["一、 甲章", "RTU here"])])
    out = tmp_path / "out"
    assert run_multiformat(dict(engineering_cfg, output_dir=str(out)), [str(p.parent)])["failed"] == 0
    with sqlite3.connect(out / "database" / "project.db") as db:
        row = db.execute("SELECT pdf_page, printed_page, citation FROM documents WHERE keyword='RTU'").fetchone()
        cols = {r[1] for r in db.execute("PRAGMA table_info(document_sections)")}
    assert row == ("1", "C-7", "PDF p.1 / Printed C-7 / § 一")
    assert {"pdf_page", "printed_page", "citation"} <= cols
