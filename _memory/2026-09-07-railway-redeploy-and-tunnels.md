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

## Fleet worker concurrency slots (founder request 2026-09-07 evening)
Root cause of "the second chat's task queues behind the first": `LeasedWorkWorker.run()` claimed one
task and awaited `_run_task` to completion (verified in the day's logs — a turn enqueued 13:17:25 only
started 13:20:13, when the previous chat's turn was stopped). Fix committed on this branch: the loop
claims while slots remain and supervises each task as its own asyncio task (`max_concurrency`;
`CLUE_FLEET_MAX_CONCURRENCY=4` in `.env`/`.env.example` with the whole CLUE_FLEET_* block now
documented; library default stays 1, so the design API's embedded worker is unchanged). Same-thread
turns still never overlap (dispatcher's per-thread advisory lock). Tests: 6 new in
`tests/fleet/test_work_worker.py` (overlap up to N, N=1 sequential, slots shared across kinds,
stop drains in-flight, supervision crash isolated, N≥1), 1 in `tests/api/test_fleet_wiring.py`;
`tests/fleet` 82 green, ruff + mypy clean. Colombo worker restarted 19:51 IST on the new code
(`worker.start max_concurrency=4`). Not proven live yet — needs two chats sending at once.

## 2026-09-08 00:15–00:45 IST — provisioning 404, env-parity audit, flags recorded
- New-account sign-in on app.cluehq.ai ended in "Provisioning failed with status 404": `POST
  /auth/v1/provision` mounts only behind `CLUE_SELF_SERVE_PROVISIONING_ENABLED`, which had been
  exported by hand on demo night and never written to `.env`, so the 2026-09-06 restart from `.env`
  dropped it (13 × 404 in the platform log). Set to 1 in `.env` + `.env.example`; platform API and
  fleet worker restarted (00:31). MISTAKE recorded: the restart script printed 2 live leases and did
  not gate on them — a website turn (run_4a39f9dd, doc_487fd7ab) was in flight on the old worker. It
  survived: SIGTERM only stops NEW claims, the inline design lane passes its own stop Event, and the
  agent-turn handler aborts only on a user Stop; the old process drained it to completion.
- Env-parity audit (founder request): 46 of 132 `clue_config.Settings` fields and 41–43 of 75
  `py_lumen_config.Settings` fields had no line in the env files. Appended at CODE defaults to
  `.env`, `.env.example`, and `subsystems/clue-design/.env.example` (None/secret/JSON-list fields as
  commented lines). Lesson: an EMPTY value for a tuple field (`CLUE_RECIPE1_WORKSPACE_ALLOWLIST=`)
  makes pydantic-settings json-decode "" and the app cannot start — caught by the load check before
  any restart. Both Settings classes verified loading from the sourced `.env`. Noted for the founder:
  `LUMEN_AD_DNA_MODEL` code default is grok-4.5 while every other model pin is grok-4.6.

## 2026-09-08 ~01:05 IST — origin/design/website merged into design/scene-ad (`5a20f2f9c`)
105 commits / 189 files. Conflicts (all unions): generating module (website veil + scene-ad lock
share one sheet/index; z-index 41/42/43 kept), artifact-stage/-header props, image-inspector (ours),
both .env.example files (SELF_SERVE stays 1; dup keys removed), CLAUDE.md + _memory/README.md.
Alembic had two heads → merge revision `fa0b41b0ffdc`; throwaway DB `clue_plan1_test` migrated to it
and the incoming platform DB tests pass there. Frontend: 2801 tests pass, lint 0 errors; `tsc --noEmit`
shows two PRE-EXISTING test-file typing errors (wasmHandshake/libraryFonts tests, untouched since Aug)
that `next build` does not trip on. Merge removed jsdom + @types/jsdom from package.json, but the scene-ad clipboard test suites DO import it (a grep that `head`-truncated to nothing read as "unused" — the verify-nonexistence-exactly rule again); restored as devDependencies in a follow-up commit. lumen-core untouched;
lumen-web changed → release helper rebuilt in an isolated target dir (`/tmp/colombo-target-merge`) so
the live binary was not swapped under the running design API. New .env keys added for colombo
(CLUE_DEV_*, LUMEN_AGENT_WEB_SOLO=1, LUMEN_AGENT_OPENROUTER_CHAT_COMPLETIONS=1).
NOT yet done (needs the founder's go — interrupts live testing): `alembic upgrade head` on
clue_colombo (3 new revisions + merge), copy the new helper over `target/release/lumen-api-helper`,
restart design API / platform API / worker; Railway needs a fast-forward push of v4 to pick up the
frontend. Mistake logged: a "focused" platform test run sourced `.env` and one DB-backed test
(`test_agent_turn_submission_note.py`) tried to migrate the SHARED clue_colombo — it failed harmlessly
on the two-heads error before touching anything (verified `alembic current` unchanged). Rule: always
override CLUE_DATABASE_URL to the throwaway DB before ANY pytest, not just `_db` files.
