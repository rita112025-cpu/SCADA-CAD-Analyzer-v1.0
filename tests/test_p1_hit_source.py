"""P1-1: hit_source column. source_type stays the source category; hit_source names the CAD element."""
import csv
import json
import sqlite3
import sys
from pathlib import Path

import ezdxf
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import find_scada  # noqa: E402
import scada_rules  # noqa: E402
from pipeline import run_multiformat  # noqa: E402

RULES = scada_rules.Rules(["SCADA", "TRAY", "RTU"])


def _dxf(path):
    doc = ezdxf.new("R2018")
    doc.layers.add("RTU-LAYER")
    msp = doc.modelspace()
    msp.add_text("RTU-01 text", dxfattribs={"handle": "AA1"})
    msp.add_mtext("RTU-02 mtext")
    doc.blocks.new("SCADA_TRAY_ST").add_attdef("NOTE", (0, 0))
    ins = msp.add_blockref("SCADA_TRAY_ST", (1, 1))
    ins.add_auto_attribs({"NOTE": "RTU-03 attrib"})
    doc.saveas(path)


@pytest.fixture
def dxf(tmp_path):
    p = tmp_path / "d.dxf"
    _dxf(p)
    return p


def test_hit_source_for_every_source(dxf):
    hits, _ = find_scada.search_doc(ezdxf.readfile(dxf), "d.dxf", RULES)
    seen = {(h["hit_source"], h["keyword"]) for h in hits}
    assert ("TEXT", "RTU") in seen and ("MTEXT", "RTU") in seen and ("ATTRIB", "RTU") in seen
    assert ("BLOCK_NAME", "SCADA") in seen and ("BLOCK_NAME", "TRAY") in seen
    assert ("LAYER_NAME", "RTU") in seen
    assert all(h["hit_source"] in scada_rules.HIT_SOURCES for h in hits)


def test_legacy_columns_kept_and_hit_source_appended():
    assert scada_rules.HIT_FIELDS[:11] == ["file", "keyword", "source_type", "layer", "block", "text",
                                           "x", "y", "z", "handle", "confidence"]
    assert scada_rules.HIT_FIELDS[-1] == "hit_source" and scada_rules.OBJECT_FIELDS[-1] == "hit_source"


def test_two_keywords_same_object_keep_hit_source_and_identity(dxf):
    hits, _ = find_scada.search_doc(ezdxf.readfile(dxf), "d.dxf", RULES)
    blk = [h for h in hits if h["hit_source"] == "BLOCK_NAME"]
    assert {h["keyword"] for h in blk} == {"SCADA", "TRAY"} and len({h["handle"] for h in blk}) == 1
    objs = scada_rules.build_object_hits(hits)
    one = [o for o in objs if o["hit_source"] == "BLOCK_NAME"]
    assert len(one) == 1 and one[0]["matched_keywords"] == "SCADA|TRAY" and one[0]["match_count"] == 2
    assert len(objs) == len({(o["hit_source"], o["handle"]) for o in objs})


def test_object_identity_survives_source_type_being_overwritten(dxf):
    """The multi-format writer sets source_type='CAD' on rows; identity must not merge different elements."""
    hits, _ = find_scada.search_doc(ezdxf.readfile(dxf), "d.dxf", RULES)
    for h in hits:
        h["source_type"] = "CAD"
    objs = scada_rules.build_object_hits(hits)
    assert {o["hit_source"] for o in objs} == {"TEXT", "MTEXT", "ATTRIB", "BLOCK_NAME", "LAYER_NAME"}


def test_multiformat_output_csv_and_sqlite(tmp_path, engineering_cfg, dxf):
    out = tmp_path / "out"
    s = run_multiformat(dict(engineering_cfg, output_dir=str(out)), [str(dxf)])
    assert s["failed"] == 0
    for name in ("scada_hits", "object_hits"):
        with open(out / "cad" / f"{name}.csv", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows and {r["source_type"] for r in rows} == {"CAD"}
        assert {r["hit_source"] for r in rows} == {"TEXT", "MTEXT", "ATTRIB", "BLOCK_NAME", "LAYER_NAME"}
    with sqlite3.connect(out / "database" / "project.db") as db:
        payloads = [json.loads(p) for (p,) in db.execute(
            "SELECT payload_json FROM exports WHERE report='cad/scada_hits.csv'")]
    assert payloads and all(p["source_type"] == "CAD" and p["hit_source"] for p in payloads)
    assert {p["hit_source"] for p in payloads} >= {"TEXT", "MTEXT", "ATTRIB", "BLOCK_NAME"}
    assert s["keyword_hits"] == len(payloads)


def test_legacy_find_scada_csv_keeps_source_type_values(tmp_path, dxf):
    """The standalone CLI output stays compatible: source_type values unchanged, hit_source added."""
    out = tmp_path / "o"
    (out / "dxf").mkdir(parents=True)
    (out / "dxf" / "d.dxf").write_bytes(dxf.read_bytes())
    find_scada.run(dict(input_dir=str(tmp_path), output_dir=str(out), keywords=["RTU", "SCADA", "TRAY"]))
    with open(out / "csv" / "scada_hits.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert {r["source_type"] for r in rows} == {"TEXT", "MTEXT", "ATTRIB", "BLOCK_NAME", "LAYER_NAME"}
    assert all(r["source_type"] == r["hit_source"] for r in rows)
