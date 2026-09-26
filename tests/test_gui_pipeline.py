"""Tests for the GUI-facing pipeline and the tkinter app (smoke)."""
import csv
import hashlib
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
from common import load_config  # noqa: E402
import pipeline  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "sample.dwg"
CFG = load_config()


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def tk_root():
    """One Tk root for the whole module: creating/destroying several roots in one process makes
    Tcl intermittently fail to find its library files on this machine."""
    tk = pytest.importorskip("tkinter")
    root = tk.Tk()
    yield root
    root.destroy()


def _fresh(root):
    for w in root.winfo_children():
        w.destroy()


@pytest.fixture
def env(tmp_path):
    inp = tmp_path / "測試 資料"          # Chinese + space, as required
    (inp / "sub").mkdir(parents=True)
    shutil.copy(FIXTURE, inp / "圖面 01.dwg")
    shutil.copy(FIXTURE, inp / "sub" / "圖面 01.dwg")   # duplicate name
    (inp / "bad.dwg").write_text("not a dwg")
    cfg = dict(CFG, input_dir=str(inp), output_dir=str(tmp_path / "輸出 out"))
    return inp, cfg


def test_scan_readonly_counts(env):
    inp, _ = env
    before = sorted((p.name, p.stat().st_mtime) for p in inp.rglob("*"))
    r = pipeline.scan(inp)
    assert r["dwg"] == 3 and r["folders"] == 1
    assert r["chinese"] == 2 and r["spaces"] == 3 and r["duplicates"] == 1
    assert before == sorted((p.name, p.stat().st_mtime) for p in inp.rglob("*"))


def test_full_pipeline_chinese_paths_and_error_isolation(env):
    inp, cfg = env
    hashes = {p: sha(p) for p in inp.rglob("*.dwg")}
    logs = []
    prog = []
    s = pipeline.run_pipeline(cfg, {}, log=lambda l, m: logs.append((l, m)),
                              progress=lambda *a: prog.append(a))
    assert not s["fatal"] and not s["stopped"]
    assert (s["dwg"], s["ok"], s["failed"]) == (3, 2, 1)
    assert s["dxf"] == 2 and s["keyword_hits"] > 0 and 0 < s["unique_objects"] <= s["keyword_hits"]
    out = Path(cfg["output_dir"])
    assert (out / "dxf" / "圖面 01.dxf").exists() and (out / "dxf" / "sub" / "圖面 01.dxf").exists()
    assert (out / "logs" / "gui.log").exists() and (out / "logs" / "errors.log").exists()
    assert any(l == "ERROR" and "bad.dwg" in m for l, m in logs)
    assert any(l == "INFO" and "continue" in m for l, m in logs)   # batch went on after failure
    assert prog and prog[-1][0] == "SCADA"
    assert all(sha(p) == h for p, h in hashes.items())              # originals untouched
    with open(out / "csv" / "scada_hits.csv", encoding="utf-8-sig") as f:
        assert len(list(csv.DictReader(f))) == s["keyword_hits"]


def test_option_toggles(env):
    _, cfg = env
    s = pipeline.run_pipeline(cfg, dict(scada=False, csv=False, json=False, analyze=True))
    out = Path(cfg["output_dir"])
    assert not (out / "csv" / "file_index.csv").exists()
    assert not (out / "json").exists() or not list((out / "json").rglob("*.json"))
    assert not (out / "csv" / "scada_hits.csv").exists()
    assert s["ok"] == 2


def test_stop_before_start(env):
    _, cfg = env
    ev = threading.Event()
    ev.set()
    s = pipeline.run_pipeline(cfg, {}, stop_event=ev)
    assert s["stopped"] and s["ok"] == 0
    assert not list((Path(cfg["output_dir"]) / "dxf").rglob("*.dxf"))


def test_stop_during_accoreconsole(env):
    _, cfg = env
    ev = threading.Event()
    seen = []

    def progress(stage, i, n, cur):
        if stage == "DWG→DXF" and i == 2 and not seen:
            seen.append(1)
            threading.Timer(0.3, ev.set).start()   # fires while file 2 is inside accoreconsole
    t0 = time.time()
    s = pipeline.run_pipeline(cfg, {}, progress=progress, stop_event=ev)
    assert s["stopped"]
    assert time.time() - t0 < 60
    out = Path(cfg["output_dir"]) / "dxf"
    assert not list(out.rglob("*.dxf")) or len(list(out.rglob("*.dxf"))) <= 1
    import convert_single
    tmp = convert_single.safe_tmpdir(Path(cfg["output_dir"]) / "logs")
    assert " " not in str(tmp) and str(tmp).isascii()
    assert not list(tmp.glob("*.dxf"))


def test_fatal_when_accore_missing(env):
    _, cfg = env
    s = pipeline.run_pipeline(dict(cfg, accoreconsole=r"C:\nope\accoreconsole.exe"), {})
    assert s["fatal"] and s["ok"] == 0


def test_gui_smoke(env, tk_root):
    import app as appmod
    inp, cfg = env
    root = tk_root
    _fresh(root)
    if True:
        a = appmod.App(root)
        a.v_in.set(str(inp))
        a.v_out.set(cfg["output_dir"])
        deadline = time.time() + 60
        while not a.env_ok and time.time() < deadline:      # env check finished via queue
            root.update()
            time.sleep(0.05)
        assert a.env_ok and str(a.btn_start["state"]) == "normal"
        a._scan()
        while "找到 DWG：3" not in a.v_scan.get() and time.time() < deadline:
            root.update()
            time.sleep(0.05)
        assert "找到 DWG：3" in a.v_scan.get()
        a._start()
        assert str(a.btn_stop["state"]) == "normal"
        while a.summary is None and time.time() < deadline + 120:
            root.update()
            time.sleep(0.05)
        assert a.summary and a.summary["ok"] == 2 and a.summary["failed"] == 1
        assert "Completed with warnings" in a.v_result.get()   # 2 ok + 1 failed is not "failed"
        assert "bad.dwg" in a.v_result.get()
        assert str(a.btn_start["state"]) == "normal"


def test_gui_partial_failure_shows_warnings_not_total_failure(tk_root):
    import app as appmod
    root = tk_root
    _fresh(root)
    if True:
        a = appmod.App(root)
        a._on_done(dict(dwg=100, ok=99, failed=1, skipped=0, failed_files=["bad.dwg: DXF_INVALID x"],
                        analyze_failed=0, dxf=99, keyword_hits=5, unique_objects=3, suspect_texts=0,
                        elapsed=3.0, stopped=False, fatal=""))
        text = a.v_result.get()
        assert "Completed with warnings" in text and "中止" not in text
        assert "成功：99" in text and "失敗：1" in text and "跳過：0" in text
        assert "bad.dwg" in text
        a._on_done(dict(dwg=3, ok=3, failed=0, skipped=0, failed_files=[], analyze_failed=0, dxf=3,
                        keyword_hits=0, unique_objects=0, suspect_texts=0, elapsed=1.0, stopped=False,
                        fatal=""))
        assert "Completed with warnings" not in a.v_result.get()
