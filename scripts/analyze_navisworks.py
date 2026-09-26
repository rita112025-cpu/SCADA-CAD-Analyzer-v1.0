"""Recognized Navisworks clash export dialects; never guess arbitrary XML."""
import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from html.parser import HTMLParser
from engineering_data import evidence, UnsupportedFormat, parser_cli


class ClashHTML(HTMLParser):
    """Read only tabular reports whose explicit columns identify clash objects."""
    def __init__(self, consume):
        super().__init__(convert_charrefs=True)
        self.consume = consume
        self.cells = []
        self.text = None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.cells = []
        if tag in ('td', 'th'): self.text = []
        if tag == 'br' and self.text is not None: self.text.append('\n')

    def handle_data(self, data):
        if self.text is not None: self.text.append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.text is not None:
            self.cells.append(''.join(self.text).strip()); self.text = None
        if tag == 'tr' and self.cells: self.consume(self.cells)


def html_report(path, store, cfg):
    aliases = cfg.get('navisworks_columns', {})
    names = {alias.casefold(): key for key, values in aliases.items() for alias in values + [key]}
    header = []
    count = 0
    def consume(cells):
        nonlocal header, count
        candidate = [names.get(c.casefold(), '') for c in cells]
        if {'clash_name', 'status', 'object_a', 'object_b'} <= set(candidate):
            header = candidate
        elif header and len(cells) == len(header):
            row = {key: value for key, value in zip(header, cells) if key}
            count += 1
            store.add('clashes', evidence(path, 'Navisworks', f'table_row:{count}', **row), 'navisworks/navis_clashes.csv')
    parser = ClashHTML(consume)
    with open(path, encoding='utf-8-sig') as f:
        for chunk in iter(lambda: f.read(65536), ''): parser.feed(chunk)
    parser.close()
    if not header: raise UnsupportedFormat('HTML lacks explicit clash name/status/object A/object B columns')
    return count


def parse(path, store, cfg):
    count = 0
    if Path(path).suffix.lower() in ('.html', '.htm'):
        count = html_report(path, store, cfg)
    elif Path(path).suffix.lower() == '.csv':
        with open(path, encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            if not {'clash_id', 'clash_name', 'object_a', 'object_b', 'status'} <= set(reader.fieldnames or []):
                raise UnsupportedFormat('Not a recognized clash CSV (canonical clash columns required)')
            for i, row in enumerate(reader, 2):
                store.add('clashes', dict(row, **evidence(path, 'Navisworks', f'row:{i}')), 'navisworks/navis_clashes.csv')
                count += 1
    else:
        # Disable DTD/entity expansion, including UTF-16 declarations.
        with open(path, 'rb') as f:
            tail = b''
            for chunk in iter(lambda: f.read(65536), b''):
                probe = (tail + chunk).replace(b'\x00', b'').upper()
                if b'<!DOCTYPE' in probe or b'<!ENTITY' in probe:
                    raise UnsupportedFormat('DTD/entity declarations are not supported')
                tail = chunk[-64:]
        recognized = False
        for event, el in ET.iterparse(path, events=('start', 'end')):
            el.tag = el.tag.rsplit('}', 1)[-1]
            if event == 'start' and el.tag == 'clashtests': recognized = True
            if event != 'end' or el.tag != 'clashresult': continue
            if not recognized: raise UnsupportedFormat('Missing Navisworks clashtests container')
            objects = el.findall('./clashobjects/clashobject')
            def obj(index):
                if index >= len(objects): return '', '', '', {}, 'UNKNOWN', None
                e = objects[index]
                props = {p.findtext('name', ''):p.findtext('value', '') for p in e.findall('.//objectattribute')}
                identity = next(((props[k], kind) for k,kind in [('GUID','GUID'),('GlobalId','GUID'),('Handle','HANDLE'),('Element ID','ELEMENT_ID')] if props.get(k)), (e.findtext('name', ''), 'NAME'))
                return identity[0], props.get('Discipline', ''), '/'.join(n.text or '' for n in e.findall('.//pathlink')), props, identity[1], props.get('Source File') or props.get('SourceFile')
            a, da, pa, ap, at, af = obj(0)
            b, db, pb, bp, bt, bf = obj(1)
            pos = el.find('./clashpoint/pos3f')
            def date(tag):
                node = el.find(f'./{tag}/date')
                return json.dumps(node.attrib) if node is not None else el.findtext(tag, '')
            row = evidence(path, 'Navisworks', f'clash:{count+1}', clash_id=el.get('guid', ''), clash_name=el.get('name', ''),
                status=el.get('status', ''), distance=el.get('distance', ''), object_a=a, object_b=b,
                discipline_a=da, discipline_b=db, path_a=pa, path_b=pb,
                object_a_type=at, object_b_type=bt, object_a_source=af, object_b_source=bf,
                x=pos.get('x', '') if pos is not None else '', y=pos.get('y', '') if pos is not None else '', z=pos.get('z', '') if pos is not None else '',
                properties_json=json.dumps([ap, bp], ensure_ascii=False), created_date=date('createddate'), updated_date=date('modifieddate'))
            store.add('clashes', row, 'navisworks/navis_clashes.csv')
            count += 1
            el.clear()
        if not recognized: raise UnsupportedFormat('Not a Navisworks Clash XML report')
    store.report('navisworks/navis_summary.csv', evidence(path, 'Navisworks', clashes=count))
    return 'OK'


if __name__ == '__main__':
    raise SystemExit(parser_cli('Navisworks'))
