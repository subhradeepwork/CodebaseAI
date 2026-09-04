from pathlib import Path

import app.db as dbmod
from app.db import init_db, db_conn
from app.services import chat as chatmod
from app.services.indexer import index_repository
from app.services.repository import add_repository, sha256_text
from app.services.retrieval import RetrievedSource, retrieve, retrieve_many


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
    assert hits[0].repository_id == repo["id"]
    assert hits[0].repository_name == repo["name"]


def test_multi_repository_conversation_context_and_retrieval(monkeypatch, tmp_path: Path):
    use_temp_db(monkeypatch, tmp_path)
    frontend_dir = tmp_path / "frontend-app"
    backend_dir = tmp_path / "backend-api"
    frontend_dir.mkdir()
    backend_dir.mkdir()
    (frontend_dir / "Checkout.tsx").write_text("export function Checkout(){ return fetch('/api/payments') }\n", encoding="utf-8")
    (backend_dir / "payments.mjs").write_text("export const handler = async () => process.env.PAYMENTS_TABLE\n", encoding="utf-8")

    front = add_repository(str(frontend_dir))
    back = add_repository(str(backend_dir))
    index_repository(front["id"], embeddings=False)
    index_repository(back["id"], embeddings=False)

    conv = chatmod.create_conversation(front["id"], repository_ids=[front["id"], back["id"]])
    assert conv["repository_ids"] == [front["id"], back["id"]]

    hits = retrieve_many(conv["repository_ids"], "payments PAYMENTS_TABLE Checkout", limit=8)
    assert {h.repository_id for h in hits} == {front["id"], back["id"]}

    updated = chatmod.update_conversation(conv["id"], repository_ids=[front["id"]])
    assert updated["repository_ids"] == [front["id"]]


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
        repository_id=repo["id"],
        repository_name=repo["name"],
    )
    monkeypatch.setattr(chatmod, "retrieve_many", lambda *_args, **_kwargs: [fake_source])
    monkeypatch.setattr(chatmod.LLMClient, "chat", lambda self, messages: "Authentication is handled in `AuthService.java:1-1`.")

    result = chatmod.ask(conv["id"], "Where is authentication handled?")
    assert result["assistant_message_id"] > 0
    assert result["sources"][0]["repository_id"] == repo["id"]
    messages = chatmod.get_messages(conv["id"])
    assistant = [m for m in messages if m["role"] == "assistant"][0]
    assert assistant["sources"][0]["stale"] is False
    assert assistant["sources"][0]["repository_id"] == repo["id"]

    source_path.write_text("class AuthService { boolean authenticate(){ return false; } }\n", encoding="utf-8")
    messages = chatmod.get_messages(conv["id"])
    assistant = [m for m in messages if m["role"] == "assistant"][0]
    assert assistant["sources"][0]["stale"] is True


def test_permanent_conversation_delete_removes_messages_and_context(monkeypatch, tmp_path: Path):
    use_temp_db(monkeypatch, tmp_path)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = add_repository(str(repo_dir))
    conv = chatmod.create_conversation(repo["id"])
    with db_conn() as conn:
        conn.execute("INSERT INTO messages(conversation_id,role,content,sequence_number) VALUES (?,?,?,?)", (conv["id"], 'user', 'hello', 1))
    chatmod.delete_conversation(conv["id"])
    with db_conn() as conn:
        assert conn.execute("SELECT 1 FROM conversations WHERE id=?", (conv["id"],)).fetchone() is None
        assert conn.execute("SELECT 1 FROM messages WHERE conversation_id=?", (conv["id"],)).fetchone() is None
        assert conn.execute("SELECT 1 FROM conversation_repositories WHERE conversation_id=?", (conv["id"],)).fetchone() is None


def test_chat_uses_and_persists_sources_from_multiple_repositories(monkeypatch, tmp_path: Path):
    use_temp_db(monkeypatch, tmp_path)
    repo_a_dir = tmp_path / "ui-repo"
    repo_b_dir = tmp_path / "api-repo"
    repo_a_dir.mkdir()
    repo_b_dir.mkdir()
    a_text = "export const loadCustomer = () => fetch('/api/customer')\n"
    b_text = "export const handler = async () => ({ statusCode: 200 })\n"
    (repo_a_dir / "customer.ts").write_text(a_text, encoding="utf-8")
    (repo_b_dir / "customer.mjs").write_text(b_text, encoding="utf-8")
    repo_a = add_repository(str(repo_a_dir))
    repo_b = add_repository(str(repo_b_dir))
    index_repository(repo_a["id"], embeddings=False)
    index_repository(repo_b["id"], embeddings=False)
    conv = chatmod.create_conversation(repo_a["id"], repository_ids=[repo_a["id"], repo_b["id"]])

    sources = [
        RetrievedSource(1, "customer.ts", 1, 1, "function", "loadCustomer", a_text, 1.0, sha256_text(a_text), repo_a["id"], repo_a["name"]),
        RetrievedSource(2, "customer.mjs", 1, 1, "function", "handler", b_text, 0.9, sha256_text(b_text), repo_b["id"], repo_b["name"]),
    ]
    monkeypatch.setattr(chatmod, "retrieve_many", lambda ids, query, limit: sources)
    captured = {}

    def fake_chat(self, messages):
        captured["messages"] = messages
        return "The UI calls the API handler across the two repositories."

    monkeypatch.setattr(chatmod.LLMClient, "chat", fake_chat)
    chatmod.ask(conv["id"], "Trace the customer request")
    assert repo_a["name"] in captured["messages"][-1]["content"]
    assert repo_b["name"] in captured["messages"][-1]["content"]

    messages = chatmod.get_messages(conv["id"])
    assistant = [m for m in messages if m["role"] == "assistant"][0]
    assert {s["repository_id"] for s in assistant["sources"]} == {repo_a["id"], repo_b["id"]}
    assert {s["repository_name"] for s in assistant["sources"]} == {repo_a["name"], repo_b["name"]}
