"""GUI-facing orchestration. No tkinter here; safe to run in a worker thread."""
import datetime
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import resolve, log_error
import env_check
import batch_convert
import analyze_dxf
import find_scada

DEFAULT_OPTS = dict(recursive=True, convert=True, analyze=True, scada=True,
                    csv=True, json=True, overwrite=False)


def scan(input_dir, recursive=True):
    """Read-only scan. Never touches AutoCAD or modifies files."""
    root = Path(input_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"input folder not found: {root}")
    it = root.rglob("*") if recursive else root.glob("*")
    dwgs, dxfs, size, folders = [], 0, 0, set()
    for p in it:
        try:
            if p.is_dir():
                folders.add(p)
            elif p.suffix.lower() == ".dwg":
                dwgs.append(p)
                size += p.stat().st_size
            elif p.suffix.lower() == ".dxf":
                dxfs += 1
        except OSError:
            continue
    names = {}
    for p in dwgs:
        names.setdefault(p.name.casefold(), []).append(p)
    return dict(
        dwg=len(dwgs), dxf=dxfs, size=size, folders=len(folders),
        chinese=sum(1 for p in dwgs if not p.name.isascii()),
        spaces=sum(1 for p in dwgs if " " in str(p)),
        duplicates=sum(1 for v in names.values() if len(v) > 1),
    )


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024


def fmt_duration(sec):
    sec = int(sec)
    return f"{sec // 60} 分 {sec % 60:02d} 秒"


def run_pipeline(cfg, opts, log=None, progress=None, stop_event=None):
    """Env check -> convert -> (validate inside convert) -> analyze -> scada -> summary.
    log(level, msg) ; progress(stage, i, n, current). Returns summary dict."""
    opts = {**DEFAULT_OPTS, **opts}
    cfg = dict(cfg, recursive=opts["recursive"], overwrite=opts["overwrite"])
    out = resolve(cfg, "output_dir")
    logs = out / "logs"
    summary = dict(dwg=0, ok=0, failed=0, skipped=0, failed_files=[], analyze_failed=0, dxf=0, keyword_hits=0, unique_objects=0, suspect_texts=0,
                   elapsed=0.0,
                   stopped=False, fatal="")
    t0 = time.time()

    def _log(level, msg):
        line = f"[{datetime.datetime.now():%H:%M:%S}] {level:<5} {msg}"
        try:
            logs.mkdir(parents=True, exist_ok=True)
            with open(logs / "gui.log", "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        if log:
            log(level, msg)

    def _prog(stage):
        return lambda i, n, cur: progress(stage, i, n, cur) if progress else None

    def stopped():
        return stop_event is not None and stop_event.is_set()

    def finish():
        summary["elapsed"] = time.time() - t0
        return summary

    _log("INFO", "environment check")
    env = env_check.check(cfg)
    if not env["ok"]:
        summary["fatal"] = "environment check failed: " + "; ".join(env["lines"][-3:])
        _log("ERROR", summary["fatal"])
        log_error(cfg, summary["fatal"])
        return finish()
    try:
        logs.mkdir(parents=True, exist_ok=True)
        (out / "dxf").mkdir(parents=True, exist_ok=True)
    except OSError as e:
        summary["fatal"] = f"output folder not writable: {e}"
        _log("ERROR", summary["fatal"])
        return finish()
    _log("OK", f"environment OK ({env['autocad']}, ezdxf {env['ezdxf']})")

    if opts["convert"]:
        n = len(batch_convert.list_dwg(cfg))
        _log("INFO", f"found {n} DWG")
        s = batch_convert.run(cfg, _log, _prog("DWG→DXF"), stop_event)
        summary.update(dwg=s["total"], ok=s["ok"], failed=s["failed"], skipped=s["skipped"])
        summary["failed_files"] += s["failed_files"]
        if s["fatal"]:
            summary["fatal"] = s["fatal"]
            _log("ERROR", s["fatal"])
            return finish()
        if s["stopped"]:
            summary["stopped"] = True
            _log("WARN", "stopped by user")
            return finish()
    summary["dxf"] = len(list((out / "dxf").rglob("*.dxf")))

    if opts["analyze"] and not stopped():
        _log("INFO", "analyzing DXF")
        a = analyze_dxf.run(cfg, opts["csv"], opts["json"], _log, _prog("Analyze"), stop_event)
        if a["failed"]:
            _log("WARN", f"{a['failed']} DXF failed to analyze")
        summary["analyze_failed"] = a["failed"]
        summary["failed_files"] += [f"(analyze) {x}" for x in a["failed_files"]]
        summary["suspect_texts"] = a["suspect"]
        summary["stopped"] |= a["stopped"]
    if opts["scada"] and not stopped():
        _log("INFO", "SCADA keyword search")
        r = find_scada.run(cfg, _log, _prog("SCADA"), stop_event)
        summary["keyword_hits"] = r["hits"]
        summary["unique_objects"] = r["objects"]
        summary["failed_files"] += [f"(search) {x}" for x in r["failed_files"]]
        summary["stopped"] |= r["stopped"]
        _log("OK", f"Keyword Hits: {r['hits']}  Unique Matched Objects: {r['objects']}")
    if stopped():
        summary["stopped"] = True
        _log("WARN", "stopped by user")
    elif summary["failed_files"]:
        _log("WARN", f"Completed with warnings: {len(summary['failed_files'])} failure(s)")
        for x in summary["failed_files"]:
            _log("WARN", f"  failed: {x}")
    else:
        _log("OK", "done")
    return finish()
