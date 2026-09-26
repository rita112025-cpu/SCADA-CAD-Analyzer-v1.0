"""Shared evidence schema and streaming SQLite/CSV persistence."""
import csv
import hashlib
import json
import sqlite3
from pathlib import Path
from name_normalizer import normalize_name

COMMON = 'source_file source_type source_location evidence_level'.split()
SCHEMA = {
    'project_files': 'file_id revision revision_label revision_status revision_basis file_hash parsed_at status error',
    'engineering_objects': 'object_id object_type name raw_name normalized_name system layer level space guid handle x y z width height length properties_json specification boq_compare_eligible comparison_role tag',
    'requirements': 'requirement_id section page requirement_text original_text keyword category responsible_party status requirement_confidence subject table_index row_number column_headers_json row_context_json merged_cells_json requirement_fragments_json',
    'boq_items': 'sheet row_number item_no description model specification quantity unit unit_price amount revision remarks system location station floor raw_name normalized_name page pdf_page printed_page table_index quantity_text parse_warnings_json tags citation',
    'documents': 'document_id page text heading_candidate section_candidate table_candidate status keyword text_excerpt section pdf_page printed_page citation',
    'document_sections': 'section_id section parent_section heading level kind source_order page text original_text cells_json pdf_page printed_page citation',
    'clashes': 'clash_id clash_name discipline_a discipline_b object_a object_b status distance x y z path_a path_b properties_json created_date updated_date object_a_type object_b_type object_a_source object_b_source',
    'cross_reference_results': 'check_type source_a source_b key value_a value_b result confidence evidence_a evidence_b note match_basis compliance_status specification_conflicts_json candidate_count',
}
SCHEMA = {k: COMMON + v.split() for k, v in SCHEMA.items()}


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def evidence(path, source_kind, source_position='', **values):
    return dict(source_file=str(Path(path).resolve()), source_type=source_kind,
                source_location=str(source_position), evidence_level='PARSED', **values)


class UnsupportedFormat(ValueError):
    pass


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        for table, fields in SCHEMA.items():
            self.db.execute(f'CREATE TABLE IF NOT EXISTS {table} (' + ','.join(f'"{f}" TEXT' for f in fields) + ', payload_json TEXT)')
            existing={r[1] for r in self.db.execute(f'PRAGMA table_info({table})')}
            for field in fields:
                if field not in existing: self.db.execute(f'ALTER TABLE {table} ADD COLUMN "{field}" TEXT')
        self.db.execute('CREATE TABLE IF NOT EXISTS exports (report TEXT, payload_json TEXT)')
        self.db.execute('CREATE INDEX IF NOT EXISTS idx_exports_report ON exports(report)')
        for field in ('normalized_name', 'source_type', 'object_type', 'system'):
            self.db.execute(f'CREATE INDEX IF NOT EXISTS idx_objects_{field} ON engineering_objects({field})')
        self.db.execute('CREATE INDEX IF NOT EXISTS idx_boq_name ON boq_items(normalized_name)')

    def clear_source(self, source_file, table, reports=()):
        """Remove rows previously derived from one source (table rows and report rows) so a parser can rebuild."""
        if table:
            self.db.execute(f'DELETE FROM {table} WHERE source_file=?', (source_file,))
        for report in reports:
            self.db.execute("DELETE FROM exports WHERE report=? AND json_extract(payload_json,'$.source_file')=?",
                            (report, source_file))

    def add(self, table, row, report=None):
        row = dict(row)
        if table == 'engineering_objects':
            row.update(normalize_name(row['name']) if row.get('name') is not None else dict(raw_name=None,normalized_name=None))
        elif table == 'boq_items':
            row.update(normalize_name(row.get('model') or row.get('description')))
        fields = SCHEMA[table]
        vals = [row.get(f) for f in fields]
        payload = json.dumps(row, ensure_ascii=False, default=str)
        self.db.execute(f'INSERT INTO {table} ({",".join(fields)},payload_json) VALUES ({",".join("?" for _ in range(len(fields)+1))})', vals + [payload])
        if report:
            self.report(report, row)

    def report(self, name, row):
        self.db.execute('INSERT INTO exports VALUES (?, ?)', (name, json.dumps(row, ensure_ascii=False, default=str)))

    def rows(self, table):
        for row in self.db.execute(f'SELECT payload_json FROM {table}'):
            yield json.loads(row[0])

    def export(self, out):
        out = Path(out)
        for table, fields in SCHEMA.items():
            self._csv(out / 'database' / (table + '.csv'), self.rows(table), fields)
        for (report,) in self.db.execute('SELECT DISTINCT report FROM exports').fetchall():
            def rows():
                for (payload,) in self.db.execute('SELECT payload_json FROM exports WHERE report=?', (report,)):
                    yield json.loads(payload)
            fields = list(dict.fromkeys(k for r in rows() for k in r))
            self._csv(out / report, rows(), fields)

    @staticmethod
    def _csv(path, rows, fields):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fields, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)


def parser_cli(kind):
    import argparse
    from common import load_config
    from pipeline import run_multiformat
    p = argparse.ArgumentParser()
    p.add_argument('input', nargs='+')
    p.add_argument('--output', required=True)
    p.add_argument('--compare', help='Explicit older BOQ file to compare against input')
    a = p.parse_args()
    cfg = dict(load_config(), output_dir=a.output)
    summary = run_multiformat(cfg, a.input, compare=a.compare, log=lambda level, msg: print(f'[{level}] {msg}'))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary['exit_code']
