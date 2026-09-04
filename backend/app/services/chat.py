from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..config import RECENT_CHAT_MESSAGES
from ..db import db_conn, fts_insert_message
from .git_utils import current_commit
from .llm import LLMClient, LLMUnavailable
from .repository import get_repository, sha256_text
from .retrieval import RetrievedSource, build_context, retrieve


def _title_from_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"^(can you|could you|please|tell me|explain|show me)\s+", "", cleaned, flags=re.I)
    if len(cleaned) > 52:
        cleaned = cleaned[:52].rsplit(" ", 1)[0] + "…"
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "New chat"


def list_conversations(repository_id: int, search: str | None = None, include_archived: bool = False) -> list[dict]:
    with db_conn() as conn:
        if search:
            like = f"%{search.lower()}%"
            rows = conn.execute(
                """
                SELECT DISTINCT c.* FROM conversations c
                LEFT JOIN messages m ON m.conversation_id=c.id
                WHERE c.repository_id=? AND (? OR c.archived=0)
                  AND (lower(c.title) LIKE ? OR lower(m.content) LIKE ?)
                ORDER BY c.updated_at DESC
                LIMIT 200
                """,
                (repository_id, 1 if include_archived else 0, like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM conversations WHERE repository_id=? AND (? OR archived=0) ORDER BY updated_at DESC LIMIT 200",
                (repository_id, 1 if include_archived else 0),
            ).fetchall()
        return [dict(r) for r in rows]


def create_conversation(repository_id: int, title: str | None = None) -> dict:
    _ = get_repository(repository_id)
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO conversations(repository_id,title) VALUES (?,?)",
            (repository_id, title or "New chat"),
        )
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (int(cur.lastrowid),)).fetchone()
        return dict(row)


def update_conversation(conversation_id: int, title: str | None = None, archived: bool | None = None) -> dict:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not row:
            raise ValueError("Conversation not found")
        if title is not None:
            title = title.strip() or "New chat"
            conn.execute("UPDATE conversations SET title=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (title[:120], conversation_id))
        if archived is not None:
            conn.execute("UPDATE conversations SET archived=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (1 if archived else 0, conversation_id))
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        return dict(row)


def delete_conversation(conversation_id: int) -> None:
    with db_conn() as conn:
        mids = conn.execute("SELECT id FROM messages WHERE conversation_id=?", (conversation_id,)).fetchall()
        for m in mids:
            conn.execute("DELETE FROM messages_fts WHERE rowid=?", (int(m["id"]),))
        conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))


def get_messages(conversation_id: int) -> list[dict]:
    with db_conn() as conn:
        conv = conn.execute("SELECT repository_id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not conv:
            return []
        repo = conn.execute("SELECT path FROM repositories WHERE id=?", (conv["repository_id"],)).fetchone()
        repo_path = Path(repo["path"]).resolve() if repo else None
        rows = conn.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY sequence_number", (conversation_id,)).fetchall()
        out: list[dict] = []
        current_hash_cache: dict[str, str | None] = {}
        for row in rows:
            item = dict(row)
            srcs = conn.execute(
                "SELECT path,start_line,end_line,file_hash,score,kind FROM message_sources WHERE message_id=? ORDER BY score DESC,id",
                (row["id"],),
            ).fetchall()
            rendered = []
            for source in srcs:
                src = dict(source)
                path = src["path"]
                if path not in current_hash_cache:
                    current_hash: str | None = None
                    if repo_path is not None:
                        try:
                            target = (repo_path / path).resolve()
                            target.relative_to(repo_path)
                            if target.is_file():
                                current_hash = sha256_text(target.read_text("utf-8", errors="replace"))
                        except Exception:
                            current_hash = None
                    current_hash_cache[path] = current_hash
                current_hash = current_hash_cache[path]
                src["stale"] = bool(src.get("file_hash")) and current_hash != src.get("file_hash")
                rendered.append(src)
            item["sources"] = rendered
            out.append(item)
        return out


def _insert_message(conn, conversation_id: int, role: str, content: str, repo_commit: str | None) -> int:
    seq_row = conn.execute("SELECT COALESCE(MAX(sequence_number),0)+1 AS seq FROM messages WHERE conversation_id=?", (conversation_id,)).fetchone()
    seq = int(seq_row["seq"])
    cur = conn.execute(
        "INSERT INTO messages(conversation_id,role,content,sequence_number,repository_commit) VALUES (?,?,?,?,?)",
        (conversation_id, role, content, seq, repo_commit),
    )
    mid = int(cur.lastrowid)
    fts_insert_message(conn, mid, conversation_id, role, content)
    return mid


def _history_for_model(conn, conversation_id: int) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT role,content FROM messages WHERE conversation_id=? ORDER BY sequence_number DESC LIMIT ?",
        (conversation_id, RECENT_CHAT_MESSAGES),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows) if r["role"] in {"user", "assistant"}]


def ask(conversation_id: int, user_text: str) -> dict[str, Any]:
    user_text = user_text.strip()
    if not user_text:
        raise ValueError("Message is empty")

    with db_conn() as conn:
        conv = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not conv:
            raise ValueError("Conversation not found")
        repo = conn.execute("SELECT * FROM repositories WHERE id=?", (conv["repository_id"],)).fetchone()
        if not repo:
            raise ValueError("Repository not found")
        repo_path = Path(repo["path"])
        commit = current_commit(repo_path)
        user_id = _insert_message(conn, conversation_id, "user", user_text, commit)
        if conv["title"] == "New chat":
            conn.execute("UPDATE conversations SET title=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (_title_from_text(user_text), conversation_id))
        else:
            conn.execute("UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (conversation_id,))
        history = _history_for_model(conn, conversation_id)

    sources = retrieve(int(conv["repository_id"]), user_text, limit=18)
    context = build_context(sources)
    prompt = (
        f"Repository question:\n{user_text}\n\n"
        f"Current repository evidence follows. Treat it as authoritative for repository-specific facts.\n\n{context or '[No relevant indexed source was retrieved.]'}"
    )
    # Replace the last user message sent to the model with the augmented grounded prompt, while keeping the persisted transcript clean.
    model_messages = history[:-1] + [{"role": "user", "content": prompt}]
    answer = LLMClient().chat(model_messages)

    with db_conn() as conn:
        assistant_id = _insert_message(conn, conversation_id, "assistant", answer, commit)
        for s in sources:
            conn.execute(
                "INSERT INTO message_sources(message_id,path,start_line,end_line,file_hash,score,kind) VALUES (?,?,?,?,?,?,?)",
                (assistant_id, s.path, s.start_line, s.end_line, s.file_hash, s.score, s.kind),
            )
        conn.execute("UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (conversation_id,))

    return {
        "user_message_id": user_id,
        "assistant_message_id": assistant_id,
        "content": answer,
        "sources": [
            {
                "path": s.path,
                "start_line": s.start_line,
                "end_line": s.end_line,
                "score": s.score,
                "kind": s.kind,
                "stale": False,
            }
            for s in sources
        ],
    }
