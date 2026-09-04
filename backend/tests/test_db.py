from pathlib import Path

from app.db import db_conn, init_db, fts_insert_message


def test_schema_message_fts_and_multi_repository_tables(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    with db_conn(db) as conn:
        rid = conn.execute("INSERT INTO repositories(name,path) VALUES ('r','/tmp/r')").lastrowid
        cid = conn.execute("INSERT INTO conversations(repository_id,title) VALUES (?,?)", (rid, 'Auth flow')).lastrowid
        # Running init_db again simulates opening a legacy database and seeds
        # the primary repository into the new context table.
    init_db(db)
    with db_conn(db) as conn:
        linked = conn.execute("SELECT repository_id,is_primary FROM conversation_repositories WHERE conversation_id=?", (cid,)).fetchone()
        assert linked is not None
        assert linked["repository_id"] == rid
        assert linked["is_primary"] == 1

        mid = conn.execute("INSERT INTO messages(conversation_id,role,content,sequence_number) VALUES (?,?,?,?)", (cid,'user','where is authentication',1)).lastrowid
        fts_insert_message(conn, mid, cid, 'user', 'where is authentication')
        hit = conn.execute("SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'authentication'").fetchone()
        assert hit is not None
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(message_sources)").fetchall()}
        assert "repository_id" in cols
        conversation_cols = {row["name"] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()}
        assert {"parent_conversation_id", "branch_from_message_id", "summary"}.issubset(conversation_cols)
        message_cols = {row["name"] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
        assert "referenced_message_id" in message_cols


def test_legacy_messages_table_is_migrated_for_reference_points(tmp_path: Path):
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE repositories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE
        );
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repository_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT 'New chat',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            archived INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sequence_number INTEGER NOT NULL,
            repository_commit TEXT
        );
        INSERT INTO repositories(id,name,path) VALUES (1,'legacy','/tmp/legacy');
        INSERT INTO conversations(id,repository_id,title) VALUES (1,1,'Existing chat');
        INSERT INTO messages(id,conversation_id,role,content,sequence_number) VALUES (1,1,'user','keep me',1);
        """
    )
    conn.commit()
    conn.close()

    init_db(db)
    with db_conn(db) as migrated:
        cols = {row["name"] for row in migrated.execute("PRAGMA table_info(messages)").fetchall()}
        assert "referenced_message_id" in cols
        row = migrated.execute("SELECT content,referenced_message_id FROM messages WHERE id=1").fetchone()
        assert row["content"] == "keep me"
        assert row["referenced_message_id"] is None
