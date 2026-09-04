from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..config import RECENT_CHAT_MESSAGES
from ..db import db_conn, fts_insert_message
from .git_utils import current_commit
from .llm import LLMClient
from .repository import get_repository, sha256_text
from .retrieval import build_context, retrieve_many

MAX_CONTEXT_REPOSITORIES = 8
MAX_REFERENCE_CONTEXT_CHARS = 16_000
MAX_REFERENCE_RETRIEVAL_CHARS = 6_000


def _title_from_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"^(can you|could you|please|tell me|explain|show me)\s+", "", cleaned, flags=re.I)
    if len(cleaned) > 52:
        cleaned = cleaned[:52].rsplit(" ", 1)[0] + "…"
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "New chat"


def _normalize_repository_ids(primary_repository_id: int, repository_ids: list[int] | None) -> list[int]:
    ids = [primary_repository_id]
    for rid in repository_ids or []:
        rid = int(rid)
        if rid not in ids:
            ids.append(rid)
    if len(ids) > MAX_CONTEXT_REPOSITORIES:
        raise ValueError(f"A conversation can use at most {MAX_CONTEXT_REPOSITORIES} repositories")
    return ids


def _validate_repository_ids(conn, repository_ids: list[int]) -> None:
    if not repository_ids:
        raise ValueError("At least one repository is required")
    placeholders = ",".join("?" for _ in repository_ids)
    rows = conn.execute(f"SELECT id FROM repositories WHERE id IN ({placeholders})", repository_ids).fetchall()
    found = {int(r["id"]) for r in rows}
    missing = [rid for rid in repository_ids if rid not in found]
    if missing:
        raise ValueError(f"Repository not found: {missing[0]}")


def _set_conversation_repositories(conn, conversation_id: int, primary_repository_id: int, repository_ids: list[int]) -> None:
    repository_ids = _normalize_repository_ids(primary_repository_id, repository_ids)
    _validate_repository_ids(conn, repository_ids)
    conn.execute("DELETE FROM conversation_repositories WHERE conversation_id=?", (conversation_id,))
    for rid in repository_ids:
        conn.execute(
            "INSERT INTO conversation_repositories(conversation_id,repository_id,is_primary) VALUES (?,?,?)",
            (conversation_id, rid, 1 if rid == primary_repository_id else 0),
        )


def _conversation_repository_ids(conn, conversation_id: int, primary_repository_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT repository_id FROM conversation_repositories WHERE conversation_id=? ORDER BY is_primary DESC, added_at, repository_id",
        (conversation_id,),
    ).fetchall()
    if not rows:
        _set_conversation_repositories(conn, conversation_id, primary_repository_id, [primary_repository_id])
        return [primary_repository_id]
    ids = [int(r["repository_id"]) for r in rows]
    if primary_repository_id not in ids:
        ids.insert(0, primary_repository_id)
    return ids


def _conversation_dict(conn, row) -> dict:
    item = dict(row)
    item["repository_ids"] = _conversation_repository_ids(conn, int(row["id"]), int(row["repository_id"]))
    return item


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
        return [_conversation_dict(conn, r) for r in rows]


def create_conversation(repository_id: int, title: str | None = None, repository_ids: list[int] | None = None) -> dict:
    _ = get_repository(repository_id)
    ids = _normalize_repository_ids(repository_id, repository_ids)
    with db_conn() as conn:
        _validate_repository_ids(conn, ids)
        cur = conn.execute(
            "INSERT INTO conversations(repository_id,title) VALUES (?,?)",
            (repository_id, title or "New chat"),
        )
        cid = int(cur.lastrowid)
        _set_conversation_repositories(conn, cid, repository_id, ids)
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        return _conversation_dict(conn, row)


