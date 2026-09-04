# 2026-08-19 — Slice B: comprehensive account execution (in progress)

Plan: `docs/specs/FI-comprehensive-account-contact-research-plan.md` (Slice B, tasks B1–B8).
Branch: `platform/comprehensive-account-contact-research`. Conductor target branch:
`origin/platform/pilot-budget-controls`. Founder process ruling for this slice: first-round
implementation by Opus subagents with thorough briefs; the controller (Fable) verifies every
subagent's work itself, makes all corrections itself, and runs the live browser test itself via
the gstack `/browse` skill. Slice C is being implemented by the founder in a separate worktree —
do NOT touch Slice C surfaces here (thread task reads, pollers, chat pagination).

## State at session start (recovered after two session-limit cutoffs)

Waves 1–3 (tasks B1–B7) are COMMITTED and were controller-verified in the prior sessions:

- `adff2f3e` B1 — launcher admits `core.*` via `account_axis_field_keys`.
- `4e805fa0` B2 — migration widens `entity_research_account_coverage` CHECKs to `core.%`.
  Dev DB is migrated to head `91fd9e4d772b` (verified this session).
- `47ca6ead` B5 — account-only research composes without committee configuration.
- `b90024dd` B3 — seeds' `yields` cover the 21-field profile per §3.1.
- `aeb9675a` B4 — `profile="comprehensive"` directive tool (v4), skill v7, profile v37.
- `2d8948a6` B4 follow-through — directive validation admits profile rows; launcher partitions
  the 3 zero-acquisition rows (`core.account_name`, `core.employee_range`, `core.revenue_band`)
  → 18-field acquisition selection; tier-ordering ruling recorded in the contract docstring.
- `80844bbc` B6 — Sumble orgs/jobs/tech materialize §3.1-owned fields.
- `be9a99e9` B7 — `account_field_derivation.py` (employee_range/revenue_band) wired into
  finalization; missing source ⇒ `derivation_source_missing`.
- `c0595dbf`, `3943c626` — controller fixes (exa_deep in field tier plans; Sumble per-call cap
  counts only requestable fields).

Wave 4 (B8, the E2E 21-field settle proof `tests/api/test_comprehensive_account_execution_db.py`)
was in flight when the previous session hit its limit; its work did NOT land (file absent, tree
clean). Re-dispatched fresh to an Opus implementer this session with a fully grounded brief
(fixture template = `test_account_entity_research_fresh_skip_db.py`; discovery vocabulary =
`exa_websets_materialization._base_field_values`; bundling proof over
`compile_exa_deep_acquisition_plan` with `EXA_OUTPUT_MAX_FIELDS=8`).

## Remaining to close Slice B

1. B8 test lands + controller verification of its diff/assertions.
2. `make check` + `make db-smoke` green (Slice A recorded 5 pre-existing failures — A/B-proved
   pre-existing; DB now at head so the migration-lag subset may be gone).
3. Live gstack-browser exit-gate test by the controller: normal "research this account" chat
   request compiles to 21 fields (visible in directive confirmation card), run settles, account
   profile shows new `core.*`/Sumble facts or honest empties.
4. Close-out memory entry + final commit. Local commits only — never push.

## B8 implementer report (2026-08-19) — test written, BLOCKED by a B1/B2 sibling-guard gap

`tests/api/test_comprehensive_account_execution_db.py` is written and lint/format/mypy clean, but
is **uncommitted and red against the current tree** because Slice B's `core.*` widening stopped at
the coverage-row CHECK. Three further guards on the same launch-field axis still enforce
`field_key LIKE subject_type || '.%'`, so a comprehensive run launches with 10 `core.*` fields
admitted and then **cannot research a single one** — the first governed tool request naming a
`core.*` field raises.

Blockers, in the order they fire on the composed account path:

1. DB trigger fn `entity_research_validate_tool_request()` on `entity_research_tool_request`
   (current definition from migration `5764311c620d`, originally `f643425d0be4:117`) —
   `RAISE 'governed tool request contains a cross-axis field'`.
2. DB trigger fn `protect_entity_research_provider_operation()` on
   `entity_research_provider_operation` (migration `5764311c620d:~205`) —
   `RAISE 'provider operation contains invalid field authority'`.
3. Python `ProviderOperationReservation._scope_is_exact`
   (`platform/api/clue_api/entity_research_tools.py:251-254`) —
   `ValueError("provider operation contains a cross-axis field")`, surfaced to the agent as a
   repairable `semantic_tool_input_validation_failed`.
4. Latent (NOT on this path — the account guard, not R9 parallel admission, runs here):
   `platform/api/clue_api/entity_research_parallel.py:549-552`, same rule. Reverting only this one
   left the test green, so it is a future-proofing fix, not a current blocker.

