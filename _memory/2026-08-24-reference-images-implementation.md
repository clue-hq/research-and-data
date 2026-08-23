# 2026-08-24 — reference images implementation

## Contract

- Reference images are enabled only for an open scene-design leg in the platform composer.
- The current hard cap is four images per turn. A fifth is refused in the UI and by API admission.
- Accepted types are PNG, JPEG, WebP, and SVG. Generic `attachment_refs` remains disabled.
- Submitted refs are immutable ordered `design_asset` context refs; the scene envelope derives
  `request.reference_asset_ids` from those durable refs.

## Implementation

- Added upload/ready/failed/removable composer states through the existing design BFF `POST
  /assets` path and snapshot refs before the first submission await.
- Added workspace, open-leg, scene-kind, ready-state, MIME, SHA-256, and durable-byte validation.
- Added the `design_asset` context-ref migration and read-time filename/thumbnail presentation.
- Fixed the design worker bridge so a missing by-value manifest resolves frozen platform asset ids
  instead of silently treating the turn as having no references.
- Empty prompt turns remain invalid unless at least one typed design asset ref is present.

## Verification

- Browser tested an existing Insight Health scene artifact on the authenticated local stack.
- One through four uploads reached ready state; at four the attachment control was disabled. After
  removing three, one reference was submitted and the composer cleared only after HTTP 202.
- Accepted turn: `8291c75e-29c0-5768-835d-75c374e12602`; durable receipt ordinal 0 is
  `design_asset` / `asset_649eb483e637`. The global fleet worker was not started because other
  queued turns exist in the shared dev database; envelope and conditioning provenance are covered
  by isolated worker/runtime tests.
- Frontend: 2,012 tests pass; design-system build, lint (two pre-existing warnings), and production
  Next build pass.
- Backend: reference/chat tests pass (18 passed, 6 DB-gated skipped); scene-turn persistence suite
  passes; changed root Python files pass Ruff; Alembic reports one head (`db145059253b`).

## Separate render-fidelity regression

- Browser inspection of the user-provided artifact shows a truthful missing-Sohne warning, but the
  canvas has severe text overlap after the deterministic Inter fallback. The fallback geometry was
  not remeasured/reflowed correctly, so this render is not acceptable evidence that feature 1 is
  closed. The warning is also visually too intrusive. Keep this separate from reference-image
  admission and address it as a render-fidelity follow-up.
