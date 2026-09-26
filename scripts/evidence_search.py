"""Real SQLite FTS5 with CJK bigram tokens; original content stays in chunks."""
import re
import sqlite3
import time
from contextlib import closing
from evidence_schema import connect, log_event
from structured_query import filter_sql, limit_value


class FTSUnavailable(RuntimeError): pass


def tokens(text):
    result=[]
    for term in re.findall(r'[A-Za-z0-9_\-]+|[\u3400-\u9fff]+',text):
        if re.fullmatch(r'[\u3400-\u9fff]+',term):
            result.extend(term[i:i+2] for i in range(max(1,len(term)-1)))
        else: result.append(term)
    return list(dict.fromkeys(result))


def indexed(text):
    return (text or '') + '\n' + ' '.join(tokens(text or ''))


def index_evidence(db):
    try:
        db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(chunk_id UNINDEXED,title,content,normalized_name,section)')
    except sqlite3.OperationalError as exc:
        raise FTSUnavailable('SKIPPED_DEPENDENCY: SQLite FTS5 unavailable') from exc
    count=0
    with db:
        for row in db.execute('SELECT c.* FROM evidence_chunks c WHERE NOT EXISTS (SELECT 1 FROM evidence_fts f WHERE f.chunk_id=c.chunk_id)'):
            db.execute('INSERT INTO evidence_fts VALUES (?,?,?,?,?)',(row['chunk_id'],indexed(row['title']),indexed(row['content']),indexed(row['normalized_name']),indexed(row['section'])))
            count+=1
    return count


def search_fts(database, query, source_type=None, project_id=None, revision=None, limit=20, source_file=None, evidence_level='PARSED', history=False):
    limit_value(limit)
    if not isinstance(query,str) or len(query)>2000: raise ValueError('query must be text, at most 2000 characters')
    words=tokens(query)
    if not words: return []
    expression=' AND '.join('"'+w.replace('"','""')+'"' for w in words[:40])
    where,params=filter_sql(dict(source_type=source_type,project_id=project_id,revision=revision,source_file=source_file,evidence_level=evidence_level))
    if not history: where.append('c.snapshot_id IN (SELECT snapshot_id FROM evidence_current)')
    where.insert(0,'evidence_fts MATCH ?')
    started=time.perf_counter()
    try:
        with closing(connect(database)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='evidence_fts'").fetchone():
                raise FTSUnavailable('FTS5 index not built or disabled')
            rows=db.execute('SELECT c.*,bm25(evidence_fts) AS score FROM evidence_fts JOIN evidence_chunks c ON c.chunk_id=evidence_fts.chunk_id WHERE '+' AND '.join(where)+' ORDER BY score,c.chunk_id LIMIT ?', [expression]+params+[limit]).fetchall()
        return [dict(dict(r),retrieval_method='FTS5') for r in rows]
    finally:
        log_event(database,'retrieval','FTS5',elapsed=time.perf_counter()-started)
