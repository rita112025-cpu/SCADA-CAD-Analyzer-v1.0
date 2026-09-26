import pytest
from analyze_navisworks import parse
from engineering_data import UnsupportedFormat

XML = '''<exchange><batchtest><clashtests><clashtest><clashresults>
<clashresult name="Clash 1" guid="c1" status="new" distance="-0.2">
<clashpoint><pos3f x="1" y="2" z="3"/></clashpoint>
<clashobjects><clashobject><objectattribute><name>GUID</name><value>g1</value></objectattribute></clashobject>
<clashobject><objectattribute><name>Handle</name><value>A2</value></objectattribute></clashobject></clashobjects>
</clashresult></clashresults></clashtest></clashtests></batchtest></exchange>'''


def test_clash_xml(tmp_path, data_store, engineering_cfg):
    p = tmp_path / 'clash.xml'; p.write_text(XML)
    assert parse(p, data_store, engineering_cfg) == 'OK'
    row = next(data_store.rows('clashes'))
    assert (row['object_a'], row['object_b'], row['x']) == ('g1', 'A2', '1')


@pytest.mark.parametrize('text', ['<root/>', '<!DOCTYPE x [<!ENTITY e "bad">]><x>&e;</x>'])
def test_unknown_xml_not_guessed(text, tmp_path, data_store, engineering_cfg):
    p = tmp_path / 'unknown.xml'; p.write_text(text)
    with pytest.raises(UnsupportedFormat): parse(p, data_store, engineering_cfg)


def test_html_clash_report(tmp_path, data_store, engineering_cfg):
    p = tmp_path / 'report.html'
    p.write_text('<html><table><tr><th>Clash Name</th><th>Status</th><th>Item 1</th><th>Item 2</th></tr><tr><td>Clash 1</td><td>new</td><td>RTU01</td><td>RACK01</td></tr></table></html>')
    assert parse(p, data_store, engineering_cfg) == 'OK'
    assert next(data_store.rows('clashes'))['object_a'] == 'RTU01'


def test_canonical_clash_csv(tmp_path, data_store, engineering_cfg):
    p = tmp_path / 'report.csv'
    p.write_text('clash_id,clash_name,object_a,object_b,status\nc1,Clash,RTU,RACK,new\n')
    assert parse(p, data_store, engineering_cfg) == 'OK'
    assert next(data_store.rows('clashes'))['clash_id'] == 'c1'
