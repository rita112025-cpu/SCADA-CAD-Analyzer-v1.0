"""BOQ row extraction from PDF tables (ported from the evidence-first BOQ analyzer, logic only).

Ported rules
  * every BOQ row is located by page + table + row (1-based, as the table is read);
  * a header is valid only inside the table that contains it; the single allowed carry-over is to the FIRST
    table of the next page, and only when the column count is identical (a continued table);
  * a row whose column count differs from the active header is never forced into it: it is reported as skipped;
  * a quantity that is not a plain number keeps its raw text and gets a parse warning (never guessed);
  * nothing is dropped silently: skipped rows / tables are returned with the reason.
Not ported: the evidence-first SQLite schema, `engineering_entities`, its citation system. Rows are handed to the
existing `boq_items` table by analyze_pdf.

Optional dependency: pdfplumber (requirements-pdf-tables.txt)."""
import re

# header aliases (casefolded, whitespace removed). Overridable with config["pdf_boq_aliases"].
DEFAULT_ALIASES = {
    "item_no": ["項次", "項目編號", "編號", "item", "itemno", "item no", "no", "no.", "s/n", "序號"],
    "description": ["說明", "品名", "項目", "工作項目", "名稱", "物件名稱", "品名規格", "description", "item description", "設備名稱"],
    "spec": ["規格", "型式", "規範", "specification", "spec", "model"],
    "unit": ["單位", "unit", "uom"],
    "qty": ["數量", "qty", "qty.", "quantity"],
    "remarks": ["備註", "remarks", "remark", "note", "notes"],
}
# '項目' is often the item-number column; it only serves as the description when no other name column exists.
WEAK_DESCRIPTION = {"項目"}
SUMMARY_PREFIXES = ("小計", "合計", "總計", "總價", "總工程款", "含稅", "稅額", "營業稅", "加值型營業稅")
SUMMARY_EN = re.compile(r"^(sub-?total|grand total|total)\s*[:：]?$", re.I)   # exact only: 'Total station' is an item
TAG_RE = re.compile(r"\b[A-Z]{2,6}[-_]\d[\w-]*\b")
NUM_RE = re.compile(r"^-?\d[\d,]*(\.\d+)?$")
THOUSANDS_RE = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")


def _norm(s):
    return re.sub(r"\s+", "", (s or "").lower())


def _clean(cell):
    return re.sub(r"\s+", " ", cell).strip() if cell else ""


def map_header(row, aliases=None):
    """{field: column index} when the row is a BOQ header (needs at least description and qty), else None."""
    aliases = aliases or DEFAULT_ALIASES
    lookup = {f: {_norm(a) for a in names} for f, names in aliases.items()}
    found, weak = {}, None
    for idx, cell in enumerate(row):
        n = _norm(cell)
        if not n:
            continue
        for field, names in lookup.items():
            if n in names:
                if field == "description" and n in WEAK_DESCRIPTION:
                    weak = idx if weak is None else weak
                elif field not in found:
                    found[field] = idx
                break
    if weak is not None:
        found.setdefault("description" if "description" not in found else "item_no", weak)
    return found if "description" in found and "qty" in found else None


def parse_qty(text):
    """Plain numbers only. A space touching a thousands comma ('1 ,806', a PDF text-layer artifact) is restored;
    a space between digits ('8 00') is ambiguous and stays unparsed."""
    t = (text or "").strip()
    if NUM_RE.match(t):
        return float(t.replace(",", ""))
    compact = re.sub(r"\s*,\s*", ",", t)
    if compact != t and THOUSANDS_RE.match(compact):
        return float(compact.replace(",", ""))
    return None


def _is_summary(desc):
    return re.sub(r"\s+", "", desc).startswith(SUMMARY_PREFIXES) or bool(SUMMARY_EN.match(desc.strip()))


def rows_from_tables(pages, aliases=None):
    """pages: iterable of (page_no, [table, ...]) where a table is a list of rows (list of cell strings).
    Returns (rows, skipped). Pure function: no PDF library needed, so it is unit-testable."""
    rows, skipped = [], []
    carry = None                                  # (header map, ncols) from the last table of the previous page
    for page_no, tables in pages:
        header = None
        for table_no, table in enumerate(tables, 1):
            header = carry if table_no == 1 else None      # carry-over: first table of the next page only
            table_has_header = False
            pending = []                                   # rows seen before any header in this table
            for r_idx, raw in enumerate(table, 1):
                cells = [_clean(c) for c in raw]
                if not any(cells):
                    continue
                hm = map_header(cells, aliases)
                if hm:                                     # a (re)printed header always starts a new scope
                    header, table_has_header = (hm, len(cells)), True
                    for p in pending:
                        skipped.append(dict(page=page_no, table=table_no, row=p[0], reason="row before the BOQ header",
                                            cells=p[1]))
                    pending = []
                    continue
                if header is None:
                    pending.append((r_idx, cells))
                    continue
                hmap, ncols = header
                if len(cells) != ncols:
                    skipped.append(dict(page=page_no, table=table_no, row=r_idx,
                                        reason=f"column count {len(cells)} != header {ncols}", cells=cells))
                    continue
                get = lambda f: cells[hmap[f]] if f in hmap else ""
                desc = get("description")
                if not desc:
                    skipped.append(dict(page=page_no, table=table_no, row=r_idx, reason="empty description", cells=cells))
                    continue
                if _is_summary(desc):
                    skipped.append(dict(page=page_no, table=table_no, row=r_idx, reason="summary row (subtotal/total)", cells=cells))
                    continue
                ids = [get(f) for f in ("item_no", "unit", "qty") if f in hmap]
                if len(ids) >= 2 and not any(ids):
                    skipped.append(dict(page=page_no, table=table_no, row=r_idx,
                                        reason="heading row (no item no, unit or quantity)", cells=cells))
                    continue
                qty_text = get("qty")
                qty = parse_qty(qty_text)
                if qty is not None:
                    warnings = []
                elif re.fullmatch(r"[\d\s,.]+", qty_text) and re.search(r"\d\s+\d", qty_text):
                    warnings = [f"quantity has a space inside the number; not restored: {qty_text!r}"]
                else:
                    warnings = [f"quantity is not a plain number: {qty_text!r}"]
                tags = TAG_RE.findall(" ".join([desc, get("spec"), get("remarks")]))
                rows.append(dict(page=page_no, table=table_no, row=r_idx, item_no=get("item_no"), description=desc,
                                 spec=get("spec"), unit=get("unit"), qty=qty, qty_text=qty_text,
                                 remarks=get("remarks"), tags=tags, parse_warnings=warnings))
            if pending and not table_has_header and header is None:
                # a table that never had a BOQ header: one entry for the table, not one per row
                skipped.append(dict(page=page_no, table=table_no, row=None, reason="table has no BOQ header (not a BOQ table)",
                                    cells=[f"{len(pending)} rows"]))
        carry = header                                    # last table's header may continue on the next page
    return rows, skipped


def extract_pdf_tables(pdf_path):
    """[(page_no, [table, ...])] via pdfplumber. Raises ImportError when pdfplumber is not installed."""
    import pdfplumber
    out = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            out.append((page_no, page.extract_tables()))
    return out


def extract_boq_rows(pdf_path, aliases=None):
    return rows_from_tables(extract_pdf_tables(pdf_path), aliases)
