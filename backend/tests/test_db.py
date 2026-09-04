from pathlib import Path

from app.db import db_conn, init_db, fts_insert_message


def test_schema_and_message_fts(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    with db_conn(db) as conn:
        rid = conn.execute("INSERT INTO repositories(name,path) VALUES ('r','/tmp/r')").lastrowid
        cid = conn.execute("INSERT INTO conversations(repository_id,title) VALUES (?,?)", (rid, 'Auth flow')).lastrowid
        mid = conn.execute("INSERT INTO messages(conversation_id,role,content,sequence_number) VALUES (?,?,?,?)", (cid,'user','where is authentication',1)).lastrowid
        fts_insert_message(conn, mid, cid, 'user', 'where is authentication')
        hit = conn.execute("SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'authentication'").fetchone()
        assert hit is not None
