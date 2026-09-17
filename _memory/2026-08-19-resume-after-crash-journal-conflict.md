# Resume-after-crash `EntityResearchJournalConflict` — root cause and fix (2026-08-19)

Follows `2026-08-19-comprehensive-research-integrity-settlement-repair.md` and
`2026-08-19-exa-reserve-without-dispatch-settlement.md`. Branch
`platform/comprehensive-account-contact-research`, diagnosed at `bcd010ea`. **No commit made.**

## The live defect

Run `b3ad33b7-…`: five paused account jobs were resumed onto a fresh HEAD fleet. All five were
claimed, driven within seconds, and re-paused with
`worker_error:EntityResearchJournalConflict` (fleet task `result_ref.outcome=supervisor_suspended`).

Raise site: `platform/api/clue_api/entity_research_runtime_wiring.py:181`
(`DbEntityResearchAgentJournal.start`) — "agent turn id was replayed with different exact
construction authority". Its invariant (R3 acceptance §4): *one `agent_turn_id` ⇒ one immutable
exact construction* (`agent_execution_id`, `job_id`, `context_sha256`,
`resource_manifest_sha256`, `tool_manifest_sha256`, `system_prompt_sha256`). The INSERT is
`ON CONFLICT DO NOTHING`, then the stored row is compared with the incoming one; a mismatch raises.

## Why it fired (root cause)

`agent_turn_id = uuid5(ns, f"{job_id}:{lease_generation}:{current_state_sha256}")`
(`account_entity_research_composition.py`, mirrored in `contact_entity_research_composition.py`),
and `agent_execution_id = authorization.attempt_id`, which is a constant of the job.

`lease_generation` is **not** monotone across drives: `release_work_lease` DELETEs the `work_lease`
row (`platform/fleet/clue_fleet/lease.py`), so the next acquisition inserts `generation = 1` again.
The five crashed jobs bought nothing durable (`current_state_sha256 == initial_state_sha256`), so
every input to the turn key repeated and the resumed drive re-minted the crashed drive's turn id.

Meanwhile the construction had legitimately moved between the two drives (crash ≈15:43, resume
≈19:30): `c9bd4bed`/`2e54b6e7` raised the provider concurrency default 8→30 and `bcd010ea` resized
the Exa atomic reservation. Both live in the tool manifest, hence in the context digest.

Row-level proof (job `04162ed5-…`, account "The Permanente Medical Group"): the stored turn
`5e5057b3-714d-5171-932c-c95302e8cafa` carries `tool_manifest_sha256=2e608adb47…`
(`research_account_deep`: reservation `20`, concurrency `8`). Re-resolving the *same* job/fence at
HEAD on a throwaway copy of the live DB yields the same turn id, same execution id, same resource
manifest, but `tool_manifest_sha256=659c78b057…` (reservation `40`, concurrency `30`), a different
`context_sha256` and a different `system_prompt_sha256` — exactly the three-way mismatch the guard
refuses. All five jobs carry exactly one turn row from their crashed drive.

## Verdict: (a) genuine resume-path defect

The guard is right and stays; the *identity derivation* was wrong. Resume (`resume_job` +
`reopen_terminal`) is a shipped path and crashed jobs must be re-drivable; under the old key any
resume of a job whose durable state had not advanced would collide, and would hard-fail whenever
anything constructing the agent moved (code, config, run budget remaining, committee plan,
resource catalog).

## Fix (minimal, uncommitted)

- `platform/fleet/clue_fleet/entity_research.py` — `EntityResearchExecutionFence` gains
  `task_attempt: int = Field(ge=1)` (docstring explains the lease-reset trap);
  `EntityResearchJobWorkHandler.handle` threads `context.task_attempt` (the durable
  `fleet_task.attempts`, `+1` on every claim, never reset by `reopen_terminal`).
- `account_entity_research_composition.py` / `contact_entity_research_composition.py` — the turn
  key becomes `job:lease_generation:task_attempt:current_state_sha256`. Facet child turns derive
  from the parent turn id, so they inherit the uniqueness.
- 13 test files updated for the new required fence field.

## Tests

`tests/api/test_comprehensive_account_execution_db.py`:
- `_drive_comprehensive_run` split into `_launch` + `_drive_launched_job(...)` so one durable job
  can be driven more than once (new knobs: `worker_id`, `model_id`,
  `assert_premature_close_refused`).
- `test_a_crashed_account_job_re_drives_after_a_supervisor_suspension_and_resume` — drive 1 dies
  inside a provider tool (`_ReserveOnlyEnrichAction`), the real `suspend_failure` + `resume_job`
  run, the lease is released (re-acquires at generation 1 again — asserted), the re-drive claims
  attempt 2 with one construction input moved (`model_id`), and it finalizes for real
  (`needs_review`, `account_fields_unresolved`) with two distinct turn rows.
  **Red-proofed**: with the account turn key reverted it raises the live
  `EntityResearchJournalConflict`.
- `test_the_journal_still_refuses_one_turn_id_under_two_constructions` — the R3 guard is intact.

Verification (throwaway `clue_journal_diag`, a `pg_dump` copy of live, dropped afterwards):
comprehensive execution 8/8; R2/R3/R6/R9 20/20; R5/launch/committee/fresh-skip/derivation 48/48;
contact R8 4/4; the 5×3 comprehensive harness green. Pre-existing failures reproduced at HEAD
without the change and attributed, not caused: `tests/integration/test_lane_e_e1_acceptance.py`,
`tests/integration/test_lane_e_e2_acceptance.py`,
`tests/fleet/test_b4_composed_run_db.py::test_composed_worker_drives_to_human_checkpoint_then_deep_quarantines`.
Ruff format/check and mypy clean on the changed source.

Against the real live rows (read-only copy): the next claim of job `04162ed5-…` is attempt 3 and
mints turn `6208a752-a439-569c-a02a-8a49b619f137`, which does not exist — so the five jobs
re-drive once the fleet runs this code.

## Residual risk

- A resume that inherits a live LangGraph checkpoint *mid tool node* now rebuilds the replayed
  model wave under a **new** batch id (`uuid5(agent_turn_id, batch_sha)`), so its budget
  reservations/permits are taken again instead of re-entering the old batch. Provider replay
  identity is job-scoped (Exa `observation_window=entity-research-account:{job_id}`), so this is
  not double provider spend, but abandoned reservations from the crashed batch are only released
  through the failed-member path.
- `work_lease` generations remain non-monotone across releases. Nothing else keys identity on
  them today, but any future identity that does will hit the same trap; the honest root fix is a
  monotone per-work generation, deliberately out of scope here (it touches every fleet lane).
- No commit, no live-DB write, no service restart; the running Missoula fleet (53485) and API
  (53580) were left alone and still run the old code, so the five jobs stay paused until it is
  restarted on this fix.
