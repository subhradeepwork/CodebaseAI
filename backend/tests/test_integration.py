from pathlib import Path

import app.db as dbmod
from app.db import init_db, db_conn
from app.services import chat as chatmod
from app.services.indexer import index_repository
from app.services.repository import add_repository, sha256_text
from app.services.retrieval import RetrievedSource, retrieve


def use_temp_db(monkeypatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "codebase-ai-test.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    init_db()
    return db_path


def test_indexer_and_lexical_retrieval(monkeypatch, tmp_path: Path):
    use_temp_db(monkeypatch, tmp_path)
    repo_dir = tmp_path / "repo"
    (repo_dir / "lambdaBackend").mkdir(parents=True)
    (repo_dir / "lambdaBackend" / "customer.mjs").write_text(
        "import { DynamoDBClient } from '@aws-sdk/client-dynamodb';\n"
        "export const handler = async () => process.env.CUSTOMER_TABLE;\n",
        encoding="utf-8",
    )
    repo = add_repository(str(repo_dir))
    index_repository(repo["id"], embeddings=False)

    with db_conn() as conn:
        row = conn.execute("SELECT status,total_files,total_symbols FROM repositories WHERE id=?", (repo["id"],)).fetchone()
        assert row["status"] == "ready"
        assert row["total_files"] == 1
        assert row["total_symbols"] >= 1

    hits = retrieve(repo["id"], "Which Lambda uses CUSTOMER_TABLE?", limit=5)
    assert hits
    assert hits[0].path == "lambdaBackend/customer.mjs"


def test_chat_persistence_and_source_staleness(monkeypatch, tmp_path: Path):
    use_temp_db(monkeypatch, tmp_path)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    source_path = repo_dir / "AuthService.java"
    original = "class AuthService { boolean authenticate(){ return true; } }\n"
    source_path.write_text(original, encoding="utf-8")
    repo = add_repository(str(repo_dir))
    index_repository(repo["id"], embeddings=False)
    conv = chatmod.create_conversation(repo["id"])

    fake_source = RetrievedSource(
        chunk_id=1,
        path="AuthService.java",
        start_line=1,
        end_line=1,
        kind="class",
        name="AuthService",
        text=original,
        score=1.0,
        file_hash=sha256_text(original),
    )
    monkeypatch.setattr(chatmod, "retrieve", lambda *_args, **_kwargs: [fake_source])
    monkeypatch.setattr(chatmod.LLMClient, "chat", lambda self, messages: "Authentication is handled in `AuthService.java:1-1`.")

    result = chatmod.ask(conv["id"], "Where is authentication handled?")
    assert result["assistant_message_id"] > 0
    messages = chatmod.get_messages(conv["id"])
    assistant = [m for m in messages if m["role"] == "assistant"][0]
    assert assistant["sources"][0]["stale"] is False

    source_path.write_text("class AuthService { boolean authenticate(){ return false; } }\n", encoding="utf-8")
    messages = chatmod.get_messages(conv["id"])
    assistant = [m for m in messages if m["role"] == "assistant"][0]
    assert assistant["sources"][0]["stale"] is True
