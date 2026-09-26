"""Tests for the SCADA search core, object/block summaries and text quality (no AutoCAD needed)."""
import csv
import sys
from pathlib import Path

import ezdxf
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import scada_rules as sr  # noqa: E402
import analyze_dxf  # noqa: E402
import find_scada  # noqa: E402
from common import load_config  # noqa: E402

CFG = load_config()
RULES = sr.build_rules(CFG)


def kws(text, rules=RULES):
    return [m["keyword"] for m in sr.find_matches(text, rules) if m["confidence"] != sr.EXCLUDED]


# ---- token matching ---------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("RACK", True), ("rack", True), ("TRACK", False), ("RACK-01", True), ("RACK_01", True),
    ("BRACKET", False), ("RACK01", True), ("RACK1", True), ("TRACK01", False), ("RACKS", False), ("設備RACK機櫃", True),
])
def test_rack_token_rules(text, expected):
    assert bool(sr.match_keyword(text, "RACK")) is expected


def test_backup_not_ups_and_panelboard_not_panel():
    assert not sr.match_keyword("BACKUP", "UPS")
    assert not sr.match_keyword("PANELBOARD", "PANEL")
    assert sr.match_keyword("UPS-1", "UPS")


def test_underscore_and_hyphen_names():
    for name in ("SCADA_TRAY", "SCADA-TRAY"):
        assert "SCADA" in kws(name) and "TRAY" in kws(name)
    assert "RTU" in kws("RTU_PANEL")
    assert "RTU PANEL" in kws("RTU_PANEL")


def test_phrase_match_and_separators():
    assert sr.match_keyword("SCADA_PANEL", "SCADA PANEL")
    assert sr.match_keyword("scada-panel", "SCADA PANEL")
    assert sr.match_keyword("SCADA   Panel #1", "SCADA PANEL")
    assert not sr.match_keyword("SCADAPANEL", "SCADA PANEL")


def test_chinese_keyword_is_substring():
    assert sr.match_keyword("一樓控制室盤面", "控制室")


# ---- panel noise --------------------------------------------------------------
@pytest.mark.parametrize("t", ["System Panel - Glazed", "Curtain Wall Panel", "Curtain Panel",
                               "Architectural Panel"])
def test_building_panels_are_excluded(t):
    ms = sr.find_matches(t, RULES)
    assert ms and all(m["confidence"] == sr.EXCLUDED for m in ms)
    assert kws(t) == []


@pytest.mark.parametrize("t,kw", [("SCADA PANEL", "SCADA PANEL"), ("RTU Panel A", "RTU PANEL"),
                                  ("control panel", "CONTROL PANEL"), ("MCC-PANEL", "MCC PANEL")])
def test_high_confidence_panels(t, kw):
    ms = [m for m in sr.find_matches(t, RULES) if m["keyword"] == kw]
    assert ms and ms[0]["confidence"] == sr.HIGH
    assert "PANEL" not in kws(t)          # bare PANEL is not reported twice


def test_plain_panel_is_normal_not_high():
    ms = sr.find_matches("LIGHTING PANEL", RULES)
    assert [(m["keyword"], m["confidence"]) for m in ms] == [("PANEL", sr.NORMAL)]


# ---- object hits -----------------------------------------------------------------
def _row(**kw):
    base = dict(file="a.dxf", keyword="SCADA", source_type="BLOCK_NAME", layer="L", block="b",
                text="b", x=1, y=2, z=0, handle="A1", confidence=sr.NORMAL)
    base.update(kw)
    return base


def test_same_handle_multiple_keywords_one_object_row():
    rows = [_row(keyword="SCADA"), _row(keyword="TRAY"), _row(handle="B2", keyword="TRAY")]
    objs = sr.build_object_hits(rows)
    assert len(objs) == 2
    assert objs[0]["matched_keywords"] == "SCADA|TRAY" and objs[0]["match_count"] == 2
    assert objs[1]["matched_keywords"] == "TRAY"


def test_object_confidence_takes_highest_and_fallback_key_without_handle():
    rows = [_row(handle="", keyword="RTU"), _row(handle="", keyword="RTU PANEL", confidence=sr.HIGH),
            _row(handle="", x=9, keyword="RTU")]
    objs = sr.build_object_hits(rows)
    assert len(objs) == 2                      # different position -> different object, none lost
    assert objs[0]["confidence"] == sr.HIGH and objs[0]["matched_keywords"] == "RTU|RTU PANEL"


