# 2026-09-17 — Custom-domain publishing S1 (system hostnames live) + the S0 runbook

Branch `research-streaming-v3`, worktree `addis-ababa`, lane DB `clue_addis-ababa@55040` (throwaway,
created EMPTY by Task 2 — no seed data, no dev-login rows). Spec:
`docs/superpowers/specs/archive/2026-09-17-custom-domain-publishing-design.md`. Plan:
`docs/superpowers/plans/2026-09-17-custom-domain-publishing-s0-s1.md`. Per-task briefs, reports and
the full ruling ledger: `.superpowers/sdd/2026-09-17-custom-domain-publishing-s0-s1/progress.md`.
Research/decision record that precedes this: `_memory/2026-09-17-custom-domain-publishing-research.md`.

S1 = every workspace gets a permanent `<label>.pages.cluehq.ai` hostname served by a new hosted page
origin, and published HTML stops naming the host it was published from. S0 (the dashboard half) is
NOT done — it is a founder-operated runbook this session wrote: `docs/specs/pages-hosting-runbook.md`.

## What landed (14 commits, `2247d1f8f..4ffd7d3da`)

| Task | Commit(s) | What |
| --- | --- | --- |
| 1 | `2835e8175` | `CLUE_PAGES_*` settings + `pages_edge_secret`; `.env.example` parity |
| 2 | `a4c1f2dd8` | migration `aaff3d831895` — `workspace_hostname` + `workspace_pages_settings` (text+CHECK, one system / one custom row per workspace) |
| 3 | `f4c50598a`, `7ca4881fc` | `clue_spine.hostnames` pure layer: label candidates, normalization, `public_origin` |
| 4 | `7deab0c26` | hostname DAL (`ensure_system_hostname`, `system_hostname`, `active_custom_hostname`, …); `create_workspace` allocates; suffix threaded to `provision_*` and `install_auth_wiring` |
| 5 | `7b819a94b` | `make pages-backfill-hostnames` (idempotent; `--dry-run`, `--suffix`, `--database-url`) |
| 6 | `271cc937f` | shared `delivery_csp` + `check_publish_asset` in the design substrate (CSP verified byte-exact, 293 chars) |
| 7 | `c7e47b8bd` | `clue_page_origin`: host→workspace reads, edge gate, GET/HEAD routes (`/healthz`, `/`, `/favicon.ico`, `/p-assets/{name}`, `/asset-store/{digest}`, `/{slug}/manifest.json`, `/{slug}`) |
| 8 | `8de6d159a` | origin entrypoint (uvicorn **factory** `clue_page_origin.main:build_application`), `Dockerfile.railway`, dev stack on 8040, mypy/import-linter/DEV_STACK rows |
| 9 | `eabd8dead` | host-independent publish package: root-relative `/p-assets/…`, no `canonical`/`og:url`, favicon link, shared CSP |
| 10 | `054c42455` | publish responses carry `url`/`custom_url`/`public_origin`/`custom_origin` from the registry; `_ensure_workspace` allocates for dev workspaces |
| 11 | `f777c4630` | the O6b interim `/w/{workspace_id}/…` serving routes deleted; suites read publishes directly |
| 12 | `4dc7ea956`, `6324e6393` | share menu shows the real public host, publishes through the design API, resets state on document switch |
| 13 | `4ffd7d3da` | `infra/cloudflare/pages-edge` Worker (+ `routing.js`, tests, README, `wrangler.toml`) |
| 14 | this commit | S0 runbook, this note, spec status line |

## The nine plan-level decisions (all reversible; plan §"Decisions this plan makes beyond the spec")

1. `kind`/`status` are `text` + CHECK, not Postgres enums (no `core.enums` mirror, no parity tests).
2. One idempotent allocator, three callers — `ensure_system_hostname` is called by
   `create_workspace`, the backfill, and the design API's `_ensure_workspace` (which inserts
   workspace rows with raw SQL and never calls `create_workspace`; without this every dev publish
   would fail).
