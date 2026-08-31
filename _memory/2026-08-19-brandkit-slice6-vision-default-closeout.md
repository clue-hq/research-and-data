# Brand-kit onboarding — Slice 6 vision-on deployment defaults and close-out (2026-08-19)

Branch `feature/brandkit-onboarding-integration`. Local commits only; never pushed.

## Deployment contract

- The Lumen library defaults remain unchanged: `lumen_ingestion_vision=False` and
  `lumen_ingestion_describe=False`. Deterministic tests and library consumers do not silently
  acquire provider spend.
- Both tracked deployment recipes now set `LUMEN_INGESTION_VISION=1` and
  `LUMEN_INGESTION_DESCRIBE=1`: root `.env.example` for the integrated monorepo and
  `subsystems/clue-design/.env.example` for a standalone design launch.
- Live assistance requires `OPENROUTER_API_KEY`. The integrated recipe aliases it to the existing
  `CLUE_OPENROUTER_API_KEY` by variable reference, so the secret is neither duplicated nor
  committed. If the key is absent, the describer is inactive and PDF vision resolves directly to
  `NullPdfVision`; ingestion completes through deterministic extraction with zero assist calls.
- The gitignored workspace `.env` was updated at the founder's request with the same alias, base
  URL, and both enabled flags. Validation printed only configuration presence/booleans: both flags
  are `1`, the key is populated, and the alias matches. No secret value entered logs or history.
- The W1 launch recipe now includes `CLUE_DESIGN_API_BASE_URL` on the platform process and the two
  ingestion flags plus `OPENROUTER_API_KEY` on the design process.

## Production wiring defect closed

Asset description already selected `OpenRouterDescriber` from its flag and skipped work without a
key. PDF ingestion did not: `OpenRouterPdfVision` existed but no production caller constructed it,
so flipping only the env flag would have been inert. `resolve_pdf_vision()` now owns that selection
and `_default_extract_pdf` threads the resolved assist into deterministic PDF extraction. The key
gate happens before page rasterization, avoiding useless image work when the gateway cannot run.

No engine/Rust sources changed; no WASM/helper rebuild was required.

## Verification

- Focused ingestion/config matrix: 43 passed, 2 expected helper-gated skips across deployment
  config, real PDF extraction, and asset description tests. Final deployment-config rerun: 5/5.
- Local `.env`: vision on, description on, base URL present, populated design key equals the
  populated platform key; values were never printed.
- Frontend full gate: 609/609 tests, design-system token build, ESLint, TypeScript, and Next.js
  production build all passed.
- Root static gates passed: ruff format (1,579 files), ruff lint, mypy (726 source files), and all
  26 import-linter contracts.
- Root pytest completed: 2,816 passed, 2,414 skipped, 5 failed. Three pilot budget-control tests
  failed only against the stale shared dev database because `core.industry` had a conflicting
  historical definition; all three passed after migrating a fresh isolated `clue_slice6_gate_20260819`
  database on port 55170. That scratch database was dropped immediately after verification.
- The other two root failures are deterministic pre-existing stale assertions, untouched by this
  slice (`git diff fe5370b7 -- <their files>` is empty):
  - `test_scripted_o3_conversations_cover_the_non_linear_gate` requests
    `skill:account-deep-steering@v4`, which the current Head-of-ABM v36 no longer discloses.
  - `test_discovery_configuration_is_the_only_head_after_the_explicit_gate_merge` expects Alembic
    head `064ad0f43519`; the integrated Part-III/platform branch correctly has merge head
    `a1c5b9842f0e`.

## Series close-out

Slices 0–6 now form the complete founder-ratified onboarding path: the Brand-context page is live,
first-time setup enqueues one fail-soft ingestion, checklist status is honest, manual re-extract and
approval are gated, approved kits stamp only newly born documents, editor theme tokens round-trip,
and deployment launches enable the two OpenRouter-assisted enrichment passes. Existing documents
remain untouched, multi-brand implicit theming fails closed, failed ingestion is manual-rescue only,
and the founder owns merge/push of this completed local branch.
