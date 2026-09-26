"""Additive evidence migrations in project.db; no second source of truth."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

VERSION = '2.0.0'
INDEX_FIELDS = ('source_type', 'source_file', 'file_hash', 'revision', 'normalized_name',
                'object_type', 'system', 'cad_handle', 'ifc_guid', 'evidence_level')


def now():
    return datetime.now(timezone.utc).isoformat()


def identity(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def connect(database, writable=False):
    path = Path(database).resolve()
    db = sqlite3.connect(path.as_uri() + ('?mode=rw' if writable else '?mode=ro'), uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def migrate(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS evidence_snapshots (
        snapshot_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, source_file TEXT NOT NULL,
        file_hash TEXT NOT NULL, revision TEXT, previous_revision TEXT,
        previous_snapshot_id TEXT, parser_version TEXT NOT NULL, content_hash TEXT NOT NULL,
        created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS evidence_current (
        project_id TEXT NOT NULL, source_file TEXT NOT NULL, snapshot_id TEXT NOT NULL,
        PRIMARY KEY(project_id, source_file));
    CREATE TABLE IF NOT EXISTS evidence_chunks (
        chunk_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
        source_file TEXT NOT NULL, source_type TEXT NOT NULL, file_hash TEXT NOT NULL,
        revision TEXT, source_location TEXT NOT NULL CHECK(length(source_location)>0),
        page INTEGER, section TEXT, sheet TEXT, row_number INTEGER,
        object_id TEXT, cad_handle TEXT, ifc_guid TEXT, title TEXT,
        content TEXT NOT NULL CHECK(length(content)>0), normalized_name TEXT,
        evidence_level TEXT NOT NULL DEFAULT 'PARSED' CHECK(evidence_level IN ('PARSED','DERIVED','MANUAL')),
        parser TEXT, parser_version TEXT NOT NULL, created_at TEXT NOT NULL, metadata_json TEXT,
        snapshot_id TEXT NOT NULL, record_table TEXT NOT NULL, record_id INTEGER NOT NULL,
        object_type TEXT, system TEXT);
    CREATE TABLE IF NOT EXISTS evidence_build_state (
        snapshot_id TEXT PRIMARY KEY, source_file TEXT NOT NULL, file_hash TEXT NOT NULL,
        parser_version TEXT NOT NULL, built_at TEXT NOT NULL, chunk_count INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_evidence_snapshot ON evidence_chunks(snapshot_id);
    CREATE INDEX IF NOT EXISTS idx_evidence_record ON evidence_chunks(record_table, record_id);
    CREATE INDEX IF NOT EXISTS idx_evidence_project ON evidence_chunks(project_id);
    ''')
    for field in INDEX_FIELDS:
        db.execute(f'CREATE INDEX IF NOT EXISTS idx_evidence_{field} ON evidence_chunks({field})')


def log_event(database, component, query_type='', status='OK', elapsed=0, error='', chunk_id=''):
    """Never log questions, model responses, HTTP bodies or document content."""
    folder = Path(database).resolve().parent.parent / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    row = dict(timestamp=now(), query_type=query_type, status=status, timing=elapsed,
               error=error, chunk_id=chunk_id)
    with (folder / (component + '.log')).open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
