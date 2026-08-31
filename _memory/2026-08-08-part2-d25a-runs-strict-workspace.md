# Part II D2.5A — agent runs + run events on Postgres, and the STRICT O4 workspace seam

Branch `platform/design-integration`. Two things: the **last** SQLite `Repository` domain moves
to Postgres, and the workspace header stops being optional.

## Task 1 — the runs DAL

**New** `subsystems/design/clue_design/runs.py`: `create_run` / `get_run` / `require_run` /
`set_run_result` / `complete_run` / `append_run_event` / `list_run_events` /
`list_running_runs` / `list_running_runs_across_workspaces`. Workspace-scoped, fail-closed,
`*_from_row` shapes reproduced with ISO timestamps. Tables keep their D1 **temporary** shape —
no reshape (that is D5; `design_run_event` dies at D7).

Three decisions worth remembering:

1. **`append_run_event` allocates its seq inside the insert's own transaction** via the existing
   `sequences.allocate_run_event_seq` (`FOR UPDATE` on the parent run). That is the O5 rule, and
   it is why `next_run_event_seq` is deliberately **not** overridden on `HybridRepository` —
   exposing the allocation as its own bridge call would be exactly the split O5 forbids.
2. **`create_run` stores an unresolvable `document_id` as NULL** rather than tripping
   `design_agent_run_document_fk`. `POST /agent/turns` carries the editor's document id with the
   scene inline in the payload — that document need not be stored — so refusing would break a
   shipped route. Behaviour-preserving: the only consumer of `document_id` was the
   `LEFT JOIN documents` for `doc_kind`, which yielded NULL for a dangling id anyway, and no
   endpoint echoes `document_id` back. Cross-workspace document ids resolve to NULL too.
3. **`list_running_runs_across_workspaces` is the DAL's one unscoped read**, for the startup
   orphan sweep only. `_fail_orphaned_runs` runs at app construction, before any request names a
   tenant, and a restart orphans *every* workspace's in-flight turns — a dev-workspace-scoped
   sweep would strand all the others. The rows carry `workspace_id` so each orphan is failed
   through a workspace-correct store.

