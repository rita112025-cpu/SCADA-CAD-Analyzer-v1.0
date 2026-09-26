"""Build immutable, incremental evidence snapshots from normalized tables only."""
import argparse
import json
import re
from pathlib import Path
from evidence_schema import VERSION, connect, identity, migrate, now
from name_normalizer import normalize_name

TABLES = ('engineering_objects', 'requirements', 'boq_items', 'documents', 'document_sections', 'clashes', 'cross_reference_results')
FIELDS = ('project_id source_file source_type file_hash revision source_location page section sheet row_number '
          'object_id cad_handle ifc_guid title content normalized_name evidence_level parser parser_version '
          'created_at metadata_json snapshot_id record_table record_id object_type system').split()


def nullable(value):
    return None if value is None or value == '' else value


def parts(text, size=1600):
    """Lossless bounded paragraph groups; no cross-page joins or rewriting."""
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind('\n', start + size // 2, end)
            if boundary > start: end = boundary + 1
        yield start, end, text[start:end]
        start = end


def content_for(table, row):
    if table == 'documents':
        return row.get('text', '') if row.get('status') != 'OCR_REQUIRED' else ''
    if table == 'requirements': return row.get('original_text') or row.get('requirement_text', '')
    if table == 'document_sections':
        return row.get('original_text') or row.get('text') or row.get('cells_json', '')
    # Object rows are formatted from existing values; blank fields remain blank.
    names = {
        'engineering_objects': ('object_type','name','layer','handle','guid','level','space','system','x','y','z','width','height','length','properties_json'),
        'boq_items': ('item_no','description','model','specification','quantity','unit','unit_price','amount','revision'),
        'clashes': ('clash_id','clash_name','status','object_a','object_b','distance','x','y','z'),
        'cross_reference_results': ('check_type','key','result','confidence','note','evidence_a','evidence_b'),
    }
    return '\n'.join(f'{key}: {row.get(key, "")}' for key in names[table])


def build(db, project_id='default', include_derived=False):
    migrate(db)
    db.row_factory = __import__('sqlite3').Row
    files = {r['source_file']: dict(r) for r in db.execute('SELECT * FROM project_files')}
    for table in TABLES:
        db.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_source ON {table}(source_file)')
    result = dict(built=0, skipped=0, chunks_added=0, rejected_files=[])
    with db:
        # Replace only active pointers. Historical chunks/snapshots remain immutable.
        previous = {r['source_file']: r['snapshot_id'] for r in db.execute('SELECT * FROM evidence_current WHERE project_id=?', (project_id,))}
        db.execute('DELETE FROM evidence_current WHERE project_id=?', (project_id,))
        for source, info in files.items():
            if info['status'] not in ('OK', 'OCR_REQUIRED') or not info['file_hash']:
                result['rejected_files'].append(source)
                continue
            records = []
            for table in TABLES:
                if table == 'cross_reference_results' and not include_derived: continue
                for rec in db.execute(f'SELECT rowid,payload_json FROM {table} WHERE source_file=? ORDER BY rowid', (source,)):
                    row = json.loads(rec['payload_json'])
                    if row.get('evidence_level', 'PARSED') == 'SOURCE': continue
                    if row.get('evidence_level') == 'DERIVED' and not include_derived: continue
                    if table == 'documents' and not row.get('text'): continue  # page, not duplicate hits
                    if table == 'document_sections' and row.get('source_type') == 'PDF': continue
                    records.append((table, rec['rowid'], row))
            # Preserve table rows as context, but do not duplicate BOQ/requirement paragraphs.
            located = {r.get('source_location') for t, _, r in records if t in ('boq_items','requirements')}
            records = [(t,i,r) for t,i,r in records if not (t == 'document_sections' and r.get('source_location') in located)]
            dependencies = []
            for table, _, row in records:
                if table == 'cross_reference_results':
                    for side in ('evidence_a','evidence_b'):
                        value = json.loads(row.get(side) or '{}')
                        file = value.get('source_file', '')
                        dependencies.append((file, files.get(file, {}).get('file_hash')))
            fingerprint = identity([records, dependencies])
            revision = nullable(info.get('revision'))
            snapshot_id = identity([project_id, source, info['file_hash'], VERSION, revision, fingerprint])
            if db.execute('SELECT 1 FROM evidence_build_state WHERE snapshot_id=?', (snapshot_id,)).fetchone():
                result['skipped'] += 1
            else:
                stamp = now()
                prior = previous.get(source)
                prior_row = db.execute('SELECT revision FROM evidence_snapshots WHERE snapshot_id=?', (prior,)).fetchone() if prior else None
                db.execute('INSERT INTO evidence_snapshots VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (snapshot_id,project_id,source,info['file_hash'],revision,prior_row[0] if prior_row else None,prior,VERSION,fingerprint,stamp))
                count = 0
                for table, record_id, row in records:
                    text = content_for(table, row)
                    if not text or not text.strip(): continue
                    source_type = row.get('source_type', info['source_type'])
                    location = {k: row[k] for k in ('source_location','handle','layer','x','y','z','guid','level','space','page','section','sheet','row_number','item_no','source_order','clash_id','object_a','object_b','table_index','pdf_page','printed_page') if row.get(k) not in (None, '')}
                    location.update(file=source, record_table=table, record_id=record_id)
                    original_location = row.get('source_location', '')
                    if source_type == 'DOCX':
                        match = re.search(r'body:(\d+)', original_location)
                        if match: location['body_index'] = int(match[1])
                    metadata = dict(original=row, locator=location, record_table=table, record_id=record_id,
                                    dependency_hashes=dependencies if table == 'cross_reference_results' else [],
                                    limitations=['Recorded derived result; not engineering confirmation'] if table == 'cross_reference_results' else [])
                    if table == 'cross_reference_results':
                        metadata.update(evidence_a=json.loads(row.get('evidence_a') or '{}'), evidence_b=json.loads(row.get('evidence_b') or '{}'), result=row.get('result'), confidence=row.get('confidence'))
                    # Semantic objects/items/clashes are one chunk each. Document text is bounded.
                    segments = parts(text) if table in ('documents','document_sections') else [(0,len(text),text)]
                    for offset, end, content in segments:
                        loc = dict(location, text_start=offset, text_end=end)
                        chunk_id = identity([snapshot_id,table,record_id,offset])
                        values = dict(project_id=project_id,source_file=source,source_type=source_type,file_hash=info['file_hash'],
                            revision=nullable(row.get('revision')) or revision,source_location=json.dumps(loc,ensure_ascii=False),
                            page=nullable(row.get('page')),section=nullable(row.get('section') or row.get('section_candidate')),
                            sheet=nullable(row.get('sheet')),row_number=nullable(row.get('row_number')),
                            object_id=nullable(row.get('object_id')),cad_handle=nullable(row.get('handle')),ifc_guid=nullable(row.get('guid')),
                            title=row.get('name') or row.get('description') or row.get('heading_candidate') or row.get('section') or row.get('clash_name') or table,
                            content=content,normalized_name=row.get('normalized_name') or normalize_name(row.get('name') or row.get('model'))['normalized_name'],
                            evidence_level='DERIVED' if table == 'cross_reference_results' else row.get('evidence_level','PARSED'),
                            parser='normalized:'+table,parser_version=VERSION,created_at=stamp,metadata_json=json.dumps(metadata,ensure_ascii=False),
                            snapshot_id=snapshot_id,record_table=table,record_id=record_id,object_type=nullable(row.get('object_type')),system=nullable(row.get('system')))
                        db.execute('INSERT INTO evidence_chunks(chunk_id,'+','.join(FIELDS)+') VALUES ('+','.join('?' for _ in range(len(FIELDS)+1))+')', [chunk_id]+[values[f] for f in FIELDS])
                        count += 1
                db.execute('INSERT INTO evidence_build_state VALUES (?,?,?,?,?,?)', (snapshot_id,source,info['file_hash'],VERSION,stamp,count))
                result['built'] += 1
                result['chunks_added'] += count
            db.execute('INSERT INTO evidence_current VALUES (?,?,?)', (project_id,source,snapshot_id))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database'); parser.add_argument('--project-id', default='default')
    parser.add_argument('--include-derived', action='store_true')
    args = parser.parse_args()
    db = connect(args.database, writable=True)
    try: print(json.dumps(build(db,args.project_id,args.include_derived),ensure_ascii=False,indent=2))
    finally: db.close()
