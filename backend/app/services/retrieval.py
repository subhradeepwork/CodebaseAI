from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..config import MODEL_CONTEXT_CHAR_BUDGET
from ..db import db_conn
from .embeddings import EmbeddingService, EmbeddingUnavailable, embedding_cache
from .repository import get_repository, read_text_file


@dataclass
class RetrievedSource:
    chunk_id: int
    path: str
    start_line: int
    end_line: int
    kind: str
    name: str
    text: str
    score: float
    file_hash: str | None = None


def _query_tokens(query: str) -> list[str]:
    toks = re.findall(r"[A-Za-z_$][A-Za-z0-9_.$/-]{1,}|\d+", query)
    seen: set[str] = set()
    out: list[str] = []
    for t in toks:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out[:12]


def _fts_query(query: str) -> str:
    toks = _query_tokens(query)
    if not toks:
        return '""'
    escaped = [t.replace('"', '""') for t in toks if len(t) >= 2]
    return " OR ".join(f'"{t}"' for t in escaped[:10])


def _rrf_add(scores: dict[int, float], ids: list[int], weight: float, k: float = 60.0) -> None:
    for rank, cid in enumerate(ids, start=1):
        scores[cid] += weight / (k + rank)


def _lexical_candidates(conn, repository_id: int, query: str, limit: int = 30) -> list[int]:
    fq = _fts_query(query)
    if fq == '""':
        return []
    try:
        rows = conn.execute(
            "SELECT rowid FROM chunks_fts WHERE repository_id=? AND chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
            (repository_id, fq, limit),
        ).fetchall()
        return [int(r["rowid"]) for r in rows]
    except Exception:
        # Safe fallback for punctuation-heavy user questions.
        rows = conn.execute(
            "SELECT id FROM chunks WHERE repository_id=? AND lower(text) LIKE ? LIMIT ?",
            (repository_id, f"%{query.lower()[:120]}%", limit),
        ).fetchall()
        return [int(r["id"]) for r in rows]


def _symbol_candidates(conn, repository_id: int, query: str, limit: int = 25) -> list[int]:
    tokens = [t for t in _query_tokens(query) if len(t) >= 3]
    if not tokens:
        return []
    scored: list[tuple[float, int]] = []
    rows = conn.execute(
        "SELECT s.id AS symbol_id,s.name,s.kind,c.id AS chunk_id FROM symbols s JOIN chunks c ON c.symbol_id=s.id WHERE s.repository_id=?",
        (repository_id,),
    ).fetchall()
    qlow = query.lower()
    for r in rows:
        name = r["name"] or ""
        nlow = name.lower()
        score = 0.0
        if nlow and nlow in qlow:
            score += 3.0
        for tok in tokens:
            tl = tok.lower()
            if nlow == tl:
                score += 5.0
            elif tl in nlow or nlow in tl:
                score += 1.5
        if score:
            scored.append((score, int(r["chunk_id"])))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [cid for _, cid in scored[:limit]]


def _semantic_candidates(conn, repository_id: int, query: str, limit: int = 30) -> list[int]:
    repo = conn.execute("SELECT semantic_ready FROM repositories WHERE id=?", (repository_id,)).fetchone()
    if not repo or not int(repo["semantic_ready"]):
        return []
    try:
        qvec = np.asarray(EmbeddingService().embed(query)[0], dtype=np.float32)
    except EmbeddingUnavailable:
        return []
    ids, matrix = embedding_cache.get_or_build(conn, repository_id)
    if matrix.size == 0 or qvec.size != matrix.shape[1]:
        return []
    sims = matrix @ qvec
    if sims.size <= limit:
        order = np.argsort(-sims)
    else:
        part = np.argpartition(-sims, limit - 1)[:limit]
        order = part[np.argsort(-sims[part])]
    return [ids[int(i)] for i in order]


def _graph_expand(conn, repository_id: int, seed_chunk_ids: list[int], limit: int = 20) -> list[int]:
    if not seed_chunk_ids:
        return []
    placeholders = ",".join("?" for _ in seed_chunk_ids)
    seed_symbols = conn.execute(
        f"SELECT DISTINCT symbol_id FROM chunks WHERE id IN ({placeholders}) AND symbol_id IS NOT NULL",
        seed_chunk_ids,
    ).fetchall()
    symbol_ids = [int(r["symbol_id"]) for r in seed_symbols]
    if not symbol_ids:
        return []
    ph = ",".join("?" for _ in symbol_ids)
    rows = conn.execute(
        f"""
        SELECT DISTINCT c.id
        FROM edges e
        JOIN chunks c ON c.symbol_id = CASE
            WHEN e.source_symbol_id IN ({ph}) THEN e.target_symbol_id
            ELSE e.source_symbol_id END
        WHERE e.repository_id=?
          AND (e.source_symbol_id IN ({ph}) OR e.target_symbol_id IN ({ph}))
          AND c.id IS NOT NULL
        LIMIT ?
        """,
        (*symbol_ids, repository_id, *symbol_ids, *symbol_ids, limit),
    ).fetchall()
    return [int(r["id"]) for r in rows]


def retrieve(repository_id: int, query: str, limit: int = 12) -> list[RetrievedSource]:
    with db_conn() as conn:
        scores: dict[int, float] = defaultdict(float)
        lexical = _lexical_candidates(conn, repository_id, query)
        symbol = _symbol_candidates(conn, repository_id, query)
        semantic = _semantic_candidates(conn, repository_id, query)
        _rrf_add(scores, lexical, 1.25)
        _rrf_add(scores, symbol, 1.6)
        _rrf_add(scores, semantic, 1.1)

        seed = [cid for cid, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:12]]
        graph = _graph_expand(conn, repository_id, seed)
        _rrf_add(scores, graph, 0.65)

        ranked_ids = [cid for cid, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[: max(limit * 2, 20)]]
        if not ranked_ids:
            return []
        ph = ",".join("?" for _ in ranked_ids)
        rows = conn.execute(
            f"""
            SELECT c.*, f.content_hash AS file_hash
            FROM chunks c JOIN files f ON f.id=c.file_id
            WHERE c.id IN ({ph})
            """,
            ranked_ids,
        ).fetchall()
        by_id = {int(r["id"]): r for r in rows}

        out: list[RetrievedSource] = []
        budget = MODEL_CONTEXT_CHAR_BUDGET
        used = 0
        per_path: dict[str, int] = defaultdict(int)
        for cid in ranked_ids:
            row = by_id.get(cid)
            if row is None:
                continue
            path = row["path"]
            # Avoid flooding context with overlapping windows from one file.
            if per_path[path] >= 3:
                continue
            text = row["text"]
            if used + len(text) > budget and out:
                continue
            out.append(
                RetrievedSource(
                    chunk_id=cid,
                    path=path,
                    start_line=int(row["start_line"]),
                    end_line=int(row["end_line"]),
                    kind=row["kind"],
                    name=row["name"] or "",
                    text=text,
                    score=float(scores.get(cid, 0.0)),
                    file_hash=row["file_hash"],
                )
            )
            used += len(text)
            per_path[path] += 1
            if len(out) >= limit:
                break
        return out


def build_context(sources: list[RetrievedSource]) -> str:
    parts: list[str] = []
    for i, s in enumerate(sources, start=1):
        parts.append(
            f"[SOURCE {i}] {s.path}:{s.start_line}-{s.end_line} | kind={s.kind} | symbol={s.name or '-'}\n{s.text.strip()}"
        )
    return "\n\n".join(parts)
