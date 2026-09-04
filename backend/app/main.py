from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import APP_NAME, FRONTEND_DIST, HOST, LLM_MODEL, MLX_BASE_URL, OLLAMA_BASE_URL, EMBEDDING_MODEL
from .db import db_conn, init_db
from .models import ConversationBranchCreate, ConversationCreate, ConversationUpdate, IndexRequest, MessageCreate, RepositoryCreate
from .services.chat import ask, branch_conversation, create_conversation, delete_conversation, get_messages, list_conversations, update_conversation
from .services.embeddings import EmbeddingService
from .services.indexer import start_index
from .services.llm import LLMClient, LLMUnavailable
from .services.repository import (
    RepositoryError,
    add_repository,
    delete_repository_metadata,
    file_excerpt,
    get_repository,
    list_repositories,
    pick_folder_macos,
    safe_repo_file,
)

init_db()
app = FastAPI(title=APP_NAME, version=__version__, docs_url="/api/docs", redoc_url=None)


def _http_error(exc: Exception, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "app": APP_NAME, "version": __version__, "host": HOST}


@app.get("/api/system/status")
def system_status() -> dict:
    embed_ok, embed_msg = EmbeddingService().health()
    llm_ok, llm_msg = LLMClient().health()
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "ollama": {"ok": embed_ok, "message": embed_msg, "url": OLLAMA_BASE_URL, "model": EMBEDDING_MODEL},
        "mlx": {"ok": llm_ok, "message": llm_msg, "url": MLX_BASE_URL, "model": LLM_MODEL},
        "privacy": {"bind": HOST, "cloud_fallback": False, "telemetry": False},
    }


@app.post("/api/system/pick-folder")
def pick_folder() -> dict:
    try:
        return {"path": pick_folder_macos()}
    except RepositoryError as e:
        raise _http_error(e)


@app.get("/api/repositories")
def repositories() -> list[dict]:
    return list_repositories()


@app.post("/api/repositories")
def repository_create(body: RepositoryCreate) -> dict:
    try:
        return add_repository(body.path)
    except RepositoryError as e:
        raise _http_error(e)


@app.get("/api/repositories/{repository_id}")
def repository_get(repository_id: int) -> dict:
    try:
        return get_repository(repository_id)
    except RepositoryError as e:
        raise _http_error(e, 404)


@app.delete("/api/repositories/{repository_id}")
def repository_delete(repository_id: int) -> dict:
    # Deletes Codebase AI metadata only; never touches the user's repository directory.
    try:
        _ = get_repository(repository_id)
        delete_repository_metadata(repository_id)
        return {"ok": True}
    except RepositoryError as e:
        raise _http_error(e, 404)


@app.post("/api/repositories/{repository_id}/index")
def repository_index(repository_id: int, body: IndexRequest) -> dict:
    try:
        _ = get_repository(repository_id)
        started = start_index(repository_id, force=body.force, embeddings=body.embeddings)
        return {"ok": True, "started": started, "message": "Indexing started" if started else "Indexing is already running"}
    except RepositoryError as e:
        raise _http_error(e, 404)


@app.get("/api/repositories/{repository_id}/tree")
def repository_tree(repository_id: int) -> dict:
    try:
        _ = get_repository(repository_id)
    except RepositoryError as e:
        raise _http_error(e, 404)
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT path,language,size FROM files WHERE repository_id=? ORDER BY path",
            (repository_id,),
        ).fetchall()
        return {"files": [dict(r) for r in rows]}


@app.get("/api/repositories/{repository_id}/file")
def repository_file(
    repository_id: int,
    path: str = Query(..., min_length=1),
    start_line: int = Query(1, ge=1),
    end_line: int = Query(220, ge=1, le=5000),
) -> dict:
    try:
        return file_excerpt(repository_id, path, start_line, end_line)
    except (RepositoryError, OSError) as e:
        raise _http_error(e, 404)


@app.get("/api/repositories/{repository_id}/symbols")
def repository_symbols(repository_id: int, q: str = "", limit: int = Query(80, ge=1, le=500)) -> list[dict]:
    try:
        _ = get_repository(repository_id)
    except RepositoryError as e:
        raise _http_error(e, 404)
    with db_conn() as conn:
        if q.strip():
            rows = conn.execute(
                "SELECT id,path,name,kind,start_line,end_line,language,signature FROM symbols WHERE repository_id=? AND lower(name) LIKE ? ORDER BY name LIMIT ?",
                (repository_id, f"%{q.lower()}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id,path,name,kind,start_line,end_line,language,signature FROM symbols WHERE repository_id=? ORDER BY path,start_line LIMIT ?",
                (repository_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/conversations")
def conversations(repository_id: int, search: str | None = None, archived: bool = False) -> list[dict]:
    return list_conversations(repository_id, search=search, include_archived=archived)


@app.post("/api/conversations")
def conversation_create(body: ConversationCreate) -> dict:
    try:
        return create_conversation(body.repository_id, body.title, body.repository_ids)
    except (RepositoryError, ValueError) as e:
        raise _http_error(e)


@app.patch("/api/conversations/{conversation_id}")
def conversation_update(conversation_id: int, body: ConversationUpdate) -> dict:
    try:
        return update_conversation(conversation_id, body.title, body.archived, body.repository_ids)
    except ValueError as e:
        raise _http_error(e, 404)


@app.delete("/api/conversations/{conversation_id}")
def conversation_delete(conversation_id: int) -> dict:
    try:
        delete_conversation(conversation_id)
        return {"ok": True}
    except ValueError as e:
        raise _http_error(e, 404)


@app.post("/api/conversations/{conversation_id}/branch")
def conversation_branch(conversation_id: int, body: ConversationBranchCreate) -> dict:
    try:
        return branch_conversation(conversation_id, body.branch_from_message_id)
    except ValueError as e:
        raise _http_error(e, 404)


@app.get("/api/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: int) -> list[dict]:
    return get_messages(conversation_id)


@app.post("/api/conversations/{conversation_id}/messages")
def conversation_ask(conversation_id: int, body: MessageCreate) -> dict:
    try:
        return ask(conversation_id, body.content)
    except LLMUnavailable as e:
        raise HTTPException(
            status_code=503,
            detail=f"Local coding model is unavailable. Start the MLX model server and retry. Details: {e}",
        )
    except (ValueError, RepositoryError) as e:
        raise _http_error(e)


# Serve the built React app from the same localhost origin.
if FRONTEND_DIST.exists():
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str):
        # API routes that reached here genuinely do not exist.
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = (FRONTEND_DIST / full_path).resolve()
        try:
            candidate.relative_to(FRONTEND_DIST)
        except ValueError:
            candidate = FRONTEND_DIST / "index.html"
        if full_path and candidate.is_file():
            response = FileResponse(candidate)
            if candidate.name == "index.html":
                response.headers["Cache-Control"] = "no-store, max-age=0"
            return response
        response = FileResponse(FRONTEND_DIST / "index.html")
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response
else:
    @app.get("/", include_in_schema=False)
    def frontend_missing():
        return JSONResponse(
            {
                "message": "Codebase AI backend is running, but the frontend is not built yet.",
                "next": "Run ./setup.command from the project root, then ./start.command",
            }
        )
