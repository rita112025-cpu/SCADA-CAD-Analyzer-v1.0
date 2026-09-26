"""Page-at-a-time text evidence, without OCR, with clause-level section tracking.

Sections follow the clause numbering used in specifications and cited by engineers:
    一、 -> (一) -> 1.        clause id e.g. 二(三)3, 四(十五)
The numbering state carries across pages in reading order. Lines repeated on most pages (running
headers / footers) are page furniture: they never start a clause and are not used as a page heading."""
import re
from collections import Counter
from pathlib import Path

import json

from engineering_data import evidence, parser_cli
import pdf_boq
import scada_rules

CN = "一二三四五六七八九十百"
L1 = re.compile(rf"^([{CN}]+)\s*、\s*(.*)$")
L2 = re.compile(rf"^[(（]([{CN}]+)[)）]\s*(.*)$")
L3 = re.compile(r"^(\d{1,2})\s*[.．、](?!\d)\s*(.*)$")
# Annex heading at line start, e.g. "附件A <title>", "附件B-1". Inside an annex the numbered
# lines are table-cell content, so clause numbering is not tracked there.
ANNEX = re.compile(r"^(附件|附表)\s*([A-Z](?:-\d+)?|\d+(?:-\d+)?)(?![A-Za-z0-9])\s*(.*)$")


# Printed page label read from the page itself (never computed from the physical page number):
# footer/header band blocks such as "附錄C-9", "C-8", "- 3 -", "第 3 頁", "Page 3", "12".
LABEL = re.compile(r"(?:第\s*\d{1,4}\s*頁|(?:page|p\.?)\s*\d{1,4}|[-–—]\s*\d{1,4}\s*[-–—]"
                   r"|[^\W\d_]{1,8}\s*[-–]\s*\d{1,4}|[^\W\d_]{1,8}\s*\d{1,4}|\d{1,4}(?:\s*/\s*\d{1,4})?)", re.I)
BAND = 0.12


def printed_page_label(blocks, height):
    """Printed page label of one page, or None. blocks: (x0, y0, x1, y1, text, ...) from PyMuPDF.
    Footer is preferred; several different candidates in the same band mean ambiguity -> None."""
    def candidates(pick):
        found = []
        for b in blocks:
            text = re.sub(r"\s+", " ", b[4]).strip()
            if text and len(text) <= 14 and pick(b) and LABEL.fullmatch(text) and text not in found:
                found.append(text)
        return found
    for band in (lambda b: b[1] >= height * (1 - BAND), lambda b: b[3] <= height * BAND):
        found = candidates(band)
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            return None
    return None


def citation(pdf_page, printed_page, section):
    """e.g. 'PDF p.9 / Printed 附錄C-8 / § 四(十五)'; parts that are unknown are omitted."""
    parts = [f"PDF p.{pdf_page}"]
    if printed_page:
        parts.append(f"Printed {printed_page}")
    if section:
        parts.append(f"§ {section}")
    return " / ".join(parts)


def furniture_lines(pages):
    """Stripped lines that appear on at least half of the pages (and on >= 3 pages)."""
    if len(pages) < 3:
        return set()
    counts = Counter(s for lines in pages for s in {l.strip() for l in lines if l.strip()})
    return {s for s, n in counts.items() if n >= 3 and n * 2 >= len(pages)}


