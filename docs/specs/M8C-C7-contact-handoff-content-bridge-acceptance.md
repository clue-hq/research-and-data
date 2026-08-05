# M8C C7 — Governed contact handoff and content bridge acceptance

- **Parent roadmap:** `M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md`
- **Depends on:** C0–C6 accepted contracts, selections, claims, and channel receipts
- **Branch:** `platform/c8-account-profiling-integration`
- **Recorded:** 2026-08-05
- **Status:** mechanically accepted; V0 and separately authorized V1 remain open

C7 is a read-side projection over the existing claim store, canonical identity, immutable
selected-contact receipt, research views, use decisions, and channel ledger. It persists no second
truth store, calls no research provider, and does not add a content-generation subsystem.

## 1. Reference-only content contract

`ContactContentHandoffService` produces one exact `account x contact x persona` bundle for every
currently eligible selected contact. The bundle contains references to canonical account/contact
identity, committee role and persona claims, professional claims, promoted account context, matching
value-narrative claims, and use-cleared personal facets. Claim bodies and evidence text remain
behind the research-view and claim-store authorities.

The core contract rejects email/phone field claims in drafting context. A channel can appear only
as a separate delivery reference to a succeeded, independently validated, fresh, retained, and
currently unsuppressed C5 operation. The reference carries operation/validation/corroboration ids,
never the email or phone value.

## 2. Exact authority and cancellation

The service composes everything in one repeatable-read database snapshot and requires the exact
workspace, project, project run, account run, product, canonical contact, selection, and claim
membership. Product-specific role/persona authority cannot be borrowed from another product.

Selection recency is ordered first by the receipt's explicit `approved_at`, avoiding PostgreSQL
transaction-time ties between a predecessor and same-transaction successor. C7 reads the latest
receipt including cancellations and returns no bundle when that receipt is cancelled; it cannot
silently fall back to the predecessor.

Channel eligibility is also selection-exact. A current selection may use either:

- its own direct `contact_channel_operation`; or
- an immutable `contact_channel_reuse` receipt that explicitly authorizes a still-usable validated
  source operation for that selection.

An older success for the same contact/channel, without one of those exact receipts, is absent from
delivery eligibility.

## 3. Coverage and fallback

Professional fields are registered into the contact research view's
`professional_signals` section with project-run-pinned, neutral-or-exact product policy. Email and
phone fields deliberately have no generic research-view route.

For each selected contact, the handoff classifies every requested field as filled, empty,
conflicted, or blocked; names searched and unsearched configured sources; classifies email and
phone as delivery-eligible, excluded, failed-validation, or not-requested; and emits immutable
selection/operation coverage refs plus policy/budget/cancellation stop refs when present. Selected
contacts that become ineligible and committee contacts that were not selected are named as
exclusions.

The existing committee worker does not durably persist its numeric coverage point into the account
run. C7 therefore emits `committee_coverage_estimate=null` together with
`committee_coverage_not_durable`; it does not fabricate a percentage from selected-contact count.
This is a truthful missing-data state, not a completeness claim.

If no use-cleared personal facet exists, drafting falls back explicitly to account-level evidence
or a generic-review state. Missing evidence never invites the downstream consumer to invent a
personal hook.

## 4. Exit-gate evidence

| C7 gate | Executable evidence |
|---|---|
| every projected fact is eligible and reference-backed | database projection test composes only governed research-view/eligibility claims and serializes ids, not values |
| facets require strong binding and allowed use | frozen core validators plus positive/negative contract tests |
| invalid channels are absent | delivery contract requires independent validation; C5/C7 regression proves selection-exact direct/reuse authorization and foreign-selection exclusion |
| raw channels stay out of drafting | contract rejects `core.work_email`/`core.direct_phone`; serialized fixture contains neither field nor raw value |
| missing evidence is explicit | fallback, field/source/channel coverage, skipped-contact, cancellation, and unavailable-committee-coverage reason tests |
| content cannot call research providers | the fixture consumer accepts only claim refs and delivery refs; the production service imports no provider/model transport |

### Recorded verification (2026-08-05)

- 71 M8C contact-research, C7 production-reader, and committee-field tests passed against the
  isolated PostgreSQL database `clue_roseau_m8c7` at the single Alembic head `4d9b02f218dc`.
- The same matrix includes C3 compilation, C4 acquisition/materialization with fake transport, C5
  validation/replay/privacy mechanics, C6 wait/selection mechanics, and the new C7 projection.
- The complete repository pytest suite passed against the same isolated migrated database.
- Scoped Ruff formatting/linting passed for every C7-owned file; repository mypy passed for 539
  source files.
- All 24 import-boundary contracts passed across 606 files and 5,049 dependencies.

No live Exa, Sumble, reveal-provider, validator, or model traffic was made for C7. That is the
correct read-side boundary: fake-transport combined acceptance belongs to V0, while explicitly
authorized paid provider behavior belongs to V1.

## 5. Acceptance boundary

C7 closes the research-to-content contract, not the content fleet. Drafting, template
finalization, artifact derivation, delivery/export, and publishing remain downstream. If a content
consumer identifies a research gap, it must ask the platform deepagent to propose a successor
research directive; it cannot reveal a channel, call Exa/Sumble, or widen research scope itself.
