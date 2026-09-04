from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any

import numpy as np

from ..config import EMBED_BATCH_SIZE, EMBEDDING_MODEL, INDEX_EMBEDDINGS
from ..db import db_conn, fts_delete_file_chunks, fts_replace_chunk
from .embeddings import EmbeddingService, EmbeddingUnavailable, embedding_cache
from .git_utils import current_commit
from .parser import ParseResult, parse_source
from .repository import discover_files, get_repository, read_text_file, sha256_text


_INDEX_THREADS: dict[int, threading.Thread] = {}
_INDEX_LOCK = threading.RLock()


def _set_status(repository_id: int, status: str, message: str) -> None:
    with db_conn() as conn:
        conn.execute(
            "UPDATE repositories SET status=?, status_message=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, message, repository_id),
        )


def _chunk_embedding_text(path: str, kind: str, name: str | None, text: str) -> str:
    prefix = f"File: {path}\nKind: {kind}\n"
    if name:
        prefix += f"Symbol: {name}\n"
    return (prefix + text)[:16000]


def _insert_parsed_file(conn, repository_id: int, repo: Path, path: Path, text: str, parsed: ParseResult) -> tuple[int, int, int, list[int]]:
    rel = str(path.relative_to(repo))
    stat = path.stat()
    content_hash = sha256_text(text)
    old = conn.execute("SELECT id FROM files WHERE repository_id=? AND path=?", (repository_id, rel)).fetchone()
    if old:
        file_id = int(old["id"])
        fts_delete_file_chunks(conn, file_id)
        conn.execute("DELETE FROM edges WHERE repository_id=? AND source_symbol_id IN (SELECT id FROM symbols WHERE file_id=?)", (repository_id, file_id))
        conn.execute("DELETE FROM chunks WHERE file_id=?", (file_id,))
        conn.execute("DELETE FROM symbols WHERE file_id=?", (file_id,))
        conn.execute(
            "UPDATE files SET content_hash=?, mtime=?, size=?, language=?, indexed_at=CURRENT_TIMESTAMP WHERE id=?",
            (content_hash, stat.st_mtime, stat.st_size, parsed.language, file_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO files(repository_id,path,content_hash,mtime,size,language) VALUES (?,?,?,?,?,?)",
            (repository_id, rel, content_hash, stat.st_mtime, stat.st_size, parsed.language),
        )
        file_id = int(cur.lastrowid)

    symbol_ids: list[int] = []
    for symbol in parsed.symbols:
        meta = dict(symbol.metadata)
        if parsed.metadata:
            # File-level framework facts are useful with every symbol without duplicating raw source.
            for key in ("package", "annotations", "aws_sdk_packages", "environment_variables", "is_lambda_handler", "feature_calls", "java_types"):
                if key in parsed.metadata and key not in meta:
                    meta[key] = parsed.metadata[key]
        cur = conn.execute(
            """INSERT INTO symbols(repository_id,file_id,path,name,qualified_name,kind,start_line,end_line,language,signature,metadata_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                repository_id, file_id, rel, symbol.name, symbol.qualified_name or symbol.name, symbol.kind,
                symbol.start_line, symbol.end_line, symbol.language, symbol.signature, json.dumps(meta, ensure_ascii=False),
            ),
        )
        symbol_ids.append(int(cur.lastrowid))

    chunk_ids: list[int] = []
    for chunk in parsed.chunks:
        symbol_id = symbol_ids[chunk.symbol_index] if chunk.symbol_index is not None and chunk.symbol_index < len(symbol_ids) else None
        chash = hashlib.sha256((rel + str(chunk.start_line) + chunk.text).encode("utf-8", errors="replace")).hexdigest()
        cur = conn.execute(
            """INSERT INTO chunks(repository_id,file_id,symbol_id,path,start_line,end_line,language,kind,name,text,content_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                repository_id, file_id, symbol_id, rel, chunk.start_line, chunk.end_line,
                chunk.language, chunk.kind, chunk.name, chunk.text, chash,
            ),
        )
        chunk_id = int(cur.lastrowid)
        fts_replace_chunk(conn, chunk_id, repository_id, rel, chunk.name, chunk.text)
        chunk_ids.append(chunk_id)

    return file_id, len(symbol_ids), len(chunk_ids), chunk_ids


def _delete_removed_files(conn, repository_id: int, current_rel_paths: set[str]) -> int:
    rows = conn.execute("SELECT id,path FROM files WHERE repository_id=?", (repository_id,)).fetchall()
    removed = 0
    for row in rows:
        if row["path"] not in current_rel_paths:
            fts_delete_file_chunks(conn, int(row["id"]))
            conn.execute("DELETE FROM files WHERE id=?", (row["id"],))
            removed += 1
    return removed


def _build_reference_edges(conn, repository_id: int) -> int:
    conn.execute("DELETE FROM edges WHERE repository_id=?", (repository_id,))
    rows = conn.execute("SELECT id,name,path FROM symbols WHERE repository_id=?", (repository_id,)).fetchall()
    by_name: dict[str, list[int]] = {}
    for row in rows:
        name = row["name"]
        if len(name) >= 3:
            by_name.setdefault(name, []).append(int(row["id"]))
    unique = {name: ids[0] for name, ids in by_name.items() if len(ids) == 1}
    count = 0
    chunk_rows = conn.execute(
        "SELECT symbol_id,text FROM chunks WHERE repository_id=? AND symbol_id IS NOT NULL AND kind!='file_window'",
        (repository_id,),
    ).fetchall()
    for chunk in chunk_rows:
        source_id = int(chunk["symbol_id"])
        tokens = set(re.findall(r"\b[A-Za-z_$][A-Za-z0-9_$]{2,}\b", chunk["text"]))
        for token in tokens:
            target_id = unique.get(token)
            if target_id and target_id != source_id:
                conn.execute(
                    "INSERT INTO edges(repository_id,source_symbol_id,target_symbol_id,target_name,kind) VALUES (?,?,?,?,?)",
                    (repository_id, source_id, target_id, token, "reference"),
                )
                count += 1
    return count


def _embed_chunk_ids(repository_id: int, chunk_ids: list[int], service: EmbeddingService) -> tuple[int, str | None]:
    if not chunk_ids:
        return 0, None
    embedded = 0
    with db_conn() as conn:
        for start in range(0, len(chunk_ids), EMBED_BATCH_SIZE):
            batch_ids = chunk_ids[start : start + EMBED_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch_ids)
            rows = conn.execute(
                f"SELECT id,path,kind,name,text FROM chunks WHERE id IN ({placeholders}) ORDER BY id",
                batch_ids,
            ).fetchall()
            if not rows:
                continue
            texts = [_chunk_embedding_text(r["path"], r["kind"], r["name"], r["text"]) for r in rows]
            try:
                vectors = service.embed(texts)
            except EmbeddingUnavailable as e:
                return embedded, str(e)
            if len(vectors) != len(rows):
                return embedded, "Embedding service returned an unexpected batch size"
            for row, vec in zip(rows, vectors):
                arr = np.asarray(vec, dtype=np.float32)
                conn.execute(
                    "UPDATE chunks SET embedding=?, embedding_dim=?, embedded_model=? WHERE id=?",
                    (arr.tobytes(), int(arr.size), service.model, int(row["id"])),
                )
                embedded += 1
            conn.commit()
            _set_status(repository_id, "indexing", f"Semantic indexing: {embedded}/{len(chunk_ids)} changed chunks")
    return embedded, None


def index_repository(repository_id: int, force: bool = False, embeddings: bool = True) -> None:
    repo_row = get_repository(repository_id)
    repo = Path(repo_row["path"]).resolve()
    _set_status(repository_id, "indexing", "Scanning repository…")
    changed_chunk_ids: list[int] = []
    try:
        files = discover_files(repo)
        current_rel = {str(p.relative_to(repo)) for p in files}
        changed_files = 0
        total_symbols_delta = 0
        total_chunks_delta = 0
        with db_conn() as conn:
            existing = {
                r["path"]: r
                for r in conn.execute("SELECT id,path,content_hash,mtime,size FROM files WHERE repository_id=?", (repository_id,)).fetchall()
            }
            _delete_removed_files(conn, repository_id, current_rel)

            for idx, path in enumerate(files, start=1):
                rel = str(path.relative_to(repo))
                try:
                    stat = path.stat()
                except OSError:
                    continue
                prior = existing.get(rel)
                if not force and prior and float(prior["mtime"]) == stat.st_mtime and int(prior["size"]) == stat.st_size:
                    if idx % 100 == 0:
                        conn.execute("UPDATE repositories SET status='indexing',status_message=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (f"Scanning: {idx}/{len(files)} files", repository_id))
                        conn.commit()
                    continue
                text = read_text_file(path)
                if text is None:
                    continue
                content_hash = sha256_text(text)
                if not force and prior and prior["content_hash"] == content_hash:
                    conn.execute("UPDATE files SET mtime=?,size=? WHERE id=?", (stat.st_mtime, stat.st_size, int(prior["id"])))
                    continue
                parsed = parse_source(rel, text)
                _, sym_count, chunk_count, chunk_ids = _insert_parsed_file(conn, repository_id, repo, path, text, parsed)
                changed_files += 1
                total_symbols_delta += sym_count
                total_chunks_delta += chunk_count
                changed_chunk_ids.extend(chunk_ids)
                if changed_files % 15 == 0:
                    conn.execute("UPDATE repositories SET status='indexing',status_message=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (f"Parsed {changed_files} changed files ({idx}/{len(files)} scanned)", repository_id))
                    conn.commit()

            conn.execute("UPDATE repositories SET status='indexing',status_message='Building symbol/reference graph…',updated_at=CURRENT_TIMESTAMP WHERE id=?", (repository_id,))
            _build_reference_edges(conn, repository_id)
            conn.commit()

        semantic_ready = 0
        semantic_message: str | None = None
        if embeddings and INDEX_EMBEDDINGS:
            service = EmbeddingService()
            # Include any chunks that were previously left without embeddings (for example if Ollama
            # was offline during an earlier index), not only chunks changed in this pass.
            with db_conn() as conn:
                missing_rows = conn.execute(
                    "SELECT id FROM chunks WHERE repository_id=? AND (embedding IS NULL OR embedded_model IS NULL OR embedded_model!=?) ORDER BY id",
                    (repository_id, service.model),
                ).fetchall()
            to_embed = sorted(set(changed_chunk_ids) | {int(r["id"]) for r in missing_rows})
            _set_status(repository_id, "indexing", f"Semantic indexing {len(to_embed)} chunks…")
            ok, health_msg = service.health()
            if ok:
                _, semantic_message = _embed_chunk_ids(repository_id, to_embed, service)
                with db_conn() as conn:
                    stats = conn.execute(
                        "SELECT COUNT(*) AS total, SUM(CASE WHEN embedding IS NULL OR embedded_model IS NULL OR embedded_model!=? THEN 1 ELSE 0 END) AS missing FROM chunks WHERE repository_id=?",
                        (service.model, repository_id),
                    ).fetchone()
                    semantic_ready = 1 if semantic_message is None and int(stats["total"] or 0) > 0 and int(stats["missing"] or 0) == 0 else 0
            else:
                semantic_message = health_msg

        embedding_cache.invalidate(repository_id)
        commit = current_commit(repo)
        with db_conn() as conn:
            counts = conn.execute(
                "SELECT (SELECT COUNT(*) FROM files WHERE repository_id=?) AS files, (SELECT COUNT(*) FROM chunks WHERE repository_id=?) AS chunks, (SELECT COUNT(*) FROM symbols WHERE repository_id=?) AS symbols",
                (repository_id, repository_id, repository_id),
            ).fetchone()
            final_message = f"Ready — {counts['files']} files, {counts['symbols']} symbols, {counts['chunks']} chunks"
            if semantic_message:
                final_message += f". Semantic search unavailable: {semantic_message}"
            conn.execute(
                """UPDATE repositories SET status='ready',status_message=?,last_indexed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP,
                   total_files=?,total_chunks=?,total_symbols=?,git_commit=?,embedding_model=?,semantic_ready=? WHERE id=?""",
                (final_message, counts["files"], counts["chunks"], counts["symbols"], commit, EMBEDDING_MODEL, semantic_ready, repository_id),
            )
    except Exception as e:
        _set_status(repository_id, "error", f"Indexing failed: {type(e).__name__}: {e}")
        raise
    finally:
        with _INDEX_LOCK:
            _INDEX_THREADS.pop(repository_id, None)


def start_index(repository_id: int, force: bool = False, embeddings: bool = True) -> bool:
    with _INDEX_LOCK:
        existing = _INDEX_THREADS.get(repository_id)
        if existing and existing.is_alive():
            return False
        thread = threading.Thread(
            target=index_repository,
            args=(repository_id, force, embeddings),
            daemon=True,
            name=f"repo-index-{repository_id}",
        )
        _INDEX_THREADS[repository_id] = thread
        thread.start()
        return True
