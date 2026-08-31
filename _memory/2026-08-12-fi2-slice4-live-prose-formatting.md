# FI-2 Slice 4 — live prose and user-facing vocabulary

## Scope and implementation

- Implemented LF-RESEARCH-002 and LF-RESEARCH-004 only. Source-link precision, inspectable Contact
  evidence and research-governance decisions remain in their separately planned/open slices.
- Added an FI-2 prose read state over Lane-E `account.summary` and `contact.overview` claims:
  `available`, `not_composed`, or `restricted`. Available values carry their durable paragraphs and
  `completed`/`needs_review` outcome; absent/withheld states never carry prose.
- Account summary and Contact overview have dedicated wire/model slots and are excluded from generic
  fact rendering. Contact overview is read directly from current Contact truth rather than from the
  older committee reference index.
- Added stable frontend mappings for `1b_plus`, `product_led`, `c_level`, and all four committee
  personas (`economic_buyer`, `champion`, `technical_evaluator`, `blocker`) while preserving raw
  tokens in API/model data. Dynamic unresolved fields now carry effective-registry descriptions;
  the browser uses the description rather than exposing a raw key as the explanation.
- Recorded the contract in `apps/frontend/docs/api-contracts/accounts.md` and committed the coherent
  implementation as `b8477bb4` (`feat(accounts): serve live research summaries`).

## Verification completed

- Frontend: 160 tests passed; ESLint, design-system build, TypeScript and webpack production build
  passed.
- Backend: 112 FI-2 frontend-read/composed-journey tests passed against the isolated
  `clue_monterrey_fi2_slice4_20260812` Postgres database; focused Ruff and mypy passed.
- Durable acceptance seed uses the authenticated Insight Health workspace and contains three active
  accounts, four active Contact identities, two live verified prose claims, and one unsupported
  `healthcare.npi` result whose registry description is present.

## Authenticated browser acceptance

- After explicit user authorization, the local Clerk development values were reused only in the
  frontend process environment; they were never printed, stored, or committed. The frontend also
  required `CLUE_AUTH_ENABLED=true`; without that explicit flag the sign-in route correctly showed
  authentication-disabled. Restarting with the flag produced the real Clerk form and successful
  `session -> principal` bootstrap for the Insight Health workspace.
- The browser followed `/accounts` -> Northstar preview -> Contacts and verified the completed
  two-paragraph Account summary, the registry-described `healthcare.npi` gap, `$1B+`, `Product-led`,
  all Contact persona labels, Dana's completed overview and `C-level` job level. Raw tokens and
  contradictory incomplete-research copy were absent from the rendered pages.
- The named, policy-withheld, unnamed/partially-researched and stale-merged Contact routes all
  returned live pages and survived direct reload. Withheld/unnamed records rendered the honest
  not-composed state; the stale id visibly resolved to Dana's survivor. Contact links had distinct
  concise accessible names and adjacent avatars were decorative.
- Next and FastAPI logs recorded `200` throughout the authenticated session-to-principal chain and
  `/frontend/v1`, including every Contact shape and a same-origin BFF Account-detail request.
  No browser runtime error dialog or server error page appeared; the only browser log message was
  Clerk's expected development-key warning.
- Browser acceptance exposed two test-only defects that were repaired before closeout: the fixture
  narrative used raw persona tokens inside synthetic prose, and the stable semantic map covered
  only `economic_buyer`. Fixture prose is now human-authored text and all four persona values have
  explicit display labels with unit coverage.
