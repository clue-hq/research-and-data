# 2026-08-05 — M8C C1 selection and lineage remediation

## Scope

- Reopened only the two P1/P2 C1 findings from the C0–C2 adversarial audit.
- Preserved existing Sumble acquisition, committee identity/role inference, contact-targeted Exa
  C2 work, reveal boundaries, and unrelated workspace changes.
- Made no provider request and spent no Sumble or Exa credits; C1 remains stored-snapshot
  materialization.

## Changes

- Replaced People-first concatenation/truncation with a bounded union selector. Strong identities
  precede weak candidates, People/Teams overlap precedes single-source rows, and remaining capacity
  alternates Teams-only then People-only candidates in provider order. Paid organization-map rows
  can no longer be categorically starved by a full People result page.
- Added `ClaimProvenanceKind` and durable `claim.provenance_kind` values for
  `provider_returned`, `provider_modeled`, `platform_inferred`, and `human_asserted`. Sumble literal
  professional facts, Teams membership, and platform role/persona inference now remain typed and
  distinguishable after persistence and replay.
- Added migration `26eaa6262063`. PostgreSQL now rejects a Sumble professional claim unless it
  matches the exact ready committee operation, succeeded source snapshot, response artifact,
  project run, workspace, operation account, and admitted contact under that account. The database
  also enforces the C1 tier/method/mode/binding/use/scope/cost/provenance shape and makes the new
  provenance column immutable.
- Added adversarial coverage for People-cap starvation, weak-vs-strong selection, fabricated or
  omitted refs, wrong typed provenance, cross-account contact writes, provenance mutation, and
  writes after response/subject evidence tombstoning.

## Verification

- Focused C1 source/materialization/claim tests: 17 passed.
- Fresh-process V0 replay acceptance: 1 passed with no provider traffic on replay.
- Complete live-Postgres repository collection: 3,398 cases reached 100%, exit 0, expected skips
  only, on fresh database `roseau_m8c_c1_verify_20260805`.
- Alembic head→base→head smoke passed on separate empty database
  `roseau_m8c_c1_smoke_20260805`; sole head is `26eaa6262063`.
- Mypy passed 525 source files; import-linter kept all 24 contracts; Ruff format/lint passed on all
  changed C1 Python files.
- An earlier full-suite run against the reused C0 database produced registry redefinition failures
  because committed seed state survived prior tests. Re-running the same suite on the fresh,
  C1-owned database removed every failure without a product-code workaround.

## Closing state

- Both audited C1 findings are mechanically closed. Teams/People composition is bounded without
  systematic organization-graph starvation, and application-supplied lineage strings are no
  longer authority at the claim-store boundary.
- C1 does not claim a new live provider call; the already-paid immutable Sumble snapshots are the
  correct input for this slice. Contact-targeted acquisition remains in later M8C slices.