3. The system suffix reaches `clue_spine` as a **parameter** with a production default
   (`DEFAULT_PAGES_SYSTEM_SUFFIX = pages.cluehq.ai`) — `clue_spine` may not import `clue_config`.
4. `X-Robots-Tag` comes from the immutable publish manifest (`manifest["robots"]`), not a second
   `design_document` read, so the header always agrees with the bytes.
5. Both §4 tables ship in S1's single migration; `workspace_pages_settings` has **no S1 reader** —
   the origin's fallback-URL and favicon reads are a seam returning `None`.
6. The publish responses also carry `public_origin`/`custom_origin` (spec §6.3 lists only
   `url`/`custom_url`), so the share menu can show the host before the first publish.
   `custom_url`/`custom_origin` are always `null` in S1.
7. `/asset-store/{sha}` on the origin serves the recorded media type as-is — **no `sniff_mime`
   fallback** (`sniff_mime` lives in `lumen_ingestion`, which the origin must not import).
8. The share menu hides the host segment and keeps Publish inert for `kind !== "web"` (ads have no
   publish backend); no new element invented. **Founder to confirm.**
9. The second link line for `custom_url` (spec §8.1) is deferred to S2 with the co-founder's frame.

Execution rulings taken during the run (each with its cost-if-wrong) are in the ledger; the
load-bearing ones: `_cut` only cuts at a hyphen when the prefix keeps the minimum label length;
FastAPI `@router.get` does **not** answer HEAD, so the origin uses
`api_route(methods=["GET","HEAD"])`; `PORT` stays out of `.env.example` (Railway injects it;
`CLUE_PAGES_ORIGIN_PORT=8040` is the documented fallback); Node ≥ 22 needs the glob form for
`node --test`; the share-menu reset uses the repo's document-stamped-session idiom rather than a
set-state-in-effect that the error-level lint rule rejects.

## Backfill on the lane DB (Task 5)

```text
make pages-backfill-hostnames ARGS="--database-url … "
{"missing": 0, "written": 0, "off_suffix": 0}
```

0 because the lane DB has **0 workspaces**. The write path was proven separately against a scratch
workspace that was then removed. `written` counts workspaces processed, not rows inserted (only
over-reports under a concurrent creator).

## Tests actually run (per the task reports in `.superpowers/sdd/…`)

- `uv run pytest tests/test_pages_settings.py tests/test_telemetry_settings.py -q` → 9 passed.
- `( set -a; source .env; set +a; uv run pytest tests/db/test_workspace_hostname_schema_db.py tests/db/test_db_migrations.py -q )` → 8 passed; `alembic heads` → single head `aaff3d831895`; `make db-smoke` clean on a scratch DB.
- `uv run pytest tests/clue_spine/test_hostnames_pure.py -q` → 23 passed; `tests/clue_spine` → 48 passed; `tests/auth` → 50 passed.
- `uv run pytest tests/design/test_publish_delivery.py -q` → 5 passed.
- `uv run pytest tests/page_origin -q` → 18 passed (16 from Task 7 + 2 from Task 8).
- Design API focused files (Tasks 9–11), run with the repo venv from `subsystems/clue-design/apps/api`: 97 passed / 0 failed across the eight files.
- `docker build -f platform/page_origin/Dockerfile.railway -t clue-page-origin .` → succeeded with **no COPY adjustments** (490 MB); container smoke against the lane DB via `host.docker.internal` → `/healthz` 200, unknown slug 404.
- Frontend: `npm test` → 2292 pass / 0 fail (113 suites); `npm run lint` → 0 errors (2 pre-existing warnings in `canvasOperations.ts`).
- Worker: `node --test 'infra/cloudflare/pages-edge/*.test.js'` → 3 passed on Node 24. **A bare directory argument does not work on Node ≥ 22** — use the glob (or an explicit file, or `cd` into the directory).
- Static gates throughout: `ruff format --check` / `ruff check` clean on touched paths; `uv run mypy` at the known baseline **4 errors in 3 files** (`ad_assets.py`, two `arv2/*` — pre-existing, not ours); `lint-imports` 27 kept → **28 kept** after Task 8 added `page origin imports only core + config + db + obs + spine + design + storage`.

