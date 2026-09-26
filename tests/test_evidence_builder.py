import json
from evidence_builder import build


def seed(store):
    store.add('project_files',dict(source_file='source',source_type='DXF',file_hash='a'*64,status='OK'))
    store.add('engineering_objects',dict(source_file='source',source_type='CAD',source_location='A1',handle='A1',name='RTU-01',layer='SCADA',x=1,evidence_level='PARSED'))


def test_incremental_and_history(data_store):
    seed(data_store)
    a=build(data_store.db); assert a['chunks_added']==1
    chunk=data_store.db.execute('SELECT * FROM evidence_chunks').fetchone()
    assert chunk['cad_handle']=='A1' and chunk['file_hash']=='a'*64 and chunk['revision'] is None
    assert json.loads(chunk['source_location'])['layer']=='SCADA'
    assert build(data_store.db)['skipped']==1
    data_store.db.execute("UPDATE project_files SET file_hash=?",('b'*64,))
    assert build(data_store.db)['chunks_added']==1
    assert data_store.db.execute('SELECT count(*) FROM evidence_chunks').fetchone()[0]==2
    assert data_store.db.execute('SELECT count(*) FROM evidence_snapshots WHERE previous_snapshot_id IS NOT NULL').fetchone()[0]==1


def test_locations_and_no_ocr_or_source(data_store):
    seed(data_store)
    for table,row in [('engineering_objects',dict(source_type='IFC',guid='aBcD',name='Tray')),('boq_items',dict(source_type='Excel',sheet='Equipment',row_number=37,item_no='01',description='RTU')),('documents',dict(source_type='PDF',page=5,section='C',text='弱電線槽淨距')),('documents',dict(source_type='PDF',page=6,status='OCR_REQUIRED',text='')),('document_sections',dict(source_type='DOCX',source_location='body:3',text='shall preserve this')),('documents',dict(source_type='PDF',text='NOT SOURCE',evidence_level='SOURCE'))]:
        data_store.add(table,dict(source_file='source',**row))
    build(data_store.db)
    chunks=list(data_store.db.execute('SELECT * FROM evidence_chunks'))
    assert len(chunks)==5
    assert any(c['ifc_guid']=='aBcD' for c in chunks)
    assert any(c['page']==5 and c['section']=='C' for c in chunks)
    assert any(c['sheet']=='Equipment' and c['row_number']==37 for c in chunks)
    assert not any('NOT SOURCE' in c['content'] for c in chunks)


def test_derived_opt_in_retains_both_sides(data_store):
    seed(data_store)
    data_store.add('cross_reference_results',dict(source_file='source',source_type='CrossReference',result='UNCERTAIN',confidence=.3,evidence_a='{"handle":"1"}',evidence_b='{"item_no":"2"}',evidence_level='DERIVED'))
    build(data_store.db)
    assert data_store.db.execute("SELECT count(*) FROM evidence_chunks WHERE evidence_level='DERIVED'").fetchone()[0]==0
    build(data_store.db,include_derived=True)
    c=data_store.db.execute("SELECT * FROM evidence_chunks WHERE evidence_level='DERIVED'").fetchone()
    assert json.loads(c['metadata_json'])['evidence_a']['handle']=='1'
