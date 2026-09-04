from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from ..config import (
    EXCLUDED_DIR_NAMES,
    EXCLUDED_FILE_NAMES,
    MAX_FILE_BYTES,
    SENSITIVE_SUFFIXES,
    SUPPORTED_EXTENSIONS,
)
from ..db import db_conn
from .git_utils import git_file_list
from .parser import language_for_path


class RepositoryError(ValueError):
    pass


def normalize_repo_path(path_str: str) -> Path:
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        raise RepositoryError("Repository path does not exist")
    if not path.is_dir():
        raise RepositoryError("Repository path must be a directory")
    return path


def add_repository(path_str: str) -> dict:
    path = normalize_repo_path(path_str)
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO repositories(name, path) VALUES (?, ?) ON CONFLICT(path) DO UPDATE SET name=excluded.name, updated_at=CURRENT_TIMESTAMP",
            (path.name or str(path), str(path)),
        )
        row = conn.execute("SELECT * FROM repositories WHERE path=?", (str(path),)).fetchone()
    return dict(row)


def list_repositories() -> list[dict]:
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM repositories ORDER BY updated_at DESC, name").fetchall()
        return [dict(r) for r in rows]


def get_repository(repository_id: int) -> dict:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM repositories WHERE id=?", (repository_id,)).fetchone()
    if not row:
        raise RepositoryError("Repository not found")
    return dict(row)


def delete_repository_metadata(repository_id: int) -> None:
    with db_conn() as conn:
        chunk_rows = conn.execute("SELECT id FROM chunks WHERE repository_id=?", (repository_id,)).fetchall()
        for row in chunk_rows:
            conn.execute("DELETE FROM chunks_fts WHERE rowid=?", (int(row["id"]),))
        message_rows = conn.execute(
            "SELECT m.id FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.repository_id=?",
            (repository_id,),
        ).fetchall()
        for row in message_rows:
            conn.execute("DELETE FROM messages_fts WHERE rowid=?", (int(row["id"]),))
        conn.execute("DELETE FROM repositories WHERE id=?", (repository_id,))


def _is_allowed_relative(rel: Path) -> bool:
    if rel.name in EXCLUDED_FILE_NAMES:
        return False
    if rel.suffix.lower() in SENSITIVE_SUFFIXES:
        return False
    lower_name = rel.name.lower()
    if lower_name.startswith(".env") or "secret" in lower_name and rel.suffix.lower() in {".json", ".yaml", ".yml"}:
        return False
    if any(part in EXCLUDED_DIR_NAMES for part in rel.parts[:-1]):
        return False
    return rel.suffix.lower() in SUPPORTED_EXTENSIONS or rel.name in {
        "Dockerfile", "Makefile", "pom.xml", "build.gradle", "settings.gradle",
        "serverless.yml", "template.yaml", "samconfig.toml", "cdk.json",
    }


def discover_files(repo: Path) -> list[Path]:
    listed = git_file_list(repo)
    candidates: list[Path] = []
    if listed is not None:
        for raw in listed:
            rel = Path(raw)
            if _is_allowed_relative(rel):
                p = (repo / rel).resolve()
                try:
                    p.relative_to(repo)
                except ValueError:
                    continue
                if p.is_file():
                    candidates.append(p)
    else:
        for root, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIR_NAMES]
            root_path = Path(root)
            for name in files:
                p = root_path / name
                rel = p.relative_to(repo)
                if _is_allowed_relative(rel):
                    candidates.append(p.resolve())
    return sorted(set(candidates), key=lambda p: str(p).lower())


def read_text_file(path: Path) -> str | None:
    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_FILE_BYTES:
            return None
        raw = path.read_bytes()
        if b"\x00" in raw[:8192]:
            return None
        return raw.decode("utf-8", errors="replace")
    except (OSError, PermissionError):
        return None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def safe_repo_file(repository_id: int, relative_path: str) -> tuple[Path, Path]:
    repo_row = get_repository(repository_id)
    repo = Path(repo_row["path"]).resolve()
    target = (repo / relative_path).resolve()
    try:
        rel = target.relative_to(repo)
    except ValueError as e:
        raise RepositoryError("Requested file is outside the repository") from e
    if not target.is_file():
        raise RepositoryError("File not found")
    return target, rel


def file_excerpt(repository_id: int, relative_path: str, start_line: int = 1, end_line: int = 200) -> dict:
    target, rel = safe_repo_file(repository_id, relative_path)
    text = target.read_text("utf-8", errors="replace")
    lines = text.splitlines()
    start_line = max(1, start_line)
    end_line = max(start_line, min(len(lines), end_line))
    out = [
        {"line": i, "text": lines[i - 1]}
        for i in range(start_line, end_line + 1)
    ]
    return {"path": str(rel), "start_line": start_line, "end_line": end_line, "lines": out, "hash": sha256_text(text)}


def pick_folder_macos() -> str:
    if sys.platform != "darwin":
        raise RepositoryError("Native folder picker is currently available on macOS only; enter the path manually.")
    script = 'POSIX path of (choose folder with prompt "Choose a code repository")'
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RepositoryError("Folder selection cancelled")
    return p.stdout.strip().rstrip("/")
