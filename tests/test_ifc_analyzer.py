import pytest
from analyze_ifc import parse


def test_ifc_missing_properties_and_globalid(tmp_path, data_store, engineering_cfg):
    ifc = pytest.importorskip('ifcopenshell')
    p = tmp_path / 'model.ifc'; model = ifc.file(schema='IFC4')
    guid = ifc.guid.new()
    model.create_entity('IfcCableCarrierSegment', GlobalId=guid, Name='TRAY-X600', PredefinedType='CABLETRAYSEGMENT')
    model.create_entity('IfcSpace', GlobalId=ifc.guid.new())
    model.write(str(p))
    assert parse(p, data_store, engineering_cfg) == 'OK'
    rows = list(data_store.rows('engineering_objects'))
    assert any(r['guid'] == guid for r in rows)
    assert all(r['x'] is None for r in rows)
    assert any(r['name'] is None for r in rows)
    assert data_store.db.execute('SELECT COUNT(*) FROM engineering_objects WHERE system IS NULL').fetchone()[0] == len(rows)
