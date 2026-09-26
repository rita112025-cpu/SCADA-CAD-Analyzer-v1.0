from analyze_pdf import parse


def test_pdf_page_evidence(tmp_path, data_store, engineering_cfg):
    import fitz
    p = tmp_path / 'text.pdf'
    doc = fitz.open(); doc.new_page(); page = doc.new_page()
    page.insert_text((30, 40), 'RTU shall be installed. TRACK is not RACK.')
    doc.save(p); doc.close()
    assert parse(p, data_store, engineering_cfg) == 'OK'
    hits = [r for r in data_store.rows('documents') if r.get('keyword')]
    assert all(r['page'] == 2 and r['text_excerpt'] for r in hits)
    assert {r['keyword'] for r in hits} >= {'RTU', 'RACK'}


def test_scanned_pdf_requires_ocr(tmp_path, data_store, engineering_cfg):
    import fitz
    p = tmp_path / 'scan.pdf'
    doc = fitz.open(); page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10), False); pix.clear_with(255)
    page.insert_image(fitz.Rect(0, 0, 100, 100), pixmap=pix)
    doc.save(p); doc.close()
    assert parse(p, data_store, engineering_cfg) == 'OCR_REQUIRED'
    assert next(data_store.rows('documents'))['status'] == 'OCR_REQUIRED'