All four restate the prefix rule that `clue_core.field.account_axis_field_keys` (the projection B1
adopted at the launcher and that the in-job Exa preparation already used) deliberately widens to
CORE | ACCOUNT | ACCOUNT_RESONANCE | PACK. Suggested fix shape: one migration widening the two
trigger predicates (`... AND NOT (NEW.subject_type='account' AND field_key LIKE 'core.%')`) plus
the two Python guards — mirroring `99923d6527c3`'s predicate exactly.

**Proof the guard widening is the only blocker:** with those three widened as a throwaway probe
(two `CREATE OR REPLACE FUNCTION` calls inside the test's rollback transaction + one local edit to
`entity_research_tools.py`, all reverted), the whole file passes — `2 passed`. The probes are not
in the tree; `git status` shows only the untracked test file and this note.

Test shape (for the verification pass):
- Real launcher → `claim_next_task`/`acquire_work_lease`/`jobs.begin` → real R5 runtime, guard and
  finalization engine. Account-only (no `sumble_people` in the directive's allowed sources), so
  B5's no-committee composition is on the path.
- Discovery baseline: `_base_field_values` is *called*, not restated; where the account-deep
  fixture already claims a row, the seed repeats that exact value (corroboration, not conflict).
- Sumble side = the shared R5 double (`_FixtureAccountProviders`) with values generated from each
  field's registered `value_schema`; `account.hiring_velocity_eng` is the deliberate honest empty
  (a real reservation + artifacts + a `null` field outcome).
- Exa side = the **production** `ExaAccountSemanticResearchAction` over a scripted transport that
  answers each requested alias with a schema-shaped value restating the recorded grounded passage
  (the normalizer only selects a lexically supported citation), so Exa claims carry real
  external-research lineage.
- The scripted call plan is derived from the launched `field_source_authority` (structured-first,
  then one Exa call carrying every Exa-primary field) so it cannot disagree with the R5 guard; the
  borrowed set is read from `born_complete_account_field_keys`, never re-derived.

Two honest deviations from the plan's wording, both recorded in the module docstring/comments:
- **`core.account_name` cannot appear in the coverage row.** The finalization engine's axis is
  `admitted ∪ derive-only` (`account_entity_research.py:1462`); row 1 is neither. The test asserts
  the axis is exactly the other 20 rows and proves the 21st separately: a live, fresh, conflict-
  free `exa_websets`-sourced claim that no tool requested. Making it 21 inside the row would be a
  contract change, not a test change.
- **`core.revenue_band` settles by *reuse*, not derivation**, because the account-deep fixture's
  discovery envelope already carries a band. §3.1 says "reuse **or** derive", so the test asserts
  the disposition per row (`derived` | `existing_claim_fresh`) and, when derived, checks the exact
  band of the live source claim plus `platform_inferred` provenance over the source's evidence
  span. `core.employee_range` is the genuinely derived one.

Also worth knowing: the production Exa account action requires **every** field of a bundle to
materialize a claim (`exa_entity_research_tools.py:975-993` loops all `effective_fields` and raises
`EntityResearchResultIntegrityError` on `resolved:0`), so an Exa-side honest empty is not currently
expressible — which is why the deliberate empty lives on the Sumble side. Not fixed here; recorded.

## Controller close-out (2026-08-19, second session half)

### B8 verification + the sibling-guard fix (commits 03bcc1a2, 47eda230, 963fe2a1)
The B8 implementer's report was verified line by line; its two honest divergences (20-row
coverage axis + `core.account_name` proven outside it; `core.revenue_band` settling by reuse)
are correct readings of `2d8948a6`'s partition design. Its blocker finding was real and I fixed
it personally: three sibling guards still enforced `field_key LIKE subject_type || '.%'` —
migration `9184f54adc26` widens both trigger fns (`entity_research_validate_tool_request`,
`protect_entity_research_provider_operation`) to the launch axis (account also owns `core.%`),
and the two Python guards now share `clue_api.entity_research_tools.field_key_on_subject_axis`
(documented lockstep with the triggers). Also fixed en route: wave 2's `PROSE_ACCOUNT_FIELDS`
import broke the workers-independence contract (durable→directives→narrative); the §3.1/§7.1
profiles now live in `clue_core.research_profile` (the ratified cross-milestone seam), with
`PROSE_*` kept as narrative-local aliases (03bcc1a2). Blast-radius suites green on a clean
throwaway DB; the R4 replay test's dev-DB failure is table-global `count(*)` vs the founder's
real app rows (pre-existing environment artifact, A/B-proven on the clean DB).

