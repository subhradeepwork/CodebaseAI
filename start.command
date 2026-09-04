#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

DATA_DIR="${CODEBASE_AI_DATA_DIR:-$HOME/Library/Application Support/CodebaseAI}"
LOG_DIR="$DATA_DIR/logs"
PID_DIR="$DATA_DIR/pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

MODEL="${CODEBASE_AI_LLM_MODEL:-mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit}"
MODEL_VENV="${CODEBASE_AI_MLX_VENV:-$HOME/CodebaseAI-ModelTools/.venv}"
MLX_URL="${CODEBASE_AI_MLX_URL:-http://127.0.0.1:8080}"
OLLAMA_URL="${CODEBASE_AI_OLLAMA_URL:-http://127.0.0.1:11434}"
APP_URL="http://127.0.0.1:${CODEBASE_AI_PORT:-8765}"
EXPECTED_VERSION="1.0.2"

if [ ! -f ".setup-complete" ] || [ ! -x ".venv/bin/python" ]; then
  echo "Codebase AI has not been set up yet. Run ./setup.command first."
  exit 1
fi

source .venv/bin/activate

function wait_http() {
  local url="$1"
  local attempts="$2"
  local i=0
  while [ $i -lt $attempts ]; do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    i=$((i+1))
    sleep 1
  done
  return 1
}

RUNNING_HEALTH=$(curl -fsS --max-time 2 "$APP_URL/api/health" 2>/dev/null || true)
if [ -n "$RUNNING_HEALTH" ]; then
  RUNNING_VERSION=$(printf '%s' "$RUNNING_HEALTH" | "$ROOT/.venv/bin/python" -c 'import json,sys; print(json.load(sys.stdin).get("version", "unknown"))' 2>/dev/null || echo unknown)
  if [ "$RUNNING_VERSION" = "$EXPECTED_VERSION" ]; then
    echo "Codebase AI $EXPECTED_VERSION is already running at $APP_URL"
    open "$APP_URL" >/dev/null 2>&1 || true
    exit 0
  fi
  echo "ERROR: Another Codebase AI instance is already running at $APP_URL (version: $RUNNING_VERSION)."
  echo "This package is version $EXPECTED_VERSION."
  echo "Run ./stop.command, then run ./start.command again so the new frontend is actually served."
  exit 1
fi

# Start Ollama only if its local API is not already running.
if ! curl -fsS --max-time 2 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  if ! command -v ollama >/dev/null 2>&1; then
    echo "ERROR: Ollama is not installed."
    exit 1
  fi
  echo "Starting local Ollama service..."
  nohup ollama serve >"$LOG_DIR/ollama.log" 2>&1 &
  echo $! > "$PID_DIR/ollama.pid"
  if ! wait_http "$OLLAMA_URL/api/tags" 20; then
    echo "ERROR: Ollama did not start. See $LOG_DIR/ollama.log"
    exit 1
  fi
fi

if ! ollama list 2>/dev/null | grep -q '^qwen3-embedding:0.6b'; then
  echo "ERROR: qwen3-embedding:0.6b is not installed in Ollama."
  echo "Run: ollama pull qwen3-embedding:0.6b"
  exit 1
fi

# Start the Apple-Silicon MLX model server only if it is not already running.
if ! curl -fsS --max-time 2 "$MLX_URL/v1/models" >/dev/null 2>&1; then
  MLX_SERVER="$MODEL_VENV/bin/mlx_lm.server"
  if [ -x "$MLX_SERVER" ]; then
    echo "Starting Qwen3-Coder 30B locally with MLX..."
    nohup "$MLX_SERVER" --model "$MODEL" >"$LOG_DIR/mlx.log" 2>&1 &
    echo $! > "$PID_DIR/mlx.pid"
  elif [ -x "$MODEL_VENV/bin/python" ]; then
    echo "Starting Qwen3-Coder 30B locally with MLX..."
    nohup "$MODEL_VENV/bin/python" -m mlx_lm.server --model "$MODEL" >"$LOG_DIR/mlx.log" 2>&1 &
    echo $! > "$PID_DIR/mlx.pid"
  else
    echo "ERROR: MLX-LM environment not found at: $MODEL_VENV"
    echo "Set CODEBASE_AI_MLX_VENV if you installed it somewhere else."
    exit 1
  fi

  echo "Loading model into unified memory. This can take a little while on first start..."
  if ! wait_http "$MLX_URL/v1/models" 180; then
    echo "ERROR: MLX model server did not become ready."
    echo "See: $LOG_DIR/mlx.log"
    exit 1
  fi
fi

function cleanup_backend() {
  if [ -f "$PID_DIR/backend.pid" ]; then
    local pid
    pid=$(cat "$PID_DIR/backend.pid" 2>/dev/null || true)
    if [ -n "$pid" ]; then kill "$pid" >/dev/null 2>&1 || true; fi
    rm -f "$PID_DIR/backend.pid"
  fi
}
trap cleanup_backend INT TERM EXIT

echo "Starting Codebase AI at $APP_URL"
PYTHONPATH="$ROOT/backend" "$ROOT/.venv/bin/uvicorn" app.main:app \
  --host 127.0.0.1 --port "${CODEBASE_AI_PORT:-8765}" \
  --log-level info >"$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$PID_DIR/backend.pid"

if ! wait_http "$APP_URL/api/health" 30; then
  echo "ERROR: Backend did not start. See $LOG_DIR/backend.log"
  exit 1
fi

open "$APP_URL" >/dev/null 2>&1 || true
printf '\nCodebase AI is running.\nBrowser: %s\nLogs: %s\n\nLeave this Terminal window open. Press Control-C to stop the web app.\nThe model server may remain warm for faster restarts; ./stop.command stops everything.\n\n' "$APP_URL" "$LOG_DIR"

wait "$BACKEND_PID"
