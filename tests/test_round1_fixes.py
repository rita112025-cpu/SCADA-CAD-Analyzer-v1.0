"""Regression tests for defects found in SB12 real-project validation round 1 (synthetic data only).
F1 MTEXT/TEXT '\\U+XXXX' not decoded; F3 absent source category reported as MISSING_B;
F4 PDF section = running page header instead of the clause."""
import csv
import sys
from pathlib import Path

import ezdxf
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import analyze_dxf  # noqa: E402
import find_scada  # noqa: E402
import scada_rules  # noqa: E402
from cross_reference import run as xref_run  # noqa: E402
from analyze_pdf import parse as pdf_parse, ClauseTracker  # noqa: E402

ESC_ROOM = "\\U+8A2D\\U+5099\\U+5BA4"          # 設備室
ESC_PAID = "\\U+4ED8\\U+8CBB\\U+5340"          # 付費區


# ---------------- F1 ----------------
@pytest.mark.parametrize("raw,expected", [
    (ESC_PAID, "付費區"),
    ("\\U+4ed8", "付"),                                   # lower-case hex
    ("COMM/SCADA " + ESC_ROOM, "COMM/SCADA 設備室"),
    ("\\U+4ED", "\\U+4ED"),                               # truncated: left as-is
    ("\\U+D800", "\\U+D800"),                             # surrogate: left as-is
    ("no escapes", "no escapes"),
])
def test_decode_dxf_unicode(raw, expected):
    assert analyze_dxf.decode_dxf_unicode(raw) == expected


def test_leftover_escape_is_suspect():
    assert analyze_dxf.text_quality("\\U+4ED") == "SUSPECT_ENCODING"
    assert analyze_dxf.text_quality("\\M+1A4A4") == "SUSPECT_ENCODING"
    assert analyze_dxf.text_quality("付費區") == "OK"


def _escaped_dxf(path):
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_mtext("{\\fArial|b0|i0|c136|p34;" + ESC_ROOM + "}\\P" + ESC_PAID, dxfattribs={"handle": "A1"})
    msp.add_mtext("A\\U+007B\\U+007D\\U+005CP")            # escaped { } \ must stay literal
    msp.add_text(ESC_PAID)
    blk = doc.blocks.new("TAGBLK")
    blk.add_attdef("ROOM", (0, 0))
    msp.add_blockref("TAGBLK", (5, 5)).add_auto_attribs({"ROOM": ESC_ROOM})
    doc.saveas(path)


def test_escaped_text_decoded_everywhere(tmp_path):
    p = tmp_path / "esc.dxf"
    _escaped_dxf(p)
    res, _ = analyze_dxf.analyze(p, "esc.dxf")
    texts = {t["entity_type"]: [] for t in res["texts"]}
    for t in res["texts"]:
        texts[t["entity_type"]].append(t["text"])
    assert "設備室\n付費區" in texts["MTEXT"]
    assert "A{}\\P" in texts["MTEXT"]                       # not re-read as a paragraph code
    assert texts["TEXT"] == ["付費區"] and texts["ATTRIB"] == ["設備室"]
    assert all("\\U+" not in t["text"] and t["text_quality"] == "OK" for t in res["texts"])
    assert res["attribs"][0]["text"] == "設備室"
    # keyword matching sees the decoded text
    rules = scada_rules.Rules(["設備室"])
    hits, _ = find_scada.search_doc(ezdxf.readfile(p), "esc.dxf", rules)
    assert {h["source_type"] for h in hits} == {"MTEXT", "ATTRIB"}


# ---------------- F3 ----------------
def _rows(store):
    return list(store.rows("cross_reference_results"))


def _coverage(store):
    import json
    return {r["check_type"]: r for r in
            (json.loads(p) for (p,) in store.db.execute("SELECT payload_json FROM exports WHERE report=?",
                                                        ("cross_reference/coverage.csv",)))}


def test_no_boq_and_no_requirements_are_not_tested_not_missing(data_store, engineering_cfg):
    for n, h in (("RTU-01", "A1"), ("SCADA TRAY", "A2")):
        data_store.add("engineering_objects", dict(name=n, source_type="CAD", object_type="INSERT",
                                                   source_file="a.dxf", handle=h))
    xref_run(data_store, engineering_cfg)
    assert not [r for r in _rows(data_store) if r["result"] == "MISSING_B"]
    cov = _coverage(data_store)
    assert cov["OBJECT_VS_BOQ"]["status"] == "NOT_TESTED" and "BOQ source unavailable" in cov["OBJECT_VS_BOQ"]["reason"]
    assert cov["KEYWORD_VS_REQUIREMENT"]["status"] == "NOT_TESTED"
    assert cov["CLASH_VS_OBJECT"]["status"] == "NOT_TESTED"


