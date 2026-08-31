# Brand-kit onboarding — Slice 5 approved themes for new documents (2026-08-19)

Branch `feature/brandkit-onboarding-integration`. Local commits only; never pushed.

## Frozen creation contract

- Brand-kit resolution happens once, at document creation. Rendering never falls back to a
  workspace brand kit.
- An explicit `scene.theme.brand_kit` always wins, including when no approved workspace kit exists.
- With no explicit reference, a new web document or web template is stamped only when its
  workspace has exactly one platform brand and that brand has an approved kit version. Multi-brand
  workspaces fail closed because the create contract carries no `brand_id` selector.
- Resolution chooses the latest approved version. A newer draft does not shadow the approved head.
- Existing documents are never changed by later approval. Documents created before approval keep
  the platform default. Re-stamping old documents is future work and must be an explicit manual
  action.

## Creation-site inventory and implementation

- `subsystems/design/clue_design/documents.py::create_document` is the authoritative direct web
  document writer and now stamps at birth before persistence.
- `derive_document` converges through `create_document`, so derived web documents receive the same
  rule without a second implementation.
- `create_web_template` is a separate writer and applies the same helper.
- The current Gallery lane is a derived read/feed and adds no document writer.
- `subsystems/design/clue_design/brand.py::latest_approved_brand_kit_ref` owns the selection query.
  It returns only `{id, version}` for the latest approved kit and refuses ambiguous multi-brand
  workspace selection.
- The lumen API creation log now reports `has_brand_kit` from the stored document theme, including
  refs applied by the DAL rather than only explicit request refs.
- The frontend contract records the stamp-at-creation consequence and future manual-restamp
  boundary.

## Verification

- DAL DB suite: 6/6 focused tests passed, covering pre-approval creation, approval stamping,
  unchanged old documents, latest-approved selection despite a newer draft, explicit-ref
  precedence, templates, and multi-brand fail-closed behavior.
- Lumen API web-document suite: 9/9 passed, including a real approved-kit document-create and
  `/web/theme` token round trip.
- Root ruff, mypy (726 files), and import-linter (26 contracts) passed. The Rust release helper
  built successfully; no Rust source or WASM rebuild was required.
- A wider API run saw three fleet tests lose queue ownership to other APIs sharing Postgres :55040.
  Those exact tests passed against the isolated branch database :55170; this was environmental,
  not an assertion failure in Slice 5.

## Authenticated browser proof

Using the test login, the live journey completed: Re-extract disabled while running, the resulting
draft was approved, a new document was created, and the canonical platform artifact route opened in
editor mode. The W4 Theme color picker visibly listed the extracted client tokens: Primary
`#44483F`, Secondary `#D85A00`, Tertiary `#00F59B`, Dark `#1C2028`, Light `#FFFFFF`, and Subtle
`#EEF1F5`.

- Workspace: `ws_8040294627e146ae93f753ec0d3e1726`
- Project: `prj_79aa603b3c3853898045e3cfa414e136`
- Document: `doc_9e41dd48fd404c81a097713dcb6d090a`
- Stamped ref: `brand_kit_ing_a686842c43a044b0aa580caa152a053c`, version 4
- Evidence: `.context/evidence/brandkit-slice5/slice5-theme-picker.jpg`

The local proof intentionally kept the design BFF/render on isolated Postgres :55170. Because the
platform artifact resolver was running on :55040, the already-stamped document row was mirrored
there only to let the canonical shell route resolve; the theme response and editor render still
came from the isolated design API. All verification services were stopped and ports 8012, 8032,
and 3032 were confirmed clear.
