from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Codebase AI"
APP_VERSION = "1.0.2"
HOST = os.getenv("CODEBASE_AI_HOST", "127.0.0.1")
PORT = int(os.getenv("CODEBASE_AI_PORT", "8765"))

DATA_DIR = Path(
    os.getenv(
        "CODEBASE_AI_DATA_DIR",
        str(Path.home() / "Library" / "Application Support" / "CodebaseAI"),
    )
).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "codebase-ai.db"
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_BASE_URL = os.getenv("CODEBASE_AI_OLLAMA_URL", "http://127.0.0.1:11434")
EMBEDDING_MODEL = os.getenv("CODEBASE_AI_EMBEDDING_MODEL", "qwen3-embedding:0.6b")
MLX_BASE_URL = os.getenv("CODEBASE_AI_MLX_URL", "http://127.0.0.1:8080")
LLM_MODEL = os.getenv(
    "CODEBASE_AI_LLM_MODEL",
    "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit",
)

MAX_FILE_BYTES = int(os.getenv("CODEBASE_AI_MAX_FILE_BYTES", str(2_000_000)))
MAX_CHUNK_CHARS = int(os.getenv("CODEBASE_AI_MAX_CHUNK_CHARS", "12000"))
INDEX_EMBEDDINGS = os.getenv("CODEBASE_AI_INDEX_EMBEDDINGS", "1") not in {"0", "false", "False"}
EMBED_BATCH_SIZE = int(os.getenv("CODEBASE_AI_EMBED_BATCH_SIZE", "12"))
MODEL_CONTEXT_CHAR_BUDGET = int(os.getenv("CODEBASE_AI_CONTEXT_CHAR_BUDGET", "120000"))
RECENT_CHAT_MESSAGES = int(os.getenv("CODEBASE_AI_RECENT_CHAT_MESSAGES", "14"))

FRONTEND_DIST = (Path(__file__).resolve().parents[2] / "frontend" / "dist").resolve()

SUPPORTED_EXTENSIONS = {
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".java", ".feature",
    ".json", ".yaml", ".yml", ".properties", ".xml", ".gradle", ".kts", ".toml",
    ".md", ".sql", ".tf", ".tfvars",
}

EXCLUDED_DIR_NAMES = {
    ".git", ".hg", ".svn", ".idea", ".vscode",
    "node_modules", "dist", "build", "target", "coverage", ".next", ".nuxt",
    ".gradle", ".mvn", "out", "vendor", "Pods", ".venv", "venv", "__pycache__",
}

EXCLUDED_FILE_NAMES = {
    ".env", ".env.local", ".env.development", ".env.production", ".env.test",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
}

SENSITIVE_SUFFIXES = {
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".crt", ".cer",
}
