#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

printf '\nCodebase AI setup\n=================\n\n'

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "ERROR: python3.12 was not found. Install Homebrew Python 3.12 first."
  exit 1
fi
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: Node/npm were not found. Install Node 24 first."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "[1/5] Creating isolated Python environment..."
  python3.12 -m venv .venv
else
  echo "[1/5] Python environment already exists."
fi

source .venv/bin/activate
python -m pip install --upgrade pip wheel

echo "[2/5] Installing backend/indexing dependencies..."
pip install -r backend/requirements.txt

# Warm the structural parsers during setup so JavaScript/TypeScript/TSX/Java parsing does
# not need to fetch/cache a grammar later in an offline work session.
python - <<'PY'
from tree_sitter_language_pack import get_parser
samples = {
    "javascript": b"export const f = () => 1;",
    "typescript": b"export function f(x: number): number { return x }",
    "tsx": b"export const App = () => <div />;",
    "java": b"class A { void f() {} }",
}
for language, source in samples.items():
    parser = get_parser(language)
    tree = parser.parse(source)
    if tree.root_node is None:
        raise RuntimeError(f"Tree-sitter parser failed: {language}")
print("Tree-sitter parsers: ready")
PY

echo "[3/5] Installing React frontend dependencies..."
cd frontend
npm install

echo "[4/5] Building localhost frontend..."
npm run build
cd "$ROOT"

echo "[5/5] Running package self-tests..."
PYTHONPATH="$ROOT/backend" python -m pytest -q backend/tests
python -m compileall -q backend/app

deactivate

chmod +x setup.command start.command stop.command verify.command scripts/doctor.py

cat > .setup-complete <<EOF
Codebase AI 1.1.0
$(date)
EOF

printf '\nSetup complete.\nRun: ./start.command\n\n'
