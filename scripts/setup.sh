#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
runtime_dir="${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies"
task_python="${PYTHON_BIN:-python3}"
if [[ -x "$runtime_dir/python/bin/python3" && -z "${PYTHON_BIN:-}" ]]; then
  task_python="$runtime_dir/python/bin/python3"
fi
"$task_python" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
"$task_python" -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
if command -v pnpm >/dev/null 2>&1; then
  (cd frontend && pnpm install --frozen-lockfile)
elif [[ -x "$runtime_dir/node/bin/node" && -f "$runtime_dir/node/node_modules/pnpm/bin/pnpm.cjs" ]]; then
  export PATH="$runtime_dir/node/bin:$PATH"
  (cd frontend && "$runtime_dir/node/bin/node" "$runtime_dir/node/node_modules/pnpm/bin/pnpm.cjs" install --frozen-lockfile)
else
  echo 'Node.js (>=22.13) and pnpm (11.25.0) are required for the frontend.' >&2
  exit 1
fi
if [[ ! -f .env ]]; then cp .env.example .env; fi
echo 'Setup complete. Start: .venv/bin/python scripts/dev.py'
