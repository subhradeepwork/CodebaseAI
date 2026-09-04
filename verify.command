#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

if [ ! -x ".venv/bin/python" ]; then
  echo "Run ./setup.command first."
  exit 1
fi

source .venv/bin/activate
printf '\nCodebase AI verification\n========================\n'

PYTHONPATH="$ROOT/backend" python -m compileall -q backend/app backend/tests
PYTHONPATH="$ROOT/backend" python -m pytest -q backend/tests

if [ ! -f "frontend/dist/index.html" ]; then
  echo "FAIL: frontend/dist/index.html is missing"
  exit 1
fi

echo "Frontend build: OK"
PYTHONPATH="$ROOT/backend" python - <<'PY'
from app.db import init_db
from app.main import app
print('Backend import: OK')
print('Routes:', len(app.routes))
PY

python scripts/doctor.py || true

deactivate
printf '\nPackage verification complete.\n'
