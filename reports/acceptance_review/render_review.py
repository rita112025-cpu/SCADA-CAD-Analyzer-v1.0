"""Static presentation of captured audit data; no parsing or matching rules."""
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
data = json.loads((HERE / 'evidence.json').read_text(encoding='utf-8'))
esc = lambda value: html.escape(str(value), quote=True)
parts = ['''<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>工程資料輸出驗收 — 合成範例</title>
<style>body{font:16px/1.7 system-ui,sans-serif;color:#20252b;background:#fff;margin:32px auto;padding:0 24px;max-width:1120px}h1,h2{line-height:1.3}a{color:#0756a3}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #bcc4cd;padding:8px;text-align:left;vertical-align:top}th{background:#edf1f5}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f7;padding:16px}details{margin:12px 0}summary{cursor:pointer}small{color:#424b56}.table{overflow-x:auto}</style>
<h1>SCADA Engineering Data Analyzer：輸出品質抽查</h1>
<p><strong>HOLD：暫不通過工程資料驗收。</strong>範圍為既有合成範例，尚無真實專案資料或人工簽核。</p>
<p>此頁僅呈現已擷取的 SQLite/CSV 證據。無 JavaScript、無 parser、無重新比對；反例與既有輸出分開列示。</p>
<p><a href="REVIEW.md">完整驗收結論</a> · <a href="evidence.json">原始抽查證據 JSON</a></p>''']
parts.append('<p>抽查時間：' + esc(data['audited_at']) + '<br>DB SHA-256：<code>' + esc(data['database_sha256']) + '</code></p>')
parts.append('<h2>既有成果</h2><ul>')
for label, path in [('project.db','database/project.db'), ('cross_reference.csv','cross_reference/cross_reference.csv'), ('boq_items.csv','excel/boq_items.csv'), ('requirements.csv','docx/requirements.csv'), ('ifc_objects.csv','ifc/ifc_objects.csv'), ('navis_clashes.csv','navisworks/navis_clashes.csv')]:
    parts.append(f'<li><a href="../../demo_multiformat/output/{esc(path)}">{esc(label)}</a></li>')
parts.append('</ul><h2>驗收判讀</h2><pre>' + esc((HERE/'REVIEW.md').read_text(encoding='utf-8')) + '</pre>')
parts.append('<h2>現有 cross_reference.csv 的 18 筆結果</h2><p>MATCH 僅按 check_type 解讀，不能代表需求滿足或設計合規。</p><div class="table"><table><thead><tr>')
columns = ['check_type','key','result','confidence','value_a','value_b','note']
parts += ['<th>'+esc(k)+'</th>' for k in columns]
parts.append('</tr></thead><tbody>')
for row in data['actual_cross_reference']:
    parts.append('<tr>' + ''.join('<td>'+esc(row.get(k,''))+'</td>' for k in columns) + '</tr>')
parts.append('</tbody></table></div><h2>逐層來源證據</h2>')
for chain in data['evidence_chains']:
    parts.append('<details><summary>'+esc(chain['kind'])+' — '+esc(chain['source'].get('location',chain['source'].get('file','')))+'</summary><pre>'+esc(json.dumps(chain,ensure_ascii=False,indent=2))+'</pre></details>')
parts.append('<h2>獨立記憶體反例（未寫入原 DB）</h2>')
for case in data['counterexamples']:
    parts.append('<details><summary>'+esc(case['case'])+'</summary><pre>'+esc(json.dumps(case,ensure_ascii=False,indent=2))+'</pre></details>')
parts.append('</html>')
(HERE/'index.html').write_text('\n'.join(parts), encoding='utf-8')
print(HERE/'index.html')