class ClauseTracker:
    def __init__(self):
        self.l1 = self.l2 = self.l3 = None      # (number, title)
        self.annex = None                       # (label, title)

    def feed(self, line):
        """Update state from a line; returns True if the line starts a clause or an annex."""
        s = line.strip()
        m = ANNEX.match(s)
        if m:
            self.annex, self.l1, self.l2, self.l3 = (m[1] + m[2], m[3]), None, None, None
            return True
        if self.annex:
            return False
        m = L1.match(s)
        if m:
            self.l1, self.l2, self.l3 = (m[1], m[2]), None, None
            return True
        m = L2.match(s)
        if m and self.l1:
            self.l2, self.l3 = (m[1], m[2]), None
            return True
        m = L3.match(s)
        if m and self.l1:
            self.l3 = (m[1], m[2])
            return True
        return False

    @property
    def clause_id(self):
        if self.annex:
            return self.annex[0]
        if not self.l1:
            return ""
        return self.l1[0] + (f"({self.l2[0]})" if self.l2 else "") + (self.l3[0] if self.l3 else "")

    @property
    def level(self):
        return 1 if self.annex else 3 if self.l3 else 2 if self.l2 else 1 if self.l1 else 0

    @property
    def title_path(self):
        if self.annex:
            return f"{self.annex[0]} {self.annex[1]}".strip()
        parts = []
        if self.l1:
            parts.append(f"{self.l1[0]}、{self.l1[1]}")
        if self.l2:
            parts.append(f"({self.l2[0]}) {self.l2[1]}")
        if self.l3:
            parts.append(f"{self.l3[0]}. {self.l3[1]}")
        return " / ".join(parts)

    @property
    def parent_id(self):
        if self.l3:
            return self.l1[0] + (f"({self.l2[0]})" if self.l2 else "")
        if self.l2:
            return self.l1[0]
        return ""


def parse(path, store, cfg):
    import pymupdf as fitz
    rules = scada_rules.build_rules(dict(cfg, keywords=cfg.get('document_keywords', cfg.get('keywords', []))))
    with fitz.open(path) as doc:
        raw = [(page.get_text(), bool(page.get_images())) for page in doc]
        labels = [printed_page_label(page.get_text('blocks'), page.rect.height) for page in doc]
    # a "label" identical on many pages is a constant (year, code), not a page number
    repeated = {v for v, n in Counter(l for l in labels if l).items() if n >= 3 and n * 2 >= len(labels)}
    labels = [None if l in repeated else l for l in labels]
    page_lines = [text.splitlines() for text, _ in raw]
    furniture = furniture_lines(page_lines)
    tracker = ClauseTracker()
    clauses = []                                  # [clause_id, level, parent, title, page, lines]
    scanned = hits = 0
    for pageno, ((text, has_images), lines) in enumerate(zip(raw, page_lines), 1):
        status = 'OK' if text.strip() else ('OCR_REQUIRED' if has_images else 'EMPTY_PAGE')
        scanned += status == 'OCR_REQUIRED'
        content = [l for l in lines if l.strip() and l.strip() not in furniture]
        heading = content[0].strip() if content else ''
        page_section = tracker.clause_id              # clause active where this page begins
        printed = labels[pageno - 1]
        page_hits = []
        for line in lines:
            is_furniture = line.strip() in furniture
            if not is_furniture and tracker.feed(line):
                page_section = page_section or tracker.clause_id   # page began before any clause
                clauses.append([tracker.clause_id, tracker.level, tracker.parent_id, tracker.title_path,
                                pageno, []])
            if clauses and not is_furniture and line.strip():
                clauses[-1][5].append(line)
            for m in scada_rules.find_matches(line, rules):
                if m['confidence'] == scada_rules.EXCLUDED:
                    continue
                sec = '' if is_furniture else tracker.clause_id
                page_hits.append(evidence(path, 'PDF', f'page:{pageno}', page=pageno, pdf_page=pageno,
                                          printed_page=printed, citation=citation(pageno, printed, sec),
                                          section=sec,
                                          heading_candidate='(page header/footer)' if is_furniture else tracker.title_path,
                                          text_excerpt=line, keyword=m['keyword']))
        row = evidence(path, 'PDF', f'page:{pageno}', page=pageno, pdf_page=pageno, printed_page=printed,
                       citation=citation(pageno, printed, page_section), text=text, heading_candidate=heading,
                       section_candidate=page_section, section=page_section,
                       table_candidate=any(len(s.split('  ')) > 2 for s in lines), status=status)
        store.add('documents', row, 'pdf/pdf_pages.csv')
        store.add('document_sections', evidence(path, 'PDF', f'page:{pageno}', page=pageno, pdf_page=pageno,
                                                printed_page=printed, citation=citation(pageno, printed, page_section),
                                                section=page_section, heading=heading, text=text, kind='page'),
                  'pdf/pdf_sections.csv')
        for h in page_hits:
            store.add('documents', h, 'pdf/pdf_hits.csv')
        hits += len(page_hits)
    for order, (cid, level, parent, title, pageno, body) in enumerate(clauses, 1):
        body_text = '\n'.join(body)
        printed = labels[pageno - 1]
        store.add('document_sections', evidence(path, 'PDF', f'page:{pageno}/clause:{cid}', page=pageno,
                                                pdf_page=pageno, printed_page=printed,
                                                citation=citation(pageno, printed, cid), section=cid,
                                                section_id=cid, parent_section=parent, heading=title, level=level,
                                                kind='clause', source_order=order, text=body_text,
                                                original_text=body_text), 'pdf/pdf_sections.csv')
    boq = store_boq_rows(path, store, cfg, labels)
    store.report('pdf/pdf_summary.csv', evidence(path, 'PDF', pages=len(raw), keyword_hits=hits, ocr_pages=scanned,
                                                 clauses=len(clauses), furniture_lines=len(furniture),
                                                 boq_status=boq['status'], boq_rows=boq['rows'],
                                                 boq_skipped=boq['skipped']))
    if boq['status'] == 'SKIPPED_DEPENDENCY' and cfg.get('pdf_boq_tables') == 'required':
        return 'SKIPPED_DEPENDENCY'
    return 'OCR_REQUIRED' if scanned else 'OK'


