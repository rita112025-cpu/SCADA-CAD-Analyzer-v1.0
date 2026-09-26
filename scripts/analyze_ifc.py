"""IFC semantic extraction; absent geometry/properties remain unknown."""
import json
from collections import Counter
from engineering_data import evidence, parser_cli
from comparison_rules import EQUIPMENT_BASES, REFERENCE_TYPES


def parse(path, store, cfg):
    import ifcopenshell
    from ifcopenshell.util.element import get_psets, get_container
    from ifcopenshell.util.placement import get_local_placement
    model = ifcopenshell.open(str(path))
    counts = Counter()
    # IfcObject includes spatial objects, systems and products, without duplicate subclass iteration.
    for obj in model.by_type('IfcObject'):
        cls = obj.is_a()
        name = getattr(obj, 'Name', None)
        tag = getattr(obj, 'Tag', None)
        container = get_container(obj) if hasattr(obj, 'ContainedInStructure') else None
        space = container.Name if container and container.is_a('IfcSpace') else None
        level = None
        ancestor = container
        visited = set()
        while ancestor and ancestor.id() not in visited:
            visited.add(ancestor.id())
            if ancestor.is_a('IfcBuildingStorey'):
                level = ancestor.Name
                break
            rels = getattr(ancestor, 'Decomposes', ())
            ancestor = rels[0].RelatingObject if rels else None
        systems, relationships = [], []
        for rel in getattr(obj, 'HasAssignments', ()):
            group = getattr(rel, 'RelatingGroup', None)
            if group and group.is_a('IfcSystem'):
                if group.Name is not None: systems.append(group.Name)
            relationships.append(dict(type=rel.is_a(), id=getattr(rel, 'GlobalId', ''), related=getattr(group, 'GlobalId', '') if group else ''))
        for rel in getattr(obj, 'ContainedInStructure', ()):
            relationships.append(dict(type=rel.is_a(), id=rel.GlobalId, related=rel.RelatingStructure.GlobalId))
        psets = get_psets(obj)
        xyz = [None, None, None]
        placement = getattr(obj, 'ObjectPlacement', None)
        if placement and placement.is_a('IfcLocalPlacement'):
            xyz = [float(v) for v in get_local_placement(placement)[:3, 3]]
        dims = dict(width=None,height=None,length=None)
        dimension_values = {key:set() for key in dims}
        for properties in psets.values():
            for key in ('Width', 'Height', 'Length'):
                value = properties.get(key)
                if type(value) in (int, float): dimension_values[key.lower()].add(value)
        for key,values in dimension_values.items():
            if len(values)==1: dims[key]=next(iter(values))
        eligible=cls not in REFERENCE_TYPES and any(obj.is_a(base) for base in EQUIPMENT_BASES)
        specs={p['Specification'] for p in psets.values() if isinstance(p.get('Specification'),str)}
        row = evidence(path, 'IFC', f'#{obj.id()}', object_id=str(obj.id()), object_type=cls,
            name=name, tag=tag, guid=getattr(obj, 'GlobalId', None), level=level, space=space,
            system='|'.join(systems) if systems else None, x=xyz[0], y=xyz[1], z=xyz[2], **dims,
            boq_compare_eligible=eligible, comparison_role='EQUIPMENT' if eligible else ('REFERENCE_ONLY' if cls in REFERENCE_TYPES else 'UNCLASSIFIED_IFC'),
            specification=next(iter(specs)) if len(specs)==1 else None,
            properties_json=json.dumps(dict(ObjectType=getattr(obj, 'ObjectType', None), Tag=tag, property_sets=psets,
                                           relationships=relationships, coordinate_units='IFC project units'), ensure_ascii=False, default=str))
        store.add('engineering_objects', row, 'ifc/ifc_objects.csv')
        if obj.is_a('IfcSystem'): store.report('ifc/ifc_systems.csv', row)
        if obj.is_a('IfcSpace'): store.report('ifc/ifc_spaces.csv', row)
        counts[('total', 'objects')] += 1
        counts[('class', cls)] += 1
        counts[('level', level)] += 1
        counts[('system', row['system'])] += 1
        counts[('missing', 'Name')] += not bool(name)
        counts[('missing', 'Tag')] += not bool(tag)
        counts[('missing', 'System')] += not bool(systems)
        counts[('total', 'Cable Tray')] += cls in ('IfcCableCarrierSegment', 'IfcCableCarrierFitting') and getattr(obj, 'PredefinedType', '') in ('CABLETRAYSEGMENT', 'CABLETRAYFITTING')
    for (metric, value), count in counts.items():
        store.report('ifc/ifc_summary.csv', evidence(path, 'IFC', metric=metric, value=value, count=count))
    return 'OK'


if __name__ == '__main__':
    raise SystemExit(parser_cli('IFC'))
