"""P1-3: revision metadata. Formal revision stays NULL; only an older/newer ORDER may be inferred."""
import os
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import revision_meta as rm  # noqa: E402
from pipeline import run_multiformat  # noqa: E402


def touch(p, mtime, content="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    os.utime(p, (mtime, mtime))
    return p


def docx(path, modified=None, text="Item,Model,Qty"):
    """Minimal .docx whose core.xml carries dcterms:modified (Word/Office-style)."""
    from docx import Document
    d = Document()
    d.add_paragraph(text)
    if modified:
        d.core_properties.modified = modified
    d.save(path)
    return path


def test_single_file_is_unknown_and_revision_null(tmp_path):
    p = touch(tmp_path / "report.docx", 1000)
    r = rm.infer([p])[p]
    assert r == dict(revision=None, revision_label=None, revision_status="unknown", revision_basis="")


def test_two_files_agree_on_all_bases(tmp_path):
    a, b = touch(tmp_path / "site_record.docx", 1000), touch(tmp_path / "site_record_更新版.docx", 2000)
    r = rm.infer([a, b])
    assert (r[a]["revision_label"], r[b]["revision_label"]) == ("older", "newer")
    assert r[b]["revision_status"] == "inferred_order" and r[b]["revision_basis"] == "filename|mtime"
    assert r[a]["revision"] is None and r[b]["revision"] is None      # never promoted to a formal revision


def test_different_stems_are_not_a_family(tmp_path):
    a, b = touch(tmp_path / "plan_a.docx", 1000), touch(tmp_path / "plan_b.docx", 2000)   # different stems!
    assert rm.infer([a, b])[a]["revision_status"] == "unknown"        # not the same family


def test_same_family_by_stem_uses_mtime_only(tmp_path):
    a, b = touch(tmp_path / "plan_v1.docx", 1000), touch(tmp_path / "plan_v2.docx", 2000)
    r = rm.infer([a, b])
    assert (r[a]["revision_label"], r[b]["revision_label"]) == ("older", "newer")
    assert r[a]["revision_basis"] == "mtime"


def test_conflicting_bases_give_no_label(tmp_path):
    a = touch(tmp_path / "plan.docx", 5000)                # plain name but modified LATER
    b = touch(tmp_path / "plan_更新版.docx", 1000)           # says "updated" but modified EARLIER
    r = rm.infer([a, b])
    for p in (a, b):
        assert r[p]["revision_status"] == "conflicting_order" and r[p]["revision_label"] is None
        assert r[p]["revision"] is None and r[p]["revision_basis"] == "filename|mtime"


def test_core_modified_is_a_basis(tmp_path):
    import datetime as dt
    a = docx(tmp_path / "spec.docx", dt.datetime(2026, 1, 1))
    b = docx(tmp_path / "spec_new.docx", dt.datetime(2026, 6, 1))
    os.utime(a, (3000, 3000))
    os.utime(b, (3000, 3000))                                # identical mtime: no vote from mtime
    r = rm.infer([a, b])
    assert r[b]["revision_label"] == "newer" and r[b]["revision_basis"] == "filename|core_modified"


def test_three_versions_are_ranked_not_labelled_newer(tmp_path):
    ps = [touch(tmp_path / f"boq_v{i}.docx", 1000 * i) for i in (3, 1, 2)]
    r = rm.infer(ps)
    assert [r[p]["revision_label"] for p in ps] == ["order_3_of_3", "order_1_of_3", "order_2_of_3"]


def test_no_signal_between_family_members_stays_unknown(tmp_path):
    a, b = touch(tmp_path / "x_v1.docx", 1000), touch(tmp_path / "x_v2.docx", 1000)   # same mtime, no marker
    r = rm.infer([a, b])
    assert r[a]["revision_status"] == "unknown" and r[a]["revision_label"] is None


def test_different_extensions_are_different_families(tmp_path):
    a, b = touch(tmp_path / "a.docx", 1000), touch(tmp_path / "a_更新版.pdf", 2000)
    assert rm.infer([a, b])[a]["revision_label"] is None


def test_pipeline_persists_metadata_in_csv_and_sqlite(tmp_path, engineering_cfg):
    inp = tmp_path / "in"
    docx(inp.mkdir() or inp / "point.docx")
    docx(inp / "point_更新版.docx")
    os.utime(inp / "point.docx", (1000, 1000))
    os.utime(inp / "point_更新版.docx", (2000, 2000))
    out = tmp_path / "out"
    assert run_multiformat(dict(engineering_cfg, output_dir=str(out)), [str(inp)])["failed"] == 0
    with sqlite3.connect(out / "database" / "project.db") as db:
        rows = {Path(f).name: (rev, lab, st, basis) for f, rev, lab, st, basis in db.execute(
            "SELECT source_file, revision, revision_label, revision_status, revision_basis FROM project_files")}
    assert rows["point.docx"] == (None, "older", "inferred_order", "filename|mtime")
    assert rows["point_更新版.docx"] == (None, "newer", "inferred_order", "filename|mtime")   # revision stays NULL
    import csv
    with open(out / "database" / "project_files.csv", encoding="utf-8-sig", newline="") as f:
        csv_rows = list(csv.DictReader(f))
    assert {"revision", "revision_label", "revision_status", "revision_basis"} <= set(csv_rows[0])