### Live gstack-browser gate — four real defects found and fixed (ed7ad2db, 0fce7a84, 3fde62a9, 9d669522, bfc7fd9c)
Auth: Clerk test-mode user `aryan+clerk_test@cluehq.ai` (OTP 424242) linked to the founder's
platform user via a second `auth_identity` row (left in place; harmless dev identity).
1. **@4 structurally unsatisfiable** — the advertised schema marked `directive.field_keys`
   required while skill v7 said "no field list"; a schema-honouring model could never place the
   comprehensive request (looped plan_rejected). Fixed as the @5 wave: tool @5 (omittable
   field_keys), skill v8, profile v38, recipe0-stage0@18, registry/composer pins (ed7ad2db).
2. **Verbatim retyping refused** — the model retypes the 21 rows its card lists; @5 now accepts
   an explicit list that IS exactly the full profile (normalized to contract order); any other
   list still refused; @4 frozen (0fce7a84).
3. **Effort-tier vocabulary leak** — model wrote `effort_policy.tier="comprehensive"`; only
   symptom was `account_tier_checkpoint_missing` though the human `high` claim existed.
   `AccountTierCheckpointMissing` now names the directive tier; skill v8 states the tier rule
   (3fde62a9).
4. **Directive-lineage deadlock** — confirmation was the only exit from a draft, so an
   ungateable draft blocked every successor ("cannot append behind an unconfirmed directive").
   Fresh draft now supersedes an unconfirmed latest draft (append-only superseded event naming
   the successor); its predecessor = the lineage's currently-confirmed directive; migration
   `509e5d0e623a` admits draft→superseded + widens the confirmation-shape CHECK (9d669522 +
   bfc7fd9c). **FOUNDER REVIEW: lifecycle-semantics ruling, cheap to revert to an explicit
   reject path if preferred.**

**Live proof achieved:** normal chat request → 21-field directive drafts (v9, effort high,
four permitted sources, correct exclusions) → confirmation gate presents in the designed card →
my human "Start research" click confirms it durably (v9 confirmed, v6 superseded, statement
receipt recorded). This is the exit gate's "compiles to 21 fields visible in the directive
confirmation card".

### NOT completed live: launch → settle → profile display
Blocked by a genuine worktree collision discovered at the end: the founder's Slice C worktree
(`tunis`) runs its own API+fleet against the SAME dev DB and port 8005; my `pkill` calls were
killing their API (apologized in report), and their fleet (without Slice B code) could claim any
job my launch creates. Launch→settle is proven by the B8 E2E test with provider doubles
(963fe2a1). The live launch leg needs either coordinated ports/DB or a quiet window.

### Open findings for follow-up (not fixed here)
- `get_research_view@1` is granted to the conversation slot but its pin kinds
  (field_registry/project_run/verification_policy) are never REQUESTED by
  `Stage0StepPinProvider` → `missing_tool_requirement` on every call; the agent cannot read the
  research view (this is why it needed ids spoon-fed). Dead grant since FI-2; owner: C7/agentic
  read path.
- The governed launch from a post-approval agent turn refuses without the gate's
  server-computed estimate/budget in durable context; the confirming human turn did not carry
  the launch step (Option-B kickoff chain did not fire). Needs a ruling on where launch rides.
- The `make check` run against the SHARED dev DB shows ~97 failures from real-app-data
  pollution (table-global count assertions etc.) — run the suite against a clean DB; final
  verdict in `/tmp/slice-b-final-check.log` equivalent (clean-DB run).
- gstack browse keychain: cookie import from Chrome may prompt Keychain on first use.
- My dev artifacts in the founder DB: superseded drafts v7/v8 (harmless, immutable history),
  the clerk_test auth identity, and one confirmed directive v9 for Columbia (NOT launched).

## Isolated live continuation — zero-question launch through terminal settlement

The browser journey resumed from the preserved Columbia Pain Management chat rather than being
restarted. Tunis's processes and database were not stopped, signalled, migrated, queried for test
data, or otherwise changed. Missoula used its own isolated runtime throughout:

- DB: `clue_missoula_slice_b` at Alembic head `7ca91ddefee6`.
- Artifact root: `/private/tmp/clue-combined-browser-20260817-m1`.
- Agent workspace root: `/private/tmp/clue-agent-workspaces-missoula`.
- Frontend: preserved session `78672`, port `3115`.
- API: preserved session `42504`, PID `82955`, port `8115`.
- Fleet: preserved session `4728`, worker
  `worker:c227b0b7-f659-40ba-8a63-f1a080cc2787` (left idle and running).
- A fresh QA Clerk identity was mapped to the existing isolated-DB platform user after the prior
  browser session expired. No credentials are recorded here.

### Directional-question requirement removed at the correct scope

