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


def test_branch_conversation_copies_history_sources_and_repository_context(monkeypatch, tmp_path: Path):
    use_temp_db(monkeypatch, tmp_path)
    repo_a_dir = tmp_path / "repo-a"
    repo_b_dir = tmp_path / "repo-b"
    repo_a_dir.mkdir()
    repo_b_dir.mkdir()
    source_text = "export const load = () => fetch('/api/data')\n"
    (repo_a_dir / "client.ts").write_text(source_text, encoding="utf-8")
    (repo_b_dir / "handler.mjs").write_text("export const handler = async () => 1\n", encoding="utf-8")
    repo_a = add_repository(str(repo_a_dir))
    repo_b = add_repository(str(repo_b_dir))
    conv = chatmod.create_conversation(repo_a["id"], title="Trace data flow", repository_ids=[repo_a["id"], repo_b["id"]])

    with db_conn() as conn:
        m1 = chatmod._insert_message(conn, conv["id"], "user", "How does data flow?", "abc123")
        m2 = chatmod._insert_message(conn, conv["id"], "assistant", "It starts in client.ts.", "abc123")
        conn.execute(
            "INSERT INTO message_sources(message_id,repository_id,path,start_line,end_line,file_hash,score,kind) VALUES (?,?,?,?,?,?,?,?)",
            (m2, repo_a["id"], "client.ts", 1, 1, sha256_text(source_text), 0.9, "function"),
        )
        m3 = chatmod._insert_message(conn, conv["id"], "user", "What happens next?", "abc123")
        chatmod._insert_message(conn, conv["id"], "assistant", "This answer should not be copied.", "abc123")

    branch = chatmod.branch_conversation(conv["id"], m3)
    assert branch["parent_conversation_id"] == conv["id"]
    assert branch["branch_from_message_id"] == m3
    assert branch["repository_ids"] == [repo_a["id"], repo_b["id"]]
    assert branch["title"] == "Trace data flow (branch)"

    branched_messages = chatmod.get_messages(branch["id"])
    assert [m["content"] for m in branched_messages] == [
        "How does data flow?",
        "It starts in client.ts.",
        "What happens next?",
    ]
    assert branched_messages[1]["sources"][0]["path"] == "client.ts"
    assert branched_messages[1]["sources"][0]["repository_id"] == repo_a["id"]

    with db_conn() as conn:
        copied_ids = [int(r["id"]) for r in conn.execute("SELECT id FROM messages WHERE conversation_id=? ORDER BY sequence_number", (branch["id"],)).fetchall()]
        fts_rows = conn.execute(
            "SELECT rowid FROM messages_fts WHERE conversation_id=? ORDER BY rowid",
            (branch["id"],),
        ).fetchall()
        assert {int(r["rowid"]) for r in fts_rows} == set(copied_ids)

    # The branch is independent: adding to it does not mutate the parent history.
    with db_conn() as conn:
        chatmod._insert_message(conn, branch["id"], "assistant", "Branch-only continuation", "abc123")
        parent_count = conn.execute("SELECT COUNT(*) AS n FROM messages WHERE conversation_id=?", (conv["id"],)).fetchone()["n"]
        branch_count = conn.execute("SELECT COUNT(*) AS n FROM messages WHERE conversation_id=?", (branch["id"],)).fetchone()["n"]
    assert parent_count == 4
    assert branch_count == 4


def test_branch_conversation_rejects_message_from_another_chat(monkeypatch, tmp_path: Path):
    use_temp_db(monkeypatch, tmp_path)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = add_repository(str(repo_dir))
    first = chatmod.create_conversation(repo["id"])
    second = chatmod.create_conversation(repo["id"])
    with db_conn() as conn:
        foreign_message = chatmod._insert_message(conn, second["id"], "user", "not in the first chat", None)
    try:
        chatmod.branch_conversation(first["id"], foreign_message)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "Branch message not found" in str(exc)



def test_reference_point_is_persisted_and_promoted_into_model_context(monkeypatch, tmp_path: Path):
    use_temp_db(monkeypatch, tmp_path)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "service.ts").write_text("export const loadCustomer = () => fetch('/api/customer')\n", encoding="utf-8")
    repo = add_repository(str(repo_dir))
    index_repository(repo["id"], embeddings=False)
    conv = chatmod.create_conversation(repo["id"])

    with db_conn() as conn:
        chatmod._insert_message(conn, conv["id"], "user", "How should customer loading work?", "abc123")
        reference_id = chatmod._insert_message(
            conn,
            conv["id"],
            "assistant",
            "Use loadCustomer in service.ts and keep transformation in the service layer.",
            "abc123",
        )

    captured = {}

    def fake_retrieve(ids, query, limit):
        captured["retrieval_query"] = query
        return []

    def fake_chat(self, messages):
        captured["model_messages"] = messages
        return "That referenced approach can be extended safely."

    monkeypatch.setattr(chatmod, "retrieve_many", fake_retrieve)
    monkeypatch.setattr(chatmod.LLMClient, "chat", fake_chat)

    result = chatmod.ask(conv["id"], "What if we also need caching?", reference_id)
    assert result["user_message_id"] > 0
    assert "Use loadCustomer in service.ts" in captured["retrieval_query"]
    prompt = captured["model_messages"][-1]["content"]
    assert "Reference point from earlier in this conversation" in prompt
    assert "Use loadCustomer in service.ts" in prompt
    assert "What if we also need caching?" in prompt

    messages = chatmod.get_messages(conv["id"])
    referenced_user = [m for m in messages if m["id"] == result["user_message_id"]][0]
    assert referenced_user["referenced_message_id"] == reference_id
    assert referenced_user["reference"]["id"] == reference_id
    assert referenced_user["reference"]["role"] == "assistant"
    assert "transformation in the service layer" in referenced_user["reference"]["content"]


def test_reference_point_rejects_message_from_another_conversation(monkeypatch, tmp_path: Path):
    use_temp_db(monkeypatch, tmp_path)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = add_repository(str(repo_dir))
    first = chatmod.create_conversation(repo["id"])
    second = chatmod.create_conversation(repo["id"])
    with db_conn() as conn:
        foreign_id = chatmod._insert_message(conn, second["id"], "assistant", "foreign answer", None)

    try:
        chatmod.ask(first["id"], "Refer to that", foreign_id)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "Referenced message not found" in str(exc)

    with db_conn() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM messages WHERE conversation_id=?", (first["id"],)).fetchone()["n"]
    assert count == 0


def test_branch_preserves_reference_point_relationship(monkeypatch, tmp_path: Path):
    use_temp_db(monkeypatch, tmp_path)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = add_repository(str(repo_dir))
    conv = chatmod.create_conversation(repo["id"], title="Reference branch")

    with db_conn() as conn:
        first_user = chatmod._insert_message(conn, conv["id"], "user", "Initial question", None)
        first_answer = chatmod._insert_message(conn, conv["id"], "assistant", "Initial answer", None)
        follow_up = chatmod._insert_message(conn, conv["id"], "user", "Expand this idea", None, first_answer)
        branch_point = chatmod._insert_message(conn, conv["id"], "assistant", "Expanded answer", None)

    branch = chatmod.branch_conversation(conv["id"], branch_point)
    branched_messages = chatmod.get_messages(branch["id"])
    copied_first_answer = branched_messages[1]
    copied_follow_up = branched_messages[2]
    assert copied_follow_up["reference"] is not None
    assert copied_follow_up["reference"]["id"] == copied_first_answer["id"]
    assert copied_follow_up["reference"]["content"] == "Initial answer"
    assert copied_follow_up["referenced_message_id"] == copied_first_answer["id"]
