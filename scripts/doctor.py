#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = os.getenv("CODEBASE_AI_LLM_MODEL", "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit")
EMBED_MODEL = os.getenv("CODEBASE_AI_EMBEDDING_MODEL", "qwen3-embedding:0.6b")
MODEL_VENV = Path(os.getenv("CODEBASE_AI_MLX_VENV", str(Path.home() / "CodebaseAI-ModelTools" / ".venv"))).expanduser()


def cmd(name: str, args: list[str]) -> tuple[bool, str]:
    exe = shutil.which(args[0])
    if not exe:
        return False, f"{args[0]} not found"
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=15, check=False)
        text = (p.stdout or p.stderr).strip().splitlines()
        return p.returncode == 0, text[0] if text else "ok"
    except Exception as e:
        return False, str(e)


def http_json(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def main() -> int:
    print("Codebase AI preflight\n")
    checks: list[tuple[str, bool, str]] = []
    checks.append(("Apple Silicon", platform.machine() == "arm64", platform.machine()))
    checks.append(("Python 3.12", sys.version_info[:2] == (3, 12), platform.python_version()))
    for label, args in [
        ("Node", ["node", "--version"]),
        ("npm", ["npm", "--version"]),
        ("Java", ["java", "-version"]),
        ("Git", ["git", "--version"]),
        ("ripgrep", ["rg", "--version"]),
        ("Ollama CLI", ["ollama", "--version"]),
    ]:
        ok, msg = cmd(label, args)
        checks.append((label, ok, msg))

    mlx_exe = MODEL_VENV / "bin" / "mlx_lm.server"
    mlx_py = MODEL_VENV / "bin" / "python"
    mlx_ok = mlx_exe.exists() or mlx_py.exists()
    checks.append(("MLX-LM environment", mlx_ok, str(MODEL_VENV)))

    try:
        tags = http_json("http://127.0.0.1:11434/api/tags")
        names = [m.get("name", "") for m in tags.get("models", [])]
        present = EMBED_MODEL in names or any(n.startswith(EMBED_MODEL + ":") for n in names)
        checks.append(("Embedding model", present, EMBED_MODEL if present else f"missing: {EMBED_MODEL}"))
    except Exception as e:
        checks.append(("Embedding model", False, f"Ollama not reachable: {e}"))

    width = max(len(x[0]) for x in checks)
    failed = 0
    for label, ok, msg in checks:
        state = "OK" if ok else "FAIL"
        print(f"{state:4}  {label:<{width}}  {msg}")
        failed += 0 if ok else 1

    print("\nPrimary model:", MODEL)
    if failed:
        print(f"\n{failed} preflight check(s) need attention.")
        return 1
    print("\nPreflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
