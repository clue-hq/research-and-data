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

## C1 checkpoint

- Registered the six C0-frozen professional-public fields: title, function, level, team,
  location, and current organization relationship.
- `SumbleCommitteeSource` now preserves field-specific People/Teams response-artifact,
  operation, snapshot, request, source/evidence, product, observed-at, and confidence metadata.
- Provider-returned facts and provider-modeled team membership remain distinct; existing platform
  role/persona claims remain LLM-derived and cannot be confused with either.
- The existing committee worker materializes professional claims only after strong identity
  admission, inside its short claim transaction. Equivalent replay returns the same ids; changed
  immutable snapshot content fails closed with `ProfessionalFactReplayConflict`.
- Professional claim refs are included in committee results and the existing handoff eligibility
  path. No parallel handoff, request, classifier, fleet, or orchestrator was added.
- The V0 fresh-process acceptance was updated from a brittle total-count assertion to the exact
  nine expected field keys (tier, six professional facts, persona, committee role).

Verification:

- 26 C1-focused DB tests passed.
- 82 broader committee/orchestrator/handoff DB tests passed.
- V0 disposable fresh-process replay passed with zero replay provider calls.
- Ruff passed; mypy passed across `libs`, `subsystems`, and `platform` (525 files); all 24
  import-linter contracts passed.
- The complete pytest suite passed to 100% against owned disposable Postgres database
  `roseau_m8c_c1_exit_0805a`, after the required `alembic upgrade head`, and the database was
  removed afterward.

Observed setup failure and resolution:

- A first monolithic run against an empty, unmigrated disposable DB failed in an unrelated DSAR
  test because that test opens schema tables without requesting its migration fixture. Running the
  supported sequence (fresh DB, migrate to head, tests) made the exact DSAR test and full suite
  pass. No product change was made for this environment/setup failure.

No new provider traffic, Sumble credits, channel reveal, identity mutation, or migration occurred.
C2 exact contact-subject durability is next.
