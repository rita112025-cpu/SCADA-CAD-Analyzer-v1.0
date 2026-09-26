from evidence_builder import build
from evidence_search import index_evidence, search_fts


def test_fts_chinese_and_metadata(tmp_path,data_store):
    for name,rev,text in [('a','A','附錄 C 規定弱電線槽淨距應保留三百毫米。'),('b','B','弱電線槽只供參考')]:
        data_store.add('project_files',dict(source_file=name,source_type='PDF',file_hash=name,revision=rev,status='OK'))
        data_store.add('documents',dict(source_file=name,source_type='PDF',page=5,text=text))
    build(data_store.db,project_id='p')
    assert index_evidence(data_store.db)==2
    assert index_evidence(data_store.db)==0
    found=search_fts(tmp_path/'project.db','弱電線槽',project_id='p',revision='A',source_type='PDF')
    assert len(found)==1 and found[0]['page']==5 and found[0]['evidence_level']=='PARSED'
    assert not search_fts(tmp_path/'project.db','弱電線槽',source_type='IFC')
    assert search_fts(tmp_path/'project.db','淨距')[0]['source_file']=='a'