# ---- block summary -------------------------------------------------------------------
def test_block_summary_counts_sorting_and_scada_flag():
    def b(name, layer, x=0):
        return dict(file="f.dxf", block_name=name, layer=layer, x=x, y=0, z=0)
    blocks = [b("chair", "FURN", 5)] + [b("750 tray_elbow_scada", "SCADA", i) for i in range(8)] + \
             [b("chair", "FURN"), b("door", "ARCH"), b("chair", "FURN")]
    rows = sr.build_block_summary(blocks, RULES)
    assert [(r["block_name"], r["count"], r["scada_related"]) for r in rows] == [
        ("750 tray_elbow_scada", 8, "true"), ("chair", 3, "false"), ("door", 1, "false")]
    assert rows[0]["first_x"] == 0 and rows[1]["first_x"] == 5


# ---- text quality ---------------------------------------------------------------------
@pytest.mark.parametrize("t,q", [("?", "SUSPECT_ENCODING"), ("??", "SUSPECT_ENCODING"),
                                 ("�abc", "SUSPECT_ENCODING"), ("???", "SUSPECT_ENCODING"), ("�", "SUSPECT_ENCODING"),
                                 ("??AB", "SUSPECT_ENCODING"), ("設備?", "OK"), ("是否?", "OK"),
                                 ("正常？", "OK"), ("中?文", "OK"),
                                 ("RTU-01", "OK"), ("中文測試", "OK"),
                                 ("", "EMPTY"), ("   ", "EMPTY"), ("Why? Because", "OK")])
def test_text_quality(t, q):
    assert analyze_dxf.text_quality(t) == q


# ---- end to end on a synthetic DXF ------------------------------------------------------
def _make_dxf(path, with_scada=True):
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    doc.layers.add("SCADA" if with_scada else "ARCH")
    if with_scada:
        msp.add_text("RACK_01", dxfattribs={"layer": "SCADA"})
        msp.add_text("TRACK LIGHT")
        msp.add_text("SCADA PANEL 1", dxfattribs={"insert": (5, 5)})
        msp.add_mtext("System Panel - Glazed")
        msp.add_text("?")
        doc.blocks.new("750 tray_elbow_scada")
        for i in range(8):
            msp.add_blockref("750 tray_elbow_scada", (i, 0), dxfattribs={"layer": "SCADA"})
    else:
        msp.add_text("hello", dxfattribs={"layer": "ARCH"})
        msp.add_text("System Panel - Glazed")
    doc.saveas(path)


@pytest.fixture
def run_cfg(tmp_path):
    out = tmp_path / "out"
    (out / "dxf").mkdir(parents=True)
    return dict(CFG, input_dir=str(tmp_path / "in"), output_dir=str(out)), out