def store_boq_rows(path, store, cfg, labels):
    """BOQ table rows -> the existing boq_items table (+ report csv). Rebuildable: earlier rows of the same
    source are removed first, so a re-run never leaves stale or duplicate rows.
    cfg["pdf_boq_tables"]: "auto" (default) | "required" | "off". Without pdfplumber: status SKIPPED_DEPENDENCY;
    the PDF text evidence is still produced."""
    mode = cfg.get('pdf_boq_tables', 'auto')
    result = dict(status='OFF', rows=0, skipped=0)
    if mode == 'off':
        return result
    try:
        rows, skipped = pdf_boq.extract_boq_rows(path, cfg.get('pdf_boq_aliases'))
    except ImportError:
        return dict(status='SKIPPED_DEPENDENCY', rows=0, skipped=0)
    store.clear_source(str(Path(path).resolve()), 'boq_items', ('pdf/boq_items.csv',))
    store.clear_source(str(Path(path).resolve()), None, ('pdf/boq_skipped.csv',))
    for r in rows:
        printed = labels[r['page'] - 1] if r['page'] - 1 < len(labels) else None
        loc = f"page:{r['page']}/table:{r['table']}/row:{r['row']}"
        store.add('boq_items', evidence(
            path, 'PDF', loc, page=r['page'], pdf_page=r['page'], printed_page=printed, table_index=r['table'],
            row_number=r['row'], sheet=f"page {r['page']} table {r['table']}", item_no=r['item_no'],
            description=r['description'], specification=r['spec'], unit=r['unit'],
            quantity='' if r['qty'] is None else r['qty'], quantity_text=r['qty_text'], remarks=r['remarks'],
            tags=' '.join(r['tags']), parse_warnings_json=json.dumps(r['parse_warnings'], ensure_ascii=False),
            citation=citation(r['page'], printed, f"table {r['table']} row {r['row']}")), 'pdf/boq_items.csv')
    for k in skipped:
        loc = f"page:{k['page']}/table:{k['table']}" + (f"/row:{k['row']}" if k['row'] else '')
        store.report('pdf/boq_skipped.csv', evidence(path, 'PDF', loc, page=k['page'], table_index=k['table'],
                                                     row_number=k['row'] or '', reason=k['reason'],
                                                     cells_json=json.dumps(k['cells'], ensure_ascii=False)))
    return dict(status='OK' if rows else 'NO_BOQ_ROWS', rows=len(rows), skipped=len(skipped))


if __name__ == '__main__':
    raise SystemExit(parser_cli('PDF'))
