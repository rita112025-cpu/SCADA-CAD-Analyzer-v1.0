"""Allowlisted parameterized queries over existing normalized tables."""
import json
from contextlib import closing
from evidence_schema import connect
from name_normalizer import normalize_name
import scada_rules

TOOLS = ('find_objects','find_missing_tags','find_missing_systems','find_boq_items',
         'find_cross_reference','find_clashes','find_requirements','find_by_normalized_name')
FILTERS = {'project_id','source_type','source_file','revision','evidence_level'}


def limit_value(limit):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError('limit must be an integer between 1 and 200')
    return limit


def filter_sql(filters, alias='c'):
    if set(filters) - FILTERS: raise ValueError('Unsupported metadata filter')
    terms, values = [], []
    for key,value in filters.items():
        if value is not None:
            terms.append(f'{alias}.{key}=?'); values.append(value)
    return terms, values


class StructuredQuery:
    def __init__(self, database): self.database = database

    def _query(self, table, clauses=(), params=(), limit=20, **filters):
        limit_value(limit)
        where, values = filter_sql(filters)
        where = ['c.record_table=?','c.snapshot_id IN (SELECT snapshot_id FROM evidence_current)'] + where + list(clauses)
        with closing(connect(self.database)) as db:
            db.create_function('engineering_match',2,lambda text,kw: bool(scada_rules.match_keyword(text or '',kw or '',engineering=True)))
            rows = db.execute(f'SELECT c.chunk_id,r.payload_json FROM {table} r JOIN evidence_chunks c ON c.record_id=r.rowid WHERE '+ ' AND '.join(where)+' ORDER BY c.chunk_id LIMIT ?',
                              [table]+values+list(params)+[limit]).fetchall()
        return [dict(chunk_id=r['chunk_id'],record=json.loads(r['payload_json']),retrieval_method='STRUCTURED',score=None) for r in rows]

    def find_objects(self, name=None, object_type=None, system=None, limit=20, **filters):
        clauses, params = [], []
        if name: clauses.append('engineering_match(r.name,?)'); params.append(name)
        for field,value in [('object_type',object_type),('system',system)]:
            if value is not None: clauses.append(f'r.{field}=?'); params.append(value)
        return self._query('engineering_objects',clauses,params,limit,**filters)

    def find_missing_tags(self, limit=20, **filters):
        filters.setdefault('source_type','IFC')
        return self._query('engineering_objects', ["NULLIF(trim(json_extract(CASE WHEN json_valid(r.properties_json) THEN r.properties_json ELSE '{}' END,'$.Tag')),'') IS NULL"],limit=limit,**filters)

    def find_missing_systems(self, limit=20, **filters):
        filters.setdefault('source_type','IFC')
        return self._query('engineering_objects',["NULLIF(trim(r.system),'') IS NULL"],limit=limit,**filters)

    def find_boq_items(self, name=None, limit=20, **filters):
        return self._query('boq_items', ['(engineering_match(r.model,?) OR engineering_match(r.description,?))'] if name else [], [name,name] if name else [],limit,**filters)

    def find_cross_reference(self, result=None, check_type=None, limit=20, **filters):
        from cross_reference import RESULTS
        if result and result not in RESULTS: raise ValueError('Unknown result')
        clauses,params=[],[]
        for field,value in [('result',result),('check_type',check_type)]:
            if value is not None: clauses.append(f'r.{field}=?'); params.append(value)
        return self._query('cross_reference_results',clauses,params,limit,**filters)

    def find_clashes(self, status=None, limit=20, **filters):
        return self._query('clashes',['r.status=?'] if status else [],[status] if status else [],limit,**filters)

    def find_requirements(self, keyword=None, limit=20, **filters):
        return self._query('requirements',['engineering_match(r.requirement_text,?)'] if keyword else [],[keyword] if keyword else [],limit,**filters)

    def find_by_normalized_name(self, name, limit=20, **filters):
        key=normalize_name(name)['normalized_name']
        a=self._query('engineering_objects',['r.normalized_name=?'],[key],limit,**filters)
        b=self._query('boq_items',['r.normalized_name=?'],[key],limit,**filters)
        return (a+b)[:limit]

    def execute(self, tool, parameters=None):
        if tool not in TOOLS: raise ValueError('Tool is not allowlisted')
        return getattr(self,tool)(**(parameters or {}))
