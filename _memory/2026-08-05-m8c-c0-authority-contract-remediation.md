# 2026-08-05 — M8C C0 authority and provider-contract remediation

## Scope

- Reopened only the four P1/P2 findings assigned to M8C C0 by the C0-C2 adversarial audit.
- Did not change C1 professional materialization, C2 persistence, provider acquisition, contact
  reveals, or the C3 contact-targeted Exa compiler.
- Preserved all unrelated modified and untracked workspace files.

## Changes

- Added `ContactResearchPolicyPin` to the core receipt contract. The selection body now embeds the
  exact effective provider refs, source plans, freshness rules, contact/field/query/result caps,
  and separate email/phone reveal caps. `ContactResearchSelection.from_body` requires the
  independently resolved effective policy to match the embedded pin.
- Made selection validation fail closed on a directive for another account, duplicate contacts,
  unsupported field classes, cap overruns, reveal/field mismatches, policy-disabled reveals,
  unapproved provider keys, and aggregate reveal budget overruns.
- Made `ContactResearchIntent` an exact projection of its embedded selection receipt. Account,
  contact, directive, fields, questions, source plan, freshness, source profile, budget reference,
  selection id, and digest are mechanically checked. `from_selection` is the canonical builder.
- Replaced duplicated config-policy validation with a `ContactResearchPolicy` subclass of the core
  pin plus a `pin()` boundary method.
- Added a provider-neutral, body-independent failure classifier for validation, authentication,
  insufficient credit, rate limit, server, timeout/transport, pre-dispatch retry, post-dispatch
  spend uncertainty, and budget pause.
- Added owned HTTP envelope fixtures plus executable Sumble empty-success fixtures. Tests exercise
  Sumble pending/running/succeeded/empty/failed parsing and verify failure-disposition parity with
  the existing Exa transport classifier.
- Corrected the C0/C3 ownership boundary: C0 records Exa Search capability and inherited
  account-level compatibility only; C3 still owns the exact contact-targeted request compiler,
  target lock, output schema, parser negatives, and request fingerprint.

## Verification

- C0 plus config tests: 54 passed.
- Clean isolated PostgreSQL database `roseau_m8c_c0_fix_20260805` migrated from base to head.
- Focused C0/C1/C2, Sumble source, and Exa E1/E2 compatibility tests: 31 passed.
- Complete repository pytest suite: 3,419 collected cases completed with expected skips only and
  no failures.
- Mypy: 525 source files, no issues.
- Import-linter: 24 contracts kept, 0 broken.
- Ruff format/lint passed on all changed Python files; JSON fixtures passed `jq empty`; relevant
  diff whitespace checks passed.
- Alembic: exactly one head, `9e3afe93b8e1`.

## Closing state

- The four audited C0 P1/P2 findings are closed mechanically and documented without claiming a
  live contact-targeted Exa call. C1/C2 audit findings remain separate work.
