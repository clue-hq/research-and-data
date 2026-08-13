# 2026-08-12 — Slice-2 adversarial review: FIX-FIRST both halves. Fix wave NOT yet applied.

Full suites: tests/api 100% green under a clean env (4 observed failures reproduced as purely
environmental — shell-exported .env auth vars + exa webhook secret; NOT slice-2 defects).

## BACKEND BLOCKERS (both verified against shipped code, not speculation)
- **BE-B1 (the big one): the D-4c kicker is a production NO-OP — the background lane never
  runs.** ToolInvoker journals by operation_id: DbInvocationJournal.begin derives node from
  ctx.operation_id and RETURNS THE CACHED ToolResult (replayed=True) for a completed node —
  second/third driver invocations with the same deterministic op id never reach the tool
  (pinned green by tests/execution/test_journal.py:203-225). My route test's stub invoker has
  no journal = exact semantics drift; `invocations == 2` proved calls, not lanes. FIX: per-
  attempt op ids (`stage0-setup:{digest}:{attempt}`) — safe: governed exact-replay only
  matches an existing row id, else falls to live-dedupe → returns existing recon → tool drives
  the queued lane. Assert result.replayed is False in the driver.
- **BE-B2: a failed fast lane is PERMANENT.** transition guard latches failed; started_fast
  only on QUEUED; same op id → journal replay; exact-replay precedes the TTL check so even
  24h expiry never mints a fresh run. Retry is a guaranteed no-op; escape = DB surgery or a
  case-different website. FIX: durable retry generation in the id derivation; never mutate the
  failed lane.

## BACKEND MAJORS
- BE-M3 viewer can trigger SPEND: /stage0/setup enforces only project.read (override default)
  while POST /tools/start_recon requires thread.write. FIX: principal + require (research.
  launch?) before capture; also fixes BE-m9 (bare ToolContext → journal has no actor
  attribution; use tool_context_for_principal).
- BE-M4 binder composed UNCONDITIONALLY while routes are flag-gated: pre-slice-2 start_recon
  refused everywhere; now any thread.write principal can POST /tools/start_recon with an
  arbitrary website → paid scrapes on our key (target-lock keys on caller-supplied website);
  + provision-replay website mutation = unbounded paid-recon loop (G2 unaddressed). FIX: gate
  binder composition on the same flag (deployment byte-identical when off) + throttle stance.
- BE-M5 "complete" over a zero-fact KB: 5¢ burned on ~5 identical homepage fetches, zero
  claims, marked COMPLETED. FIX: surface fast_client_kb_version/coverage in SetupStatusResponse
  so "ran and found nothing" is distinguishable (pairs with the LLM-extractor work item).
- BE-M6 no observable RUNNING (whole lane = one commit-on-exit transaction → GET sees
  none→complete) AND driver refusal/death leaves status "none" forever (202 already returned).
  FIX now: durable started/refused marker readable by GET; transaction granularity = slice 3.
- BE-M7 DSAR: erase nulls provisioning.company_website but slice 2 COPIES it into
  onboarding_input.source_ref + artifact bytes — my own erase docstring is now false. FIX:
  extend erasure or amend docstring + backlog entry.
- BE-M8 casefold drift 500: digest casefolds, artifact bytes don't; case-only website edit →
  same onboarding_input_id + different sha → drift ValueError → uncaught 500 forever. FIX:
  capture the SAME normalized string the digest uses; wrap drift error → typed 409.
- BE-m10 projections root passes no pre_spend_gate (fleet does) → no gate_decision audit rows
  on this path ([M9.1] family). BE-m11 no scrape artifact cache (N fetches per recon;
  pre-existing, now paid+live). BE-m12 CLUE_SCRAPE_BACKEND undocumented in .env.example
  (default=paid firecrawl; local scrapling is untracked). BE-m13 binder: unbounded process
  dict + last-write-wins global rebinding (single-owner landmine for a future real-extractor
  resolver; add workspace assert in key_for). BE-m14 concurrent POST: second driver's journal
  begin hits execution_attempt unique violation → logged misleadingly as driver_failed.

## FRONTEND BLOCKERS
- FE-B1 "unavailable" stranded state: POST 409 sets failure, then the poll's setFailure(null)
  WIPES it within 1.5s and 'unavailable' falls through silently → eternal motionless screen,
  no message/retry (guaranteed for invited members/deep links — the server-side redirect
  guard was deleted this slice). FIX: 'unavailable' = surfaced terminal state; poll must not
  clear failures it didn't set.
- FE-B2 failed lane: "or continue — we'll pick it up later" has NO continue affordance, and
  Retry (reload+re-POST) is provably a no-op (BE-B2). FIX: real "Continue anyway" →
  /session/establish; retry only once BE-B2 gives it meaning.

## FRONTEND MAJORS/MINORS
- FE-M1 running never renders (BE-M6) + MAX_PENDING_POLLS=20 (30s) fires false "hasn't
  started" during a healthy long fast lane → user reloads into an advisory-lock wait. FIX:
  after 202, stop counting none→failure; copy "still starting…".
- FE-M2 permanently-failing poll invisible (catch{} swallows 401/403/parse; counter only on
  successful 'none'). FIX: consecutive-error counter; 401/403 surfaced with sign-in link.
- FE-M3 failed/paused lanes render as 'queued' (background failure invisible = wrong-direction
  lie). FIX: distinct terminal visual or drop the row.
- FE-N1 failure block displaces the frozen centered geometry (second grid row) — render
  inside the setup stack. FE-N2 SetupStatusSchema strict enum → additive backend status kills
  every poll silently (use .catch/safeParse). FE-N3 error envelope discarded (copy
  provisionWorkspace's parsing; code on SetupApiError). FE-N4 StrictMode drops a POST failure
  (cancelled-flag guards a ref-latched one-shot). FE-N5 finalizing renders non-compact
  LiveSetupScreen (unreachable in clerk mode; controller's setting-up→finalizing submit is
  pre-existing dead code). FE-N6 location.assign → back-button trap (use replace). FE-N7 no
  poll backoff/cap (~2400 cycles/hr stranded tab ×2 backend round trips). FE-N8 setStatus
  identity churn. FE-N9 brand-kit row coupled to fixture id string.
- Tests: zero new FE tests; extract laneItemStatus/item-derivation + a pure poll reducer;
  test runner only collects *.test.ts (not .tsx). BE tests: real-invoker test needed (journal
  semantics!), failed-lane, flag/mount/override, PreconditionFailed path, concurrency.

## FOUNDER-AWARENESS
- Checklist copy divergence table (FE report): 4 designed rows → 3 real rows; competitors/
  buyers rows removed (honest until slice 3), ONE NEW non-designer row ("Deep research on your
  company"), brand-kit row inert grey (was 'running' in design), and with BE-M6 the whole
  screen currently shows NO motion at all until release. Needs founder eyes.
- Viewer-spend permission choice (which permission gates setup — research.launch?).
- Binder flag-gating stance + G2 throttle (BE-M4) before any enabled deployment.

## CLEARED
Tenancy sound (no cross-tenant path in any mode); dedupe inputs match GET↔tool; capture-
before-use ordering right; project-less onboarding_input acceptable for kind=website (binds
by explicit id); fixture-mode fidelity PASS end-to-end; hold=1 intact; binder composition
itself (explicit settings/policy) correct; frontend gates genuinely green.
