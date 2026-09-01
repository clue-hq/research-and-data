# 2026-08-19 — permanent committee-discovery blocker inventory

**Branch:** `platform/comprehensive-account-contact-research-v2`

**Implementation commits:** `2fef333e` and `e770bd52`

**Related read-contract commit:** `58636bed` (not itself a blocker removal)

## Purpose and terminology

This note inventories every eligibility or reachability blocker that was permanently removed,
disabled for the exact explicitly launched Account-job path, or reduced to its least restrictive
supported threshold during this session. “Permanent” means the behavior is in committed source,
contracts, tests, or the reversible Alembic migration. It does not mean that all governance was
removed: exact user selection, directive authority, sealed discovery lineage, privacy/use policy,
provider pre-spend decisions, durable receipts, and spend accounting remain fail-closed.

There are two intentionally different paths:

1. **Exact R6 Account job:** a user explicitly selected the Account and confirmed its immutable
   research directive. That exact running job is the durable selection authority, so legacy
   scoring/tier prerequisites no longer re-veto it.
2. **Historical claim-backed path:** older batch/deep callers still have to prove their discovery,
   ICP, checkpoint, and selected-claim lineage. Their *thresholds* were lowered so a low/tier-4
   Account and a source-tier-4 claim are eligible.

No global “allow everything” switch was added.

## Summary of before/after thresholds

| Blocker or threshold | Before | Permanent state now |
| --- | --- | --- |
| Account signal label at research launch | One exact human-approved tier claim had to exist and match the directive effort tier | Signal label may be high, low, tier 4, or absent; explicit selection plus directive authority controls launch |
| Signal-tier / effort-tier equality | Required | Removed; scoring priority and execution effort are independent vocabularies |
| Committee-eligible Account labels | `high`/`top` in committee and `high` in provider preflights | `top`, `high`, `standard`, `low`, `tier1`, `tier2`, `tier3`, `tier4`, and `4` |
| Tier-claim source trust | Human extraction at source tier exactly 1 | Any coherent live tier claim with `source_tier <= 4`, including source tier 4 |
| Tier claim on an exact Account job | Required by request models and database columns | Optional only when an exact matching `entity_research_job_id` exists |
| Pass-A scoring checkpoint before committee discovery | Committed checkpoint required | Exact Account job is sufficient evidence; historical callers still require the checkpoint |
| ICP must-have selection proof before committee discovery | A valid non-empty policy plus evidenced pass required | Exact Account job is sufficient evidence; historical callers retain the proof |
| Human tier-checkpoint approval before committee discovery | Required | Not required for the exact Account job; historical callers retain it |
| Outer project-run state for provider spend | Must be active/deep | Exact live Account job may spend while outer run is paused specifically at `tier_checkpoint` |
| Current-job provider result for committee scope | Prompt effectively required a new `research-result:` ref | A fresh durable `claim:` ref from an earlier governed run is valid |
| Sumble Organizations prerequisite | Only a succeeded Account-gap Organizations snapshot qualified | Exact artifact-backed Organizations result from the same sealed discovery batch also qualifies |
| Multiple Account-run history | Older same-account runs could make the plan reader ambiguous | Reader filters by the job’s exact immutable directive reference |

## Detailed blocker inventory

### 1. Gate-opening blocker based on a numeric/signal tier — removed

`compute_account_research_estimate` previously refused an Account unless it found exactly one
`account.scoring.tier` claim that was human-extracted, source tier 1, selected for the same project
run, and whose tier string equaled the directive's effort tier. This made the directive-confirmation
gate impossible to open for a low-tier, tier-4, untiered, or merely vocabulary-mismatched Account.

That predicate and the typed `AccountTierCheckpointMissing` failure were removed. The estimate now
resolves the effective directive for each explicitly selected Account and sums the directive's
immutable `effort_policy.budget_cap_cents`. The user-selected Account set and directive determine
the amount; scoring metadata does not determine eligibility.

The gate tool consequently no longer emits `account_tier_checkpoint_missing`. A low/no-tier
Account can receive the same confirmation gate, spend estimate, and immutable receipt as any other
explicitly selected Account.

### 2. Fleet-launch tier veto — removed

The normal Account research fleet launcher used the same estimator but translated a missing or
mismatched tier into `AccountResearchFleetLaunchError`. That catch/translation was removed with
the underlying predicate. The launcher still verifies that the approved gate amount exactly equals
the sum of the confirmed directives, so removing tier eligibility did not remove price integrity.

### 3. Duplicate durable deep-launch tier veto — removed

The quarantined/historical `account_deep_launch` preview carried a second copy of the requirement
for one human, source-tier-1, selected tier claim equal to the directive effort tier. That duplicate
predicate was removed as well, preventing a later seam from silently reintroducing the launch veto.

### 4. “Committee discovery is high-tier only” policy threshold — reduced to the floor

Committee eligibility, Sumble Account-gap enrichment, and Exa targeted enrichment previously
admitted only `high` or `top` Accounts. They now share one policy constant:

