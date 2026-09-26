"""Environment check -> environment_check.txt. Exit 3 if accoreconsole is missing."""
import platform
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_config, ROOT, log_error

AUTODESK_DIRS = (r"C:\Program Files\Autodesk", r"C:\Program Files (x86)\Autodesk")


def search_accore():
    """All accoreconsole.exe under the standard Autodesk folders (no guessing)."""
    found = []
    for base in AUTODESK_DIRS:
        b = Path(base)
        if b.exists():
            try:
                found += [str(p) for p in b.rglob("accoreconsole.exe")]
            except OSError:
                pass
    return sorted(set(found))


def accore_from_env_file():
    f = ROOT / "environment_check.txt"
    if f.exists():
        m = re.search(r"^accoreconsole:\s*(.+?)\s+exists=", f.read_text(encoding="utf-8"), re.M)
        if m:
            return m.group(1)
    return ""


def find_accore(cfg):
    """Returns (configured_or_recorded_path_or_'', candidates). Order: config, env file, search."""
    for c in (cfg.get("accoreconsole", ""), accore_from_env_file()):
        if c and Path(c).is_file():
            return c, [c]
    cands = search_accore()
    return (cands[0] if len(cands) == 1 else ""), cands


def check(cfg):
    """Returns dict(python, pip, ezdxf, accore, accore_ok, autocad, ok, lines)."""
    accore = Path(cfg.get("accoreconsole", ""))
    r = dict(python=sys.version.split()[0], pip="", ezdxf="", accore=str(accore),
             accore_ok=accore.is_file(), autocad="")
    try:  # in-process: spawning "pip --version" flashes a console window under pythonw
        from importlib.metadata import version
        r["pip"] = "pip " + version("pip")
    except Exception:  # noqa: BLE001
        r["pip"] = ""
    try:
        import ezdxf
        r["ezdxf"] = ezdxf.__version__
    except Exception:  # noqa: BLE001
        r["ezdxf"] = ""
    lines = [f"Windows: {platform.platform()}", f"Python: {r['python']} ({sys.executable})",
             f"pip: {r['pip'] or 'ERROR'}", f"ezdxf: {r['ezdxf'] or 'MISSING'}",
             f"accoreconsole: {accore} exists={r['accore_ok']}"]
    if r["accore_ok"]:
        full = (accore.parent / "acad.exe").exists()
        r["autocad"] = accore.parent.name
        lines.append("AutoCAD version: " + accore.parent.name +
                     (" (acad.exe present => full AutoCAD, not LT)" if full else ""))
    else:
        lines.append(f"AutoCAD version: NOT FOUND; candidates: {search_accore()}")
    r["ok"] = bool(r["accore_ok"] and r["ezdxf"] and r["pip"])
    lines.append("test status: " + ("OK" if r["ok"] else "FAIL"))
    r["lines"] = lines
    return r


def main():
    cfg = load_config()
    r = check(cfg)
    (ROOT / "environment_check.txt").write_text("\n".join(r["lines"]) + "\n", encoding="utf-8")
    print("\n".join(r["lines"]))
    if not r["ok"]:
        log_error(cfg, "env_check FAIL")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
