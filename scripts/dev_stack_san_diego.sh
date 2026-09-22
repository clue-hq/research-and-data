#!/bin/bash
# San Diego's isolated stack. Settings live in .env and apps/frontend/.env.local.
# Usage: bash scripts/dev_stack_san_diego.sh up|down|restart-api|restart-workers|restart-ingestion|status
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -a
source "$ROOT/.env"
set +a

# Validate configuration without printing credentials from either env file.
"$ROOT/.venv/bin/python" - "$ROOT" <<'PY'
import sys
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import dotenv_values

root = Path(sys.argv[1])
env = dotenv_values(root / '.env')
frontend = dotenv_values(root / 'apps/frontend/.env.local')
def require(ok, message):
    if not ok:
        raise SystemExit(message)

require(root.name == 'san-diego', 'This launcher belongs to the San Diego checkout.')
db = urlsplit(env['CLUE_DATABASE_URL'])
require((db.hostname, db.port, db.path) == ('127.0.0.1', 55170, '/clue_san_diego'),
        'San Diego requires its isolated database on 55170.')
require(env['DEV_STACK_DB_URL'] == env['CLUE_DATABASE_URL'], 'Database settings disagree.')
require(env['CLUE_REDIS_URL'] == 'redis://127.0.0.1:65170/0', 'San Diego requires Redis 65170.')
for key, port in [('FRONTEND', '3033'), ('DESIGN', '8013'), ('PLATFORM', '8023'), ('PLATFORM2', '8033')]:
    require(env[f'DEV_STACK_{key}_PORT'] == port, f'San Diego {key} port must be {port}.')
app = 'http://localhost:3033'
design = 'http://127.0.0.1:8013'
require(env['CLUE_APP_ORIGIN'] == frontend['CLUE_APP_ORIGIN'] == app, 'Frontend origins disagree.')
require(frontend['CLUE_API_BASE_URL'] == 'http://127.0.0.1:8023', 'Frontend platform target disagrees.')
require(env['CLUE_DESIGN_API_BASE_URL'] == env['LUMEN_API_ORIGIN'] == frontend['LUMEN_API_BASE_URL'] == design,
        'Design API targets disagree.')
for key in ['LUMEN_API_CORS_ORIGINS', 'CLUE_AUTH_CLERK_AUTHORIZED_PARTIES']:
    require(app in env[key].split(','), f'{key} must allow the San Diego frontend.')
require(Path(env['CLUE_STORAGE_FS_ROOT']).resolve() == root / '.artifacts', 'Storage must belong to San Diego.')
require(env['CLUE_AGENT_WORKSPACE_ROOT'] == env['DEV_STACK_AGENT_WORKSPACE_ROOT'] ==
        '/private/tmp/clue-agent-workspaces-san-diego', 'Agent workspace roots disagree.')
helper = Path(env['LUMEN_CORE_HELPER'])
require(helper.is_file() and helper.resolve().is_relative_to(root), 'Build the San Diego engine helper first.')
PY

# The common launcher clears .next during startup: never run it over a live stack.
if [ "${1:-status}" = up ]; then
  for port in "$DEV_STACK_FRONTEND_PORT" "$DEV_STACK_DESIGN_PORT" "$DEV_STACK_PLATFORM_PORT" "$DEV_STACK_PLATFORM2_PORT"; do
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "Port $port is already occupied; inspect its owner before starting this stack." >&2
      exit 2
    fi
  done
  if pgrep -f "$ROOT/.venv/bin/python -m (clue_api.fleet_main|lumen_api.ingestion_pool)" >/dev/null; then
    echo 'San Diego workers are already running; use restart-workers or restart-ingestion.' >&2
    exit 2
  fi
fi
exec bash "$ROOT/scripts/dev_stack.sh" "$@"
