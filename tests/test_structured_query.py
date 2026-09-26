import pytest
from evidence_builder import build
from structured_query import StructuredQuery


def test_structured_objects_and_missing(tmp_path,data_store):
    data_store.add('project_files',dict(source_file='a',source_type='IFC',file_hash='h',status='OK'))
    for name in ('RTU01','RTU-02','TRACK01'):
        data_store.add('engineering_objects',dict(source_file='a',source_type='IFC',name=name,properties_json='{}'))
    build(data_store.db)
    q=StructuredQuery(tmp_path/'project.db')
    assert len(q.find_objects(name='RTU'))==2
    assert len(q.find_missing_tags())==3 and len(q.find_missing_systems())==3
    assert len(q.find_by_normalized_name('RTU_01'))==1
    assert not q.find_objects(name="RTU' OR 1=1 --")
    with pytest.raises(ValueError): q.execute('sql',dict(sql='DELETE FROM engineering_objects'))
    with pytest.raises(ValueError): q.find_objects(limit=999999)
    with pytest.raises(ValueError): q.find_objects(untrusted_filter='x')
