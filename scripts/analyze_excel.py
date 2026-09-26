"""Read-only workbook/CSV extraction and explicit BOQ revision comparison."""
import csv
import json
import re
from collections import defaultdict
from itertools import chain, islice
from pathlib import Path
from engineering_data import evidence, parser_cli
from name_normalizer import normalize_name


def number(value):
    if value is None or str(value).strip() == '':
        return ''
    s = str(value).strip().replace(',', '')
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', s):
        return ''
    import pandas as pd
    return float(pd.to_numeric(s))


def header_key(value):
    return re.sub(r'[\s._-]+', '', str(value or '')).casefold()


def sheets(path):
    if Path(path).suffix.lower() == '.csv':
        # csv.reader streams rows and also supports ragged title/header rows.
        with open(path, encoding='utf-8-sig', newline='') as f:
            yield 'CSV', csv.reader(f)
    else:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
        try:
            for ws in wb.worksheets:
                yield ws.title, ws.iter_rows(values_only=True)
        finally:
            wb.close()


def parse(path, store, cfg):
    aliases = {header_key(a): key for key, names in cfg['excel_aliases'].items() for a in names + [key]}
    for sheet, iterator in sheets(path):
        iterator = iter(iterator)
        preview = list(islice(iterator, 40))
        scores = [len({aliases[header_key(v)] for v in row if header_key(v) in aliases}) for row in preview]
        head = max(range(len(scores)), key=scores.__getitem__) if scores else 0
        headers = [aliases.get(header_key(v), '') for v in preview[head]] if preview else []
        boq = 'quantity' in headers and bool({'description', 'model', 'item_no'} & set(headers))
        count = 0
        for rowno, values in enumerate(chain(preview, iterator), 1):
            if not any(v is not None and str(v).strip() for v in values):
                continue
            raw = evidence(path, 'Excel', f'{sheet}!row:{rowno}', section=sheet, kind='table_row', source_order=rowno,
                           cells_json=json.dumps(values, ensure_ascii=False, default=str))
            store.add('document_sections', raw, 'excel/excel_tables.csv')
            if not boq or rowno <= head + 1:
                continue
            data = {k: values[i] if i < len(values) and values[i] is not None else '' for i, k in enumerate(headers) if k}
            if not any(data.get(k) for k in ('item_no', 'description', 'model')):
                continue
            for k in ('quantity', 'unit_price', 'amount'):
                data[k] = number(data.get(k))
            store.add('boq_items', evidence(path, 'Excel', f'{sheet}!row:{rowno}', sheet=sheet, row_number=rowno, **data), 'excel/boq_items.csv')
            count += 1
        store.report('excel/excel_sheets.csv', evidence(path, 'Excel', sheet, sheet=sheet, header_row=head+1, is_boq=boq, items=count))
        store.report('excel/boq_summary.csv', evidence(path, 'Excel', sheet, sheet=sheet, items=count))
    return 'OK'


def compare(old, new):
    """Unique item/model identifiers first; ambiguous duplicate keys never forced."""
    def key(r):
        item, model = (normalize_name(r.get(k))['normalized_name'] for k in ('item_no', 'model'))
        return (item, model) if item or model else ('', normalize_name(r.get('description'))['normalized_name'])
    a, b = defaultdict(list), defaultdict(list)
    for r in old: a[key(r)].append(r)
    for r in new: b[key(r)].append(r)
    for k in sorted(a.keys() | b.keys()):
        left, right = a[k], b[k]
        if not any(k) or len(left) > 1 or len(right) > 1:
            status = ['MATCH_UNCERTAIN']
        elif not left: status = ['ADDED']
        elif not right: status = ['REMOVED']
        else:
            x, y = left[0], right[0]
            status = []
            for field, label in [('quantity','QUANTITY_CHANGED'), ('description','DESCRIPTION_CHANGED'), ('unit_price','PRICE_CHANGED'), ('amount','PRICE_CHANGED')]:
                if x.get(field, '') != y.get(field, '') and label not in status: status.append(label)
            status = status or ['UNCHANGED']
        yield dict(key=json.dumps(k), result='|'.join(status), evidence_a=json.dumps(left, ensure_ascii=False), evidence_b=json.dumps(right, ensure_ascii=False), evidence_level='DERIVED', source_type='Excel', source_file='|'.join(sorted({r['source_file'] for r in left+right})), source_location='explicit revision comparison')


if __name__ == '__main__':
    raise SystemExit(parser_cli('Excel'))
