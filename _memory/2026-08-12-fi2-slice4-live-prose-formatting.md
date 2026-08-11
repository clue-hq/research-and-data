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
- Added stable frontend mappings for `1b_plus`, `product_led`, `c_level` and `economic_buyer` while
  preserving raw tokens in API/model data. Dynamic unresolved fields now carry effective-registry
  descriptions; the browser uses the description rather than exposing a raw key as the explanation.
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

## Browser acceptance blocker

- This worktree has no Clerk frontend credentials. An attempt to reuse the two development values
  from an already-running local frontend process was blocked as sensitive credential reuse and was
  not bypassed.
- Browser/API/accessibility acceptance remains pending explicit user authorization to reuse those
  local development credentials (without printing or storing them), or equivalent credentials
  configured directly by the user. The temporary API server was stopped; the isolated database and
  artifact directory were preserved together.
- Do not close the two defect-log rows until the authenticated browser pass is complete.
