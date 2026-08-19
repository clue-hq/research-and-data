# Live research approval: queued UI and Missoula fleet failure

Date: 2026-08-19, observed from 14:11:13 through 14:17 IST. This is an evidence/state
note only. No source fix, database mutation, queue repair, or further research action was made
while documenting it.

## What the frontend is showing

The founder's screenshot at 14:11:47 IST is an honest rendering of a durable post-approval turn
that has not started. It is not evidence that the approval disappeared or that the React tree
crashed:

- The card still shows `Research approved` and `1 research run launched` for the one R6 research
  fleet containing the ten selected Accounts.
- The next Clue article contains only the `Queued` status and the page-level message
  `Queued — waiting for the current turn to start.` Because there is no assistant text or result
  card yet, the chat column below it is visually sparse.
- The composer is present, but Send is disabled while this turn is treated as active.
- The artifact workspace is still mounted and its selected Gallery reports `0 artifacts` /
  `No artifacts found`; its empty panel contributes to the large white area. The browser's
  `ChatGPT started debugging this browser` banner in the founder screenshot belongs to Chrome's
  automation surface, not the Clue frontend.

An unchanged authenticated DOM inspection at 14:17 IST still found the complete project history,
all ten Account context chips, the research-approval receipt, the queued article, the disabled
composer, and the empty Gallery. A fresh 1800x987 screenshot was byte-identical to the pre-failure
browser capture `46-research-approved-and-launched.png` (SHA-256
`638640167099548f5e321324a11b13dd89eae57ff425b8544b42b895baa6ce54`). It is retained as
`.context/live-browser-20260819/47-current-queued-frontend-state.png`. The founder attachment is
`.context/attachments/6mlNht/Screenshot 2026-08-19 at 2.11.47 PM.png` (3600x2338; SHA-256
`9636108de0f0e5be5bedac948230d01cdbe00b540ef3023743b720e499124654`).

## Durable approval and launch state

The human approval committed at `2026-08-19 14:11:13.717314+05:30`:

- project `prj_a4cfd10af5775d2c831eaed63373e3b3`;
- project run `d5264587-4297-5db8-bfed-4f67597401c1`;
- directive gate `a5b32db2-abc8-511f-bfec-643f43de776e`;
- confirmed directive `9b8109ef-fbd3-5f61-acb5-6109950f29f8`, version 1, canonical SHA-256
  `8e6a105380d1a3eadbd5633cec9536d4df6effc870331490cc53bf196b5c3fff`;
- research fleet `9bb6ce35-5460-5625-9427-6d77797c4ba7`;
- ten durable `account_run` rows, all `high` and `pending`, all pinned to that directive; and
- ten durable Account research jobs/tasks plus the automatic follow-up agent turn
  `fd53cfd8-5797-51a1-a261-1ece94b103f1`.

The `1 research run launched` copy means one research fleet was durably created for ten Accounts;
it does not mean one Account finished, that a provider request was made, or that research results
exist. At the final read, no `account_gap_operation` existed and the research fleet reported zero
spent cents, zero active Accounts, zero completed Accounts, and no contact research started. The
`account_deep_launch` table also had no row for this project run; the live R6 launch authority is
the research-fleet/job set above.

## Primary failure: launch was allowed before discovery was sealed

The ten Accounts were visible and selectable in the frontend, but the governing discovery batch
`d831d343-e7ef-5dcd-9caa-c838505836ac` was still `seal_pending`, not `sealed`. Its discovery phase
checkpoint remained `waiting_external` with blockers `operation_terminality`, `dispatch_receipts`,
`required_fields`, and `spend_reconciliation`.

That produced a cross-layer contract mismatch:

1. The Accounts surface exposed the ten admitted candidates.
2. The directive gate accepted that exact set and created the R6 Account jobs.
3. The first Account agent tried its admitted Sumble tools.
4. `DbSealedDiscoveryAccountManifestReader` rejected provider compilation because its immutable
   source manifest did not exist in a `sealed` generation.

