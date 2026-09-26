"""Typed identifiers, comparison scope and relation evidence; never compliance inference."""
import json
from collections import defaultdict
from name_normalizer import normalize_name
from comparison_rules import boq_eligibility, specification_conflicts
import scada_rules

RESULTS = {'EXACT_MATCH','NORMALIZED_MATCH','RELATED','MISMATCH','MISSING_A','MISSING_B','UNCERTAIN','NOT_APPLICABLE'}
COMPLIANCE_STATUSES = {'NOT_EVALUATED','SUPPORTED','NOT_SUPPORTED','INSUFFICIENT_EVIDENCE'}


def norm(value): return normalize_name(value)['normalized_name']


def display(row):
    return next((row[k] for k in ('raw_name','name','model','description','requirement_text','keyword','clash_name') if row.get(k) is not None), '')


def result(kind,a,b,key,state,confidence,note='',basis='',compliance='NOT_EVALUATED',**extra):
    assert state in RESULTS and compliance in COMPLIANCE_STATUSES
    return dict(check_type=kind,source_a=a.get('source_file',''),source_b=b.get('source_file',''),
        key=key,value_a=display(a),value_b=display(b),result=state,confidence=confidence,
        match_basis=basis,compliance_status=compliance,
        evidence_a=json.dumps(a,ensure_ascii=False),evidence_b=json.dumps(b,ensure_ascii=False),note=note,
        source_file=a.get('source_file') or b.get('source_file',''),source_type='CrossReference',
        source_location=kind,evidence_level='DERIVED',**extra)


def compare_objects(objects,boq):
    index,prefix,prefix_ids=defaultdict(set),defaultdict(set),defaultdict(set)
    for i,row in enumerate(boq):
        for value in (row.get('model'),row.get('description'),row.get('item_no')):
            key=norm(value)
            if key:
                index[key].add(i); prefix[key[:4]].add(key); prefix_ids[key[:4]].add(i)
    first={k:min(v) for k,v in index.items()}
    prefix_first={k: min(v) for k,v in prefix.items() if len(v)<=20}
    covered_keys,candidate_prefixes=set(),set()
    for obj in objects:
        key=norm(obj.get('name')); ids=index.get(key,set())
        kind=obj.get('source_type','CAD')+'_OBJECT_VS_BOQ'
        if obj.get('source_type')=='IFC' and not boq_eligibility(obj)[0]:
            yield result(kind,obj,{},key,'NOT_APPLICABLE',0,'Outside equipment comparison scope.',boq_eligibility(obj)[1])
            continue
        if ids:
            covered_keys.add(key); item=boq[first[key]]
            exact=any(obj.get('name') == item.get(f) for f in ('model','description','item_no'))
            state='EXACT_MATCH' if exact else 'NORMALIZED_MATCH'
            conflicts=specification_conflicts(obj,item) if len(ids)==1 else []
            if len(ids)>1: state='UNCERTAIN'
            elif conflicts: state='MISMATCH'
            yield result(kind,obj,item,key,state,.5 if len(ids)>1 else (1 if exact or conflicts else .9),
                'Names/specification statements only; quantity, delivery and requirement compliance are not evaluated.',
                'SPECIFICATION_CONFLICT' if conflicts else ('NAME_EXACT' if exact else 'NAME_NORMALIZED'),
                specification_conflicts_json=json.dumps(conflicts,ensure_ascii=False),candidate_count=len(ids))
        else:
            candidates=prefix.get(key[:4],set()) if key else set()
            if candidates: candidate_prefixes.add(key[:4])
            similar=prefix_first.get(key[:4], '') if candidates else ''
            yield result(kind,obj,boq[first[similar]] if similar else {},key,
                'UNCERTAIN' if candidates or not key else 'MISSING_B',.3 if candidates else 0,
                'Unconfirmed candidates; no equipment/compliance conclusion.' if candidates or not key else 'No matching name in supplied BOQ scope.',
                'NAME_CANDIDATE' if candidates else 'NO_NAME_EVIDENCE',candidate_count=len(prefix_ids.get(key[:4],())))
    covered=set().union(*(index[k] for k in covered_keys)) if covered_keys else set()
    possible=set().union(*(prefix_ids[k] for k in candidate_prefixes)) if candidate_prefixes else set()
    for i,row in enumerate(boq):
        if i not in covered:
            yield result('OBJECT_VS_BOQ',{},row,norm(row.get('model') or row.get('description')),
                'UNCERTAIN' if i in possible else 'MISSING_A',.3 if i in possible else 0,
                'Unconfirmed object candidate exists.' if i in possible else 'No eligible object name in supplied CAD/IFC scope; not proof of a missing physical item.',
                'NAME_CANDIDATE' if i in possible else 'NO_NAME_EVIDENCE')


