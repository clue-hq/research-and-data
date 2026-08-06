# M8C C6 provider-neutral contact composition

## Final state

C6 is mechanically complete on `platform/c8-account-profiling-integration`. It adds immutable
post-committee contact selections, append-only cancellation, registered ordered preparation,
existing-fleet wait/resume, generic external wake dispatch, and governed independent
`profile_contact@2` composition. No new project phase, provider branch, or fleet was added.

## Important decisions

- Automatic selection admits only strongly identified, plausible committee members and never
  authorizes email/phone. A reveal requires a separately persisted approved successor.
- Same-content concurrent selection returns the elected original receipt id. A cancelled latest
  receipt cannot be automatically regenerated from the same directive.
- Preparation source keys must be registered exactly once. Adapters execute in plan order and a
  later adapter cannot start until its predecessor is `READY`.
- Provider calls/polls occur after database contexts close. C6 passes prepared claim refs into the
  existing contact worker; that mode only projects durable claims and cannot enter the resolver
  waterfall under its claim transaction. Raw channel claims are excluded from generic profile
  output.
- Waiting folds immutable refs into the existing account run at `COMMITTEE_DISCOVERED`; the generic
  wake dispatcher only re-offers owning project runs to the existing detached fleet.
- Exa contact acquisition is independently default-off. Channel enrichment fails production
  composition if enabled without a concrete validator-backed coordinator; no fake validator is
  substituted.

## Main implementation

- Migration `4d9b02f218dc_m8c_c6_contact_research_selection.py` adds selection and cancellation
  authority with exact-scope checks and immutability triggers.
- `durable/contact_research_selection.py` owns persistence, replay election, and cancellation.
- `contact_research_selection.py` and `contact_research_preparation.py` own post-committee selection
  and provider-neutral intent preparation.
- `deep/orchestrator.py`, `external_research_wake.py`, and `fleet_main.py` compose waiting/resume
  without provider branches or a new fleet.
- `independent_contact_research.py`, `toolbelt_wiring.py`, and the current harness catalog expose
  governed `profile_contact@2`; v1 stays available only for historical exact pins.
- The binding record is
  `docs/specs/M8C-C6-provider-neutral-contact-composition-acceptance.md`.

## Verification

- Disposable PostgreSQL migration cycle `head -> base -> head` passed with single head
  `4d9b02f218dc`.
- Combined C4-C6 and deep-orchestrator database regressions passed.
- Full repository pytest passed against a newly created clean disposable database. Re-running the
  full suite on the already-used first database reproduced known global seed/order pollution; a
  fresh database passed, confirming it was not a C6 regression.
- Mypy passed for 537 files; all 24 import contracts passed over 604 files/5,022 dependencies;
  scoped Ruff passed for C6-owned files.
- Repository-wide Ruff findings were confined to unrelated pre-existing tracked/untracked files and
  were not modified.

No paid provider call was made. The seeded development database on port 55010 was not changed;
destructive migration verification used port 64466 and the final fresh full-suite gate used port
64467. V1 remains the explicitly authorized live-provider gate, and concrete channel validator
deployment remains fail-closed.

## Next handoff

C7 owns the additive contact handoff/content-consumption bridge. It must preserve the separate
delivery-channel eligibility surface and consume only eligible claim/provenance refs.
