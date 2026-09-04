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
