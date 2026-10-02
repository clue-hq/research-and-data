# Live comprehensive-research day — close-out (2026-08-19, late evening)

## What was achieved (the headline)

The comprehensive account-research loop ran END TO END WITH REAL PROVIDERS for the
first time: launch → receipt-pinned selection → real Exa/Sumble dispatch → claims
with evidence → execution-closure settlement → prose + value narrative. 10 of 15
jobs across the two live runs settled terminally. First-ever full
crash → governed resume → settlement recovery also proven live (old-run job).

- Fresh run accdce64-de08-5e9f-953c-1eee0cfcabae: 4 of 5 settled (Texas Health first:
  11/21 fields claim-backed, 10 honest terminal gaps), 1 cycling.
- Original run b3ad33b7: 6 settled (5 pre-existing + 1 resumed crash recovery).
- Real spend recorded; dozens of provider dispatches; ~19+ new claims.

## Commits landed today (this session, chronological)

6955b601 format; c875e76e test reconcile; 2e54b6e7 concurrency 30; 9a6d139d F3/F5
launch authority; 7e2bae49 settlement closure (F1/F2/F4/F6 + Exa root cause);
1e5a066b 5x3 proof harness (~17s, at realistic 7c bundles after bcd010ea);
bcd010ea Exa reservation sizing; 9cfe4a49 resume turn identity (task_attempt);
eca414fb 3 live crash shapes (artifact anchor idempotency, empty-turn repair,
research_intent bound); 9897ea48 wave-2 (historical requestability, read-only
round shapes, unreconciled-spend replay); 9dc3e693 committee-consistency draft
guard; ebfcae63 gateway transient retry (HTTP-200-with-error-body!); 4f3c2b0b
identical-read loop breaker; 7ce9fc5c outcome normalization; 257c1f8f
question narrowing (account). ALL red-proven. make check green at 9897ea48-era;
re-run pending for the last four commits.

## Runtime state at close

- Missoula fleet: single process tree (launcher 18778) on 257c1f8f, integration_pilot
  posture (budget record-only, verification off). API 70471 on 8115 (started earlier —
  RESTART IT when convenient to load post-ebfcae63 code; it serves reads fine).
  Frontend 3115 (apps/frontend dev). Live DB clue@5432. Tunis/istanbul NEVER touched.
- Auth fix that unblocked the browser: CLUE_AUTH_CLERK_AUTHORIZED_PARTIES needed
  http://localhost:3115 (overrides in .context/live-restart-20260819/live-overrides.env).
- Browser session: QA account authenticated via browse daemon; screenshots 83-87 in
  .context/live-browser-20260819/.

## The 5 held jobs (bounded, characterized — tomorrow's queue)

1. 04162ed5 (Permanente, old run): "active tool replay changed its atomic provider
   admission" — replay-identity guard vs evolved code. Options: replay-compat pass or
   fresh relaunch of the account.
2. d46d1414 (old run): ExaDeepSnapshotError "stored Exa normalization differs from
   recomputation" — same replay-strictness class.
3. 5d9dfe7b (Millennium, old run): serial model-wedge; last shape assess↔committee
   refusal loop. Fixes 4f3c2b0b + 257c1f8f address the observed loops but the job
   re-paused before the narrowing fix drove it — resume ONCE more on 257c1f8f.
4. 298f3dec (old run): EntityResearchAgentAborted (new, undiagnosed — read journal).
5. 5f274942 (fresh run): GraphRecursionError again — verify against 257c1f8f-loaded
   fleet before deeper diagnosis; may be the committee-wedge unlocked by narrowing.

## Open work items (tasks)

- #6 pre-existing fi2_slice3_economics failures (reproduce at HEAD).
- #7 Exa alias truncation — agent "alias-fix" still working at close.
- #10 generalize refused-call loop breaker + committee composition guidance.
- Replay-compat decision for held jobs 1-2 (or fresh relaunch).
- Committee relaunch for the 5 fresh-run accounts (their directive v3 lost committee
  to the silent narrowing — guard now exists, 9dc3e693; relaunch committee-only or
  successor directive with sumble_people restored).
- BUSINESS: Sumble plan returns 402 on /techs and /people — tech stacks and committee
  members stay honest-empty until the subscription covers them. Founder decision.
- Restart API process to load latest code; run make check on final HEAD; browser
  screenshot pass over settled accounts for founder evidence.

## Key patterns ratified today (carry forward)

- Engine disposes, never quizzes: outcome normalization (7ce9fc5c), question
  narrowing (257c1f8f). Model text is not authority; narrowing to confirmed scope is
  always safe, refusing invites wedge-loops.
- Fold = settlement only; release = read-side (the F6 saga).
- Terminal attempt = dispatched + (result|fold); every genuine-exchange path stamps.
- Raw exception escaping to the supervisor = defect; governed refusal/honest
  settlement = correct. Every "worker_error:<raw type>" pause is a bug by definition.

## Late-night addendum (post close-out)

Three more commits after the close-out note:
- 01c66700: fixed-width Exa aliases (k_ + 8 base32; live root cause was provider
  TRANSCRIPTION loss over 52-74-char hex tokens - 16 of 20 unknown-spend attempts)
  + jsonb key-order normalization fix (the exact ExaDeepSnapshotError holding d46d1414).
  v1 compat proven against real stored production bytes.
- (fixture commit): contract fixture made committee-executable under the 9dc3e693 guard.
- 0296c177772f migration: committee_acquisition_snapshot_provider_unique was
  UNIQUE NULLS NOT DISTINCT (source_key, provider_operation_id) - a database-wide
  singleton for pre-dispatch snapshots; tonight's terminal 402 row occupied the
  sumble_people slot forever. Now a partial unique index (non-null only).
  Applied to the live DB. NOTE: make check's default DSN IS the live clue DB
  (rollback-conn tests are safe by design, but full-gate runs share it - the r5
  collision with the real 402 row is how the singleton defect was found).

FINAL STATE: make check GREEN on final HEAD. Fleet restarted on final code
(PID 41228 lineage) and ALL five held jobs resumed - d46d1414's exact error is
fixed; the others get their first drive under narrowing+alias+migration. Left
driving overnight; check settlement states first thing next session.