**Defect found and fixed during the port: terminal result and terminal marker event were two
writes.** Every finishing path did `set_run_result` then `append_run_event`. Under SQLite those
were two fast local commits; through the O5 bridge each is its own engine + round trip, and the
async-turn test reliably caught a run that was `succeeded` with `events == []` (the poller then
saw the worker's catch-all overwrite it to `failed`). Fused into one transaction —
`clue_design.runs.complete_run` / `Repository.complete_run` / the `HybridRepository` override —
with the result written **before** the marker, so the SSE stream (which reads the run row the
moment it sees a terminal event) can never read an uncommitted result. All five call sites
(agent-turn success/failure, web-turn success/failure, the sweep) now use it; `set_run_result`
survives as a primitive but has no caller in `main.py`.

## Task 2 — the strict seam

`resolve_workspace_id(request)` now raises `401 {"code": "workspace.header_required", ...}` when
`X-Workspace-Id` is absent. **The env fallback is deleted from the request path**;
`default_workspace_id()` survives only for direct constructions (sweep, scripts, tests). The
silent fallback was the dangerous part: a miswired caller read and wrote the dev tenant's data
and looked healthy doing it.

**Exempt (headerless), exactly three** — each because the caller *cannot* send a header:
`/build-info`; `/asset-store/{digest}`; and the `/w/{workspace_id}/...` group (`/p/{slug}`,
`/p/{slug}/manifest.json`, `/p-assets/{name}` — O6b path-scoped). No health route exists.
`/font-library` and `/agent/turn-preview` had no store dependency and were therefore accidentally
headerless; both now carry `dependencies=[Depends(resolve_workspace_id)]` so the exemption list is
exactly three, not four.

**`/asset-store/{digest}` ruling (asked for explicitly):** stays PUBLIC. `lumen-web`'s *delivery*
render emits `/asset-store/{digest}` URLs for images and `@font-face` — the published page loads
them — and so does the editor's origin-`"null"` srcdoc preview iframe. Adding a header would turn
both into preflighted requests the wildcard CORS response cannot satisfy. Content-addressed +
immutable, so serving without a tenant leaks nothing an unguessable sha256 did not already gate.
Residual recorded at the route: content addressing is not authorization — D4 (`clue_storage`) +
Part-IV auth own the real serving policy (same class as the platform's `[B2×presign]` follow-up).

**The SSE exception.** `GET /agent/runs/{id}/events` cannot take a header: browsers' `EventSource`
cannot set one, by specification. New `resolve_stream_workspace_id` accepts the header **or**
`?workspace_id=`, and 401s with the same code when neither is present — the same "no header
possible, put it in the URL" move O6b makes with the path. Its `poll_once`/`read_run` now build
`HybridRepository` with that workspace instead of a plain SQLite `Repository`.
**Poll cost, accepted interim:** the O5 bridge builds a private engine per call, so a 4 Hz stream
pays two engine setups/second/subscriber. Dies with the bridge at D5; the polling loop itself dies
at D7. Commented at the site.

**Editor.** `editorConfig.ts` gains `editorWorkspaceId()` (`NEXT_PUBLIC_LUMEN_WORKSPACE_ID`,
default `ws_lumen_dev`), `lumenFetch` (fetch + the header; caller headers win), and
`runEventsUrl()` (SSE url with `workspace_id`). All 13 API-calling engine modules now go through
`lumenFetch` — including the injectable `fetchImpl` defaults. `canvaskit/imageCache.ts` is
deliberately left on bare `fetch` (it pulls `/asset-store` bytes; see the CORS reason above).
`NEXT_PUBLIC_LUMEN_WORKSPACE_ID` added to `apps/editor/.env.development` and `.env.example`.

**Design suite.** `tests/conftest.py` gains `make_client(app)` (TestClient with the header from
the per-test `LUMEN_DEV_WORKSPACE_ID`) — all 26 `TestClient(app)` constructions switched — and
`unique_run_id(label)`. The latter matters: `design_agent_run_pkey` is `PRIMARY KEY (run_id)`,
**global, not workspace-scoped**, so unlike workspace-local document ids a hard-coded test run id
collides with the previous suite run on a persistent DB. Three run tests were re-pointed at minted
ids. New `tests/test_workspace_seam.py` (8) covers the 401, the three exemptions, and the SSE
carrier.

## Verification

- `ruff format`/`check` (`subsystems/design tests/design`) clean; `mypy` 586 files clean;
  `lint-imports` 25/25.
- Fresh `clue_d25a`: `make db-smoke` exit 0; `tests/design/` **46 passed** (40 + 6 new).
- Full design-API suite on Postgres: **505 items, 495 passed, 10 skipped, 0 failed**, exit 0.
  (First pass surfaced 4 failures, all fixed: 1 real defect — the two-write terminal race above —
  and 3 fixed-run-id PK collisions.)
- Offline platform suite: **2176 passed, 1493 skipped**, exit 0 (baseline 2176/1487; +6 skips are
  the new DB-gated runs tests).
- Editor: `npx tsc --noEmit` clean; `npx vitest run` **988 passed, 101 skipped**, 0 failed.

## Residuals

- **Module-level helpers in `main.py` still default to the dev workspace.**
  `resolve_agent_turn_brand_kit`, `resolve_web_turn_brand_kit`, `workspace_asset_library_manifest`,
  `reference_asset_manifest` build `HybridRepository(connection)` with no workspace (~lines
  6860–7290). They run off the request thread for the agent-turn/preview paths. Harmless in the
  single-tenant dev harness, but now the *only* implicit-tenant path left; thread the workspace
  through when D5 reshapes the workers (the workers already carry `workspace_id` for their store).
- **`WebPublishDialog.tsx:121`** still mints `/p/{slug}/manifest.json` client-side (pre-existing
  D2.4B residual; Part IV).
- The SQLite `agent_runs` / `run_events` tables and the rest of the legacy schema are now fully
  dead behind `HybridRepository`; Part II retires them wholesale.
