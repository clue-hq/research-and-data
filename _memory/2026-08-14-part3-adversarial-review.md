# 2026-08-14 — Part III adversarial review (P3.0–P3.5): findings ledger

Founder-requested exhaustive adversarial self-review of the Part III train
(commits `7ef224c9` P3.0 … `20281320` P3.5). Review dimensions: tenancy/fail-closed,
authority derivation, replay/crash convergence, races, spec conformance, and the seams
between the leg engine and the older substrates (fleet leases, the D5 design reaper,
lane-D turn machinery, the gate flow). NO fixes applied in the review itself — every
finding below is verified against ground truth (file:line) and awaits disposition.

## Confirmed defects (ordered by severity)

- **[E — HIGH] The inline design lane never renews its work lease.**
  `design_fleet.InlineDesignLaneDriver.drive` acquires the design run's work lease once
  (`DEFAULT_LEASE_TTL` = 30s, `clue_fleet/lease.py:23`) and holds it across a design turn
  that runs minutes, with NO heartbeat/renewal (unlike `LeasedWorkWorker._heartbeat` and
  the B1 supervised-heartbeat precedent). The lease expires ~30s in; the design reaper —
  enabled by exactly the same switch that enables the lane — declares the still-executing
  run stranded at ~120s (`fleet_reaper._is_stranded`: lease not live + `task_missing`,
  since inline runs have no fleet task) and re-offers it. Generation fencing prevents row
  corruption, but the outcomes are timing-dependent: duplicate design execution (double
  model spend), the inline body fenced out mid-flight, or the AGENT_TURN turn failing
  ("returned without a terminal design run") while a detached design_job completes the
  run later. Worse: `reoffer_stranded_run` CLEARS `lease_generation`, so the abandoned
  inline body's terminal write can land *after* the re-offer. Fix: a supervised renewal
  loop inside `drive` racing `handler.handle` (set `context.lease_lost` on renewal
  failure so the handler abandons cooperatively), per the B1 pattern.

- **[B — HIGH, couples with E] Leg-run row payload is not the frozen envelope.**
  `DesignLegTurnRunner._dispatch` stores `payload=dict(envelope.config)` on the run row;
  the design substrate's contract is that the row payload IS the frozen
  `DesignTurnEnvelope` (the reaper re-enqueues `payload=handed_back["payload"]`,
  `fleet_reaper._reoffer` — "re-read from the design row rather than rebuilt"). A
  stranded leg run is therefore re-offered as a design_job whose payload fails envelope
  validation at `DesignJobWorkHandler._parse` → poison task, and the strand-repair
  machinery is broken for leg runs. Fix: store `envelope.model_dump(mode="json")`; with
  E fixed, reaper re-offers then become a working second-chance completion path and the
  retried AGENT_TURN converges via the existing terminal-run re-join.

- **[A — MEDIUM] The design-turn thread summary silently loses the run's stop reason.**
  `design_leg_wiring._assistant_summary` reads `run.get("result_json")`, but
  `clue_design.runs.get_run` returns the DTO key **`"result"`**
  (`_agent_run_from_row`, runs.py:97) — so the branch is always `{}` and every summary
  degrades to "Design turn succeeded." Test-weakness meta-finding: the engine tests
  asserted `assistant_message is not None` / replay-equality, never the content, which
  is exactly how this slipped. Fix: read `"result"` + strengthen the assertion to pin
  the stop-reason text.