## Owed / not run (honest list)

- **The dev-stack `up` smoke** (`./scripts/dev_stack.sh up`, publish a page, open
  `http://<label>.pages.localhost:8040/<slug>`) — not run.
- **The S1 exit-gate browser walk** (spec §11, plan gate items 6) — not run. It needs a workspace
  **and a dev-login mapping** on the empty lane DB first (the hangzhou pattern: a hand-inserted
  `auth_identity` row). Founder-triggered.
- **`cd apps/frontend && npm run build`** — not run, port 3020 was busy. Substitute evidence:
  `npx tsc --noEmit` gives 107 errors on the change tree and 107 on the restored base (no new type
  error); it does not exercise Next's build-time route/type generation.
- **The hosted acceptance walk (spec §3 item 7)** — S0, founder-operated per
  `docs/specs/pages-hosting-runbook.md`. Nothing hosted exists yet: no Railway Postgres, no R2
  bucket, no `page-origin` service, no Cloudflare for SaaS, no wildcard certificate, no deployed
  Worker.
- **The whole-branch final review** runs after this task.
- `DbPageReads` (the origin's real database reads) is executed by **no test** — the fakes cover the
  routes; the dev-stack walk is its first real exercise.

## Follow-ups

**S2 (the custom-domain control plane):** connect / check / remove routes + the Cloudflare API
client + DNS observation of the ownership TXT; the Settings → Pages screen with the connection card;
the workspace **label change** (frees the old hostname immediately, no redirect — spec A1); the
`DbPageReads` **fallback-URL and favicon** reads that return `None` today (decision 5); the **second
link line** for `custom_url` (decision 9); and the S0/S2 env keys that do not exist yet —
`CLUE_PAGES_CNAME_TARGET`, `CLUE_CLOUDFLARE_*`.

**Carried defects / traps:**

- The **design subsystem's own editor copy** of `webDocuments.ts`
  (`subsystems/clue-design/apps/editor/src/engine/webDocuments.ts`) still types `url` as a path; the
  platform frontend copy is now an absolute URL. Same class as the AD4.C-3a split — unassigned.
- No `sniff_mime` fallback on the origin's `/asset-store/{digest}` (decision 7): a blob recorded as
  `application/octet-stream` is served as such.
- **Reserved slugs are not refused at publish time.** A page published under `p-assets`,
  `asset-store`, `favicon.ico` or `healthz` is unreachable on the origin (the route wins). S2 or a
  small follow-up adds them to the design API's slug refusals.
- Every `minor (deferred)` line in the ledger, notably: `PUBLISH_ASSET_EXTENSIONS` duplicates
  `tuple(PUBLISH_ASSET_MEDIA_TYPES)`; publish responses make ~6 bridged hostname reads + 4
  `Settings()` constructions per request; `_ensured_workspaces` caching means a hostname-less
  pre-existing workspace does not self-heal in a running process (the error names
  `make pages-backfill-hostnames`); the share menu has a single session slot; the Worker's in-zone
  check `host.endsWith("cluehq.ai")` is unanchored (fail-safe: passthrough) and `worker.js`'s fetch
  handler is untested (no Workers runtime under `node --test`); `test_custom_component_publish.py`
  needs `npm ci` in `subsystems/clue-design/apps/custom-component-compiler` (pre-existing worktree trap); 6 pre-existing
  ruff errors in the two alembic merge revisions; the pre-existing red
  `tests/api/test_brand_kit_onboarding_ingestion_db.py::test_no_design_api_base_url_means_no_trigger`
  when `.env` is sourced (env pollution, not ours).

## Process notes

- One implementer ran a bare `git stash` (Task 11) — popped immediately, other sessions' entries
  untouched. The rule was reinforced in every later dispatch.
- Two implementers were cut off mid-task by network/API timeouts (Tasks 8 and 11) with all edits
  present uncommitted; both were resumed rather than redone.
