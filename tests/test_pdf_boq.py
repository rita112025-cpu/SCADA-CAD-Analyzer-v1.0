"""BOQ row parsing from PDF tables. SYNTHETIC data only: Implementation / Synthetic regression only,
Real BOQ validation: NOT TESTED. Gates B1-B10."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pdf_boq  # noqa: E402
from analyze_pdf import parse as pdf_parse  # noqa: E402
from engineering_data import digest  # noqa: E402
from pipeline import run_multiformat  # noqa: E402

pytest.importorskip("pdfplumber")
HEAD = ["Item", "Description", "Spec", "Unit", "Qty", "Remarks"]


def draw_table(page, top, rows, col_w=85, row_h=22, x0=30):
    import fitz
    for i, r in enumerate(rows):
        for j, cell in enumerate(r):
            rect = fitz.Rect(x0 + j * col_w, top + i * row_h, x0 + (j + 1) * col_w, top + (i + 1) * row_h)
            page.draw_rect(rect, color=(0, 0, 0), width=0.8)
            page.insert_text((rect.x0 + 3, rect.y1 - 7), cell, fontsize=7, fontname="china-t")
    return top + len(rows) * row_h


def make_pdf(path, pages):
    """pages: list of pages; each page = list of tables; each table = list of rows."""
    import fitz
    doc = fitz.open()
    for tables in pages:
        page = doc.new_page()
        top = 60
        for t in tables:
            top = draw_table(page, top, t) + 40
    doc.save(path)
    doc.close()
    return path


def boq_rows(store):
    return [r for r in store.rows("boq_items") if r.get("source_type") == "PDF"]


# ---------------- pure logic (no PDF library) ----------------
def test_header_map_needs_description_and_qty():
    assert pdf_boq.map_header(HEAD) == dict(item_no=0, description=1, spec=2, unit=3, qty=4, remarks=5)
    assert pdf_boq.map_header(["Name", "Value"]) is None
    assert pdf_boq.map_header(["Description", "Unit"]) is None


def test_rows_from_tables_carry_over_rules():
    h = ["Item", "Description", "Qty"]
    pages = [(1, [[h, ["1", "RTU", "2"]]]),                       # header on page 1
             (2, [[["2", "UPS", "1"]], [["3", "not attached", "9"]]]),   # first table continues; second must not
             (3, [[["4", "orphan", "5"]]])]                        # page 2's last table had no header: no carry
    rows, skipped = pdf_boq.rows_from_tables(pages)
    assert [(r["page"], r["table"], r["item_no"]) for r in rows] == [(1, 1, "1"), (2, 1, "2")]
    reasons = [(k["page"], k["table"]) for k in skipped if "no BOQ header" in k["reason"]]
    assert reasons == [(2, 2), (3, 1)]


def test_qty_parse():
    assert pdf_boq.parse_qty("1,200") == 1200.0 and pdf_boq.parse_qty("-3.5") == -3.5
    assert pdf_boq.parse_qty("TBD") is None and pdf_boq.parse_qty("約 5") is None and pdf_boq.parse_qty("") is None


# ---------------- item column vs name column, summary/heading rows, spaced numbers (synthetic) ----------------
HEAD_ZH = ["項目", "物件名稱", "規格", "單位", "數量", "總價", "備註"]
HEAD_ZH10 = ["項目", "物件名稱", "規格", "單位", "數量", "材料", "工資", "材料", "工資", "備註"]


def test_header_prefers_object_name_over_item_column():
    """'項目' is both an item-number column and a weak name alias: a dedicated name column must win, and '項目' becomes item_no."""
    assert pdf_boq.map_header(HEAD_ZH) == dict(item_no=0, description=1, spec=2, unit=3, qty=4, remarks=6)
    assert pdf_boq.map_header(HEAD_ZH10) == dict(item_no=0, description=1, spec=2, unit=3, qty=4, remarks=9)
    assert pdf_boq.map_header(["項目", "數量"]) == dict(description=0, qty=1)      # weak alias still works when it is the only name
    assert pdf_boq.map_header(["項目", "品名", "數量"]) == dict(item_no=0, description=1, qty=2)


def test_summary_and_heading_rows_are_not_items():
    table = [HEAD_ZH10[:5] + ["備註"],
             ["", "A - 設備室", "", "", "", ""],                          # section heading: no item no / unit / qty
             ["1.1-1", "線槽", "100W", "M", "57", "ASI"],
             ["1.1-2", "T接頭", "600W", "PCs", "-", ""],                  # real item with a blank quantity: kept, with a warning
             ["", "小計", "", "", "", ""],
             ["", "總價 (材料/工資)", "", "", "", ""],
             ["", "總工程款 (未含加值型營業稅)", "", "", "", ""],
             ["", "G-雜項費用 (運輸 / 保險)", "", "", "", "0.23"],
             ["2", "Total station", "", "set", "1", ""],                  # 'Total ...' as an item name is NOT a summary row
             ["", "Total", "", "", "", ""]]
    rows, skipped = pdf_boq.rows_from_tables([(3, [table])])
    assert [(r["row"], r["item_no"], r["description"]) for r in rows] == [
        (3, "1.1-1", "線槽"), (4, "1.1-2", "T接頭"), (9, "2", "Total station")]
    assert rows[1]["parse_warnings"]                                      # '-' is not a plain number
    why = {k["row"]: k["reason"] for k in skipped}
    assert [(k["page"], k["table"]) for k in skipped] == [(3, 1)] * 6
    assert set(why) == {2, 5, 6, 7, 8, 10}
    assert "heading" in why[2] and "heading" in why[8]
    assert all("summary" in why[i] for i in (5, 6, 7, 10))


def test_qty_thousands_separator_with_stray_space():
    """PDF text layers sometimes emit '1 ,806' for 1,806. Only a space touching a thousands comma is restored."""
    assert pdf_boq.parse_qty("1 ,806") == 1806.0
    assert pdf_boq.parse_qty("1, 806") == 1806.0
    assert pdf_boq.parse_qty("12 ,345.5") == 12345.5
    assert pdf_boq.parse_qty("1 ,80") is None        # not a valid thousands group: keep raw
    assert pdf_boq.parse_qty("8 00") is None          # digit-space-digit is ambiguous: keep raw
    assert pdf_boq.parse_qty("1 33.4") is None
    assert pdf_boq.parse_qty("1,806") == 1806.0 and pdf_boq.parse_qty("57") == 57.0


def test_qty_ambiguous_space_keeps_raw_text_and_warns():
    table = [["Item", "Description", "Unit", "Qty"], ["1", "Cable", "M", "1 ,806"], ["2", "Duct", "M", "8 00"]]
    rows, _ = pdf_boq.rows_from_tables([(1, [table])])
    assert (rows[0]["qty"], rows[0]["qty_text"], rows[0]["parse_warnings"]) == (1806.0, "1 ,806", [])
    assert rows[1]["qty"] is None and rows[1]["qty_text"] == "8 00"
    assert "space" in rows[1]["parse_warnings"][0]


# ---------------- B1 / B2 / B3 ----------------
def test_b1_single_table_one_page(tmp_path, data_store, engineering_cfg):
    p = make_pdf(tmp_path / "b.pdf", [[[HEAD, ["1", "RTU cabinet", "IP65", "set", "2", "see RTU-01"],
                                        ["2", "UPS 3kVA", "220V", "set", "1", ""]]]])
    assert pdf_parse(p, data_store, engineering_cfg) == "OK"
    rows = boq_rows(data_store)
    assert [(r["item_no"], r["description"], r["specification"], r["unit"], r["quantity"]) for r in rows] == [
        ("1", "RTU cabinet", "IP65", "set", 2.0), ("2", "UPS 3kVA", "220V", "set", 1.0)]
    assert [r["source_location"] for r in rows] == ["page:1/table:1/row:2", "page:1/table:1/row:3"]
    assert rows[0]["tags"] == "RTU-01"


def test_b2_two_boq_tables_on_one_page_do_not_collide(tmp_path, data_store, engineering_cfg):
    t1 = [HEAD, ["1", "RTU A", "", "set", "1", ""], ["2", "RTU B", "", "set", "1", ""]]
    t2 = [HEAD, ["1", "UPS A", "", "set", "1", ""], ["2", "UPS B", "", "set", "1", ""]]   # same item numbers
    p = make_pdf(tmp_path / "b.pdf", [[t1, t2]])
    pdf_parse(p, data_store, engineering_cfg)
    rows = boq_rows(data_store)
    assert len(rows) == 4 and len({r["source_location"] for r in rows}) == 4
    assert {(r["table_index"], r["item_no"]) for r in rows} == {(1, "1"), (1, "2"), (2, "1"), (2, "2")}


def test_b3_non_boq_table_is_not_parsed_and_reported(tmp_path, data_store, engineering_cfg):
    p = make_pdf(tmp_path / "n.pdf", [[[["Name", "Value"], ["Width", "600"], ["Height", "100"]]]])
    pdf_parse(p, data_store, engineering_cfg)
    assert boq_rows(data_store) == []
    skipped = [json.loads(x) for (x,) in data_store.db.execute(
        "SELECT payload_json FROM exports WHERE report='pdf/boq_skipped.csv'")]
    assert len(skipped) == 1 and "not a BOQ table" in skipped[0]["reason"]      # one entry per table, not per row


# ---------------- B4 / B5 ----------------
def test_b4_continued_table_only_first_table_of_next_page(tmp_path, data_store, engineering_cfg):
    page1 = [[HEAD, ["1", "RTU", "", "set", "1", ""]]]
    page2 = [[["2", "UPS", "", "set", "1", ""]],                    # continuation (same column count)
             [["3", "Other table", "", "set", "9", ""]]]           # second table: header not inherited
    p = make_pdf(tmp_path / "c.pdf", [page1, page2])
    pdf_parse(p, data_store, engineering_cfg)
    assert [(r["pdf_page"], r["item_no"]) for r in boq_rows(data_store)] == [(1, "1"), (2, "2")]


def test_b5_column_count_change_does_not_reuse_header(tmp_path, data_store, engineering_cfg):
    page1 = [[HEAD, ["1", "RTU", "", "set", "1", ""]]]
    page2 = [[["Note", "x", "y", "z"]]]                            # 4 columns vs 6-column header
    p = make_pdf(tmp_path / "d.pdf", [page1, page2])
    pdf_parse(p, data_store, engineering_cfg)
    assert [r["item_no"] for r in boq_rows(data_store)] == ["1"]
    skipped = [json.loads(x) for (x,) in data_store.db.execute(
        "SELECT payload_json FROM exports WHERE report='pdf/boq_skipped.csv'")]
    assert any("column count 4 != header 6" in k["reason"] for k in skipped)


# ---------------- B6 / B7 ----------------
def test_b6_unparsable_quantity_keeps_raw_text(tmp_path, data_store, engineering_cfg):
    p = make_pdf(tmp_path / "q.pdf", [[[HEAD, ["1", "A", "", "m", "TBD", ""], ["2", "B", "", "m", "1,200", ""],
                                        ["3", "C", "", "m", "約 5", ""]]]])
    pdf_parse(p, data_store, engineering_cfg)
    rows = {r["item_no"]: r for r in boq_rows(data_store)}
    assert rows["1"]["quantity"] == "" and rows["1"]["quantity_text"] == "TBD"
    assert "TBD" in json.loads(rows["1"]["parse_warnings_json"])[0]
    assert float(rows["2"]["quantity"]) == 1200.0 and json.loads(rows["2"]["parse_warnings_json"]) == []
    assert rows["3"]["quantity_text"] == "約 5" and rows["3"]["quantity"] == ""


def test_b7_every_row_has_page_table_row_evidence_and_chunk(tmp_path, engineering_cfg):
    inp = tmp_path / "in"
    inp.mkdir()
    make_pdf(inp / "b.pdf", [[[HEAD, ["1", "RTU", "", "set", "1", ""], ["2", "UPS", "", "set", "TBD", ""]]],
                             [[["3", "Cable tray", "", "m", "40", ""]]]])
    out = tmp_path / "out"
    s = run_multiformat(dict(engineering_cfg, output_dir=str(out)), [str(inp)])
    assert s["failed"] == 0
    with sqlite3.connect(out / "database" / "project.db") as db:
        rows = db.execute("SELECT pdf_page, table_index, row_number, source_location, citation FROM boq_items "
                          "WHERE source_type='PDF' ORDER BY rowid").fetchall()
    assert rows == [("1", "1", "2", "page:1/table:1/row:2", "PDF p.1 / § table 1 row 2"),
                    ("1", "1", "3", "page:1/table:1/row:3", "PDF p.1 / § table 1 row 3"),
                    ("2", "1", "1", "page:2/table:1/row:1", "PDF p.2 / § table 1 row 1")]
    # evidence chunks: one per BOQ row, locator carries page/table/row
    import evidence_builder
    from evidence_schema import connect
    db = connect(out / "database" / "project.db", writable=True)
    try:
        evidence_builder.build(db)
        chunks = db.execute("SELECT chunk_id, source_location FROM evidence_chunks WHERE record_table='boq_items'").fetchall()
    finally:
        db.close()
    assert len(chunks) == 3 and len({c["chunk_id"] for c in chunks}) == 3
    locs = [json.loads(c["source_location"]) for c in chunks]
    assert all(l["pdf_page"] and l["table_index"] and l["row_number"] for l in locs)


# ---------------- B8 / B9 / B10 ----------------
def test_b8_rerun_does_not_duplicate_or_leave_stale_rows(tmp_path, data_store, engineering_cfg):
    p = make_pdf(tmp_path / "r.pdf", [[[HEAD, ["1", "RTU", "", "set", "1", ""], ["2", "UPS", "", "set", "1", ""]]]])
    pdf_parse(p, data_store, engineering_cfg)
    pdf_parse(p, data_store, engineering_cfg)                                   # rebuild same source
    assert len(boq_rows(data_store)) == 2
    q = make_pdf(p, [[[HEAD, ["1", "RTU", "", "set", "5", ""]]]])                 # source now has one row
    pdf_parse(q, data_store, engineering_cfg)
    rows = boq_rows(data_store)
    assert len(rows) == 1 and rows[0]["quantity"] == 5.0                        # stale row 2 gone
    n_exports = data_store.db.execute("SELECT count(*) FROM exports WHERE report='pdf/boq_items.csv'").fetchone()[0]
    assert n_exports == 1


def test_b8b_pipeline_reruns_are_identical(tmp_path, engineering_cfg):
    inp = tmp_path / "in"
    inp.mkdir()
    make_pdf(inp / "b.pdf", [[[HEAD, ["1", "RTU", "", "set", "1", ""]]]])
    out = tmp_path / "out"
    counts = []
    for _ in range(2):
        run_multiformat(dict(engineering_cfg, output_dir=str(out)), [str(inp)])
        with sqlite3.connect(out / "database" / "project.db") as db:
            counts.append(db.execute("SELECT count(*) FROM boq_items").fetchone()[0])
        db.close()                      # sqlite3's "with" does not close: keep the file replaceable on Windows
    assert counts == [1, 1]


def test_b9_source_pdf_is_not_modified(tmp_path, data_store, engineering_cfg):
    p = make_pdf(tmp_path / "s.pdf", [[[HEAD, ["1", "RTU", "", "set", "1", ""]]]])
    before = digest(p)
    pdf_parse(p, data_store, engineering_cfg)
    assert digest(p) == before


def test_b10_missing_pdfplumber_is_graceful(tmp_path, data_store, engineering_cfg, monkeypatch):
    p = make_pdf(tmp_path / "s.pdf", [[[HEAD, ["1", "RTU", "", "set", "1", ""]]]])
    monkeypatch.setitem(sys.modules, "pdfplumber", None)                        # import raises ImportError
    assert pdf_parse(p, data_store, engineering_cfg) == "OK"                    # default: text evidence still produced
    assert boq_rows(data_store) == [] and any(r.get("page") for r in data_store.rows("documents"))
    summary = [json.loads(x) for (x,) in data_store.db.execute(
        "SELECT payload_json FROM exports WHERE report='pdf/pdf_summary.csv'")][0]
    assert summary["boq_status"] == "SKIPPED_DEPENDENCY"
    assert pdf_parse(p, data_store, dict(engineering_cfg, pdf_boq_tables="required")) == "SKIPPED_DEPENDENCY"


def test_b10b_pipeline_records_skipped_dependency_status(tmp_path, engineering_cfg, monkeypatch):
    inp = tmp_path / "in"
    inp.mkdir()
    make_pdf(inp / "b.pdf", [[[HEAD, ["1", "RTU", "", "set", "1", ""]]]])
    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    out = tmp_path / "out"
    s = run_multiformat(dict(engineering_cfg, output_dir=str(out), pdf_boq_tables="required"), [str(inp)])
    assert s["warnings"] == 1 and s["failed"] == 0
    with sqlite3.connect(out / "database" / "project.db") as db:
        assert db.execute("SELECT status FROM project_files").fetchone()[0] == "SKIPPED_DEPENDENCY"
        assert db.execute("SELECT count(*) FROM documents").fetchone()[0] > 0   # text evidence kept


def test_off_mode_does_nothing(tmp_path, data_store, engineering_cfg):
    p = make_pdf(tmp_path / "s.pdf", [[[HEAD, ["1", "RTU", "", "set", "1", ""]]]])
    pdf_parse(p, data_store, dict(engineering_cfg, pdf_boq_tables="off"))
    assert boq_rows(data_store) == []
