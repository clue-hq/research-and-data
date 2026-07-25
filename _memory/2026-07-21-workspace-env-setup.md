# 2026-07-21 — Conductor workspace env setup (nouakchott) + parallel-worktree isolation

## What happened
The Conductor setup script failed on its second step: `uv sync` succeeded (all 15 workspace
packages built, 93 wheels installed), but `docker run` failed with "Cannot connect to the
Docker daemon" — Docker Desktop was not running on the host.

## Isolation scheme (user ruling — 3 parallel worktrees coming for Phase B)
Every workspace gets its own Postgres container, a **non-obvious hash-derived port**, a
**per-workspace database name** (never the shared default `clue` on 5432), and a hash-derived
Redis DB index. Derivation (deterministic from the workspace name):

- `HASH = cksum(workspace_name)`
- `PG_PORT = 20000 + HASH % 10000`  (nouakchott → **23482**)
- `DB_NAME = clue_<workspace_name with - → _>`  (→ **clue_nouakchott**)
- `REDIS_DB = HASH % 16`  (→ **10**)
- container `clue-pg-<workspace_name>`

All values live in a git-ignored root **`.env`**; every command imports it via
`set -a; source .env; set +a` — never inline exports (user ruling). Note `clue_db.database_url()`
falls back to `localhost:5432/clue` when `CLUE_DATABASE_URL` is unset — a worktree without its
`.env` sourced would silently hit that shared default, so always source before make/pytest.

## Verification (all green, 2026-07-21, against clue_nouakchott@23482)
- Connectivity through the `clue_db` seam (`current_database = clue_nouakchott`).
- `make db-smoke` — alembic up → base → up, single head.
- `make check` — lint, mypy, import-linter contracts, full pytest **including the DB suite**:
  **1938 passed / 14 skipped** — identical to the Phase-A / R3 baseline (e615e81).

## Recommended setup script (Settings > Setup script)
```sh
uv sync

# Ensure the Docker daemon is up (Docker Desktop)
if ! docker info >/dev/null 2>&1; then
  open -a Docker
  for i in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
fi
docker info >/dev/null 2>&1 || { echo "Docker daemon did not start" >&2; exit 1; }

# Per-workspace isolation: hash-derived non-obvious port, own database, own Redis index
HASH=$(printf '%s' "$CONDUCTOR_WORKSPACE_NAME" | cksum | cut -d' ' -f1)
PG_PORT=$((20000 + HASH % 10000))
REDIS_DB=$((HASH % 16))
DB_NAME="clue_$(printf '%s' "$CONDUCTOR_WORKSPACE_NAME" | tr '-' '_')"

docker rm -f "clue-pg-$CONDUCTOR_WORKSPACE_NAME" >/dev/null 2>&1 || true
docker run -d --name "clue-pg-$CONDUCTOR_WORKSPACE_NAME" \
  -e POSTGRES_USER=clue -e POSTGRES_PASSWORD=clue -e POSTGRES_DB="$DB_NAME" \
  -p "$PG_PORT:5432" pgvector/pgvector:pg16 >/dev/null

# Wait until Postgres accepts connections
for i in $(seq 1 30); do
  docker exec "clue-pg-$CONDUCTOR_WORKSPACE_NAME" pg_isready -U clue -d "$DB_NAME" >/dev/null 2>&1 && break
  sleep 1
done

# Workspace-local .env — every make/test invocation imports it (set -a; source .env; set +a)
cat > .env <<EOF
CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:$PG_PORT/$DB_NAME
CLUE_REDIS_URL=redis://localhost:6379/$REDIS_DB
EOF
```
