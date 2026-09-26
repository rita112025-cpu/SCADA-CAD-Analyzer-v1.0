"""Ordered Word paragraphs/tables with verbatim requirement candidates."""
import json
import re
from engineering_data import evidence, parser_cli
import scada_rules


def table_rows(table):
    """Keep logical rows plus XML-backed origins for horizontally/vertically merged cells."""
    from docx.oxml.ns import qn
    origins={}
    headers=[]
    subject_labels={'subject','equipment','item','設備','設備名稱','主體','項目'}
    requirement_labels={'requirement','requirements','description','要求','需求','規範'}
    for rno,row in enumerate(table.rows,1):
        cells=list(row.cells)
        texts=[cell.text for cell in cells]
        flags=row._tr.xpath('./w:trPr/w:tblHeader')
        explicit=any(flag.get(qn('w:val'),'1') not in ('0','false','off') for flag in flags)
        recognized=rno==1 and bool({s.strip().casefold() for s in texts}&subject_labels) and bool({s.strip().casefold() for s in texts}&requirement_labels)
        if explicit or recognized: headers=texts
        context=[]
        for col,cell in enumerate(cells,1):
            origin=origins.setdefault(cell._tc,(rno,col))
            context.append(dict(column=col,header=headers[col-1] if col<=len(headers) else None,
                                text=cell.text,origin_row=origin[0],origin_column=origin[1],
                                grid_span=cell._tc.grid_span,merged=origin!=(rno,col) or cell._tc.grid_span>1))
        yield rno,texts,context,headers,explicit or recognized


def parse(path, store, cfg):
    from docx import Document
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    doc = Document(path)
    hierarchy = {}
    rules = scada_rules.build_rules(dict(cfg, keywords=cfg.get('document_keywords', cfg.get('keywords', []))))
    candidate = re.compile(r'不得|應|須|需|\b(?:shall|must|should|required|requirement)\b', re.I)
    table_index=0
    for order, element in enumerate(doc.element.body, 1):
        texts = []
        section = ' / '.join(hierarchy.values())
        if element.tag.endswith('}p'):
            p = Paragraph(element, doc)
            text = p.text
            match = re.search(r'Heading (\d+)', p.style.name if p.style else '')
            level = int(match[1]) if match else 0
            if level:
                hierarchy = {k:v for k,v in hierarchy.items() if k < level}
                parent = ' / '.join(hierarchy.values())
                hierarchy[level] = text
                section = ' / '.join(hierarchy.values())
            else: parent = section
            kind = 'heading' if level else ('list_item' if p._p.xpath('./w:pPr/w:numPr') or 'List' in (p.style.name if p.style else '') else 'paragraph')
            store.add('document_sections', evidence(path, 'DOCX', f'body:{order}', section=section, parent_section=parent, level=level, kind=kind, source_order=order, text=text, original_text=text), 'docx/docx_sections.csv')
            texts.append((text, f'body:{order}'))
        elif element.tag.endswith('}tbl'):
            table_index+=1
            table = Table(element, doc)
            for rno,cells,context,headers,is_header in table_rows(table):
                location = f'body:{order}/table:{table_index}/row:{rno}'
                row_context=json.dumps(context,ensure_ascii=False)
                merged=json.dumps([cell for cell in context if cell['merged']],ensure_ascii=False)
                store.add('document_sections', evidence(path, 'DOCX', location, section=section, kind='table_row', source_order=order, table_index=table_index,row_number=rno,column_headers_json=json.dumps(headers,ensure_ascii=False),row_context_json=row_context,merged_cells_json=merged,cells_json=json.dumps(cells, ensure_ascii=False)), 'docx/docx_tables.csv')
                fragments=[cell for cell in context if candidate.search(cell['text'])]
                if is_header or not fragments: continue
                # Keep each requirement cell verbatim in fragments. The comparison unit is the row.
                nonrequirements=[cell['text'] for cell in context if cell['text'].strip() and not candidate.search(cell['text'])]
                explicit_subject=[cell['text'] for cell in context if (cell['header'] or '').strip().casefold() in {'subject','equipment','item','設備','設備名稱','主體','項目'}]
                subject=explicit_subject[0] if len(set(explicit_subject))==1 else (nonrequirements[0] if len(set(nonrequirements))==1 else None)
                original=fragments[0]['text']
                kws=[m['keyword'] for m in scada_rules.find_matches('\n'.join(cells),rules) if m['confidence']!=scada_rules.EXCLUDED]
                store.add('requirements',evidence(path,'DOCX',location,requirement_id=location,section=section,
                    requirement_text=original,original_text=original,keyword='|'.join(kws),status='CANDIDATE',
                    requirement_confidence='high' if re.search(r'不得|須|\b(?:shall|must)\b',original,re.I) else 'candidate',
                    subject=subject,table_index=table_index,row_number=rno,column_headers_json=json.dumps(headers,ensure_ascii=False),
                    row_context_json=row_context,merged_cells_json=merged,requirement_fragments_json=json.dumps(fragments,ensure_ascii=False)), 'docx/requirements.csv')
        for text, location in texts:
            if candidate.search(text):
                strong = bool(re.search(r'不得|須|\b(?:shall|must)\b', text, re.I))
                kws = [m['keyword'] for m in scada_rules.find_matches(text, rules) if m['confidence'] != scada_rules.EXCLUDED]
                store.add('requirements', evidence(path, 'DOCX', location, requirement_id=location, section=section,
                    requirement_text=text, original_text=text, keyword='|'.join(kws), status='CANDIDATE',
                    requirement_confidence='high' if strong else ('normal' if re.search(r'應|需|\bshould\b', text, re.I) else 'candidate')), 'docx/requirements.csv')
    return 'OK'


if __name__ == '__main__':
    raise SystemExit(parser_cli('DOCX'))
