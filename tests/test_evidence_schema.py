import sqlite3
import pytest
from evidence_schema import migrate, INDEX_FIELDS


def test_additive_schema_and_indexes(data_store):
    data_store.add('engineering_objects', dict(name='RTU01'))
    migrate(data_store.db); migrate(data_store.db)
    assert next(data_store.rows('engineering_objects'))['name'] == 'RTU01'
    indexes = {r[1] for r in data_store.db.execute('PRAGMA index_list(evidence_chunks)')}
    assert {'idx_evidence_'+f for f in INDEX_FIELDS} <= indexes
    fields = {r[1] for r in data_store.db.execute('PRAGMA table_info(evidence_chunks)')}
    assert {'cad_handle','ifc_guid','page','sheet','row_number','file_hash','revision'} <= fields


def test_source_cannot_be_new_evidence(data_store):
    migrate(data_store.db)
    with pytest.raises(sqlite3.IntegrityError):
        data_store.db.execute("INSERT INTO evidence_chunks(chunk_id,project_id,source_file,source_type,file_hash,source_location,content,evidence_level,parser_version,created_at,snapshot_id,record_table,record_id) VALUES ('1','p','a','CAD','h','handle=1','x','SOURCE','1','now','s','engineering_objects',1)")
