from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Iterator

from .config import DB_PATH


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextlib.contextmanager
def db_conn(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS repositories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_indexed_at TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    status_message TEXT NOT NULL DEFAULT '',
    total_files INTEGER NOT NULL DEFAULT 0,
    total_chunks INTEGER NOT NULL DEFAULT 0,
    total_symbols INTEGER NOT NULL DEFAULT 0,
    git_commit TEXT,
    embedding_model TEXT,
    semantic_ready INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    language TEXT NOT NULL,
    indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(repository_id, path)
);

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT,
    kind TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    language TEXT NOT NULL,
    signature TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_symbols_repo_name ON symbols(repository_id, name);
CREATE INDEX IF NOT EXISTS idx_symbols_repo_path ON symbols(repository_id, path);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    symbol_id INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
    path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    language TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT,
    text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding BLOB,
    embedding_dim INTEGER,
    embedded_model TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_repo_path ON chunks(repository_id, path);
CREATE INDEX IF NOT EXISTS idx_chunks_symbol ON chunks(symbol_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    repository_id UNINDEXED,
    path,
    name,
    text,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    source_symbol_id INTEGER REFERENCES symbols(id) ON DELETE CASCADE,
    target_symbol_id INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
    source_name TEXT,
    target_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_edges_repo_source ON edges(repository_id, source_symbol_id);
CREATE INDEX IF NOT EXISTS idx_edges_repo_target ON edges(repository_id, target_symbol_id);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'New chat',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived INTEGER NOT NULL DEFAULT 0,
    parent_conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    branch_from_message_id INTEGER,
    summary TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_conversations_repo_updated ON conversations(repository_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS conversation_repositories (
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    is_primary INTEGER NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (conversation_id, repository_id)
);
CREATE INDEX IF NOT EXISTS idx_conversation_repositories_repo ON conversation_repositories(repository_id, conversation_id);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sequence_number INTEGER NOT NULL,
    repository_commit TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_sequence ON messages(conversation_id, sequence_number);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    conversation_id UNINDEXED,
    role UNINDEXED,
    content,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS message_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    repository_id INTEGER,
    path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    file_hash TEXT,
    score REAL NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'retrieval'
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db(db_path: Path | None = None) -> None:
    with db_conn(db_path) as conn:
        conn.executescript(SCHEMA)

        # Forward-compatible migrations for databases created by v1.0.x.
        source_columns = {r["name"] for r in conn.execute("PRAGMA table_info(message_sources)").fetchall()}
        if "repository_id" not in source_columns:
            conn.execute("ALTER TABLE message_sources ADD COLUMN repository_id INTEGER")

        conversation_columns = {r["name"] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()}
        if "parent_conversation_id" not in conversation_columns:
            conn.execute("ALTER TABLE conversations ADD COLUMN parent_conversation_id INTEGER")
        if "branch_from_message_id" not in conversation_columns:
            conn.execute("ALTER TABLE conversations ADD COLUMN branch_from_message_id INTEGER")
        if "summary" not in conversation_columns:
            conn.execute("ALTER TABLE conversations ADD COLUMN summary TEXT NOT NULL DEFAULT ''")

        # Every legacy conversation had exactly one repository. Seed the new
        # many-repository context table without changing existing chat history.
        conn.execute(
            """
            INSERT OR IGNORE INTO conversation_repositories(conversation_id,repository_id,is_primary)
            SELECT id,repository_id,1 FROM conversations
            """
        )
        conn.execute(
            """
            UPDATE message_sources
               SET repository_id = (
                    SELECT c.repository_id
                      FROM messages m
                      JOIN conversations c ON c.id=m.conversation_id
                     WHERE m.id=message_sources.message_id
               )
             WHERE repository_id IS NULL
            """
        )


def fts_replace_chunk(conn: sqlite3.Connection, chunk_id: int, repository_id: int, path: str, name: str | None, text: str) -> None:
    conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (chunk_id,))
    conn.execute(
        "INSERT INTO chunks_fts(rowid, repository_id, path, name, text) VALUES (?, ?, ?, ?, ?)",
        (chunk_id, repository_id, path, name or "", text),
    )


def fts_delete_file_chunks(conn: sqlite3.Connection, file_id: int) -> None:
    rows = conn.execute("SELECT id FROM chunks WHERE file_id = ?", (file_id,)).fetchall()
    for row in rows:
        conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (row["id"],))


def fts_insert_message(conn: sqlite3.Connection, message_id: int, conversation_id: int, role: str, content: str) -> None:
    conn.execute("DELETE FROM messages_fts WHERE rowid = ?", (message_id,))
    conn.execute(
        "INSERT INTO messages_fts(rowid, conversation_id, role, content) VALUES (?, ?, ?, ?)",
        (message_id, conversation_id, role, content),
    )
