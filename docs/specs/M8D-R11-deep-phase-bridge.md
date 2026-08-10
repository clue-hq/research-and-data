# M8D R11 — DEEP-phase bridge: project-run integration of the entity-research fleet

**Status:** RATIFIED 2026-08-10 (founder) — all §6 decisions ruled, incl. the new (f) committee-bridge scope amendment (R11.5). §5 is the frozen acceptance matrix. Implementation lane: **Lane F**, worktree branch `platform/lane-f-r11-bridge` off the post-Lane-E hub head (`d9bed0d0`), merged into `platform/frontend-integration` when accepted.
**Authority:** founder ruling 2026-08-07 (this spec's §1); `M8D-entity-research-agents-and-shared-fleet-refactor-roadmap.md`; `M8D-R1-active-path-quarantine-acceptance.md`; `M8D-R6-account-research-fleet-acceptance.md`
**Context trail:** `_memory/2026-08-07-dead-code-stale-endpoint-audit.md` (gap discovery + verified mechanics); CLAUDE.md backlog `[M8D×M7×frontend]`, `[LaneE×R11/C7]` (the committee-bridge gap R11.5 closes); `_memory/2026-08-10-verification-scope-ruling-lane-f.md`; `_memory/2026-08-09-lane-e-e3-complete.md` (HB-1)

## 1. Ratified diagnosis (founder, 2026-08-07)

> M8D correctly quarantined the wrong orchestration and successfully built its replacement, but
> the outer project-run state machine and verification selector were never migrated to that
> replacement.

The R1 quarantine retired the M8A/M8B/M8C orchestration model (mechanical account orchestrator,
pre-agent provider preparation, committee walking, automatic account→contact progression) because
it did not match the M8D requirement: one subject-neutral fleet, one bounded `create_agent()`
unit per account/contact, separately authorized account and contact research. R6 deliberately
made the replacement fleet independent of the outer machine: *"no legacy `account_deep_launch`
is created, and the launch works without the outer project state machine being at `DEEP`"*
(`M8D-R6-account-research-fleet-acceptance.md:30`). What was left unfinished is the follow-up
integration. **The fix is forward integration with the M8D fleet. Unquarantining or restoring
any M8C code path is out of the question; the R1 quarantine handler leaves the DEEP slot only
when the R11 adapter replaces it.**

## 1a. Interim verification-scope ruling (founder, 2026-08-10)

For the time being, deployments run with **`CLUE_VERIFICATION_ENABLED=false`** — the
temporary M9 runtime-verification toggle (landed 2026-08-08, extended by the A+B
toggle-compat change 2026-08-09). With the flag off: M9.2 deterministic corroboration and
the M9.3 faithfulness judge are skipped at **every** call site (the VERIFICATION phase, the
reverse-profiling judge, toolbelt entailment, and the M12.1/Lane-E synthesis writers — zero
judge spend), and the one merge chokepoint (`claimstore.active_merge_policy()`) relaxes only
`require_verified_tier4` so unverified tier-4 claims serve. Structural protections stay on
in both modes: pre-spend authorization, born contact identity binding, freshness/retention,
M10's use gate, and the rejected/weak-binding merge exclusions. The disabled VERIFICATION
phase still *runs and advances*, recording `verification_enabled=false` + `accounts_skipped`
honestly.

**Consequence for R11 — binding:** the bridge is built and accepted against **both toggle
states**. The DEEP adapter's COMPLETED→VERIFICATION advance, the R11.2 wake source, and the
R11.3 selector must behave identically in both modes; in disabled mode the phase records the
skip and advances (never a silent full-verification claim), and R11.3's fail-loud
missing-fleet-run error fires in both modes — the toggle bypasses *judging*, never the
selector's honesty. Nothing in R11 may construct a judge or gateway dependency that makes
disabled-mode composition fail (Lane E's optional-judge pattern is the precedent).

## 2. Boundary

In scope:
1. Replace `EntityResearchQuarantinePhaseHandler` in the project-run DEEP slot with an
   M8D-compatible phase adapter (R11.1).
2. Have that adapter join/wait on the M8D account-research fleet (R11.1–R11.2).
3. Make VERIFICATION (both the composed phase handler and `run_verification@1`) select accounts
   from M8D research-run membership/finalization instead of the legacy `account_deep_launch`
   ledger (R11.3).
4. Preserve M8D's separate human approval before contact research (non-goal below restates).
5. **(2026-08-10 scope amendment, founder-ratified — R11.5.)** Bridge the governed committee
   read to M8D fleet output: `ContactEligibilityResolver` (and every reader built over it —
   handoff, the governed committee view, Lane E's `ProductionHandoffCommitteeReader`) is
   data-starved on real M8D runs because its claim-reference source is
   `account_run.references_index`, whose only writers are R1-quarantined. Until bridged, the
   FI-2 committee/contacts sections serve `[]` and Lane E's value narrative refuses
   `committee_unavailable` on every live run (the `[LaneE×R11/C7]` HB-1 gap). R11.5 supplies an
   M8D claim-reference source over `entity_research_account_coverage`
   (`committee_member_ids` + `claim_refs`), leaving all downstream governance unchanged.

Non-goals (violating any of these fails acceptance):
- **No unquarantine.** `QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES` and the
  `ReplayOnlyEntityResearchTool` wrappers are untouched; the superseded implementation trees are
  deleted only by the separately triggered cleanup PR (CLAUDE.md `[audit 2026-08-07]`).
- **No automatic account→contact progression.** Contact research remains separately authorized
  (`approve_contact_research_selection@2` → `launch_contact_research@1`).
- **No HANDOFF cutover change.** HANDOFF stays fail-closed behind
  `c7_production_handoff_enabled`; R11 only makes the phase *reachable*.
- **No new fleet, no provider-specific controller** (R6 boundary holds).

## 3. Verified substrate facts the design stands on (verified 2026-08-07; **re-verified 2026-08-10 at the post-Lane-B/D/E hub head `d9bed0d0`** — every fact below still holds, with the current line anchors and the R11.5 additions noted)

- The phase machine already supports non-human external waits **for DEEP specifically**:
  `PhaseStatus.WAITING_EXTERNAL` is valid only for DISCOVERY and DEEP
  (`durable/project.py:494-506`), lands a `WAITING_EXTERNAL` checkpoint, and *"deliberately
  falls through: a scheduled/webhook wake re-enters the same handler with the persisted
  batch/operation refs"* (`durable/project.py:440-442`). `PAUSED` is the human/budget hold.
- The typed DEEP wait payload `core.external_research.DeepExternalWait` is shaped for the legacy
  per-account provider waits (`pending_accounts[].account_run_id` +
  `preparation.retry_after`) — a fleet-shaped wait needs a contract-delta (R11.4).
- `AccountResearchFleetLauncher.launch` requires an attributable human-confirmed action
  (`actor`, `source_action_ref`, `source_operation_id`), binds to a real `project_run_id`
  (`account_research_fleet_launch.py:160`), commits compile+offer in one transaction, is
  idempotent per action/operation, and produces a content-addressed account selection plus
  compatibility `account_run` rows. The launch authorization **is** the R6 fleet selection.
- Fleet observability exists: `EntityResearchJobStore.get_run`/`list_jobs`
  (`clue_fleet/entity_research.py:320,324`; `list_jobs` currently has zero callers — R11 is its
  first customer, else it goes in the cleanup PR), and the account-fleet controller computes
  `all_terminal` and a `return_kind: "suspended" | "terminal"`
  (`account_research_fleet.py:1001,207`).
- `ExternalResearchWakeDispatcher` (`external_research_wake.py:128`) takes a pluggable
  `sources` sequence feeding a `ProjectRunWaker` — the seam for a fleet-terminal wake source.
- The defect R11.3 closes: `build_high_tier_resolver` (`deep/composition.py:150,201`) returns
  `()` when `get_account_deep_launch` finds no row; the row's only production writer is the
  quarantined `launch_account_deep@1`. Both the composed VERIFICATION handler
  (`run_composition.py:368,428-433` — note the **shared instance** also feeds the HANDOFF
  retention sweep at `:456`) and `run_verification@1` (`toolbelt_wiring.py:2226`) consume it,
  so verification silently reports `accounts_processed=0` on M8D-researched accounts. The
  resolver contract both consumers expect is
  `HighTierResolver = Callable[[PhaseContext], Awaitable[Sequence[AccountSpec]]]`
  (`deep/handler.py:92`; `AccountSpec` at `durable/scheduler.py:43`).
- Facts added at the 2026-08-10 re-verification (grounding R11.1 and R11.5):
  - The phase machine's exact result semantics (`durable/project.py:476-515`): `COMPLETED` →
    ledger finalize + transition; `PAUSED` → `AWAITING_INPUT` checkpoint + run `PAUSED`
    (explicit `resume` required — advance is a no-op while paused, `:428`); `WAITING_EXTERNAL`
    → checkpoint written, run stays ACTIVE, a wake re-enters the same handler. The DEEP wait
    payload is validated at `:499-503` — the R11.4 arm lands there.
  - The join-only fleet-state read R11.1 needs already exists as one row:
    `AccountResearchFleetRow` (`account_research_fleet.py:122-142`) — `project_run_id`,
    `state ∈ {canary, open, waiting_external, suspended, terminal}`
    (`AccountResearchFleetState`, `:73-78`), `diagnosis`, `source_action_ref`,
    `suspended_at`/`terminal_at`; the underlying `entity_research_run` row
    (`clue_fleet/entity_research.py:133-153`) carries `project_run_id`, `selection_id`,
    `spent_cents`, `state`, `created_at`, `terminal_at`.
  - Wake sources are plain callables
    `ExternalResearchWakeSource = Callable[[AsyncConnection, datetime, int], Awaitable[Sequence[ProjectRunId]]]`
    (`external_research_wake.py:20`), compiled by
    `registered_external_research_wake_sources` (`:92`) into
    `ExternalResearchWakeDispatcher.sources` (`:135`).
  - R11.5 substrate: `ContactEligibilityResolver.resolve_account`
    (`contact_eligibility.py:167-262`) is starved only at its claim-reference source —
    `find_account_runs_for_entity` → `account_run.references_index` (`:183-196`); everything
    downstream (product filter, survivor redirects, `latest_use_decisions`,
    `_resolve_contact_claims`) is source-agnostic and reusable. The M8D coverage row
    (`entity_research_account_coverage`, written at `account_entity_research.py:559-594`)
    already carries `committee_member_ids`, `committee_status`, **and** `claim_refs`
    (`claim:<id>` strings) — the M8D-native equivalent of the references index.
  - No R11 piece needs a migration: the wait payload is checkpoint jsonb, the wake source is a
    query, the selector and committee source are reads over existing tables.

## 4. Design

### R11.1 — DEEP adapter (`EntityResearchDeepPhaseHandler`, join-only)

Registered for `ProjectPhase.DEEP` in `run_composition.py`, replacing the quarantine handler.
**Join-only:** the adapter never launches the fleet itself — launch authority stays with the
human-confirmed `launch_account_research@1` (R6: the confirmed selection is the authorization;
an adapter-initiated launch would recreate exactly the automatic progression M8D retired).

Per `run(ctx)` evaluation, keyed on the M8D account-research run(s) bound to
`ctx.project_run_id` — **the current run is the latest human-confirmed fleet run** (ratified
§6c: max `created_at` among account-subject fleet runs bound to the project run; every fleet
run is human-confirmed by construction since the launcher requires `source_action_ref`);
earlier runs remain visible history and never drive the phase:

| Fleet state | PhaseResult | Semantics |
|---|---|---|
| No account-research run exists | `PAUSED` (ratified §6b) | Durable human hold: the operator launches via the confirmed `launch_account_research@1` and resumes the run; parity with the budget graceful-stop hold |
| Run exists, jobs nonterminal (`canary`/`open`/`waiting_external`) | `WAITING_EXTERNAL` + R11.4 payload | Non-human wait; run stays ACTIVE; wake re-enters this handler |
| Fleet suspended (canary block / review fraction / worker failure) | `PAUSED`, payload carries the durable diagnosis/return-snapshot refs | Human decision point — never silent, never `FAILED` (the fleet's suspension is honest, not broken) |
| Fleet terminal | `COMPLETED`; `accounts_processed` = terminal account count; `cost_cents` = the fleet run's settled spend (ratified §6d: reported into the M7.4 phase ledger for attribution — **never** re-gated; budget enforcement happened once, at fleet admission) | Run advances to VERIFICATION |

Idempotent on `(project_run, phase)` per the existing ledger; re-entry after crash re-evaluates
fleet state (pure read — the adapter owns no spend, so double-entry is harmless by construction).

### R11.2 — Fleet-terminal wake source

A new `ExternalResearchWakeSource` registered in `ExternalResearchWakeDispatcher.sources`: lists
project runs holding a DEEP `WAITING_EXTERNAL` checkpoint whose bound account-research run went
terminal (or suspended) since the checkpoint, and re-offers them to the `ProjectRunWaker`.
Scheduled-poll fallback via the payload's `next_poll_at` stays (same discipline as discovery).

### R11.3 — Verification account selector

New `build_entity_research_account_resolver`: reads the R6 content-addressed account selection +
per-account finalization outcomes for the project run's account-research run, yields the
`AccountSpec` set for accepted/terminal accounts. Replaces `build_high_tier_resolver` at **both**
consumers (`run_composition.py` VERIFICATION registration; `run_verification@1`). **Fail loud:**
no M8D account-research run for the project run → typed error, never an empty-success
(`accounts_processed=0`) — closing the audit's silent-zero defect. `build_high_tier_resolver`
and the `account_deep_launch` read move to the cleanup-PR inventory once nothing consumes them.

### R11.4 — Contract-delta: fleet-shaped DEEP wait payload

Frozen-core delta (same process as prior `core` deltas): either (a) a new
`DeepFleetExternalWait` model (`research_run_id`, job-state counts, `next_poll_at`,
`wake_reason`) accepted by the DEEP `WAITING_EXTERNAL` validation arm alongside the legacy
shape, or (b) extend `DeepExternalWait` with an alternative fleet variant. **Option (a)
adopted** — the legacy shape keeps validating historical checkpoints byte-for-byte.

### R11.5 — M8D committee bridge (2026-08-10 scope amendment, founder-ratified)

The committee read is bridged at the **claim-reference source**, never at the governance
logic. `ContactEligibilityResolver` gains an injectable reference-source seam with two
implementations:

- **Legacy source** (default-compatible): today's `find_account_runs_for_entity` →
  `account_run.references_index` read (`contact_eligibility.py:183-196`), byte-identical
  behavior for historical/legacy runs.
- **M8D source**: for the project run's **latest** account-research fleet run (§6c), read the
  account's `entity_research_account_coverage` row and yield its `claim_refs` claim ids,
  scoped to the members in `committee_member_ids`. A missing coverage row (no fleet research
  on this account) yields the same honest empty committee as today.

Everything downstream is unchanged and shared: the product-exact claim filter, contact
survivor redirects, `contact_ids_for_account` liveness, `latest_use_decisions` governance,
`_resolve_contact_claims`, and the sorted deterministic output. Composition: the resolver
build sites (`build_contact_eligibility_resolver` consumers — the HANDOFF registration in
`run_composition.py:440-445`, Lane E's value-narrative wiring, and the governed committee
view reader) select the M8D source when the project run has an M8D fleet run, falling back
to the legacy source otherwise — so seeded/historical fixtures keep passing while live M8D
runs stop starving. Lane E's probe semantics are preserved: an account genuinely without
committee members still refuses `committee_unavailable` loudly; R11.5 only stops the *false*
refusal on runs that did resolve a committee.

Non-goals restated for R11.5: no automatic contact-research launch (reading the committee is
not launching contact research); no edit to Lane E's `value_narrative_tools.py` logic or to
FI-2's `frontend_read/**` (both benefit through the composed reader seam, not through file
edits); the FI-2/C7-owned product-pin fallback-run serving gap stays **out** (ratified §6f).

## 5. Acceptance criteria (**FROZEN 2026-08-10** at implementation kickoff)

1. A composed project run at DEEP with a confirmed `launch_account_research@1` fleet run reaches
   VERIFICATION after the fleet goes terminal, with `accounts_processed` equal to the fleet's
   terminal account count. No `account_deep_launch` row exists anywhere in the flow.
2. A composed run at DEEP with **no** fleet run holds durably (no failure, no silent completion)
   and resumes on the confirmed launch.
3. Fleet suspension surfaces as a PAUSED run carrying the diagnosis refs; operator resume after
   fleet resume re-enters DEEP and proceeds.
4. `run_verification@1` on a project run with no M8D research run fails loud (typed error);
   on an M8D-researched run it processes exactly the R6 selection's terminal accounts.
5. No contact-research launch occurs anywhere in the bridge path (the R6 "contact-research
   request suspends honestly" behavior is preserved).
6. Every quarantined address still refuses a cache-miss invocation (R1 regression gate re-run).
7. Crash/replay: SIGKILL during WAITING_EXTERNAL and during COMPLETED-finalize replays to the
   same terminal state (existing phase-ledger discipline).
8. Every criterion above holds under `CLUE_VERIFICATION_ENABLED` **true and false** (§1a).
   In disabled mode the run advances DEEP → VERIFICATION → (HANDOFF-reachable) with the
   verification checkpoint recording `verification_enabled=false` + `accounts_skipped`, zero
   judge calls anywhere in the flow, and R11.3's typed missing-fleet-run error still firing.
9. **(R11.5)** On an M8D-shaped fixture (fleet run + coverage rows carrying
   `committee_member_ids` + `claim_refs`, zero `account_run.references_index` writes), the
   governed committee read returns the coverage-scoped committee with governance intact
   (product-exact filter, survivor redirects, use-gate decisions all exercised), and Lane E's
   value-narrative committee probe **no longer** refuses `committee_unavailable`. An account
   whose fleet research resolved no committee still yields the honest empty committee/loud
   refusal. Legacy-shaped fixtures (references_index populated, no fleet run) are byte-identical
   before/after.
10. **(R11.5)** The FI-2 follow-up is honored: the committee/contacts read-layer suite shapes
    are re-run against real M8D output (the fixture above), proving the read layer's committee
    sections populate from a live-shaped run.

## 6. Decisions — RATIFIED (founder, 2026-08-10)

- **(a) Branch placement: RATIFIED.** Lane F builds in its own worktree branch
  `platform/lane-f-r11-bridge`, cut from the post-Lane-E hub head (`d9bed0d0`), merged into
  `platform/frontend-integration` when accepted.
- **(b) "No fleet run yet" semantics: RATIFIED — plain `PAUSED`.** The operator resumes the run
  after launching research via the confirmed launch tool. Upgrade to a first-class
  `AWAITING_INPUT` gate card only if the phase-2 frontend asks for it.
- **(c) Multiple fleet runs: RATIFIED — the latest human-confirmed fleet run is current**;
  older runs are preserved as visible history and never drive the phase or the selectors.
- **(d) Budget attribution: RATIFIED — enforce once at fleet admission; copy settled cost into
  the project ledger.** The adapter reports the fleet run's settled spend as the DEEP phase's
  `cost_cents` (M7.4 exactly-once phase charge); the M7.5 pre-gate remains the coarse
  project-cap pre-check it is today; nothing re-gates the fleet's spend.
- **(e) Interim `run_verification@1` guard: RATIFIED — skipped.** R11.3 replaces the broken
  selector now, so no temporary fail-loud patch is needed.
- **(f) Committee bridge: RATIFIED — IN as R11.5.** Without it the workflow advances while
  committees, contacts, and value narratives remain unusable on live runs. The adjacent
  product-pin fallback-run serving gap remains FI-2/C7-owned, **out** of Lane F.

## 7. Worktree kickoff (read this first in the Lane F worktree)

1. **Worktree/branch.** `platform/lane-f-r11-bridge` off hub head `d9bed0d0`. Local commits
   only; never push (repo rule). Merges back into `platform/frontend-integration`.
2. **Required reading, in order:** this spec (§1–§6, esp. §1a's both-toggle-states obligation);
   `docs/specs/FI-lane-demarcation.md` §2.6; `_memory/2026-08-07-dead-code-stale-endpoint-audit.md`
   (gap mechanics — do not re-derive); `_memory/2026-08-10-verification-scope-ruling-lane-f.md`;
   `_memory/2026-08-09-lane-e-e3-complete.md` (the HB-1 committee gap R11.5 closes).
3. **Lane F's files:** the DEEP adapter module (new, `platform/api/clue_api/` — proposed
   `entity_research_deep_phase.py`), the `run_composition.py` DEEP slot + resolver swap lines,
   the R11.4 delta in `libs/clue-core/clue_core/external_research.py` + the
   `durable/project.py:499-503` validation arm, the R11.2 source in
   `external_research_wake.py` + its dispatcher composition site, the R11.3 resolver module
   (new), the `toolbelt_wiring.py:2226` swap, and the R11.5 reference-source seam in
   `contact_eligibility.py` + its composition sites. **Never edit:** `frontend_read/**`,
   `apps/frontend/**`, `api-contracts/*.md`, FI-2 membership/lineage/economics files,
   quarantine addresses/wrappers, Lane E's `narrative/prose.py`/`value_narrative_tools.py`
   logic, or the fleet's launch/finalization write paths.
4. **Slice order:** F1 (R11.4+R11.1) → F2 (R11.2) → F3 (R11.3) → F4 (R11.5) → F5 (frozen-AC
   acceptance, both toggle states, quarantine regression re-run, live smoke).
5. **Checks:** `make check` + targeted suites on fresh throwaway DBs (the full-suite shared-DB
   pollution debt is documented — per-module fresh-DB runs are the trustworthy signal). No
   migration is expected anywhere in this lane; if one becomes necessary, hash ids off the
   current head, single head, `make db-smoke`.
6. **Memory protocol:** dated `_memory/` entries per slice; a close-out entry at lane end.
