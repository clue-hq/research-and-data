# Clean Insight Health project browser run (2026-08-19)

## Scope and preserved runtime

The authenticated Insight Health account was tested in a new project without changing the
existing Missoula runtime or the old incident project. Tunis was not touched.

- frontend: `http://localhost:3115` (PID 82408)
- API/projections: `http://127.0.0.1:8115` (PID 60591)
- Missoula fleet: PID 47541
- database: `postgresql+asyncpg://clue:clue@localhost:5432/clue`
- artifact root: `/private/tmp/clue-combined-browser-20260817-m1`
- agent workspace root: `/private/tmp/clue-agent-workspaces-missoula`
- new project: `prj_39a425a0ae0b5aae833a14df0ef93bb6`
- new thread: `thr_2fb681bde9175201a4b6f6587eeaccaf`

## Stage 0 and discovery result

Aura AI Scribe was selected. Product-KB v1 was present, a broad specialty-care-provider ICP was
synthesized and approved, and project run `94a7f76c-aa2d-5065-91b7-01c3644a6ec6` started.

Discovery batch `f939c228-ffc7-5eb8-abb2-1b47820b10a7` completed and sealed at
2026-08-19 15:33:11 IST with 10 admitted Accounts, 0 exclusions, 154 Exa units, 62.860 cents,
65 resolved required fields, four confirmed-missing fields, and one Sumble terminal-absent field.
The immutable seal is `aa4db0f8ca9332c084e9944d9a756bd993ba334450cd250f4d9bc9737944bf9b`.

The ten exact sealed Accounts were attached to the new chat. A frontend handoff defect was found:
calling the editor's fill operation deleted the Account chips, so the first agent turn correctly
refused an unbound selection. Reattaching and appending with normal typing preserved all ten chips.

## Directive and launch authority

Directive `research-directive:b57b48d9-1c68-5f40-ac4d-7ff39ff02aed:v1` contains the fixed 21-field
profile, high effort, all currently approved Exa/Sumble sources, no exclusions, and committee
discovery with candidate cap 200 and relationship depth 2. Research run
`b3ad33b7-94d7-5524-8bee-e5350ecc41d4` launched for the exact ten Accounts.

No browser confirmation card appeared. This was not an approval bypass: the active
account-deep-steering v8 contract intentionally uses the exact-current-message direct launch when
budget controls are disabled. The captured human turn is the approval authority. The directive has
a durable human `confirmed` event, `confirmed_by=usr_450d2a5cefe0427ab256ec97cd9f9245`, and
confirmation operation `be175f1a-7d50-550e-b074-44f2befedb40`; no separate directive `agent_gate`
row is expected on that route.

## Live stop condition

The run did not reach comprehensive profiling or committee discovery:

- five Accounts terminally finalized as `needs_review` after only 5-8 admitted fields resolved and
  12-15 remained unresolved; every one records `committee_not_researched` and zero committee
  members;
- five Accounts are paused/queued while the fleet is `suspended`;
- the run row remains `running`, the UI shows `5 of 10 accounts settled`, `Queued 5`, `Partial 5`;
- there are zero committee-scope rows, zero committee members, zero new contacts, and zero settled
  provider spend;
- the Accounts UI shows the same five `Needs review` and five `Suspended` states. Central Ohio's
  preview reports `No committee resolved yet` and only discovery-derived profile content.

The five suspended Accounts and causes are:

- Envision Physician Services, Millennium Physician Group, and SurgOne:
  `EntityResearchParallelAdmissionError` because the Sumble account provider concurrency limit was
  exhausted. The agent issued parallel Sumble calls, and contention became job suspension instead
  of a wait/retry.
- The Permanente Medical Group: `EntityResearchResultIntegrityError` because an Exa action produced
  no settled ready snapshots. Four Exa operations were reserved but none dispatched.
- VillageMD: `SumbleAccountGapEligibilityError` reporting that an intact discovery seal was
  required.

The VillageMD message does **not** mean the discovery batch became unsealed. The batch, seal row,
manifest rows, artifact rows, and artifact bodies remain present and internally valid. The actual
cross-layer bug is that `discovery_manifest_members()` recomputes the sealed claim set from live
claims by artifact-key association. Each of the five prematurely finalized profiles added a derived
`core.employee_range` claim reusing a discovery artifact. The live recomputation therefore grew
from the sealed 94 claims to 99, and `DbSealedDiscoveryAccountManifestReader` rejected the immutable
claim manifest as different. Post-seal derived Account claims must not mutate seal membership.