`ACCOUNT_RESEARCH_ELIGIBLE_TIERS = {top, high, standard, low, tier1, tier2, tier3, tier4, 4}`.

This explicitly includes the least supported Account tier, `tier4`/`4`, as well as the current
two-label `high`/`low` policy. The committee worker's contract language was also corrected from
“known high-tier account” to “known explicitly selected account” so documentation no longer
asserts a gate the runtime does not have.

### 5. Tier-claim provenance threshold — reduced from source tier 1 to source tier 4

Historical claim-backed provider paths previously required a tier decision to be both:

- extracted by a human; and
- sourced at trust tier exactly 1.

They now accept an otherwise valid exact live selected claim when `source_tier <= 4` through the
shared `TIER_CLAIM_MAX_SOURCE_TIER = 4`. Source tier 4 is the least-trusted tier supported by the
claim model, so this is the lowest possible trust threshold without inventing a fifth tier or
bypassing claim validation.

This change applies to committee eligibility, Sumble Account-gap preflight, Sumble committee-input
resolution, and Exa targeted-enrichment preflight. Historical callers still have to supply the
exact claim ID, and the claim must remain live, Account/workspace matched, selected, and bound to
the exact project run, sealed discovery batch, ICP, and selection policy where that path requires
them. Only the high-trust/high-label restriction was relaxed.

### 6. Tier claim as a prerequisite for an exact Account job — disabled on that path

`AccountGapRequest` and `CommitteeAcquisitionRequest` formerly required a `tier_claim_id` even
when an exact running R6 Account job already proved direct user selection. The field is now nullable
only when `entity_research_job_id` is present. Model validation continues to reject a historical
request with neither an exact job nor a tier claim.

Alembic revision `fc3e5477e872` makes the two operation-table columns nullable and replaces their
database validation functions. A NULL tier claim is accepted only if request JSON names an
`entity_research_job` whose subject type, Account, workspace, project, and project run exactly match
the operation. Tierless historical inserts and tierless mismatched-job inserts remain database
errors. The downgrade restores the prior functions and NOT NULL columns.

### 7. Pass-A scoring checkpoint prerequisite — disabled for an exact Account job

Committee eligibility formerly required a committed Pass-A scoring checkpoint even after a user
had explicitly launched research for the exact Account. The exact R6 job now supplies the audit
evidence for this condition. Historical/non-job committee requests still require the committed
scoring checkpoint.

### 8. ICP must-have criteria prerequisite — disabled for an exact Account job

The committee evaluator previously rejected an Account when the pinned ICP selection policy was
invalid, had no must-have criteria, lacked a sealed must-have proof, or did not evidence every
must-have. Those checks remain useful when broad discovery selection is the authority, but they
were a second, unrelated veto after direct Account selection.

For an exact R6 job, the job is now recorded as the evidence for explicit selection and those
must-have checks are not rerun. Historical/non-job requests retain the full ICP-policy and
evidence-backed must-have evaluation.

### 9. Human tier-checkpoint approval prerequisite — disabled for an exact Account job

The committee path no longer requires a committed/approved `tier_checkpoint` phase record or any
tier claim when the request belongs to the exact running Account job. The job itself is the durable
human-selection receipt. Historical callers still require the approved checkpoint and exact live
selected tier claim, now at the tier-4 thresholds described above.

### 10. Active/deep outer-project-state blocker — narrowly relaxed

Provider spend capacity previously rejected the committee and Account-gap calls because the outer
discovery project run was paused at its legacy `tier_checkpoint`, even though the independently
confirmed Account research job and its fleet run were actively running.

An exact live entity-research job may now reserve provider spend when the outer project is either:

- active; or
- paused at exactly `tier_checkpoint`.

The exception is intentionally narrow. The job and its research run must both be `running`, and
exactly one fleet authority type must match. Pauses at any other phase, cancelled/missing/mismatched
jobs, terminal project states, and historical/non-job requests remain ineligible. Historical
requests still require an active project run in the allowed deep phase.

### 11. Sumble Account-gap active-project check — narrowly relaxed

The Sumble Account-gap compiler also independently rejected any non-active outer project run. For
an exact Account job it now proves that the job is an Account job with the same Account, workspace,
project, and project run, then delegates the live-job/state/budget authority to the durable spend
check. Without an exact job, it still requires an active deep-phase project run and the historical
tier claim.

### 12. Current-run provider-result prerequisite — removed

When Account fields were already covered by fresh persisted claims, the agent correctly skipped
paying to fetch them again, but the committee prompt then effectively demanded a current-run
`research-result:` reference for the buying-unit scope. That made “fresh data, no new provider
call” an accidental committee blocker.

The active Account-agent prompt and skill now explicitly allow `buying_unit_scope.evidence_refs`
to use durable `claim:` references surfaced by persisted Account state. If all selected fields are
fresh, the agent is instructed to continue to requested committee discovery instead of refusing
or manufacturing a redundant provider call. Exact same-office scope and confirmed target-function
requirements remain enforced.

### 13. Sumble Organizations snapshot-source blocker — removed by governed reuse