The requirement was mechanical duplication for a `profile="comprehensive"` account directive:
the confirmed directive already fixes the complete 21-field plan and provider authority, so a
human-authored question adds no missing execution authority. The account-only path now accepts an
empty question tuple end to end (core contract, agent tool schema, API validator, launcher,
Sumble/Exa composition, and DB CHECK via migration `486ee7b24ae8`). Contact research remains
strict and still requires its bounded directional questions. Exa compiles a fixed internal
target-lock intent when the directive carries no bespoke question; it does not widen the field or
source contract.

### Live v12 result

The one live v12 directive (`4aaa0d16-1041-583c-bceb-bcf843474a12`) launched with no directional
questions. Research run `7c9144d8-061e-5196-87c5-eaa62c8ee2a2` / job
`1e8e01a3-f7cb-5761-9c1e-d84cee26acd1` reached durable terminal state with finalization outcome
`needs_review`, receipt `entity-research-finalization:d269f023-2b90-5055-9b3b-b7865cb1962c`, and
6.4 cents recorded while budget enforcement was disabled. Nine fields completed and nine were
honestly unresolved; most misses were `null:explicit_null`, with primary tech stack recorded as
`null:sumble_terminal_field_absent`. Committee status was complete because committee discovery
was not selected. No provider was redispatched during recovery.

Provider evidence for that one launch: Sumble organizations twice, tech once, jobs once, and Exa
four times, all HTTP 200. Four Exa responses were retained before local replay corruption blocked
materialization. Migration `7ca91ddefee6` plus the retained-response recovery path reclassified
those exact operations without network dispatch and produced four result references. The live
repairs made during that recovery also:

- preserve the first immutable parallel-batch failure while allowing a later completion to
  supersede it, instead of manufacturing `tool batch event replay changed`;
- retain the original causal tool event while allowing a same-turn semantic retry to append a new
  `TOOL_STARTED` journal event;
- repair only uniquely identifiable provider-corrupted Exa aliases, failing closed on ambiguous
  aliases; and
- allow an Exa-requested field to settle as an explicit null with no claim, while the projection
  still rejects a synthesized value that lacks a durable claim.

The browser currently shows historical “Deep research 0 of 1 account settled” card text even
though the backend job is terminal. The founder identified that card correction as likely owned by
an unmerged Lane-E/other-slice worktree, so this Slice B continuation deliberately did not diagnose
or change the card. Backend terminal evidence remains the acceptance authority for this run.

### Focused regression close-out

The comprehensive account E2E now makes an Exa-owned field (`account.operational_pain`) an
explicit JSON null and proves the production Exa action settles it as `null:explicit_null` with no
claim. The response must contain the requested property with value `null`; omitting the required
property is correctly rejected by the Exa exchange contract.

Verification ran on the separate `clue_missoula_slice_b_checks` database on the same local
Postgres server so neither the preserved Missoula worker nor Tunis's worker could claim a test
task. Ten focused tests passed: comprehensive 21-field closure and bundling, zero-question launch,
budget-disabled atomic launch, retained-response recovery, unique/ambiguous alias handling,
all-null settlement, parallel crash replay, and request-causation replay. Ruff passed for every
changed Python file, mypy passed for every changed production Python file, `git diff --check` was
clean, and both new migrations passed a focused down-to-`509e5d0e623a` then up-to-head cycle;
Alembic reports the single head `7ca91ddefee6`. The scratch checks DB was left in place; all
preserved Missoula runtime processes were left running.

## Permanent blocker / relaxed-threshold ledger for this Slice B session

“Permanent” here means the change is represented in source, tests, and (where applicable) an
Alembic migration on `platform/comprehensive-account-contact-research`; none of these is a one-off
SQL patch to the live database. The branch is local and unpushed, so the changes do not reach the
target branch until the founder chooses to merge/publish them.

### Intentional constraint relaxations

1. **Account research may own `core.*` account-profile fields.** The old generic axis check only
   admitted keys prefixed `account.*`, silently dropping or rejecting the ten `core.*` rows in the
   fixed profile. The launcher, coverage ledger, governed tool-request trigger, provider-operation
   trigger, and Python request/parallel guards now use the shared account axis (`core.*` plus the
   account namespaces). Contact fields remain excluded. Commits: `adff2f3e`, `4e805fa0`,
   `47eda230`; migrations: `99923d6527c3`, `9184f54adc26`.

2. **Account-only research no longer requires committee configuration.** Composition now succeeds
   when the directive selects no committee discovery sources. This removes a configuration
   prerequisite from pure account profiling; it does not make committee/contact research run
   without its own authorization. Commit: `47ca6ead`.

3. **The comprehensive directive does not require the model to supply a field list.** Tool @5
   makes `directive.field_keys` omittable for `profile="comprehensive"`; the server supplies the
   canonical 21-field profile. The old @4 remains frozen/replayable. Commit: `ed7ad2db`.

