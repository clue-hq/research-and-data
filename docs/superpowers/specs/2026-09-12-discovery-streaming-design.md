# Discovery streaming — verified rows land on the Target accounts tab as Exa finds them

**Status:** design approved in chat by the founder, 2026-09-12. Branch `research-streaming`.
**Rulings (founder, 2026-09-12):** a row appears only when Exa found the company **and** Exa Answer
verified it against every ICP gate; polling on both ends, no Exa webhooks; the tab shows the
climbing account count plus a spinner in its label while a run is live, nothing else new; gate
questions run in parallel per candidate and candidates verify in a bounded pool with a settings cap.

## 1. Today, and what changes

Today `discovery_driver.py` polls the webset every 15 s until `idle`, then lists all items, then
verifies them one at a time, one Exa Answer call per gate. Rows therefore appear only after the
search has finished, in list order, at the pace of serial gate calls; the Target accounts tab
fetches once and never refetches. Both halves change.

## 2. Driver: verify as items arrive, in a bounded pool

* **Per poll tick** (`arv2_discovery_poll_interval_s`, unchanged): after `get(webset)` the driver
  also `items(webset)`s and hands every item it has not yet **claimed** to the verification pool.
  The billed-items bookkeeping (`priced_item_ids`) is unchanged: a row is priced once per run.
* **Claiming** happens when a task is taken, not when it finishes: the registrable domain goes
  into `state.seen` before any await, so two tasks can never verify the same company.
* **Pool:** `asyncio` tasks under a semaphore of `arv2_discovery_verify_concurrency`
  (new setting, default 4, `CLUE_ARV2_DISCOVERY_VERIFY_CONCURRENCY=4` in `.env.example`).
* **Gates in parallel:** `_verify_gates` fires every gate's Answer call together
  (`asyncio.gather`) and assembles the verdicts once all are back; `apply_guards` is unchanged.
* **Writes:** each candidate keeps its one transaction (account entity, claims, candidate row with
  verdicts, project membership). `_connection()` becomes one connection per in-flight candidate
  from the engine, dropping the "strictly sequential" note; the post-hop money drain already opens
  its own connection.
* **Idle:** on `idle` one last `items()` catches stragglers, the pool is drained, then the relaxed
  pass runs under the same rule.
* **Counters:** `found_strict`/`found_relaxed`/`analyzed` on `arv2_discovery_run` are written on
  every tick, not only at landing; `shown` and `cost_usd` stay in run state and land as today.
* **Containment:** unchanged per candidate (`_verify_contained`). `ProviderHalted` and the wall
  clock cancel the pool and suspend the run. A resumed attempt re-lists the webset and re-verifies
  only candidates still `pending` (existing rule).

## 3. One new read: the project's current discovery run

`GET /frontend/v1/projects/{project_id}/discovery/current` (new module
`frontend_read/discovery_status.py`, registered in `frontend_read/app.py`) returns the latest
`arv2_discovery_run` for the project in this workspace:
everything under a `data` envelope —
`{ "data": { run_id, status, asked, found, verified, shown, started_at, finished_at } }`, or
`{ "data": null }` when the project has never launched a run.
`verified` counts candidate rows with a disposition; `shown` counts pass/partial/unclear. It reads
ARV2's own tables only. Mirrored by a BFF route `GET /api/projects/[projectId]/discovery`.

## 4. Frontend: open, poll, spin

* **Open on launch:** in `chat-surface.tsx`, when the stream delivers a `tool` part with
  `toolName === "launch_arv2_discovery"` and state `output-available`, call
  `shell.openTargetAccounts()` — the same path the gallery card and the auto-open of a new
  artifact use. Pure rule in `chat-shell/model/discovery-launch-signal.ts`, tested.
* **Poll while live:** `ProjectTargetAccounts` reads the discovery status on mount; while
  `status` is `not_started`/`in_progress`/`suspended`-pending it polls every 5 s and refetches
  `/api/projects/[projectId]/accounts` on each tick (rows and count climb; the table keeps
  columns, selection and page as the existing re-read does). Polling stops on the first terminal
  status. A page reload mid-run restores this from the read alone.
* **Spinner:** `ArtifactTabs` takes `targetAccountsBusy?: boolean`; when true the "Target
  accounts" label carries `<ProjectIcon name="loader" className={rotatingLoader}>`, the glyph the
  chat's agent-activity row already uses. No other new UI.
* **Global Accounts page:** untouched.

## 5. Failures

A `failed`/`suspended` run stops the spinner and the polling; verified rows stay. A status read
that fails is retried on the next tick and never blanks the table. A discovery launch the tool
refused produces no `output-available` part, so nothing opens.

## 6. Tests

* Driver: items arriving across ticks land as they verify; a straggler after idle is verified;
  a claimed domain is never verified twice; the pool never exceeds the cap; gate calls for one
  candidate are issued together; a resume re-verifies only pending candidates; counters advance
  per tick. All against fakes; the DB suite covers the per-candidate transaction under concurrency.
* Read: DB test for the status shape and the `null` case.
* Frontend: pure-rule tests for the launch signal and "poll while live"; source-contract tests
  for the spinner prop and the BFF route.

## 7. Out of scope

Exa webhooks; any change to what discovery writes; any new text on the tab.
