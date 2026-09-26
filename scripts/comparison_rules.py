"""Engineering comparison eligibility and explicitly comparable specifications."""
import json
import re
from decimal import Decimal

REFERENCE_TYPES = {'IfcSpace','IfcBuildingStorey','IfcSystem','IfcDistributionSystem','IfcBuilding','IfcSite','IfcProject','IfcZone','IfcGroup'}
EQUIPMENT_BASES = ('IfcDistributionElement','IfcElectricalElement','IfcCableCarrierSegment','IfcCableCarrierFitting')
EQUIPMENT_TYPES = set(EQUIPMENT_BASES) | {'IfcFlowSegment','IfcFlowFitting','IfcFlowTerminal','IfcFlowController','IfcFlowMovingDevice','IfcFlowStorageDevice','IfcFlowTreatmentDevice','IfcEnergyConversionDevice','IfcElectricDistributionBoard','IfcCableSegment','IfcDuctSegment','IfcPipeSegment'}


def boq_eligibility(obj):
    kind=obj.get('object_type')
    if obj.get('source_type') == 'IFC':
        if kind in REFERENCE_TYPES: return False, 'REFERENCE_ONLY'
        if obj.get('boq_compare_eligible') is True or kind in EQUIPMENT_TYPES: return True, 'EQUIPMENT'
        return False, 'UNCLASSIFIED_IFC'
    if obj.get('source_type') == 'CAD':
        if kind == 'INSERT' and not obj.get('context'): return True, 'BLOCK_INSTANCE'
        return False, 'REFERENCE_ONLY'
    return False, 'UNSUPPORTED_SOURCE'


def specification_facts(row):
    """Only explicit same-unit quantities. No dimensions inferred from names."""
    value=row.get('specification')
    if not value:
        try: value=json.loads(row.get('properties_json') or '{}').get('specification')
        except (ValueError,TypeError): value=None
    if not isinstance(value,str): return {}
    facts={}
    for part in re.split(r'[;；\n]',value):
        m=re.fullmatch(r'\s*(Voltage|電壓|Current|電流|Power|功率|Width|寬度)\s*[:=：]\s*(\d+(?:\.\d+)?)\s*(V|A|W|kW|mm)\s*',part,re.I)
        if not m: continue
        label={'電壓':'voltage','電流':'current','功率':'power','寬度':'width'}.get(m[1],m[1].lower())
        key=(label,m[3].lower())
        if key[1] not in {'voltage':{'v'},'current':{'a'},'power':{'w','kw'},'width':{'mm'}}[label]: continue
        if key in facts: return {}
        facts[key]=dict(value=str(Decimal(m[2])),raw=part)
    return facts


def specification_conflicts(a,b):
    left,right=specification_facts(a),specification_facts(b)
    return [dict(property=k[0],unit=k[1],value_a=left[k]['value'],value_b=right[k]['value'],raw_a=left[k]['raw'],raw_b=right[k]['raw'])
            for k in sorted(left.keys() & right.keys()) if Decimal(left[k]['value']) != Decimal(right[k]['value'])]
