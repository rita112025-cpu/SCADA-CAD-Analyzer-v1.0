"""Page-at-a-time text evidence, without OCR, with clause-level section tracking.

Sections follow the clause numbering used in specifications and cited by engineers:
    一、 -> (一) -> 1.        clause id e.g. 二(三)3, 四(十五)
The numbering state carries across pages in reading order. Lines repeated on most pages (running
headers / footers) are page furniture: they never start a clause and are not used as a page heading."""
import re
from collections import Counter

from engineering_data import evidence, parser_cli
import scada_rules

CN = "一二三四五六七八九十百"
L1 = re.compile(rf"^([{CN}]+)\s*、\s*(.*)$")
L2 = re.compile(rf"^[(（]([{CN}]+)[)）]\s*(.*)$")
L3 = re.compile(r"^(\d{1,2})\s*[.．、](?!\d)\s*(.*)$")
# Annex heading at line start, e.g. "附件A <title>", "附件B-1". Inside an annex the numbered
# lines are table-cell content, so clause numbering is not tracked there.
ANNEX = re.compile(r"^(附件|附表)\s*([A-Z](?:-\d+)?|\d+(?:-\d+)?)(?![A-Za-z0-9])\s*(.*)$")


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
                page_hits.append(evidence(path, 'PDF', f'page:{pageno}', page=pageno,
                                          section='' if is_furniture else tracker.clause_id,
                                          heading_candidate='(page header/footer)' if is_furniture else tracker.title_path,
                                          text_excerpt=line, keyword=m['keyword']))
        row = evidence(path, 'PDF', f'page:{pageno}', page=pageno, text=text, heading_candidate=heading,
                       section_candidate=page_section, section=page_section,
                       table_candidate=any(len(s.split('  ')) > 2 for s in lines), status=status)
        store.add('documents', row, 'pdf/pdf_pages.csv')
        store.add('document_sections', evidence(path, 'PDF', f'page:{pageno}', page=pageno, section=page_section,
                                                heading=heading, text=text, kind='page'), 'pdf/pdf_sections.csv')
        for h in page_hits:
            store.add('documents', h, 'pdf/pdf_hits.csv')
        hits += len(page_hits)
    for order, (cid, level, parent, title, pageno, body) in enumerate(clauses, 1):
        body_text = '\n'.join(body)
        store.add('document_sections', evidence(path, 'PDF', f'page:{pageno}/clause:{cid}', page=pageno, section=cid,
                                                section_id=cid, parent_section=parent, heading=title, level=level,
                                                kind='clause', source_order=order, text=body_text,
                                                original_text=body_text), 'pdf/pdf_sections.csv')
    store.report('pdf/pdf_summary.csv', evidence(path, 'PDF', pages=len(raw), keyword_hits=hits, ocr_pages=scanned,
                                                 clauses=len(clauses), furniture_lines=len(furniture)))
    return 'OCR_REQUIRED' if scanned else 'OK'


if __name__ == '__main__':
    raise SystemExit(parser_cli('PDF'))
