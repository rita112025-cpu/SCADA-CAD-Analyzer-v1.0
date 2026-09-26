"""Revision metadata for files that look like versions of the same document.

Never invents a formal revision: `revision` stays NULL unless a source declares one (none is read here).
When several files of one family (same stem after removing version words, same extension) are analysed
together, an older/newer ORDER may be inferred from independent bases:
    filename   version words in the name (更新版 / updated / latest ... vs 舊版 / old ...)
    mtime      file modification time
    core_modified   docProps/core.xml dcterms:modified of Office files
Fields written to project_files:
    revision         always NULL here (formal revision label unknown)
    revision_label   older | newer | order_i_of_n | NULL
    revision_status  inferred_order | conflicting_order | unknown
    revision_basis   agreeing bases, e.g. 'filename|mtime'
A conflict between bases yields conflicting_order with NO label; a single file is 'unknown'."""
import re
import unicodedata
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

NEWER = re.compile(r"更新版|更新|新版|最新|修訂版|updated?|latest|newer|new|final", re.I)
OLDER = re.compile(r"舊版|初版|older|old|previous|prev|backup|draft", re.I)
VERSION = re.compile(r"(?<![a-z0-9])v\d+(?:\.\d+)*(?![a-z0-9])|\(\d+\)|copy", re.I)
BASES = ("filename", "mtime", "core_modified")


def _norm(name):
    return unicodedata.normalize("NFKC", name).casefold()


def family_key(path):
    p = Path(path)
    stem = _norm(p.stem)
    stem = VERSION.sub("", NEWER.sub("", OLDER.sub("", stem)))
    return (p.suffix.lower(), re.sub(r"[\s_\-.()\[\]]+", "", stem))


def name_rank(path):
    stem = _norm(Path(path).stem)
    newer, older = bool(NEWER.search(stem)), bool(OLDER.search(stem))
    return 1 if newer and not older else -1 if older and not newer else 0


def core_modified(path):
    if Path(path).suffix.lower() not in (".docx", ".xlsx", ".xlsm"):
        return None
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("docProps/core.xml").decode("utf-8", "replace")
        m = re.search(r"<dcterms:modified[^>]*>([^<]+)<", xml)
        return datetime.fromisoformat(m.group(1).replace("Z", "+00:00")).timestamp() if m else None
    except Exception:  # noqa: BLE001
        return None


def signals(path):
    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        mtime = None
    return dict(filename=name_rank(path), mtime=mtime, core_modified=core_modified(path))


def infer(paths):
    """{path: dict(revision, revision_label, revision_status, revision_basis)}"""
    unknown = dict(revision=None, revision_label=None, revision_status="unknown", revision_basis="")
    result = {p: dict(unknown) for p in paths}
    families = defaultdict(list)
    for p in paths:
        families[family_key(p)].append(p)
    for members in families.values():
        n = len(members)
        if n < 2:
            continue
        sig = {p: signals(p) for p in members}
        older = defaultdict(set)          # (i, j): bases saying members[i] is older than members[j]
        for i in range(n):
            for j in range(i + 1, n):
                for basis in BASES:
                    a, b = sig[members[i]][basis], sig[members[j]][basis]
                    if a is None or b is None or a == b:
                        continue
                    older[(i, j) if a < b else (j, i)].add(basis)
        conflict = any((j, i) in older for (i, j) in older)
        if conflict:
            bases = "|".join(b for b in BASES if any(b in v for v in older.values()))
            for p in members:
                result[p].update(revision_status="conflicting_order", revision_basis=bases)
            continue
        rank = {i: sum((j, i) in older for j in range(n) if j != i) for i in range(n)}
        if not older or len(set(rank.values())) != n:
            continue                      # nothing usable, or ties: leave as unknown
        bases = "|".join(b for b in BASES if any(b in v for v in older.values()))
        order = sorted(range(n), key=rank.get)
        for pos, i in enumerate(order):
            label = ("older", "newer")[pos] if n == 2 else f"order_{pos + 1}_of_{n}"
            result[members[i]].update(revision_label=label, revision_status="inferred_order", revision_basis=bases)
    return result
