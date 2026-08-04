# 2026-08-05 — M8C C0/C1 implementation

## Scope

- Branch: `platform/c8-account-profiling-integration`
- Roadmap: `docs/specs/M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md`
- User required C0 implementation and exit-gate verification before beginning C1.

## C0 checkpoint

- Added provider-neutral, reference-only selected-contact selection/intent/preparation contracts.
- Froze the professional field vocabulary and reused `core.work_email`; reserved
  `core.direct_phone` for C5 rather than misusing `core.company_phone`.
- Added executable channel states separating observed, corroborated, validated, verified-email
  identity, rejected, and independent outreach-use permission. Phone cannot be identity-promoted.
- Added the conservative layered `ContactResearchPolicy`: existing Sumble snapshots and Exa Deep
  plans are present; all contact reveal providers and budgets remain disabled/zero.
- Retained the pinned, canary-proven Sumble v9 runtime contract and captured public v3 as a dated,
  non-authorizing reference. No silent migration or reveal endpoint was introduced.
- Added `M8C-C0-contact-research-contract-acceptance.md` and machine-readable provider authority
  fixtures.

Verification:

- 59 focused C0/config/Exa/Sumble tests passed.
- Ruff passed on changed C0 code.
- Mypy passed across `clue_core`, `clue_config`, and C0 tests (53 source files).
- Import-linter kept all 24 contracts.
- No migration, network/provider call, credit, channel reveal, or identity mutation occurred.

## C1 next

- Register the six professional-public contact fields.
- Preserve field-specific Sumble People/Teams artifact provenance on committee candidates.
- Materialize snapshot facts idempotently in the existing committee claim transaction.
- Include professional claim references in the existing handoff path without a new request,
  classifier, fleet, or orchestrator.