def _read(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_end_to_end_outputs(run_cfg):
    cfg, out = run_cfg
    _make_dxf(out / "dxf" / "x.dxf")
    a = analyze_dxf.run(cfg)
    s = find_scada.run(cfg)
    hits = _read(out / "csv" / "scada_hits.csv")
    objs = _read(out / "csv" / "object_hits.csv")
    assert ("RACK", "RACK_01") in {(h["keyword"], h["text"]) for h in hits}
    assert not any("TRACK" in h["text"] for h in hits)                       # TRACK does not hit RACK
    assert not any("Glazed" in h["text"] for h in hits)                      # building panel excluded
    assert any(h["keyword"] == "SCADA PANEL" and h["confidence"] == "high_confidence" for h in hits)
    assert any(h["keyword"] == "SCADA" and h["source_type"] == "BLOCK_NAME" for h in hits)
    assert any("Glazed" in r["text"] for r in _read(out / "csv" / "scada_excluded.csv"))
    blk = [o for o in objs if o["source_type"] == "BLOCK_NAME"]
    assert len(blk) == 8 and all(o["matched_keywords"] == "SCADA|TRAY" and o["match_count"] == "2"
                                 for o in blk)
    assert s["objects"] == len(objs) and s["hits"] == len(hits) and s["objects"] < s["hits"]
    bs = _read(out / "csv" / "block_summary.csv")
    assert bs[0]["block_name"] == "750 tray_elbow_scada" and bs[0]["count"] == "8"
    assert bs[0]["scada_related"] == "true" and bs[0]["layer"] == "SCADA"
    assert len(_read(out / "csv" / "blocks.csv")) == 8                       # instance detail kept
    tx = _read(out / "csv" / "texts.csv")
    assert {t["text"]: t["text_quality"] for t in tx}["?"] == "SUSPECT_ENCODING"
    assert a["suspect"] == 1 and a["failed"] == 0
    assert _read(out / "csv" / "file_index.csv")[0]["status"] == "OK"        # suspect text != failure


def test_no_hits_and_empty_attribs_still_valid_csv(run_cfg):
    cfg, out = run_cfg
    _make_dxf(out / "dxf" / "plain.dxf", with_scada=False)
    analyze_dxf.run(cfg)
    s = find_scada.run(cfg)
    assert s["hits"] == 0 and s["objects"] == 0 and s["excluded"] >= 1
    for name in ("scada_hits", "object_hits", "attribs", "block_summary"):
        p = out / "csv" / f"{name}.csv"
        assert p.read_text(encoding="utf-8-sig").splitlines()[0].startswith("file")   # header
        assert _read(p) == []                                                        # no rows


def test_repeated_keyword_in_one_text_gives_one_hit():
    ms = [m for m in sr.find_matches("RACK_01 NETWORK RACK", RULES) if m["keyword"] == "RACK"]
    assert len(ms) == 1


@pytest.mark.parametrize("text,kw,expected", [
    ("RACK01", "RACK", True), ("RACK1", "RACK", True), ("RACK-01", "RACK", True),
    ("RACK_01", "RACK", True), ("TRACK01", "RACK", False),
    ("UPS1", "UPS", True), ("UPS01", "UPS", True), ("BACKUPS1", "UPS", False),
    ("RTU01", "RTU", True), ("PLC01", "PLC", True), ("plc01", "PLC", True),
    ("SB12-01", "SB12", True), ("SB123", "SB12", False),
    ("PANELBOARD", "PANEL", False), ("SCADAPANEL", "SCADA PANEL", False),
    ("SCADA PANEL01", "SCADA PANEL", True), ("NETWORK RACK2", "NETWORK RACK", True),
])
def test_numeric_suffix_rules(text, kw, expected):
    assert bool(sr.match_keyword(text, kw)) is expected


def test_numeric_suffix_still_needs_leading_boundary():
    assert not sr.match_keyword("XUPS1", "UPS")
    assert sr.match_keyword("設備UPS1", "UPS")


def test_block_summary_scada_related_by():
    def b(name, layer, handle="1"):
        return dict(file="f.dxf", block_name=name, layer=layer, handle=handle, x=0, y=0, z=0)
    blocks = [b("chair", "SCADA"), b("tray_elbow_scada", "ARCH"), b("rtu_box", "SCADA"),
              b("plain", "FURN", "H9"), b("door", "ARCH", "H1")]
    attribs = [dict(file="f.dxf", parent_handle="H9", text="UPS-01"),
               dict(file="f.dxf", parent_handle="H1", text="hello")]
    rows = {r["block_name"]: r for r in sr.build_block_summary(blocks, RULES, attribs)}
    assert (rows["chair"]["scada_related"], rows["chair"]["scada_related_by"]) == ("true", "layer")
    assert rows["tray_elbow_scada"]["scada_related_by"] == "block_name"
    assert rows["rtu_box"]["scada_related_by"] == "block_name|layer"
    assert rows["plain"]["scada_related_by"] == "text"
    assert (rows["door"]["scada_related"], rows["door"]["scada_related_by"]) == ("false", "")
    assert "scada_related_by" in sr.BLOCK_SUMMARY_FIELDS


@pytest.mark.parametrize("text,expected", [
    ("TRAYX600", True), ("trayX600", True), ("TRAYW300", True), ("TRAYH150", True),
    ("TRAY300", True), ("TRAY-300", True), ("TRAY_X600", True), ("750 tray_Tee_scada", True),
    ("BETRAYAL", False), ("ENTRYWAY", False), ("XTRAY", False), ("TRAYX", False),
    ("TRAYX600A", False), ("TRAYS", False),
])
def test_engineering_suffix_for_tray(text, expected):
    assert bool(sr.match_keyword(text, "TRAY", engineering=True)) is expected
    assert ("TRAY" in kws(text)) is expected          # default config lists TRAY


def test_engineering_suffix_is_not_applied_to_other_keywords():
    for text, kw in (("RACKX600", "RACK"), ("UPSX1", "UPS"), ("PLCW300", "PLC"), ("RTUH150", "RTU")):
        assert kw not in kws(text)
    # opt-in through config
    r = sr.build_rules(dict(CFG, engineering_suffix_keywords=["TRAY", "RACK"]))
    assert "RACK" in kws("RACKX600", r) and "UPS" not in kws("UPSX1", r)
    r0 = sr.build_rules(dict(CFG, engineering_suffix_keywords=[]))
    assert "TRAY" not in kws("trayX600", r0)


def test_previous_rules_unchanged():
    for text, kw, exp in (("TRACK01", "RACK", False), ("BACKUPS1", "UPS", False), ("RACK01", "RACK", True),
                          ("UPS1", "UPS", True), ("RTU01", "RTU", True), ("PLC01", "PLC", True),
                          ("SB123", "SB12", False), ("SB12-01", "SB12", True)):
        assert bool(sr.match_keyword(text, kw)) is exp