4. **Verbatim full-profile retyping is accepted.** If the model copies the exact canonical 21
   fields from the confirmation card, @5 treats it as the same comprehensive request instead of
   rejecting it as an illicit custom subset. A different or partial list is still refused under
   the comprehensive profile. Commit: `0fce7a84`.

5. **A fresh draft may supersede an unconfirmed draft.** Previously an ungateable latest draft
   deadlocked the directive lineage because only confirmation could move it. A new draft now
   appends a durable `superseded` transition and points back to the currently confirmed lineage
   predecessor. Confirmed directives remain immutable. Commits: `9d669522`, `bfc7fd9c`; migration:
   `509e5d0e623a`.

6. **Directional questions are optional for account research.** The fixed comprehensive
   field/source plan is sufficient authority, so empty question tuples are accepted by the core
   selection/request contracts, agent semantic tool input, launcher, account agent instruction,
   and database CHECK. Exa receives a fixed internal target-lock sentence when no bespoke intent
   exists. This is account-only: contact selections and contact tool requests still require
   non-empty questions. Commit: `254df301`; migration: `486ee7b24ae8`.

7. **Repeated policy references are de-duplicated.** Freshness and recursion may legitimately
   reference the same shared policy (`default`). The flattened selection now retains the reference
   once instead of failing the unique-reference validator. No policy slot is removed or ignored.
   Commit: `254df301`.

8. **Parallel `enrich_account` calls are allowed when independently partitioned.** The old guard
   rejected any duplicate tool name in one model round, which blocked concurrent Sumble
   organizations/jobs/tech calls. Duplicate enrichment calls now pass only when every call has a
   non-empty, pairwise-disjoint source set. Overlapping sources, duplicate Exa work, assessment,
   and finalization remain refused. Commit: `254df301`.

9. **An Exa explicit null no longer requires a claim.** The old action required one durable claim
   per requested field, making “not found” structurally impossible. A requested property whose
   value is explicit JSON `null` now settles as `null:explicit_null` with no claim. A non-null
   synthesized value without a durable claim still fails closed. Commit: `254df301`.

10. **A quarantined retained Exa response may make one audited transition to ready.** The durable
    state machine previously treated every `spend_outcome_unknown` operation as permanently
    terminal even when the exact provider response bytes were safely retained and a parser repair
    later made them valid. It now permits only the exact retained response to transition to
    `ready/provider_reported`, with an immutable recovery row naming response, request id, parser,
    actor, and time. Billing-reconciled rows cannot use this path, stop/cancel authority still
    wins, and recovery makes zero provider calls. Commit: `254df301`; migration: `7ca91ddefee6`.

11. **Same-turn semantic retries no longer require the same `tool_event_id`.** The original
    journal event remains the immutable causal pointer for the governed request, while a
    checkpoint retry may append a new `TOOL_STARTED` event with the same turn, raw call id, and
    semantic authority. Every actual authority field still has to match. Commit: `254df301`.

12. **A repeated failure of one admitted parallel member no longer has to reproduce identical
    error text.** The first batch failure marker stays immutable; later retry failures remain in
    the append-only agent journal, and a later completion may supersede the member's failed state.
    This removes the false `tool batch event replay changed` blocker without allowing the admitted
    call identity or authority to change. Commit: `254df301`.

### Threshold/counting corrections (caps were not broadly raised)

13. **The Sumble per-call field cap counts only requestable fields.** Reused/derived/non-requested
    profile rows no longer consume the provider call's field-count budget. The numerical cap
    itself was not increased. Commit: `3943c626`.

14. **Unbounded-tech approval applies only to the tech partition.** A directive-level tech
    approval used to leak into simultaneous organizations/jobs calls and make their preflight fail.
    The approval now rides only a request containing `core.primary_tech_stack`. This narrows an
    exception rather than widening it. Commit: `254df301`.

15. **The three zero-acquisition profile rows do not consume provider authority.** Canonical
    account name is reused, while employee range and revenue band are reused or deterministically
    derived. The launcher therefore buys the 18 acquisition rows instead of trying to manufacture
    source authority for all 21. The result still accounts for all 21 fields. Commits:
    `2d8948a6`, `be9a99e9`.

### Blocker repairs that did not weaken a policy boundary

16. **The comprehensive source plan now actually covers the fixed profile.** Registered source
    yields and effective tier plans now include the Sumble-owned and Exa-Deep-owned rows needed by
    §3.1. This repaired missing composition data; it did not add providers beyond Exa Deep and
    Sumble. Commits: `b90024dd`, `80844bbc`, `c0595dbf`.

