"""Page-at-a-time text evidence, without OCR."""
from engineering_data import evidence, parser_cli
import scada_rules


def parse(path, store, cfg):
    import pymupdf as fitz
    rules = scada_rules.build_rules(dict(cfg, keywords=cfg.get('document_keywords', cfg.get('keywords', []))))
    scanned = hits = pages = 0
    with fitz.open(path) as doc:
        for pages, page in enumerate(doc, 1):
            text = page.get_text()
            status = 'OK' if text.strip() else ('OCR_REQUIRED' if page.get_images() else 'EMPTY_PAGE')
            scanned += status == 'OCR_REQUIRED'
            lines = text.splitlines()
            heading = next((s for s in lines if s.strip()), '')
            table = any(len(s.split('  ')) > 2 for s in lines)
            row = evidence(path, 'PDF', f'page:{pages}', page=pages, text=text, heading_candidate=heading,
                           section_candidate=heading, table_candidate=table, status=status)
            store.add('documents', row, 'pdf/pdf_pages.csv')
            store.add('document_sections', evidence(path, 'PDF', f'page:{pages}', page=pages, section=heading, text=text, kind='section_candidate'), 'pdf/pdf_sections.csv')
            for line in lines:
                for m in scada_rules.find_matches(line, rules):
                    if m['confidence'] == scada_rules.EXCLUDED: continue
                    store.add('documents', evidence(path, 'PDF', f'page:{pages}', page=pages, section=heading, text_excerpt=line, keyword=m['keyword']), 'pdf/pdf_hits.csv')
                    hits += 1
    store.report('pdf/pdf_summary.csv', evidence(path, 'PDF', pages=pages, keyword_hits=hits, ocr_pages=scanned))
    return 'OCR_REQUIRED' if scanned else 'OK'


if __name__ == '__main__':
    raise SystemExit(parser_cli('PDF'))
