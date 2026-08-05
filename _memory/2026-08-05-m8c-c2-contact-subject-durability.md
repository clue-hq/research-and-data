# 2026-08-05 — M8C C2 exact contact-subject durability

## Scope

- Branch: `platform/c8-account-profiling-integration`
- Roadmap: `docs/specs/M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md`
- C2 only. C3 Exa contact compilation, C4 live acquisition/materialization, C5 channel reveal, and
  C6 wake/fleet composition remain untouched.

## Implementation

- Extended external-research operation/snapshot runtime rows with validated `subject_kind` and
  `contact_id`; exposed the exact routed subject entity.
- Made reusable-operation, ready-snapshot, active-materialization, adoption, and replay checks
  compare the complete account/contact subject.
- Required new work to target the current canonical account and contact under the exact workspace.
  Immutable merged-loser history remains auditable but cannot be silently adopted by the survivor.
- Added migration `9e3afe93b8e1`: snapshots and snapshot-use receipts now persist the subject,
  operation/snapshot/use equality is trigger-enforced, contact-aware indexes are present, and Exa
  claim lineage binds account claims to the account and contact claims to the exact contact.
- Added disposable-DB, fresh-process acceptance for concurrent reservation, post-dispatch crash,
  stale-lease quarantine, exact settlement, and zero-HTTP replay.
- Persisted binding evidence in `M8C-C2-contact-subject-durability-acceptance.md` and marked C3 as
  the next roadmap slice.

## Verification

- One Alembic head: `9e3afe93b8e1`.
- Migration passed head to prior head to head and the complete head to base to head cycle on owned
  database `roseau_m8c_c2_dev_0805a`.
- 22 focused C0/C1/C2 and E1/E2 tests passed.
- Complete live-DB pytest suite reached 100% with exit code 0; 3,391 tests collected, with only
  normal environment-gated skips.
- Ruff lint/format, mypy across all 525 source files, and all 24 import-linter contracts passed.
- C2 provider call count was zero. Synthetic durable response/cost fixtures are not live provider
  evidence and are recorded as such.

## Next

C3 owns the production contact-targeted Exa Deep compiler: exact person/employer lock,
registry-shaped output schema, directional questions, source evidence, bounded deep-reasoning
policy, and parser fixtures. C2 must remain provider-neutral and should not grow a provider worker.