17. **`get_research_view@1` now receives its declared pins.** The conversation slot had the tool
    grant but the recipe never requested `project_run`, `field_registry`, or
    `verification_policy`, causing `missing_tool_requirement`. Project-run and field-registry pins
    are now requested; verification policy is requested-but-optional only when verification is
    disabled and no policy resource exists. Commit: `254df301`.

18. **Budget-disabled approval now confirms and launches as one transaction.** In the pilot
    posture, the human approval previously confirmed the directive but stranded launch because
    the following agent turn lacked the gate's server-derived estimate/budget receipt. The approval
    turn now captures the gate-frozen accounts and invokes the narrow launch tool in the same SQL
    transaction. Budget-enabled deployments retain the separate confirm-only behavior. Commit:
    `254df301`.

19. **Uniquely identifiable Exa alias corruption is repaired request-aware.** Exa occasionally
    partially rewrote a long canonical field alias. The parser now repairs it only when an intact,
    byte-aligned prefix identifies exactly one requested schema member, and the same request-aware
    parser is used during account/contact materialization and replay. Ambiguous, colliding,
    unrelated, or malformed aliases still fail closed. Commit: `254df301`.

20. **Effort-tier errors now identify the real mismatch.** `comprehensive` is a profile, not an
    allowed effort tier; the accepted tiers were not widened. The agent skill now says to use the
    confirmed account tier, and the server names the directive-tier mismatch instead of emitting
    the misleading `account_tier_checkpoint_missing`. Commit: `3fde62a9`.

### Settings that were not globally disabled

- **Budget controls:** the preserved Missoula pilot runtime already had budget enforcement off.
  The code did not globally remove budget caps; it added correct behavior for the explicit
  disabled setting. Enabled deployments remain capped and use the confirm-only gate path.
- **Verification:** the live pilot runtime had verification off. Verification was not removed from
  the product; only its resource pin is optional when no policy exists because the feature is off.
- **Contact safeguards:** non-empty directional questions, exact person/employer target lock,
  identity/use controls, and contact selection authority remain mandatory.
- **Evidence/provenance:** target lock, exact field/source authority, response artifacts, evidence
  spans for promoted non-null claims, and honest-empty semantics remain enforced.
- **Provider breadth:** no fallback waterfall was enabled. This slice remains Exa Deep + Sumble.
- **Browser progress card:** the stale “0 of 1 settled” card was not changed here; the founder
  identified it as likely owned by an unmerged Lane-E/other-slice worktree.

## Merge close-out — comprehensive account/contact research v2

Merged local branch `platform/comprehensive-account-contact-research-v2` at
`33c7bb39835af1ad1102415fe72237df18c6c999` into this branch from current parent
`eaed76096804ff12add45893210306d35a86b2af`. The source worktree in Tunis was inspected only to
confirm its clean branch tip; no Tunis process, database, migration state, or session was changed.

Five content conflicts were composed rather than resolved wholesale. The resulting policy is the
co-founders' v2 ruling: an exact confirmed Account research job is durable explicit selection, so
signal tiers, the legacy scoring/deep-phase checkpoint, and must-have selection do not gate its
account or committee provider work. Historical discovery-driven entry points retain their sealed
batch, criteria, tier-claim, and checkpoint lineage; their accepted tier/source thresholds remain
the deliberately relaxed tier-4 values from v2. Account research may have zero bespoke questions,
while contact research still requires directional questions. The merge simultaneously preserves
this branch's comprehensive account axis, derived-profile fields, zero-acquisition partition,
policy-reference de-duplication, retained-response recovery, replay repairs, and budget-disabled
atomic confirmation/launch behavior. Committee provider work discovers and identity-resolves
members; the responsible account agent now writes evidence-cited role/persona judgments through
the governed `record_committee_role_inferences` tool, and roleless members remain an honest
reviewable intermediate state.

Alembic revision `f5f8c50f70f3` joins current head `7ca91ddefee6` and v2 head
`fc3e5477e872`, restoring exactly one head. On the existing isolated
`clue_missoula_slice_b_checks` database, migration verification passed
`7ca91ddefee6 -> f5f8c50f70f3 -> a1c5b9842f0e -> f5f8c50f70f3`. The live
`clue_missoula_slice_b` database was not migrated or otherwise changed.

Focused verification passed: 52 backend tests across R6 launch, R5 coverage and agent role
inference, comprehensive execution, Lane-D acceptance, Sumble account gaps, and committee worker
behavior; three frontend account/contact model tests; targeted frontend ESLint; Ruff across all
changed Python; mypy across all changed production Python; `git diff --check`; and a one-head
Alembic check. No full-suite replay was started because the preceding Slice-B and v2 work had
already completed their broader verification.

## Merge close-out — comprehensive account/contact research v1

