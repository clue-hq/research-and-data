# 2026-09-07 — Railway frontend redeployed from `design/scene-ad`; tunnels back up for co-founder testing

Founder request: deploy the latest frontend (with the current wasm) to Railway and re-host the
platform API, design API and fleet worker via ngrok so the co-founder can test.

## What was done
- **Deploy = fast-forward push.** Railway builds `integration/frontend-design-part-iv-v4` (root `/`,
  `RAILWAY_DOCKERFILE_PATH=/apps/frontend/Dockerfile.railway`; env already points at the two static
  ngrok domains). HEAD `f67469e48` (already on GitHub as `design/scene-ad`) was pushed to v4 as a plain
  fast-forward (`3fa3f5669..f67469e48`, 281 commits). Founder authorized the push explicitly.
- **Pre-push gate:** `verify_handshake.mjs` HANDSHAKE OK at `32ce2d50a1ca`; the exact Railway
  Dockerfile built green locally (`docker build -f apps/frontend/Dockerfile.railway .`, image
  `colombo-frontend-railway-check`), wasm preflight inside the build passed, image wasm hash == tracked
  wasm hash (`67c61d3d…`).
- **Railway rebuild took ~3.5 min** after the push; verified by polling the served
  `/vendor/wasm/lumen_wasm_bg.wasm` hash until it flipped from the v4 build (`84471dda…`) to `67c61d3d…`.
- **ngrok:** `ngrok start --all` (config at `~/Library/Application Support/ngrok/ngrok.yml`, two named
  endpoints: `clue-platform-api.ngrok.app → 8052`, `clue-design-api.ngrok.app → 8060`), log
  `/private/tmp/colombo-ngrok.log`, inspector `localhost:4040`. The fleet worker is not an HTTP
  service — it needs no tunnel, just to be running against the same DB (it is, pid from the 22:04 restart).
- **End-to-end proof on the hosted app:** signed in as the Apollo test account on app.cluehq.ai →
  workspace select → projects list (platform tunnel; Railway egress IP 136.107.183.205 in the
  platform API log) → Apollo project gallery: 8 thumbnails rendered, served through the design tunnel
  (`GET /documents/…/thumbnail` 200 from the Railway IP in the design API log).

## Rules re-learned
- Railway watches v4 only (founder confirmation 2026-09-07). Deploying any branch = fast-forward v4 to
  it; never repoint the service without the founder.
- Always run the Railway Dockerfile locally before pushing a deploy — no Railway CLI/token on this
  machine, so a failed remote build would be invisible except as "wasm hash never flips".
- Tunnels die with reboots/sessions; check `pgrep -fl ngrok` and `localhost:4040/api/tunnels` first.

## Incident right after the deploy (12:51–12:55 IST): 500 on sign-in — Docker VM disk full
The local Railway Dockerfile build (image + ~6 GB build cache) filled the Docker Desktop VM disk
(~36 GB virtual disk). Postgres (`clue-pg-istanbul`) hit `No space left on device` writing
`pg_logical/replorigin_checkpoint.tmp`, PANICked and crash-looped in recovery; the platform API
returned 500 on `/auth/v1/session` (`CannotConnectNowError: the database system is in recovery mode`),
the design reaper logged the same, and colombo's fleet worker process DIED on it. Fix: removed the
check image + `docker builder prune -af` (8.2 GB reclaimed) → Postgres completed its checkpoint and
came back on its own within seconds; sign-in/projects/gallery healthy again; fleet worker restarted
from the repo root with `.env` sourced (`nohup .venv/bin/python -m clue_api.fleet_main`).
**Rules:** (1) never leave a local Railway image/build cache behind on this box — the VM disk is
small and Postgres lives on it; `docker system df` before and after; (2) after any DB outage, check
`pgrep -f clue_api.fleet_main` — the worker does not survive a lost connection. Still reclaimable and
NOT touched (founder's call): a dangling 1.5 GB image + two `clue-frontend-railway:*` images from
2026-08-27, ~9 GB of unused Docker volumes. VM free after cleanup: 5.6 GB of 36.4 GB.

## Docker cleanup (founder-requested, 2026-09-07 ~14:30 IST; cutoff = volumes older than 20 days, i.e. before 2026-08-18)
Removed: 11 stopped per-worktree Postgres containers older than the cutoff (integ, tel-aviv, hartford,
perth, m131/m132/m134, buffalo, sparta, roseau-m8b-v1, damascus); 74 unattached volumes created before
the cutoff (anonymous hashes + old `<worktree>_clue_pgdata` names); the two 2026-08-27
`clue-frontend-railway` check images; dangling images. Docker VM free: 7.7 GB → 17.3 GB of 36.4 GB.
Deliberately KEPT (founder to rule): `context-graph_neo4j_*` (other project, 820 MB, container
exited since May), `content-strategy-engine_*` pgdata/redisdata (Deep Presence, June), and every
container/volume newer than the cutoff (clue-postgres/dar-es-salaam, missoula, calgary, stuttgart,
tunis, colombo, chicago, semarang, the redis ones). Live DBs untouched: istanbul (colombo's), managua,
san-salvador. Unused base images (complex-gh-*, ingress-nginx, old redis/postgres tags, ~5 GB) also
left — `docker image prune -a` would take them if wanted.