- **[C — MEDIUM, needs a founder ruling] A gate answer submitted while a leg is open
  becomes a design prompt.** The submit route's gate path applies the confirmation
  effect at accept (correct), but the captured gate-response turn then routes by the
  D1 rule — an open leg receives it — so the design agent gets the canonical
  gate-answer JSON as a design instruction. The spec's "no other routing input exists"
  read literally produces this; the gate flow is semantically head-of-abm's. Options:
  (a) the route refuses gate answers while a leg is open (409, "finish the design
  session first"); (b) gate-response turns are an explicit routing exception to
  head-of-abm; (c) accept as-is. Recommend (a) as the smallest honest rule; needs a
  ratified amendment either way (P3.6/P3.7).

## Lower-severity findings

- **[D — LOW/MED] Reopen provenance is untracked.** `reopen_leg` flips state and nulls
  `close_reason`; `opened_by_turn_id` keeps the ORIGINAL opener, and nothing durable
  records WHO re-delegated or WHEN. §2.1 promises the exit record survives (it does),
  but an auditor cannot reconstruct the reopen act itself. Recommend journaling reopens
  (append-only, same table or a sibling) or re-stamping an opener column.

- **[LOW] Redelivery idempotency key lives in the client key space.** The out_of_scope
  redelivery derives its turn id from key `design-leg-redelivery:<leg>:<turn>`; an
  authenticated same-workspace client could submit that literal key first, planting a
  different message under the derived id → finish's `insert_submission` raises
  `SubmissionConflict` and the close aborts (leg stays open — recoverable nuisance,
  not corruption). Recommend the route rejecting client-supplied keys with the reserved
  prefix.

- **[LOW] Head-of-abm history include is fragile to malformed journal rows.** The
  summary-include subquery CASTs `summary_refs->>'summary_message_id'` to uuid for
  every journal row in the workspace; any future `close_leg` caller writing a non-uuid
  value there breaks the whole workspace's conversation history load. Only P3.5's tool
  writes the key today. Recommend a defensive regex filter in the SQL or validation in
  `close_leg`.

- **[LOW, bridge-time] A mid-turn `finish_design_leg` leaves the closing turn's
  finalize envelope claiming `AWAITING_INPUT` with the leg as an open gate ref** even
  though the leg is closed — when the orchestrator bridge lands (P3.7), the runner
  should finalize a leg-closing turn as COMPLETED without the leg gate ref. Also: a
  locked close currently produces TWO assistant messages for one turn (the runner's
  outcome summary + the leg summary) — transcript noise for Part IV to render or for
  the runner to suppress when a close is detected.

- **[LOW] A stopped (user-Stop) design turn leaves the leg in `running`** until the
  next message self-heals it (the runner tolerates `running` on entry). Speaker chip
  shows "running" in the interim. Acceptable; noting so P3.6's cancellation tests pin
  the self-heal.

- **[LOW, doc] The P3.2 gate follow-up #3 (document the ratified trio config —
  reviewer=claude-opus-4.8, reasoning=medium — in `subsystems/clue-design/.env.example`)
  was NOT done in P3.3;** the file still has blank `LUMEN_AGENT_MODEL_REVIEWER=`.

## Reviewed and found sound (the load-bearing negatives)

- Tenancy: every new leg/journal/history/speaker read and write keys workspace;
  cross-tenant rows are indistinguishable from missing. The summary-include subquery is
  outer-scoped by thread, so no cross-thread leakage.
- Authority: nothing model-authored crosses an authority line — leg anchor, exit turn,
  and the out_of_scope pending message are all derived from durable rows
  (TRUSTED_TURN_FIELD / submission), and the finish replay-before-open-leg ordering
  means a stale close retry can never re-close a deliberately reopened leg.
- Replay/crash: leg id, execution id, run id, redelivered turn id, and both history
  message ids are all derived; every crash window replays convergently (verified path
  by path); the committed-finalization short-circuit covers the design turn exactly as
  it covers head-of-abm's.
- Races: per-thread single-flight (fleet task exclusivity) is the umbrella that makes
  the leg state machine's guarded transitions sufficient; finish-vs-runner interleaving
  is safe (`_leg_back_to_awaiting` only transitions from `running`).
- §2.4 scoping holds in both directions incl. after close (summary in, transcripts out);
  routing rule, speaker projection, accept-time visibility all behave per spec.
- Spec deviations, all deliberate and recorded: platform context assembler not used for
  design turns (bundle rides constitution + envelope; fail-closed equivalent); the
  §2.4 "summaries as DelegationResult shapes" materialized as a text summary message +
  the closing turn's real finalize envelope; inline lane instead of a queue hop (the
  single-worker deadlock); delta-8 stream vocabulary deferred to P3.7 per the spec's own
  slice table. P3.1–P3.3 re-examined structurally (migrations up/down/up, audit
  machinery, catalog pins==grants): sound; P3.2's known constraints (cross-model
  fallback vs encrypted reasoning, terra 500 shape, cost_millicredits=0) remain in
  their ledger with owners.

## Disposition

Fixes NOT applied in this review session (assessment-only per founder request). E+B
should land together before any production leg traffic (they are the crash-resilience
story); A is a two-line fix plus a stronger test; C needs a ruling. D and the LOWs can
ride P3.6/P3.7.