The prior fleet DB-connection recovery fix held: Missoula fleet PID 47541 remained alive after all
job suspensions. There was no repeat of the process-wide closed-connection crash. The run is stuck
at a governed fleet suspension, not because the worker process died.

## Sumble concurrency remediation

Follow-up inspection proved the `provider concurrency limit is exhausted` event was entirely local,
not a Sumble HTTP or subscription-tier response. The platform policy was 8 concurrent
`sumble_account` permits. Six permits from old research run
`9bb6ce35-5460-5625-9427-6d77797c4ba7` remained unreleased after their sibling tool failures;
each clean-run failure then tried to atomically admit three new Sumble calls, so `6 + 3 > 8`.
No clean-run `account_gap_operation` was created and Sumble received no request.

At the founder's instruction, the default provider concurrency setting is now 10. The six exact
old-run permits were append-only released with disposition `failed`, each referencing an existing
failed event from its own tool batch. Zero unreleased `sumble_account` permits remain. The Missoula
fleet alone was restarted against the same database, artifact root, and agent workspace; its new
PID is 25720, worker id is `worker:764bfb0c-6b05-4538-bff6-ef69b94408af`, and its process setting
is 10. API PID 60591 and frontend PID 82408 were unchanged; Tunis remained untouched.

Focused verification passed: all 12 tests in `test_entity_research_cutover_r10.py`, Ruff check and
format for the changed settings/test files, strict mypy for `clue_config/settings.py`, and database
postconditions proving zero unreleased Sumble permits. The suspended clean run was deliberately not
resumed because the false seal-claim drift, Exa no-snapshot failure, and premature partial
finalization remain independent blockers.

## Browser evidence

Screenshots are retained under `.context/live-browser-20260819/`:

- `60`-`68`: new project, Aura selection, ICP approval, and discovery start
- `69`-`72`: sealed discovery Accounts, exact selection, and chat handoff
- `73`-`77`: first lost-chip refusal and corrected chip-preserving directive submission
- `78`: comprehensive research launch acknowledgement
- `79`: five-settled suspended chat state
- `80`: Accounts table with `Needs review` / `Suspended` results
- `81`: Central Ohio partial profile and no committee
- `82`: final preserved new-project chat state

No queue, database, discovery, or provider state was manually repaired during this browser pass.

## Exact-five retry with provider concurrency 30

After the founder changed the default provider concurrency to 30, only the five unsettled Accounts
were selected again in the browser and attached to the same clean project chat. The new confirmed
directive is `research-directive:98a97bbe-3894-57b8-b347-f9a3b12605fd:v2`; its immutable content
contains exactly those five Account ids, all 21 fixed fields, high effort, every approved Exa and
Sumble source, no exclusions, and committee discovery. Research run
`79a24bd8-a0e2-5ff3-9483-7396bff31667` launched at 2026-08-19 16:23 IST.

The live batch ledger proves the new setting was active: three Exa permits and nine Sumble permits
all recorded concurrency limit 30. All 12 were released as failed; no permits remain active. The
old concurrency-admission error did not recur.

The retry stopped at the independent false discovery-seal failure:

- Envision Physician Services, Millennium Physician Group, SurgOne, and VillageMD were returned to
  `queued` after `SumbleAccountGapEligibilityError: Sumble account-gap enrichment requires an
  intact discovery seal`. Sibling provider calls were cancelled.
- The Permanente Medical Group did not attempt provider research; its agent read current state,
  assessed coverage, and finalized `needs_review` with 5 completed fields, 15 unresolved fields,
  `committee_not_researched`, and zero committee members.
- There are zero new `external_research_operation` rows, zero new `account_gap_operation` rows,
  zero committee-scope rows, and run spend remains 0. The browser card shows `1 of 5 accounts
  settled`, `Queued 4`, `Partial 1`.
- Cancellation again emitted SQLAlchemy/asyncpg connection-termination errors, but the Missoula
  fleet remained alive (PID 48415). API/projections and frontend remained up. Tunis was untouched.

Retry screenshots `83`-`92` are under `.context/live-browser-20260819/`, ending with the exact
five-account `1 of 5 accounts settled` state. No queued job, seal, claim, or provider operation was
manually mutated during the retry.
