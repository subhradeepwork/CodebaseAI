from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterable

import numpy as np

from ..config import EMBEDDING_MODEL, OLLAMA_BASE_URL


class EmbeddingUnavailable(RuntimeError):
    pass


@dataclass
class EmbeddingService:
    base_url: str = OLLAMA_BASE_URL
    model: str = EMBEDDING_MODEL
    timeout: int = 120

    def health(self) -> tuple[bool, str]:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=3) as r:
                data = json.load(r)
            names = {m.get("name") for m in data.get("models", [])}
            ok = self.model in names or any((n or "").startswith(self.model + ":") for n in names)
            return ok, "ready" if ok else f"Ollama is running but {self.model} is not installed"
        except Exception as e:
            return False, f"Ollama unavailable: {e}"

    def embed(self, inputs: str | list[str]) -> list[list[float]]:
        body = json.dumps({"model": self.model, "input": inputs, "truncate": True}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.load(r)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise EmbeddingUnavailable(str(e)) from e
        embeddings = data.get("embeddings") or []
        if not embeddings:
            raise EmbeddingUnavailable("Ollama returned no embeddings")
        return embeddings


class EmbeddingCache:
    """In-memory vector matrix per repository for fast cosine retrieval.

    Ollama's /api/embed returns normalized vectors, so dot product is cosine similarity.
    The cache is invalidated whenever indexing changes a repository.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cache: dict[int, tuple[list[int], np.ndarray]] = {}

    def invalidate(self, repository_id: int) -> None:
        with self._lock:
            self._cache.pop(repository_id, None)

    def get_or_build(self, conn, repository_id: int) -> tuple[list[int], np.ndarray]:
        with self._lock:
            if repository_id in self._cache:
                return self._cache[repository_id]
            rows = conn.execute(
                "SELECT id, embedding, embedding_dim FROM chunks WHERE repository_id=? AND embedding IS NOT NULL AND embedding_dim IS NOT NULL ORDER BY id",
                (repository_id,),
            ).fetchall()
            ids: list[int] = []
            vectors: list[np.ndarray] = []
            for row in rows:
                dim = int(row["embedding_dim"])
                vec = np.frombuffer(row["embedding"], dtype=np.float32, count=dim)
                if vec.size != dim:
                    continue
                ids.append(int(row["id"]))
                vectors.append(vec)
            matrix = np.vstack(vectors) if vectors else np.empty((0, 0), dtype=np.float32)
            self._cache[repository_id] = (ids, matrix)
            return ids, matrix


embedding_cache = EmbeddingCache()