def update_conversation(
    conversation_id: int,
    title: str | None = None,
    archived: bool | None = None,
    repository_ids: list[int] | None = None,
) -> dict:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not row:
            raise ValueError("Conversation not found")
        if title is not None:
            title = title.strip() or "New chat"
            conn.execute("UPDATE conversations SET title=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (title[:120], conversation_id))
        if archived is not None:
            conn.execute("UPDATE conversations SET archived=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (1 if archived else 0, conversation_id))
        if repository_ids is not None:
            ids = _normalize_repository_ids(int(row["repository_id"]), repository_ids)
            _set_conversation_repositories(conn, conversation_id, int(row["repository_id"]), ids)
            conn.execute("UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (conversation_id,))
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        return _conversation_dict(conn, row)


def delete_conversation(conversation_id: int) -> None:
    with db_conn() as conn:
        exists = conn.execute("SELECT 1 FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not exists:
            raise ValueError("Conversation not found")
        mids = conn.execute("SELECT id FROM messages WHERE conversation_id=?", (conversation_id,)).fetchall()
        for m in mids:
            conn.execute("DELETE FROM messages_fts WHERE rowid=?", (int(m["id"]),))
        conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))


def branch_conversation(conversation_id: int, branch_from_message_id: int) -> dict:
    """Create an independent conversation branch through one persisted message.

    The new conversation keeps the same repository context and copies all
    messages up to and including the selected branch point. Repository evidence
    attached to copied assistant messages is preserved as well.
    """
    with db_conn() as conn:
        parent = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not parent:
            raise ValueError("Conversation not found")

        branch_message = conn.execute(
            "SELECT * FROM messages WHERE id=? AND conversation_id=?",
            (branch_from_message_id, conversation_id),
        ).fetchone()
        if not branch_message:
            raise ValueError("Branch message not found in this conversation")

        repository_ids = _conversation_repository_ids(conn, conversation_id, int(parent["repository_id"]))
        base_title = str(parent["title"] or "New chat").strip() or "New chat"
        suffix = " (branch)"
        branch_title = base_title if base_title.endswith(suffix) else f"{base_title[:120-len(suffix)]}{suffix}"

        cur = conn.execute(
            """
            INSERT INTO conversations(
                repository_id,title,parent_conversation_id,branch_from_message_id,summary
            ) VALUES (?,?,?,?,?)
            """,
            (
                int(parent["repository_id"]),
                branch_title,
                conversation_id,
                branch_from_message_id,
                "",
            ),
        )
        branched_id = int(cur.lastrowid)
        _set_conversation_repositories(conn, branched_id, int(parent["repository_id"]), repository_ids)

        source_messages = conn.execute(
            """
            SELECT * FROM messages
             WHERE conversation_id=? AND sequence_number<=?
             ORDER BY sequence_number
            """,
            (conversation_id, int(branch_message["sequence_number"])),
        ).fetchall()

        message_id_map: dict[int, int] = {}
        for message in source_messages:
            referenced_message_id = message["referenced_message_id"] if "referenced_message_id" in message.keys() else None
            copied_reference_id = message_id_map.get(int(referenced_message_id)) if referenced_message_id is not None else None
            copied = conn.execute(
                """
                INSERT INTO messages(
                    conversation_id,role,content,created_at,sequence_number,repository_commit,referenced_message_id
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    branched_id,
                    message["role"],
                    message["content"],
                    message["created_at"],
                    int(message["sequence_number"]),
                    message["repository_commit"],
                    copied_reference_id,
                ),
            )
            copied_message_id = int(copied.lastrowid)
            message_id_map[int(message["id"])] = copied_message_id
            fts_insert_message(
                conn,
                copied_message_id,
                branched_id,
                str(message["role"]),
                str(message["content"]),
            )

            sources = conn.execute(
                """
                SELECT repository_id,path,start_line,end_line,file_hash,score,kind
                  FROM message_sources
                 WHERE message_id=?
                 ORDER BY id
                """,
                (int(message["id"]),),
            ).fetchall()
            for source in sources:
                conn.execute(
                    """
                    INSERT INTO message_sources(
                        message_id,repository_id,path,start_line,end_line,file_hash,score,kind
                    ) VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        copied_message_id,
                        source["repository_id"],
                        source["path"],
                        int(source["start_line"]),
                        int(source["end_line"]),
                        source["file_hash"],
                        float(source["score"]),
                        source["kind"],
                    ),
                )

        row = conn.execute("SELECT * FROM conversations WHERE id=?", (branched_id,)).fetchone()
        return _conversation_dict(conn, row)


def get_messages(conversation_id: int) -> list[dict]:
    with db_conn() as conn:
        conv = conn.execute("SELECT repository_id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not conv:
            return []
        primary_repository_id = int(conv["repository_id"])
        repo_path_cache: dict[int, Path | None] = {}
        repo_name_cache: dict[int, str | None] = {}

        def repo_info(repository_id: int) -> tuple[Path | None, str | None]:
            if repository_id not in repo_path_cache:
                repo = conn.execute("SELECT path,name FROM repositories WHERE id=?", (repository_id,)).fetchone()
                repo_path_cache[repository_id] = Path(repo["path"]).resolve() if repo else None
                repo_name_cache[repository_id] = repo["name"] if repo else None
            return repo_path_cache[repository_id], repo_name_cache[repository_id]

        rows = conn.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY sequence_number", (conversation_id,)).fetchall()
        out: list[dict] = []
        current_hash_cache: dict[tuple[int, str], str | None] = {}
        message_by_id = {int(r["id"]): r for r in rows}
        for row in rows:
            item = dict(row)
            reference = None
            referenced_message_id = item.get("referenced_message_id")
            if referenced_message_id is not None:
                referenced = message_by_id.get(int(referenced_message_id))
                if referenced is None:
                    referenced = conn.execute(
                        "SELECT id,role,content,sequence_number FROM messages WHERE id=? AND conversation_id=?",
                        (int(referenced_message_id), conversation_id),
                    ).fetchone()
                if referenced:
                    reference = {
                        "id": int(referenced["id"]),
                        "role": referenced["role"],
                        "content": referenced["content"],
                        "sequence_number": int(referenced["sequence_number"]),
                    }
            item["reference"] = reference
            srcs = conn.execute(
                "SELECT repository_id,path,start_line,end_line,file_hash,score,kind FROM message_sources WHERE message_id=? ORDER BY score DESC,id",
                (row["id"],),
            ).fetchall()
            rendered = []
            for source in srcs:
                src = dict(source)
                repository_id = int(src.get("repository_id") or primary_repository_id)
                repo_path, repo_name = repo_info(repository_id)
                path = src["path"]
                cache_key = (repository_id, path)
                if cache_key not in current_hash_cache:
                    current_hash: str | None = None
                    if repo_path is not None:
                        try:
                            target = (repo_path / path).resolve()
                            target.relative_to(repo_path)
                            if target.is_file():
                                current_hash = sha256_text(target.read_text("utf-8", errors="replace"))
                        except Exception:
                            current_hash = None
                    current_hash_cache[cache_key] = current_hash
                current_hash = current_hash_cache[cache_key]
                src["repository_id"] = repository_id
                src["repository_name"] = repo_name
                src["stale"] = bool(src.get("file_hash")) and current_hash != src.get("file_hash")
                rendered.append(src)
            item["sources"] = rendered
            out.append(item)
        return out


def _insert_message(conn, conversation_id: int, role: str, content: str, repo_commit: str | None, referenced_message_id: int | None = None) -> int:
    seq_row = conn.execute("SELECT COALESCE(MAX(sequence_number),0)+1 AS seq FROM messages WHERE conversation_id=?", (conversation_id,)).fetchone()
    seq = int(seq_row["seq"])
    cur = conn.execute(
        "INSERT INTO messages(conversation_id,role,content,sequence_number,repository_commit,referenced_message_id) VALUES (?,?,?,?,?,?)",
        (conversation_id, role, content, seq, repo_commit, referenced_message_id),
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


def ask(conversation_id: int, user_text: str, referenced_message_id: int | None = None) -> dict[str, Any]:
    user_text = user_text.strip()
    if not user_text:
        raise ValueError("Message is empty")

    with db_conn() as conn:
        conv = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not conv:
            raise ValueError("Conversation not found")
        primary_repo = conn.execute("SELECT * FROM repositories WHERE id=?", (conv["repository_id"],)).fetchone()
        if not primary_repo:
            raise ValueError("Repository not found")
        repository_ids = _conversation_repository_ids(conn, conversation_id, int(conv["repository_id"]))
        referenced_message = None
        if referenced_message_id is not None:
            referenced_message = conn.execute(
                "SELECT id,role,content,sequence_number FROM messages WHERE id=? AND conversation_id=?",
                (referenced_message_id, conversation_id),
            ).fetchone()
            if not referenced_message:
                raise ValueError("Referenced message not found in this conversation")
        commit = current_commit(Path(primary_repo["path"]))
        user_id = _insert_message(conn, conversation_id, "user", user_text, commit, referenced_message_id)
        if conv["title"] == "New chat":
            conn.execute("UPDATE conversations SET title=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (_title_from_text(user_text), conversation_id))
        else:
            conn.execute("UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (conversation_id,))
        history = _history_for_model(conn, conversation_id)

    reference_block = ""
    retrieval_query = user_text
    if referenced_message is not None:
        reference_text = str(referenced_message["content"])
        reference_role = "AI response" if referenced_message["role"] == "assistant" else "user message"
        truncated_reference = reference_text[:MAX_REFERENCE_CONTEXT_CHARS]
        if len(reference_text) > MAX_REFERENCE_CONTEXT_CHARS:
            truncated_reference += "\n[Reference truncated for model context.]"
        reference_block = (
            f"Reference point from earlier in this conversation ({reference_role}, message "
            f"{int(referenced_message['sequence_number'])}):\n"
            f"--- BEGIN REFERENCED MESSAGE ---\n{truncated_reference}\n--- END REFERENCED MESSAGE ---\n\n"
            "The current question explicitly refers to that message. Use it as the primary conversational reference point, "
            "while still verifying repository-specific claims against the retrieved repository evidence.\n\n"
        )
        retrieval_query = f"{user_text}\n\nReferenced conversation message:\n{reference_text[:MAX_REFERENCE_RETRIEVAL_CHARS]}"

    sources = retrieve_many(repository_ids, retrieval_query, limit=24 if len(repository_ids) > 1 else 18)
    context = build_context(sources)
    repo_names = [get_repository(rid)["name"] for rid in repository_ids]
    repo_scope = ", ".join(repo_names)
    prompt = (
        f"{reference_block}"
        f"Repository question:\n{user_text}\n\n"
        f"Active repository context: {repo_scope}.\n"
        f"Repository evidence follows. Treat it as authoritative for repository-specific facts. "
        f"When evidence comes from multiple repositories, identify the repository when that distinction matters.\n\n"
        f"{context or '[No relevant indexed source was retrieved.]'}"
    )
    model_messages = history[:-1] + [{"role": "user", "content": prompt}]
    answer = LLMClient().chat(model_messages)

    with db_conn() as conn:
        assistant_id = _insert_message(conn, conversation_id, "assistant", answer, commit)
        for s in sources:
            conn.execute(
                "INSERT INTO message_sources(message_id,repository_id,path,start_line,end_line,file_hash,score,kind) VALUES (?,?,?,?,?,?,?,?)",
                (assistant_id, s.repository_id, s.path, s.start_line, s.end_line, s.file_hash, s.score, s.kind),
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
                "repository_id": s.repository_id,
                "repository_name": s.repository_name,
            }
            for s in sources
        ],
    }
