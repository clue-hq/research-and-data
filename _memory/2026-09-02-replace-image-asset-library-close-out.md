# 2026-09-02 — Replace Image: upload / workspace asset-library picker + Brand context uploads — close-out

Branch `design/replace-image-asset-library` (off `design/scene-ad-clipboard`), nashville worktree.
Spec `docs/superpowers/specs/archive/2026-09-02-replace-image-asset-library-design.md`; plan
`docs/superpowers/plans/2026-09-02-replace-image-asset-library.md` (8 tasks, all ticked).
Process: subagent-driven development, Opus-only implementers; every review, verification and ruling
by the orchestrator (founder ruling 2026-09-02). All commits local; nothing pushed.

## What shipped (commits in order)

- `734c4c64f` T1 `listImageAssets` — registry read (3 image kinds, paged, archived hidden).
- `5c8cf3db5` T2 pure `composeAssetLibrary` / `filterAssetLibrary` / `kitLibraryEntries` /
  `registryCategory` — kit pinned first, registry after (server order), dedupe kit-wins, categories.
- `ddc9b165d` T3 **bug fix**: every replace-image refusal now speaks (`NOT_ACCEPTING_EDITS`,
  `NOT_AN_IMAGE_TARGET`, `SELECTION_MOVED`, `SAME_IMAGE_IN_USE`); file dialog stops offering GIF
  (server sniff accepts PNG/JPEG/WebP/SVG only — verified at `main.py:7948`).
- `94c1d8a79` T4 `useSceneAssetLibrary` — fetch on open, `pick` = the upload path's own
  `upsert_asset` + `place_asset_in_node` batch through `applyOps` (one undo frame); session exposes
  `assetLibrary`; kit entries derived from the existing brand-kit fetch.
- `5552758d9` T5 chooser (founder option A): the "Replace image" pill is a Base UI `Menu` trigger
  with a caret and two rows (Upload from computer / Choose from asset library), 1.1px icons, no
  format list; dummy path byte-preserved; `assetLibrary` threaded like `imageAi`.
- `206c0e4c6` + `e0960c4e7` + `267961787` + `995cfadbe` T6 `AssetLibraryPanel` (founder option 2):
  anchored beside the inspector over the stage via an `overlay` pass-through on `ArtifactStage`
  (both surfaces); Brand kit / Workspace sections, "Brand" + "In use" badges, search + category
  chip, keyboard grid nav, footer "Upload from computer"; closes on ✕/Esc/outside click.
  Fix rounds: (1) ignore the panel's own portalled chip/menu surfaces for outside-click and Esc;
  (2) z-index 60 above the canvas banner layers (40/41) + filters reset on open; (3) toolbar gives
  the search box its room.
- `be30ffab0` T7 Brand context Assets = kit ∪ workspace registry, "Uploads" category, "Brand"
  badge, `origin` on `BrandAsset`, `DesignAssetListRecordSchema` for the bare list records.

## Gates (final tree)

- `npm run lint`: 0 errors (2 pre-existing warnings in `canvasOperations.ts`, untouched).
- `npm test`: 2489 tests, 2488 pass, 0 fail, 1 skip (pre-existing jsdom skip).
- `npm run design-system:build` and `npm run build`: clean (route table emitted).

## Live walk (nashville stack, Apollo account, Cursor LinkedIn ad) — all verified

Chooser is a real menu (aria-haspopup=menu, caret, exactly two rows, no format text); panel opens
beside the inspector with 70–71 tiles, 34 pinned "Brand" first, "In use" on the current asset;
workspace pick and brand pick each applied (asset id + version changed, "In use" moved); ⌘Z
stepped back exactly one write per press; in-use click → "That's the image already in use.";
search filtered; category chip → Uploads (27) with the panel staying open; Esc/✕ close; footer
upload uploaded, applied and appeared in the list; Brand context Filter menu shows "Uploads" and
lists the same 27 uploads with kit items badged "Brand".

## Rulings made by the orchestrator (all ledgered during the run)

- Plan defect fixed by the implementer and ratified: `GET /brand-kits` returns a bare list (the
  brief's stub body was wrong). Fixture parsed through `BrandKitDetailSchema` in the test.
- Lint-forced deviations ratified: `isOpen` derived from the armed document (closes on artifact
  switch by construction); kit entries derived rather than reset in an effect.
- `InspectorSelect` takes `readonly string[]` options → label-keyed chip with lookups (no
  primitive change). `shouldCloseOnPointer` typing widened for `HTMLElement.contains`.
- The chooser's `Menu.Positioner` reuses `.inspectorSelectPositioner` (z-index 1000).
- Pre-existing tests that encoded silent refusals were flipped to the sentences (the silence was
  the reported bug); one test title renamed to match.
- Filters reset on `open()` is React state plumbing — documented, not fake-tested.
- Brand context name/description edits are local drafts already; no read-only gating needed
  (spec §4.4 note moot).

## Residuals (deferred, none load-bearing)

- Armed-before-target refusal ORDER is protected by a comment, not a discriminating test.
- The `accept` attribute change is unpinned by a test (presentation attribute).
- Brand context reads ONE 200-item page per image kind (explicit plan choice; the editor picker
  pages further) — >200 uploads of one kind truncate there.
- The Brand-kit section can be long (the Apollo kit carries 34 logos/icons incl. spacers) — the
  panel scrolls; a "collapse Brand kit" affordance is a possible follow-up, not a defect.

## Nashville workspace note

Stack recipe and the blob-store clone gap: `_memory/2026-09-01-nashville-workspace-setup.md`. The
Cursor ad now carries walk artifacts (its wash was replaced several times; undo history intact).
