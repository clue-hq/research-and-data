# Same-window account-gap re-buy: raw DBAPIError → governed refusal (2026-08-20)

## The live failure

Job `3cc0a4f2-3997-5bf6-b9d7-52bfae1d7b4c` (05:40:51 IST). The account agent called
`enrich_account(field_keys=["core.hq_location"], source_keys=["sumble_organizations"])`; the worker
died with a raw `sqlalchemy DBAPIError` wrapping `asyncpg RaiseError`, SQLSTATE **P0001**, message
`account-gap field already acquired in this observation window`. It escaped as `execution_failed`
and paused the whole job (`worker_error:DBAPIError`).

## Forensics (verified against the live DB, read-only)

- Operation `7e29c0bf-…` (job `eea48931`, 02:14) had already bought `core.employee_count` +
  `core.hq_location` in ONE operation, account `17aab088`, project run `94a7f76c`.
- `hq_location` settled `conflict` / `authoritative_sources_disagree` (no `current_claim_id`), so
  the §6.3(a) freshness ladder legitimately wanted to re-buy it.
- The observation window is `project-run:{run}:sumble-gaps:{policy}` — **per run, not per job**
  (cross-job reuse is the anti-double-spend rule). Both jobs shared it.
- `find_account_gap_operation_for_fields` rejoins only on **exact field-set equality**, so the
  subset request `[core.hq_location]` did not find the owning operation, the starter compiled a new
  one, and the `account_gap_field_no_overlap` trigger (migration `bd0b7e62a2b4`) raised on the
  first `account_gap_field_result` insert. The reservation transaction rolled back — the failure
  was already zero-spend/zero-state; the only defect was the raw escape.

## The fix (three layers, no trigger weakened)

1. `durable/account_gap_enrichment.py`
   - `account_gap_window_acquired_fields(...)` — the pre-check read (field-results joined to
     operations on `observation_window`, scoped `(workspace, account)`).
   - `AccountGapFieldWindowConflict(AccountGapRepositoryError)` carrying `.fields`.
   - **Narrow** catch around the field-result INSERT only: converts iff SQLSTATE `P0001` *and* the
     trigger's verbatim message. Everything else re-raises (a blanket DBAPIError→refusal would let
     unknown-spend/integrity failures be talked past — the load-bearing boundary).
2. `sumble_account_gaps.py`
   - `SumbleAccountGapFieldAlreadyAcquired(SumbleAccountGapNotEligible)` — model-repairable species.
   - Pre-check in `compile_sumble_account_gap_preflight`, placed **after** every world-fact check
     (run/job authority, discovery seal, survivor, account, species) so those keep suspending.
   - `SumbleAccountGapCoordinator.start` converts a raced `AccountGapFieldWindowConflict`.
3. `sumble_entity_research_tools.py` — new `except` ahead of the §6.3(b) one, raising
   `EntityResearchGovernedRejection("account_gap_field_already_acquired", …)`, so the existing
   rendered-rejection lineage turns it into a recoverable error tool message (replay included).

Refusal is **whole-request** even when only some fields overlap; the message names exactly the
bought fields so the agent re-asks for the remainder. Operation-reuse-by-overlap was explicitly
NOT attempted (it would change replay identity semantics).

## Tests

`tests/api/test_sumble_account_gap_window_reacquisition.py` (3 tests, real DB):
same-window subset + mixed-set refusal with zero new operations/calls; the durable narrow-catch
plus its boundary (an `account_gap_result_claim_lineage` raise on the *same statement* still
propagates as `DBAPIError`); the governed rendered rejection repeated on a replayed call.

RED proof captured before the fix: `DBAPIError`, orig SQLSTATE `P0001`, exact trigger message.

## Verification

`ruff format`/`check` clean on edited files; `uv run mypy` 732 files clean; `make contracts` 26/0.
`tests/api` failure set is **byte-identical** before and after the change (23 pre-existing
failures on this branch, all unrelated: production-context S3, frontend bulk actions, lane D4/BD,
projections app, toolbelt out-of-order matrix, fi2_62 bundle shrink).

## Amendment (same day, after live evidence 06:18–06:20)

The first refusal fired correctly but under-steered. Live journal for job `3cc0a4f2`:
06:18:13 refusal → 06:18:34 the agent obediently called `read_account_research_state` → then
06:19:04 / 06:19:07 / 06:19:30 / 06:20:54 it tried four more subsets, and 06:19:39
`assess_account_coverage` refused: `coverage cannot close ... core.hq_location@sumble_organizations`.
The pair was OUTSTANDING and, as far as the agent could tell, unattemptable.

**The exit exists and was never blocked.** `SumbleAccountGapStarter.start` calls
`find_account_gap_operation_for_fields` BEFORE `compile_sumble_account_gap_preflight`, so an
exact-owning-set request rejoins and replays zero-spend and never reaches the pre-check. Proven by
probe and now pinned by `test_the_exact_owning_field_set_still_replays_and_settles_under_the_new_job`
(action level: the later job gets its own result draft, no dispatch, no new operation row). So the
proposed "exempt the exact set inside compile" would have been dead code — NOT added.

**What was actually missing was the signpost.** `account_gap_window_acquired_fields` →
`account_gap_window_field_owners`, now returning each owning operation's WHOLE field set, and the
refusal names it: *"This window's operations acquired exactly [core.employee_count,
core.hq_location]; re-ask one of those exact field sets to replay its durable outcome at zero
spend … Re-asking a subset or a different overlapping set can never succeed."* Asserted through
`render()` so it survives the 1000-char detail clamp.

## Not mine — the actual 06:20:59 job killer

`{account.hiring_velocity_eng}` (its own exact owning set) DID rejoin and replay, then died on
`EntityResearchResultIntegrityError: provider settlement replay differs from its immutable first
fold` → `execution_failed`. `_fold_settled_spend` compared the fold's `research_run_id`/`job_id`,
which necessarily differ on a cross-job replay of a content-keyed operation. That is being fixed
concurrently by the **fold-visibility** session in `entity_research_tools.py` (its in-tree comment
names this exact job and timestamp). I did not touch that file. My steering fix only pays off once
that lands — otherwise it points the agent at a path that still suspends.

## Open / follow-ups

- **Refusal-loop risk.** For a field that settled `confirmed_missing`, `read_account_research_state`
  shows nothing, so an agent can re-ask, get the same refusal, and loop. The message says
  "finalize with an honest gap" and the identical-read loop breaker (4f3c2b0b) + question narrowing
  (257c1f8f) should hold it, but this is worth watching on the next live run.
- Whether a partially-overlapping request should proceed for the unbought fields instead of being
  refused whole is a product decision left open (rationale for refusing whole is in-code).
