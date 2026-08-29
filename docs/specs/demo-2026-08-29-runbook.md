# Clue demo environment — RUNBOOK (2026-08-29, post-successful-demo)

Everything needed to bring the demo environment back exactly as it ran.

## The database (DO NOT DELETE)

| | |
|---|---|
| **Name** | `clue_colombo` |
| **URL** | `postgresql+asyncpg://clue:clue@localhost:55040/clue_colombo` |
| **Where it lives** | Docker container `clue-pg-istanbul` (Postgres 16, port 55040 → 5432). ⚠️ The container ALSO serves istanbul's `clue` DB — never stop/remove the container, never drop `clue`. |
| **Migration head** | `7247c55459c4` (the website-editor merge join) |
| **Redis** | `redis://localhost:6379/2` (db 2 = colombo; db 0 = istanbul) |
| **Backup** | `~/clue-db-backups/clue_colombo-demo-success-2026-08-29.sql.gz` (660MB, gzip-verified) |
| **Restore** | `gunzip -c ~/clue-db-backups/clue_colombo-demo-success-2026-08-29.sql.gz \| docker exec -i clue-pg-istanbul psql -U clue -d clue_colombo_restored` (create the target DB first). Dump/restore MUST use the container's pg tools (local pg_dump is v15, server is v16). |

## Public URLs

| Surface | URL | Notes |
|---|---|---|
| **The app (Railway)** | `https://app.cluehq.ai` | Railway service built from GitHub `clue-hq/research-and-data` @ `integration/frontend-design-part-iv-v4`, root dir `apps/frontend`. DNS: Cloudflare CNAME `app` → Railway (DNS-only/grey cloud). Redeploys on push to the branch. |
| Platform API tunnel | `https://clue-platform-api.ngrok.app` → localhost:8052 | Railway env var `CLUE_API_BASE_URL` |
| Design API tunnel | `https://clue-design-api.ngrok.app` → localhost:8060 | Railway env var `LUMEN_API_BASE_URL` |
| ngrok agent | `ngrok start --all` (config has both named tunnels; authtoken installed) | |

## Demo accounts (Clerk test mode — instance precise-lamb-56)

Password for all: `CluehqDemo2026!!` · OTP always: `424242`

| Account | Email | Workspace | Has |
|---|---|---|---|
| Apollo.io | `apollo+clerk_test@example.com` | `ws_8163898e0d0e4420b578bdbc57d7f3e4` | kit v2 (corrected yellow/black palette), ad library (4 real ads + card + 8 grounds), 3 generated ads |
| Stripe | `stripe+clerk_test@example.com` | `ws_add9d796c5bd4937813d55cd4130e7b0` | kit (+ real Söhne bound), 15 real ads + card + 8 grounds, 1 accepted ad |
| OpenAI | `openai+clerk_test@example.com` | `ws_2cada1e4ebaf40baad43a886a10ed03e` | kit, honest-empty ad lane (video-only advertiser) |

Key artifacts (Apollo campaign project `prj_491f5449e20d5d53b218f6758e2d620b`):
- "Find. Engage. Close." brand ad — thread `thr_f8fbbbfa1bd35d5080f14b506b99affb`, doc `doc_1c35a98d…`
- Apollo→Cursor personalized ad — thread `thr_0f100eea83fc5cdfb95796ea9c44c80e`, doc `doc_75111d69…`
- Cursor landing page — thread `thr_75fd9f2a4af75366aeb0732f5c175916` — ⚠️ NEVER COMMITTED (run died overnight without finalizing; built previews live at `subsystems/clue-design/.deepagent-workspace/run_53cd49f3b82b4e649f50515ca8b7cb9e/iter_4/`; re-run the go-ahead or direct-commit to bring it into the Gallery)
- Stripe ad — project `prj_7fc6e4cee61955ac8c7ad1b6ff7db8f2`, doc `doc_c451f16c…` (v93+, real Söhne)

## Bring-up sequence (from repo root, branch `integration/frontend-design-part-iv-v4`)

```sh
cd /Users/aryankeshri/conductor/workspaces/research-and-data/colombo
set -a; source .env; set +a
export CLUE_SELF_SERVE_PROVISIONING_ENABLED=1 OPENROUTER_API_KEY="$CLUE_OPENROUTER_API_KEY"

# 1. design API (8060)
(cd subsystems/clue-design/apps/api && nohup ../../../.venv/bin/python -m uvicorn lumen_api.main:app --host 127.0.0.1 --port 8060 >> /tmp/colombo-demo-api.log 2>&1 &)

# 2. platform API (8052)
nohup .venv/bin/python -m uvicorn clue_api.projections_main:app --host 127.0.0.1 --port 8052 >> /tmp/colombo-platform-api.log 2>&1 &

# 3. fleet workers (3×)
export LUMEN_API_ORIGIN=http://127.0.0.1:8060
nohup .venv/bin/python -m clue_api.fleet_main >> /tmp/colombo-fleet-worker.log 2>&1 &
nohup .venv/bin/python -m clue_api.fleet_main >> /tmp/colombo-fleet-worker-2.log 2>&1 &
nohup .venv/bin/python -m clue_api.fleet_main >> /tmp/colombo-fleet-worker-3.log 2>&1 &

# 4. tunnels (for the Railway frontend)
ngrok start --all &

# 5. optional local frontend (localhost:3033)
(cd apps/frontend && nohup ./node_modules/.bin/next dev --hostname localhost --port 3033 >> /tmp/colombo-frontend-3033.log 2>&1 &)

# health: all four should pass
curl -s -o /dev/null -w 'design:%{http_code}\n' localhost:8060/docs
curl -s -o /dev/null -w 'platform:%{http_code}\n' localhost:8052/docs
pgrep -f fleet_main | wc -l   # expect 3
curl -s -o /dev/null -w 'public:%{http_code}\n' https://app.cluehq.ai/
```

## Hard-won rules (violate at your peril)

- Never start a second design API without `LUMEN_EMBEDDED_FLEET_WORKER=0` (silent turn theft).
- `.env` is the single source: grok everywhere, Scrapling scraper, Images transport for gpt-image-2, `LUMEN_API_ORIGIN` set. Model pins beyond env are in code (see user-memory `grok-model-config-map`).
- Assets must enter via `POST /assets` (DB-seeded assets are viewable-not-placeable).
- Local pg tools are v15; the server is v16 — always `docker exec clue-pg-istanbul pg_dump/psql`.
- Editor ports must be in `LUMEN_API_CORS_ORIGINS` (3000/3001/3210/3033).
- Account-personalized ads use full logo lockups (tool contract enforces; founder supplies official files when sites ship dirty SVGs).

## Deferred/open items

- Cursor landing page commit (previews built, never committed — see above)
- SVG-in-editor real fix (D3 class, ~1–2 days, spec'd in ledger); the raster band-aid covers existing ads
- OpenAI ad lane (video-only on LinkedIn; needs the Wave C second harvest source)
- Old broken Apollo test project `prj_19a43a55…` (terra-era failures) — delete or keep, founder call
- Wave C decision list (see `_memory/2026-08-26-brand-ad-assets-spec-and-w1.md`)