def test_missing_b_still_reported_when_source_present(data_store, engineering_cfg):
    data_store.add("engineering_objects", dict(name="UPS99", source_type="CAD", object_type="INSERT",
                                               source_file="a.dxf", handle="A1"))
    data_store.add("boq_items", dict(model="RTU-01", source_file="boq.xlsx"))
    data_store.add("requirements", dict(keyword="RTU", requirement_text="RTU shall exist", source_file="s.docx"))
    xref_run(data_store, engineering_cfg)
    rows = _rows(data_store)
    assert any(r["check_type"] == "CAD_OBJECT_VS_BOQ" and r["result"] == "MISSING_B" for r in rows)
    assert any(r["check_type"] == "CAD_KEYWORD_VS_REQUIREMENT" and r["result"] == "MISSING_B" for r in rows)
    cov = _coverage(data_store)
    assert cov["OBJECT_VS_BOQ"]["status"] == "PERFORMED" and cov["KEYWORD_VS_REQUIREMENT"]["status"] == "PERFORMED"


# ---------------- F4 ----------------
@pytest.mark.parametrize("lines,expected", [
    (["一、 甲章", "(二) 甲章第二款"], "一(二)"),
    (["二、 乙章", "(三) 乙章第三款", "1. 第一目", "3. 第三目"], "二(三)3"),
    (["四、 丁章", "(十四) x", "(十五) 第十五款"], "四(十五)"),
    (["四、 丁章", "(四) 第四款", "2.5M 以上"], "四(四)"),        # decimal is not a clause
    (["(一) 沒有上層條文"], ""),                                               # no L1 yet
    (["五、 戊章", "(四) 第四款", "1. 第一目，另見附件B-1 及B-2"], "五(四)1"),
    (["五、 戊章", "(四) 第四款", "附件B-1", "1. 表格內容"], "附件B-1"),  # table cell, not 五(四)1
    (["附件A 附表標題", "(二) x", "3. y"], "附件A"),
    (["附件B-1", "附件B-2", "2. 表格內容"], "附件B-2"),
])
def test_clause_tracker(lines, expected):
    t = ClauseTracker()
    for l in lines:
        t.feed(l)
    assert t.clause_id == expected


def test_pdf_sections_follow_clauses_across_pages(tmp_path, data_store, engineering_cfg):
    import fitz
    p = tmp_path / "spec.pdf"
    doc = fitz.open()
    bodies = [["一、 甲章：", "(一) 甲章第一款。"],
              ["二、 乙章：", "(三) 乙章第三款", "3. 第三目：RTU 與 RACK"],
              ["續上頁：TRAY 之間距", "四、 丁章", "(十五) 第十五款 TRAY 200mm"]]
    for i, body in enumerate(bodies, 1):
        page = doc.new_page()
        y = 40
        for line in ["Running Header Project", "Appendix C Pipe Rules"] + body + [f"C-{i}"]:
            page.insert_text((30, y), line, fontname="china-t")
            y += 20
    doc.save(p)
    doc.close()
    assert pdf_parse(p, data_store, engineering_cfg) == "OK"
    hits = [r for r in data_store.rows("documents") if r.get("keyword")]
    by_kw = {(r["page"], r["keyword"]): r["section"] for r in hits}
    assert by_kw[(2, "RTU")] == "二(三)3"
    assert by_kw[(3, "TRAY")] in ("二(三)3", "四(十五)")   # first TRAY line continues 二(三)3
    assert sorted(r["section"] for r in hits if r["page"] == 3 and r["keyword"] == "TRAY") == ["二(三)3", "四(十五)"]
    pages = {r["page"]: r for r in data_store.rows("documents") if r.get("status")}
    assert pages[1]["heading_candidate"] == "一、 甲章："          # running header is not the heading
    assert pages[3]["section"] == "二(三)3"                           # clause active where page 3 begins
    assert all("Running Header" not in (r.get("section") or "") for r in data_store.rows("documents"))
    clauses = [r for r in data_store.rows("document_sections") if r.get("kind") == "clause"]
    assert [c["section"] for c in clauses] == ["一", "一(一)", "二", "二(三)", "二(三)3", "四", "四(十五)"]
    assert next(c for c in clauses if c["section"] == "四(十五)")["page"] == 3
