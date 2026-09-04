#!/bin/zsh
set -u
DATA_DIR="${CODEBASE_AI_DATA_DIR:-$HOME/Library/Application Support/CodebaseAI}"
PID_DIR="$DATA_DIR/pids"

stop_pidfile() {
  local name="$1"
  local file="$PID_DIR/$name.pid"
  if [ -f "$file" ]; then
    local pid
    pid=$(cat "$file" 2>/dev/null || true)
    if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
      echo "Stopping $name ($pid)..."
      kill "$pid" >/dev/null 2>&1 || true
      sleep 1
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
    rm -f "$file"
  fi
}

stop_pidfile backend
stop_pidfile mlx
stop_pidfile ollama

echo "Codebase AI local processes stopped."
