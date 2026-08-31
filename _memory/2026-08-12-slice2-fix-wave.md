# 2026-08-12 — Slice-2 review fix wave SHIPPED (commits 18001189 backend, d0b866b0 frontend)

## Every scoped finding resolved
- **BE-B1 (kicker no-op)**: per-iteration op ids `stage0-setup:{digest}:a{attempt}:i{k}`.
  Journal replay of a cached iteration is benign (driver reads lane refs, continues only
  while non-terminal). REGRESSION GUARD: `test_kicker_drives_both_lanes_through_the_real_
  invoker` uses build_tool_invoker + DbIdempotencyStore + a fake start_recon Tool writing
  real durable rows — asserts 2 genuine executions with distinct ids.
- **BE-B2 (failed lane permanent)**: `transition_recon_lane` releases the dedupe slot on
  fast FAILED (dedupe_expires_at=now(); lane latch untouched); attempt = durable count of
  failed-fast runs per (ws, dedupe) → a retry POST mints a fresh run. Guarded by
  `test_failed_fast_lane_is_retryable_via_a_fresh_attempt` (incl. slot-release assert).
- **BE-M3/m9**: POST requires research.launch when a principal is present; driver uses
  tool_context_for_principal (journaled human authority). Viewer refusal pinned.
- **BE-M4**: binder composition at BOTH roots gated on self_serve_provisioning_enabled —
  flag-off deployments byte-identical to pre-slice-2. Route mounting pinned by
  `test_setup_routes_mount_only_behind_the_flag`.
- **BE-M5/M6**: status gains `starting` (input row durably captured, recon row not visible —
  detected via the deterministic attempt input id); complete carries fast_client_kb_version
  + fact_count (recon_brief facts length). Driver refusal ≈ impossible in flag-consistent
  builds (binder+routes same flag) — documented, not silently absorbed.
- **BE-M7**: no source_ref URL copy (append-only row un-redactable); artifact-bytes residual
  recorded in erase_platform_user docstring. **BE-M8**: digest no longer casefolds (must
  equal captured bytes; tool dedupe still casefolds); drift ValueError → typed 409.
- **FE-B1/B2**: start-vs-poll failure channels separated; unavailable/failed/session are
  surfaced terminal states with real controls (Try again = fresh attempt; Continue anyway →
  location.replace('/session/establish'); session → sign-in). Polling stops on terminal.
- **FE-M1**: `starting` renders fast row as running (motion restored); pending budget 60s
  with "taking longer" copy — never "hasn't started". **FE-M2**: 401/403 surfaced
  immediately; ≥5 consecutive transport errors surface a retrying note. **FE-M3**: pure
  `deriveSetupItems` + `laneItemStatus` (model/setup-items.ts) map failed/paused to an
  annotated honest state; all five lane statuses pinned. FE-N1 (.setupStack single-cell
  wrapper), N2 (.catch → surfaced terminal), N3 (envelope code on SetupApiError), N4
  (ref-latched start failure re-applied — StrictMode safe), N5 (compact threads through),
  N6 (location.replace everywhere), N9 (BRAND_KIT_ITEM_ID constant), controller dead
  setting-up submit branch removed.

## Gotchas this wave
- pydantic Settings() reads the repo .env FILE directly → an untracked env line can flip
  backend-selection tests. CLUE_SCRAPE_BACKEND removed from .env (comment left); set
  scrapling PER DEPLOYMENT while the extractor is empty.
- Real-invoker tests must not poll the DB concurrently with the driver on the shared
  rollback conn (InterfaceError) — wait on fake.executions (loop-local), then read once.

## Still open (recorded, not silently dropped)
- G2/D-9 throttle stance (founder); checklist copy divergence + currently-limited motion
  (founder awareness — 'starting' restores row-1 motion; row-2 motion appears when the
  background lane runs post-fast); BE-m11 scrape artifact cache (N fetches/recon — slice-3
  rider); BE-m13 binder single-owner landmine note + unbounded dict; transaction granularity
  (running visible mid-lane) = slice-3 prerequisite; LLM claim extractor = named slice-3
  work item; live-Clerk browser pass still pending founder dashboard actions.

## Gates
Backend: stage0 + auth + setup suites green (130 tests incl. 6 setup); make lint 0; mypy
clean. Frontend: eslint clean; 164/164 (11 new); production build green.