Committee preparation previously accepted only a succeeded Sumble Organizations snapshot created
by later Account-gap enrichment. Some valid research plans contain only qualitative gaps, so they
never create that unrelated snapshot even though the same exact Organization identity had already
been purchased and persisted during discovery.

The resolver still prefers the Account-gap snapshot. If absent, it may reuse the latest succeeded,
artifact-backed Sumble Organizations discovery-gap operation only when it matches the same project
run, sealed discovery batch, Account, and provider source. The artifact is read through verified
storage before extracting the provider organization ID. This removes a needless re-purchase and
reachability blocker without allowing arbitrary provider blobs or weakening organization identity.

### 14. Retry/history ambiguity blocker — removed by exact directive filtering

The committee-plan reader previously loaded Account runs only by project run and Account. A retry
or older run for the same Account could produce more than one candidate and cause the current job
to appear unready.

`find_account_runs_for_entity` now supports an immutable `directive_ref` filter, and the committee
plan reader supplies the current job's authorized directive ref. An older run under a different
directive no longer blocks the current job. More than one run for the *same exact directive* still
fails closed with `AccountResearchAuthorityError`, because that remains a genuine authority
ambiguity.

## What was deliberately not removed or disabled

The following controls remain in force and should not be mistaken for blockers removed in this
session:

- an attributable user turn must explicitly select the exact Account;
- the Account must be in the confirmed directive scope, and gate amount/pins must match;
- the exact Account job, research run, fleet authority, workspace, project, project run, and
  Account lineage must match and be live;
- the Account must belong to the exact sealed discovery batch used by committee acquisition;
- the committee plan and research directive must match and be human-confirmed;
- personal-data acquisition, jurisdiction, identity acquisition, and
  `professional_public` use-class policy must pass;
- contact reveals remain prohibited in this committee enumeration path;
- every configured provider still goes through `PreSpendGate.check`;
- provider requests, provider units/credits, money, reservations, artifacts, and terminal receipts
  continue to be recorded durably;
- no provider-credit check or paid-provider call was mocked or bypassed for live acceptance;
- no arbitrary contact or cross-office candidate is admitted; strict same-office scope and
  identity resolution remain;
- ambiguous or roleless candidates remain honest review outcomes rather than being forced into a
  role; the successful live job therefore ended `needs_review` instead of falsely reporting full
  completion;
- no financial-cap behavior was newly disabled by these commits. The pre-existing pilot
  `enforce_budget` setting remains configuration-owned; regardless of that setting, true spend and
  outstanding reservations are still computed and written;
- no new buying-committee UI component or field was rendered. The backend additionally serves
  role reasoning, the frontend schema preserves it, and the existing UI remains visually
  unchanged.

## Changes that were operational, not permanent blocker removals

The following same-session actions helped validate the flow but are not product-policy changes:

- restarting the API and fleet against the preserved database, artifact root, and agent workspace;
- applying the current migration/function definitions to the live test database;
- logging in and continuing the preserved authenticated browser session;
- making a raw paid Sumble canary before the full run;
- navigating to Contacts and probing the authenticated read response.

They must not be counted as disabled gates. The permanent behavior is the committed code and
migration above.

## Verification and live outcome

The permanent changes were exercised with a mixed high/low-signal launch under a differently named
`standard` effort tier, a selected Account with no numeric tier, tier-4 policy cases, source-tier-4
claim cases, exact-job tierless database cases, wrong-job/historical rejection cases, paused
`tier_checkpoint` provider-spend cases, fresh-claim committee evidence, sealed-discovery
Organizations reuse, and retry/directive filtering.

Final verification in this session:

- 89 focused backend tests passed across committee/provider/R5/R6/D5/governed-contacts paths;
- 353 frontend tests passed;
- root lint, typecheck, and contract gates passed;
- frontend design-system build, lint, and production build passed;
- Alembic had one head and an isolated downgrade -> upgrade -> current cycle passed at
  `fc3e5477e872`;
- a real paid Sumble canary succeeded before the full run;
- the browser-driven committee run made real paid Teams and People calls, returned two
  identity-resolved candidates, and persisted one evidence-backed committee-role inference;
- the final `needs_review` state was caused by genuine candidate ambiguity/one roleless member,
  not by signal level, tier claim, scoring checkpoint, must-have criteria, project phase, missing
  provider result, Organizations identity, provider credits, or backend/API reachability.

## Commit mapping

- `2fef333e` — removes signal-tier eligibility from gate pricing, normal fleet launch, and the
  duplicate durable deep-launch path; freezes high/low/no-tier acceptance.
- `e770bd52` — makes the exact R6 job the committee authority; lowers historical Account/source
  tiers to tier 4; relaxes the exact paused-phase path; adds tierless exact-job persistence; accepts
  durable claim evidence and sealed-discovery Organizations reuse; isolates retries by directive.
- `58636bed` — exposes committee role reasoning through the backend/frontend read contract without
  rendering additional UI. This is data delivery, not an eligibility change.