def clash_results(objects,clashes):
    indexes={k:defaultdict(dict) for k in ('guid','handle','name')}
    for i,obj in enumerate(objects):
        for field in indexes:
            value=obj.get(field)
            if value: indexes[field][norm(value) if field=='name' else value][i]=obj
    for clash in clashes:
        for side in ('a','b'):
            raw=clash.get('object_'+side) or ''
            kind=(clash.get('object_'+side+'_type') or 'UNKNOWN').upper()
            source=clash.get('object_'+side+'_source')
            basis=''; candidates={}; state='MISSING_B'; confidence=0
            if not raw:
                state='UNCERTAIN'; basis='MISSING_IDENTIFIER'
            elif kind in ('GUID','GLOBALID'):
                candidates=indexes['guid'].get(raw,{}); basis='GUID_EXACT'
            elif kind == 'HANDLE':
                candidates=indexes['handle'].get(raw,{}); basis='HANDLE_EXACT'
            elif kind == 'NAME':
                candidates=indexes['name'].get(norm(raw),{}); basis='NAME'
            elif kind == 'ELEMENT_ID':
                state='UNCERTAIN'; basis='UNSUPPORTED_IDENTIFIER_TYPE'
            else:
                candidates=indexes['guid'].get(raw,{})
                if candidates: basis='GUID_EXACT'
                elif len(raw)==22 and all(c.isalnum() or c in '_$' for c in raw): basis='GUID_EXACT'
                elif raw in indexes['handle']:
                    candidates=indexes['handle'][raw]; basis='HANDLE_EXACT'
                else:
                    candidates=indexes['name'].get(norm(raw),{}); basis='NAME'
            if source: candidates={i:o for i,o in candidates.items() if o.get('source_file')==source}
            candidate=next(iter(candidates.values()),{})
            if candidates:
                if len(candidates)>1 or (basis=='HANDLE_EXACT' and not source):
                    state='UNCERTAIN'; confidence=.5
                elif basis=='NAME':
                    state='EXACT_MATCH' if raw==candidate.get('name') else 'NORMALIZED_MATCH'
                    confidence=1 if state=='EXACT_MATCH' else .9
                else: state='EXACT_MATCH'; confidence=1
            row=result('CLASH_VS_OBJECT',clash,candidate,raw,state,confidence,
                'object_'+side+': typed identifier/name evidence only; handles require an explicit source file.',basis,candidate_count=len(candidates))
            row['value_a']=raw
            yield row


def run(store,cfg,historical_boq=None):
    objects=list(store.rows('engineering_objects'))
    boq=[r for r in store.rows('boq_items') if r.get('source_file')!=historical_boq]
    def emit(row): store.add('cross_reference_results',row,'cross_reference/cross_reference.csv')
    eligible=[]
    for obj in objects:
        allowed,reason=boq_eligibility(obj)
        if allowed: eligible.append(obj)
        elif obj.get('source_type')=='IFC':
            emit(result('IFC_OBJECT_VS_BOQ',obj,{},norm(obj.get('name')),'NOT_APPLICABLE',0,
                        reason+': outside equipment comparison scope.',reason))
    for row in compare_objects(eligible,boq): emit(row)
    requirements=defaultdict(list)
    for req in store.rows('requirements'):
        for keyword in (req.get('keyword') or '').split('|'):
            if keyword: requirements[norm(keyword)].append(req)
    rules=scada_rules.build_rules(dict(cfg,keywords=cfg.get('document_keywords',cfg.get('keywords',[]))))
    for obj in objects:
        text=(obj.get('system') or (obj.get('name') if obj.get('object_type') in ('IfcSystem','IfcDistributionSystem') else '')) if obj.get('source_type')=='IFC' else obj.get('name','')
        for hit in scada_rules.find_matches(text,rules):
            if hit['confidence']==scada_rules.EXCLUDED: continue
            key=norm(hit['keyword']); reqs=requirements.get(key,[])
            kind='IFC_SYSTEM_VS_REQUIREMENT' if obj.get('source_type')=='IFC' else 'CAD_KEYWORD_VS_REQUIREMENT'
            for req in (reqs[:1] if len(reqs)>20 else reqs) or [{}]:
                emit(result(kind,obj,req,key,'UNCERTAIN' if len(reqs)>20 else ('RELATED' if req else 'MISSING_B'),
                    .5 if req else 0, 'Shared keyword only; requirement satisfaction is not evaluated.',
                    'KEYWORD_RELATION','INSUFFICIENT_EVIDENCE',candidate_count=len(reqs)))
    for row in clash_results(objects,store.rows('clashes')): emit(row)