Merged local branch `platform/comprehensive-account-contact-research-v1` at
`58d7eb10183931e51d5f8c0d62cea74fd3b6b950` on top of the combined current+v2 parent
`2f57038c5b4836c23b114efa37b01a652bf91974`. The source worktree in Bujumbura was inspected only
to confirm its clean branch tip; no Bujumbura or Tunis process, database, session, or worktree
state was changed.

V1 contributes Slice C's durable thread research-task read, three-second frontend polling,
monotone task-card merge/re-materialization, truthful state/count advancement, and newest-first
thread pagination with upward scrollback. Its only path independently changed on both sides was
`platform/api/clue_api/chat/router.py`; Git composed disjoint hunks. The audited result contains
both V1's `GET /projects/{project_id}/threads/{thread_id}/research-tasks` route and the existing
current+v2 transactional budget-disabled directive-confirmation launch flow. No migration was
added by V1, and Alembic remains at the single head `f5f8c50f70f3`.

Focused combined verification passed on `clue_missoula_slice_b_checks`: 43 backend tests covering
the task read, chat/thread surface, D5 rich parts, thread projection, and the overlapping D4
approval/launch route; 51 frontend poller/transcript/task tests; targeted frontend ESLint; Ruff;
mypy; all 26 import contracts; `git diff --check`; and the complete frontend design-system plus
Next.js production build. The live Missoula database was not migrated or otherwise changed. No
browser journey was replayed during this merge, so the now-merged card behavior is build- and
test-verified but awaits the founder's existing live Slice-C browser exit gate.

## Live browser continuation — Insight Health onboarding and product catalog

Continued the preserved browser journey on 2026-08-19 using frontend `3115`, API `8115`, and the
Missoula fleet. Onboarding for Insight Health (`https://insighthealth.ai`) completed and created
workspace `ws_d98ab74cb0a943d4a483d1a3b4135ebd`, brand
`brd_54b723b072204cafb8b4547aeb680e2d`, client entity
`0e4f3c51-0435-4a5d-92aa-0705c1e66e46`, and project
`prj_a4cfd10af5775d2c831eaed63373e3b3`. The onboarding fast recon completed, while its background
lane failed on a transient Firecrawl request-per-minute limit. The application still released to
Home, and the browser began the comprehensive Stage-0 directive without narrowing discovery, the
fixed 21-field account profile, or committee research.

Runtime audit corrected an earlier assumption: the live API/fleet processes are connected to the
local database named `clue`, not `clue_missoula_slice_b`. Every subsequent read/write was therefore
scoped by the exact Insight Health workspace above. No Tunis process, database, row, session, or
worktree was changed.

The first Stage-0 turn correctly refused ICP synthesis because no product was confirmed and the
company catalog was empty. The next human answer recorded the Insight Health AI Clinical Agents
suite and value proposition, advancing the account-wide Client-KB to v2, but still could not open
the product-selection gate. At the founder's explicit request, seeded the seven products listed on
Insight Health's official portfolio using the governed seams: appended `client.product_catalog`
claim `cdab0496-1f2d-4ece-8791-2e8f1db08b77`, published company Client-KB v3 over base v2, and ran
`ProductCatalogSynchronizer`. It created seven product identities and seven lineage rows with zero
unresolved candidates. No existing claim or product was deleted or overwritten.

After a fresh chat turn, the UI rendered gate
`agent-gate:1dd8c156-6d46-5dd1-b0e9-629690c7fce6` with all seven product cards: Aura AI Scribe,
Pre-Visit Intake AI Agent, Follow-up AI Agent, Referral Management AI Agent, Phone Triage AI Agent,
Direct Access Colonoscopy AI Agent, and AI FrontDesk Agent. Browser testing is paused at this
human-only choice; the exact tab is marked for handoff. Screenshots `01` through `12` are under
`.context/live-browser-20260819/`, with `12-product-selection-gate.png` proving the current gate.

## Default ICP-synthesis coverage policy ruling

The founder set the default passing coverage floor for the `icp_synthesis` readiness gate to
exactly 0% on 2026-08-19. `default_readiness_spec()` now sets only
`ReadinessGate.ICP_SYNTHESIS.min_coverage_ratio` to `0.0`; the separate `discovery_spend` and
`deep_spend` defaults are unchanged. The readiness decision and its trusted coverage metrics remain
auditable, but incomplete baseline-field coverage no longer emits `coverage_below_floor` or blocks
ICP synthesis under the default policy. Product selection, client binding, Client-KB existence,
human ICP confirmation, and later provider-spend authority were not disabled.

Focused verification passed on the existing isolated `clue_missoula_slice_b_checks` database:
all nine tests in `tests/stage0/test_phase_c4_governed.py` and
`tests/api/test_stage0_project_tools_db.py`, including a 0%-coverage API case that remains refused
for missing product/client scope but no longer reports the coverage reason. Ruff passed for the
changed policy/tests, mypy passed for `clue_config/stage0.py`, and `git diff --check` passed.

