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
