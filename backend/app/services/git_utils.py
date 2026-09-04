from __future__ import annotations

import subprocess
from pathlib import Path


def _run(repo: Path, args: list[str], timeout: int = 15) -> str | None:
    try:
        p = subprocess.run(
            ["git", "-C", str(repo), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
        if p.returncode == 0:
            return p.stdout.strip()
    except Exception:
        pass
    return None


def is_git_repo(repo: Path) -> bool:
    return _run(repo, ["rev-parse", "--is-inside-work-tree"]) == "true"


def current_commit(repo: Path) -> str | None:
    return _run(repo, ["rev-parse", "HEAD"])


def git_file_list(repo: Path) -> list[str] | None:
    if not is_git_repo(repo):
        return None
    # cached + untracked, while honoring .gitignore. This intentionally includes a newly copied lambdaBackend folder.
    out = _run(repo, ["ls-files", "-co", "--exclude-standard"], timeout=60)
    if out is None:
        return None
    return [line for line in out.splitlines() if line.strip()]
