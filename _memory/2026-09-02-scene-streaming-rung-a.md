# 2026-09-02 — scene-ad live streaming, rung A SHIPPED (lock + checkpoint streaming); P0.4 was silently dead

Plan: `docs/superpowers/plans/2026-09-02-scene-live-streaming.md` (rung A = Tasks 1–5, + amendment
Task 4b). Regime: Opus implementers, Fable orchestrates/reviews/verifies/decides (founder rule
2026-09-02; recorded in user memory). SDD ledger: `.superpowers/sdd/2026-09-02-scene-live-streaming/`.

## Commits (local, `design/scene-ad`, base b5bcb7f88)
- 742dafab + 2c718336 — design-API 409 `document.agent_run_active` on SIX manual scene-write routes
  (/scene /operations /undo /redo /edits /revert); predicate = any RUNNING run whose frozen envelope
  targets the document (queued does not lock); agent's own tool path proven unaffected.
- a9b63fb26 — platform forwards `scene_checkpoint_committed` → `design.checkpoint` turn frames
  (background tailer in the leg driver + final drain); migration 35cda1939728 widens the closed
  `agent_turn_event_stream_type` CHECK (the plan's "no migrations" was wrong).
- 8085141f4 — frontend parses `design.checkpoint`; canvas reloads throttled ≥2s trailing; feed
  never refetches on checkpoints.
- 214cb9897 + f4e5a1cbd — editor lock: pure `agent-run-lock.ts` fold + derivation; durable leg seed
  from `ThreadWire.speaker.design_leg_state` (was unparsed); per-turn leg release; `writeGate()`
  note at consumers; proactive note in the inspector on engage.
- 4aa344bf6 — runtime: P0.4 checkpoint trigger keys on ROUND ACCEPTANCE (critic PNG clean;
  canonical-SVG failure excused only when every error is the font-embedding refusal).

## THE finding: P0.4 mid-run checkpoints never fired for ~71% of brands
Brand fonts are stored as WOFF2 (367 of 517 font assets, 47 workspaces). `lumen-skia/embed.rs`
refuses to embed WOFF2 into SVG → canonical SVG export status=error every round →
`bundle_validation_errors` folds it into reviewer.status=error → `render.py` checkpoint gate never
passed. Finalize does not gate on it, so runs "succeeded" while no mid-run version ever committed —
P0.4's durability AND rung A's streaming were dead. Task 4b fixed the trigger. SEPARATE follow-up:
WOFF2 embedding in the Rust exporter (SVG exports for those brands ship without embedded fonts).
Marker is the Rust string "SVG font embedding failed" (pinned by test); durable fix = thread
`CoreError.code` into ExportSummary (a separate ruled change: it alters reviewer strings).

## Live walk verdicts (colombo stack, Apollo ws, thread thr_f8fbbbfa…, doc_1c35a98d…)
Walk #1 (pre-4b): lock engages on send (Edit disabled, title = ruled sentence); sibling-thread doc
stays unlocked; second-client POST → 409 naming the run, doc untouched; Edit entry refused even via
`&edit=1`; unlock at terminal; gallery quiet; NO checkpoints (→ root cause above).
Walk #2 (post-4b): checkpoint at 00:08:18Z (v119→121 mid-run, frame payload on contract) → canvas
GET one second later (checkpoint-driven reload); terminal at 00:09:23Z with the terminal reload;
thumbnails 0; run's final version == checkpointed version.

## Ops facts (hard-won)
- Design-API/platform/runtime TEST SUITES SEED RUNS INTO THE SHARED DEV DB and the LIVE fleet worker
  executes them with real LLM spend (26 rows drained after Tasks 1–2; a 57-call run after Task 4b
  delayed a real turn by 16 min). Mitigate: fail `ws_test_%` queued/running rows; durable fix =
  worker claim-query exclusion for test workspaces or a disposable test DSN (founder ruling wanted).
- Restart colombo services by PID after cwd check (three worktrees' workers run on this box);
  a fleet worker mid-turn ignores SIGTERM → SIGKILL after cwd check. Frontend hot-reloads.
- Design-api focused tests need `set -a; source .env; set +a` (else the un-migrated default DB).
- `features/projects`/`chat-shell` tests are node:test (`npx tsx --test`), not vitest.

## Deferred minors (none block merge) — triaged at rung close
T1: queued/cross-workspace non-lock untested; lock predicate unindexed; stranded running row locks
until reaper; `/finalize` unguarded can flip draft mid-run (scope); web routes unguarded (deferred
lane); monkeypatch raising=False. T2: restated topic literal (DRY); filter test could go vacuous;
suppress(CancelledError) on tail; shared `_forwarder` on process-wide driver; dropped-frame counter;
design_fleet.py at size ceiling (extract forwarder in Task 7); 0.5s settle window. T3: untyped
event-type constant; controller wiring branch untested; int-vs-number leniency. T4: post-submit
one-RTT unlock window (409 nets); press-refusal prose; 3 lock-check sites; reportNote leaves stale
error; refused force-commit leaves caret; force-commit/pointer paths pure-tested only.

## Founder questions (open)
1. ~~Visible lock reason OUTSIDE edit mode~~ — RULED 2026-09-02: the disabled Edit pill's hover
   title is accepted as sufficient for now (no new chrome); revisit only on user confusion.
2. `turn.awaiting_input` (gate-parked design turn) holds the lock — flip if a parked run should be
   editable.
3. `/finalize` (and `agent-instructions`/`layout-managed-editing`) unguarded during runs — scope?
4. Test-DB hygiene fix shape (claim-query exclusion vs disposable DSN).
5. WOFF2 SVG font embedding (Rust exporter lane) — schedule?

## Rung B next
Op-batch frames (`operations_total` cursor), ported MVP reveal pump, late join via checkpoint
versions. Walk residuals to cover there: lock engaging over an OPEN text session (start a run from
edit mode); kill-worker → turn.failed → unlock (pure-tested only in rung A).
