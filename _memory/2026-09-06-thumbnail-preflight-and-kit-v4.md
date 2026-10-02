# 2026-09-06 — Gallery thumbnails preflight before rendering; Apollo kit v4 approved

## Thumbnails (plan `docs/superpowers/plans/2026-09-06-thumbnail-preflight.md`, commit `3fe19ce6e`)
- Defect (pre-existing, route written 2026-08-31 before token-based documents existed): the scene branch
  of `GET /documents/{id}/thumbnail` exported the RAW stored scene — no brand kit, no layout — so every
  agent-authored ad (token fills, hug/fill sizes, `computed: null`) failed LUME0209 + LUME0205 on every
  node and, with `raise_on_error=False`, came back as a blank white 724×724 PNG with HTTP 200, cached per
  version. Documents with no token fills and stored geometry rendered, which is why some cards worked.
- Fix: the scene branch now chooses the document's effective brand (`choose_effective_brand` with a
  default `PreflightRequest`), its mode and fonts, runs `core.preflight_scene`, and renders the
  PREFLIGHTED scene. Best-effort (diagnostics logged as `document_thumbnail_preflight`, never refused)
  and read-only (nothing persisted). `except (CoreError, NotFoundError)` → 502 `thumbnail.export_failed`
  (`NotFoundError` is a `KeyError`, not a `CoreError`).
- Test: `seeded_token_scene_document` — a `fill×fill` rect with `surface.brand` token + hug text, all
  `computed: null`, kit attached; asserts a non-blank PNG, no magenta sentinel pixels, and the document
  unchanged. A FIXED-size token rect does NOT reproduce the blank (raw export paints the magenta
  LUME0213 sentinel instead) — the blank needs a layout-solved size. 28/28 thumbnail tests.
- Deployed to colombo (design API restarted); the 26 cached scene thumbnails of the Apollo workspace
  were deleted from `design_document_thumbnail` so the gallery regenerated: all 8 cards load with
  content (`/tmp/gallery-after-fix.png`). Larger alternative (re-solve geometry + resolve tokens on
  every write) deliberately not taken; the editor-writes-drop-geometry wrinkle stays open.

## Apollo kit v4 approved; v2 documents re-attached
- Plan 1's corrected type units lived in kit versions 3–4 as DRAFTS; a new document is born on the
  latest APPROVED kit, so every ad since inherited v2's headline line-height 4.5 (the Deel ad's huge
  leading). Founder asked why the fix was invisible → v4 approved via `POST /brand-kits/{id}/approval`
  and the four v2-pinned documents re-attached to v4 (`POST /documents/{id}/brand-kit`).
- Consequence: v4's headline letter-spacing (−0.01) is looser than v2's (−0.045); the Deel headline
  (fixed 493-wide box, `max_lines: 2`) now wraps to three lines and the cap cuts "happen." — the
  document needs a wider box / smaller size / no cap. Re-attaching that one document to v2 restores its
  old look if preferred.
- The line-height toolbar control does not exist yet: item G is still gated on three founder decisions.
