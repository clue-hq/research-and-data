# FI-2 Slice 5 — exact sources and inspectable evidence

## Scope and decisions

- Implementing LF-RESEARCH-001 and LF-RESEARCH-003 only. Governance-decision display remains open;
  no email enrichment, bulk actions, local Account creation or unrelated workspace-tab capability
  is changed.
- Exact public source URLs may cross the FI-2 screen-shaped read contract after the shared C7 URL
  safety predicate accepts them. The visible label is the complete URL; the frontend cannot author
  a more-specific source label.
- Retained artifacts are exposed only through an authenticated same-origin action that re-runs the
  current Account/Contact read, workspace scope, Contact display policy, retention-aware claim read
  and artifact lifecycle/content-integrity checks. No object key or signed URL crosses the wire.

## Implementation state

- Added claim-mapped evidence records with source identity, exact safe URL, display-eligible span,
  confidence, freshness, observed time and an opaque protected-artifact availability flag.
- Account neutral facts and project narrative/insight facts now carry their own evidence record.
  Contact evidence is one item per displayed current claim; withheld and expired claims contribute
  no value or provenance metadata.
- Added Account and Contact artifact routes plus BFF forwarding for no-store, CSP-sandboxed,
  `nosniff` responses. Unknown, cross-workspace, erased and no-longer-authorized requests share one
  non-enumerating 404.
- Added frontend evidence cards and exact-label contract validation. The Account Insights tab now
  renders evidence from the live Account read instead of depending on removed runtime fixtures.

## Verification complete

- Fresh isolated database `clue_monterrey_fi2_slice5_20260812` migrated to the current head.
- 84 focused frontend-read Account/Contact/app tests pass against that real database, including
  public URL safety, claim mapping, withheld/expired non-disclosure, cross-workspace refusal,
  erased-artifact refusal, content integrity and both protected artifact routes.
- The composed FI-2 journey plus Slice-5 API set passes 94 real-Postgres tests. Repository-wide
  Ruff, mypy (633 source files) and 25 import contracts pass. Frontend passes 163 tests, ESLint,
  design-system build, TypeScript and the production webpack build.
- The repository-wide pytest run reached 100%. Three apparent failures were local-Postgres sandbox
  access and passed when rerun correctly against the isolated database. Two unrelated existing
  failures remain: the Head-of-ABM registry test expects the absent
  `stage0-interview/v9/SKILL.md`, and the logging-discipline test scans the intentionally excluded
  `subsystems/clue-design` subtree. Neither failing test imports or exercises Slice-5 code.
- Authenticated acceptance used two durable Accounts, six Contact identities, 28 current
  evidence-bearing claims and two live artifact records/bytes under the Insight Health workspace.
  Health returned 200 and an unauthenticated Account read was denied.
- The real browser traversed the Account list, Account Insights, Contacts list, named Dana Buyer,
  partially researched Sam Technical and title-withheld Chris Blocker. Visible source labels
  matched their targets exactly. A public Account source opened the exact test URL, and a protected
  Contact evidence action opened through the same-origin BFF and rendered its retained evidence
  body. Browser, Next and FastAPI logs showed authenticated 200 responses for all reads and both
  protected evidence routes; no framework overlay or application console error appeared. The only
  console message was Clerk's expected development-key warning.
- Postgres correlated the browser-visible Account employee-count claim and Dana current-title claim
  to the exact entity, field, URL, evidence span, confidence and live artifact rows. The withheld
  title exists durably but the governed Contact response and browser omit its value and provenance;
  allowed persona and committee-role evidence remains visible.
- One adjacent Slice-2 defect was discovered during reauthentication: the expired-session button
  clears the workspace cookie but Clerk can return without navigating to canonical `/sign-in`.
  Direct navigation renders the real sign-in form and succeeds. This is not a Slice-5 provenance
  failure and remains follow-up work.
- The evidence presentation currently uses a new card renderer. The user questioned that visual
  change; no corrective visual edit was requested in the follow-up, so testing continued without
  changing the presentation. Preserve the contract work if the presentation is restyled later.