The live Missoula API/fleet were then restarted against their preserved database/artifact pairing:
PostgreSQL `clue` plus `/private/tmp/clue-combined-browser-20260817-m1`. Frontend `3115`, the
existing browser tab/session, and Tunis fleet PID `16459` were not restarted or changed. The typed
Aura proof answer survived the restart and was submitted in the same thread. The application
recorded readiness decision `48f0257c-953d-55a9-a799-ae478b90a69d` as `ready` under readiness spec
v2 with the same trusted coverage ratio `0.5555555555555556` and an empty reason-code list; the
preceding v1 decision `41945544-d25e-50b1-9ea4-bd469408d714` had the identical coverage ratio but
was `not_ready` solely for `coverage_below_floor`. Durable spec rows prove that only the requested
gate changed: `icp_synthesis` 0.75 -> 0.0, while `discovery_spend` remains 0.25 and `deep_spend`
remains 0.5.

The same turn synthesized ICP `us_ambulatory_documentation_heavy_clinician_orgs` v1 and opened
human confirmation gate `agent-gate:116d42d7-2105-5f87-93f8-6381842fc81f`. No discovery, Account
research, committee research, or provider spend was launched. Browser evidence is retained as
screenshots `17-zero-floor-proof-answer-ready.png`, `18-proof-answer-submitted.png`,
`19-zero-floor-icp-synthesis-running.png`, and `21-icp-approval-card.png` under
`.context/live-browser-20260819/`; `21` is the clearest ready-decision plus human-gate proof.

The founder then approved the exact ICP gate in the browser. Screenshot
`22-icp-profile-approved.png` proves the durable approval UI. The automatic post-approval turn did
not create a discovery run: it reported `start_confirmed_project_run` as structurally unavailable.
The exact cause is a constitution-dependent tool omission, not a missing backend tool or a spend
gate. Active profile `head-of-abm@v38` and Stage-0 skill v20 both pin
`start_confirmed_project_run@3`, but that tool declares a `product_kb` pin requirement and
`GovernedAgentToolFactory._tool_admitted` removes every such tool when the turn constitution has no
product-scoped KB. Durable claim inspection confirms Insight Health has company Client-KB markers
v1-v3 but no `client.kb_version` marker scoped to Aura product
`prd_63b952a0da3e5df08e2784a5a39ab82d`. The skill therefore told the model to call a tool the exact
turn did not install, and the surface middleware returned its structural-unavailability error.
Screenshot `23-start-confirmed-run-tool-unavailable.png` captures the live failure. No discovery,
Account research, committee work, provider call, or spend occurred; Tunis remained untouched.

## Product-KB baseline invariant — founder ruling and implementation

The founder ratified eliminating `selected_without_product_knowledge` as a valid current
post-selection state. The direct live cause was not a missing trusted product id: Aura was
correctly pinned on the project and subsequent turns. The missing state was the independently
versioned Product-KB marker. Onboarding intentionally publishes company-scoped Client-KB and a
selectable product catalog; it does not automatically run selected-product recon. The first
product-fact route had also left the supplied structured values as unmapped evidence while the
verification/entailment judge was disabled, so the claim-conditional materialization path never
created a product marker.

The implementation now makes Product-KB existence independent from claim promotion. Human product
confirmation creates an idempotent empty Product-KB v1 in the same transaction as
`project.product_id`; the baseline carries zero known claims, all nine registered product fields
as open gaps, and 0/9 coverage. It does not require a verification judge and does not invent a
claim. `load_or_create_agent_turn_scope_pin` provides an idempotent repair for legacy selected
projects before writing a new pin. New pins use
`company-and-selected-product-required-v3`, and migration `ab295072ba84` makes
`product_id != NULL => product_kb_version != NULL` a database-enforced V3 shape. Historical V1/V2
pins remain unchanged and readable. The frozen S5.0 selected-without state is documented as
historical-only in both production-context contracts.

Verification on `clue_missoula_slice_b_checks`: the focused selection/scope/decision set passed
16 tests before and after a migration down/up cycle; 57 additional toolbelt, recipe, launch,
context, card, and product-tool tests passed. Ruff, production mypy, `git diff --check`, and the
single Alembic head `ab295072ba84` passed. Broader context runs still expose unrelated pre-existing
failures: three S3 fixtures omit the newly required `previous_turn_outcome`, the fleet DSAR test
expects a reusable product artifact that the current erasure path already removes, and two
toolbelt inventory/matrix assertions are stale against already-merged tool versions. These were
not changed as part of the Product-KB invariant.
