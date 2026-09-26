from cross_reference import compare_objects, run


def test_match_missing_uncertain():
    objects = [dict(name=n, source_type='CAD', source_file='drawing') for n in ('RTU01','UPS99','RACK02')]
    boq = [dict(model=n, source_file='boq') for n in ('RTU-01', 'RACK01')]
    rows = list(compare_objects(objects, boq))
    assert rows[0]['result'] == 'NORMALIZED_MATCH'
    assert rows[0]['compliance_status'] == 'NOT_EVALUATED'
    assert rows[1]['result'] == 'MISSING_B'
    assert rows[2]['result'] == 'UNCERTAIN' and rows[2]['confidence'] < 1
    assert all(r['evidence_level'] == 'DERIVED' for r in rows)


def test_requirements_and_clash_indexes(data_store, engineering_cfg):
    data_store.add('engineering_objects', dict(name='RTU-01', source_type='CAD', object_type='INSERT', source_file='a.dxf', handle='A2'))
    data_store.add('requirements', dict(keyword='RTU', requirement_text='RTU shall exist', source_file='a.docx'))
    data_store.add('clashes', dict(object_a='A2', object_b='UNKNOWN', source_file='clash.xml'))
    run(data_store, engineering_cfg)
    rows = list(data_store.rows('cross_reference_results'))
    assert any(r['check_type'] == 'CAD_KEYWORD_VS_REQUIREMENT' and r['result'] == 'RELATED' and r['compliance_status'] == 'INSUFFICIENT_EVIDENCE' for r in rows)
    assert any(r['check_type'] == 'CLASH_VS_OBJECT' and r['result'] == 'UNCERTAIN' for r in rows)  # bare CAD handle has no file scope