The durable parallel-tool ledger preserves the exact suspending error:

```text
SumbleAccountGapEligibilityError:
Sumble account-gap enrichment requires an intact discovery seal
```

This is a zero-spend pre-dispatch authority failure. It is not a provider HTTP failure, an
Account-fit decision, a budget threshold, a coverage percentage, or a demand for more human
questions. The check exists so paid enrichment cannot bind its claims to a mutable or incomplete
discovery generation. The immediate product defect is that the UI/launcher allowed research
approval before that same prerequisite was ready (or did not present the pending seal honestly).

The first tool batch also contains a separate, correctly recoverable refusal for
`account.recent_funding` and `account.total_funding`: the pinned Sumble v9 actions cannot request
either field. That event was converted to `_EntityResearchToolRejected` with guidance to choose
another source or retain an honest gap; it did **not** spend and was not the event that suspended
the Account job. The intact-discovery-seal error was the suspending event.

## Supervisor response and current job state

The Account-fleet supervisor intentionally treats the base
`SumbleAccountGapEligibilityError` as a world/authority failure that the model cannot repair by
changing fields. It therefore:

- paused Colorado Springs Health Partners at 14:11:21 with
  `worker_error:SumbleAccountGapEligibilityError`;
- suspended the fleet with diagnosis `account_jobs_suspended`; and
- durably recorded only a SHA-256 of the error message in the control event while the exact
  message remains in the tool-batch event ledger.

The first same-state restart claimed AdventHealth and reproduced the identical intact-seal error
at 14:12:08. The supervisor then paused AdventHealth too. The resulting durable fleet state is
`suspended`: two Account jobs are paused, eight remain admitted/queued, all ten Account runs remain
pending, and no job is terminal.

## Secondary failure: cancellation poisoned the worker's DB connection

Suspending an Account job should not by itself kill the process. A separate cleanup/connection
handling defect turned each governed job suspension into a Missoula fleet exit:

1. The parallel tool batch recorded the handler failure.
2. Concurrent work was cancelled, producing `CancelledError` while SQLAlchemy was terminating an
   `asyncpg` connection.
3. Cleanup logged `connection not in pipeline mode` during rollback.
4. The worker loop immediately tried to acquire the next `fleet_task` lease with the closed
   connection.
5. The unhandled terminal exception was
   `sqlalchemy.exc.InterfaceError: ... asyncpg.exceptions.InterfaceError: connection is closed`
   from the `fleet_task` claim `UPDATE`, so the Missoula fleet process exited.

The same sequence happened on the restart, for a different Account and tool batch. Therefore the
worker exit is reproducible secondary fallout, not merely the operator stopping a process. The
primary authorization failure is the unsealed discovery generation; the process-wide failure is
the cancellation/connection recovery bug.

## Current live instances at close of observation

- Missoula frontend: PID `82408`, Next 16.2.12, listening on `localhost:3115`; authenticated
  project DOM still loaded and queued.
- Missoula API/combined projections process: PID `96889`, listening on `127.0.0.1:8115`; database
  reads and the frontend API remain available.
- Database: the same local `clue` database at `localhost:5432`; no replacement or reset.
- Artifact root: `/private/tmp/clue-combined-browser-20260817-m1`.
- Agent workspace root: `/private/tmp/clue-agent-workspaces-missoula`.
- Missoula fleet: **not running** after the original process and the one same-state restart both
  exited through the closed-connection path. The claimed follow-up turn remains displayed as
  queued because no Missoula worker is alive to recover its expired lease.
- Tunis fleet: PID `16459` remained alive and was not signalled, stopped, queried for work, or
  otherwise changed.

No second automatic restart was attempted after the failure reproduced. Recovery/fix work should
first decide whether to (a) prevent launch until discovery has an immutable seal, (b) allow this R6
explicit-selection path to carry an equivalent immutable selection receipt, and independently
(c) contain a single Account/tool cancellation without poisoning the fleet's next queue claim.
