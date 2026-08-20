# 2026-08-20 — Phase AD2 COMPLETE: the read path is whole — a real ad renders, selects, hydrates, lists and zooms in the platform shell

Branch `integration/frontend-design-part-iv-v4`, commits `7aff35b4..d102c1f8` (+ this note).
Plan: `docs/superpowers/plans/2026-08-20-ad-editor-integration-execution-plan.md`. Ledger:
`.superpowers/sdd/2026-08-20-ad-editor-integration-execution-plan/progress.md`.
Predecessor record: `_memory/2026-08-20-ad1-close-out.md` (the scene-engine substrate).

## What AD2 shipped

| Task | Commit(s) | What landed |
|---|---|---|
| AD2.1 | `7aff35b4` | The gallery feed serves scene documents. `design_leg_wiring.project_design_documents` drops `WHERE d.doc_kind = 'web'` and carries `doc_kind`; `chat/router.py` maps it to the wire's `kind` (`"web"` / `"ad"`). Closes audit finding **F1** — the rail was structurally unable to reach an ad. Failing-first proven on both sides. |
| AD2.2 | `05183534` | The demo document: `doc_ad22linkedinsquare00000000001` — a plausible LinkedIn square ad with all 10 inventory node kinds (frame / auto_layout / 2× text / image / rect / ellipse / group / line) plus a token fill and a linear gradient, written **through the engine** (`POST /documents`, so `validate_scene` produced the bytes) with a real hero asset. Harvested into typed `Scene` fixtures. Idempotent seeder `scripts/seed_ad_document.py`. |
| AD2.3 | `4f2c5574`, `3961d9fd` | **The payoff.** The CanvasKit scene canvas mounts read-only inside the dummy's artboard card — real wasm engine, real skia text measurement, asset bytes through the AD1.7 headerless passthrough. Ruling 17 fixed the fit margin (128 → 0) so the page fills the card edge-to-edge. |
| AD2.4 | `2b22ae89` | `scene-hydrate.ts` — the selection-routing + value-hydration adapter (kind → schema; node → inspector state), 46 fixture-backed tests. Ruling 14 amended, Ruling 18 added. |
| AD2.5 | `d7953943` | `scene-selection.ts` — pointer-down → engine `hitTest` → §5 nearest-representable-ancestor resolution. Selection is **state only** (Gate G-A open): readable as `data-scene-selected-node`. |
| AD2.6 | `c7a6f3a3` | `scene-layers.ts` — the real layer tree in the dummy's Layers section: depth, kind→icon, expand/collapse, selectable vs not, shift/⌘ accumulation. Markup parity proven (the fixture branches are byte-untouched). |
| AD2.7 | `cde3d94e` | `use-scene-editing-session.ts` — one session, both mounts (artifact route + chats route). Closes **F2** (the artifact route now docks the ad inspector) and **F3** (the `/web/theme` 409 is gone: `enabled?: boolean` on the web session, not a conditional hook). |
| AD2.8 | `d102c1f8` | The header zoom menu drives the real viewport. `sceneViewportModel` keeps *applied* (the exact contain-fit) and *displayed* (the nearest of 29 offered steps) apart, so fit-on-open never regresses Ruling 17 while the label stays honest. |
| AD2.9 | this note | Exit audit — the full walk on both routes, root `make check`, this record. One trivially-safe fix (below). |

End state: **1386 frontend tests** (1274 at AD1 close → +112), lint 0 errors / 3 pre-existing
warnings, production build green. Root `make check` = ruff clean (1582 files), mypy clean (726
files), import-linter **26 kept / 0 broken**, pytest **5 failed / 2816 passed** — exactly the
documented pre-existing reds (3× `test_pilot_budget_controls`, 1× `test_unified_agent_gate_migration`,
1× `test_o3_account_deep_behavior`), the same set AD0.5 and AD1.8 recorded.

Backend touch across the whole phase (`git diff --name-only 9253001c..HEAD`, non-frontend):
`platform/api/clue_api/design_leg_wiring.py`, `platform/api/clue_api/chat/router.py`,
`tests/api/test_design_artifact_feed_db.py`, and the new dev seeder `scripts/seed_ad_document.py`.
Nothing else in the backend moved.

## What a user can now do

Open a project, see the ad in the gallery rail beside the websites, click it, and watch the **real**
document render inside the artboard card at contain-fit, edge to edge. Press **Edit**: the inspector
docks and shows that document's own values. Click anything on the canvas — headline, hero image,
accent bar, the proof dot, inside the group, the background — and the right node is selected and the
right schema appears. The Layers panel is the document's real tree: rows select, parents expand and
collapse, shift-click accumulates. The zoom menu shows the real fit on open and moves the real
viewport when you pick a step; reopening returns to fit. A website artifact behaves exactly as it did
before. Nothing writes yet — that is AD3.

## The rulings that fired

- **Ruling 14 (amended at AD2.4)** — `hydrateSceneInspectorState` returns
  `Partial<InspectorPresentationState> & SceneInspectorExtraState`. The extra type widened by six
  (`grow`, `alignX`, `alignY`, `title`, `customWidth`, `customHeight`) because `alignX`/`alignY`
  **cannot** reuse `horizontalAlignment`/`verticalAlignment` — those are the text toggles
  (left|center|right|justify / top|middle|bottom); §1.4's Align selects are
  Start|Center|End|Space between|Stretch, a different vocabulary *and* a different type. The
  chat-shell controller stayed untouched; AD4.B decides the fields' final home.
- **Ruling 15** — AD2.1's browser check deferred into AD2.3's stack session (the only running API
  served another workspace's code). Discharged: AD2.3 asserted the ad card in the rail first, and
  this audit re-asserted it.
- **Ruling 16 (founder gate G-H, recorded not coded)** — `normalizeGalleryArtifact`'s
  `defaultCollateralType` falls through to `"linkedin-ad"` for `type: "canvas"`, so a real ad card
  labels **"LinkedIn ad"** and groups under Ads regardless of channel. A fabricated claim about a
  real document — the class `defaultAccount()` refuses two functions above. No neutral member exists
  in `GalleryCollateralType`, so the honest fix touches designed card UI = founder territory.
- **Ruling 17** — fit margin 128 → 0. The dummy's `.imageCanvas` card **is** the artboard (founder:
  "the canvas fills the existing div"); the upstream 128 is the standalone editor's infinite-workspace
  margin and left the ad at ~60% of the card. Parity restoration, not restyling.
- **Ruling 18** — a fourth export `hydrateSceneCanvasState(scene, pageId)`. A plan interface defect:
  §1.1's canvas rows belong to an EMPTY selection with no Node, so they cannot ride the `(node, scene)`
  signature. The web lane got this free because its canvas selection IS the page-root node; the
  scene lane's is not.

## Open gates

- **G-A — BLOCKING the demo's one visible gap.** The selection-outline visual is unruled, so AD2.5
  shipped selection as **state only**: clicking a node changes `data-scene-selected-node` and swaps
  the inspector, but **nothing is drawn on the canvas**. Stated plainly rather than worked around —
  no outline was invented. The G-A sheet also owns: the canvas chrome (§1.1 name label + W×H chip,
  no dummy CSS exists), the layer-row fill swatch (computed at AD2.6, no slot to render it), and
  handles. Founder decision (AD2.5 finding 4): keep `data-scene-selected-node` *after* G-A rather
  than replacing it with chrome.
- **G-H** — the fabricated "LinkedIn ad" chip (Ruling 16). **Second instance found by this audit:**
  `project-gallery.ts::defaultSize` returns a hardcoded `1080 × 1080` for every non-website artifact,
  so the 1200×1200 demo ad advertises a size it does not have. Same class, same owner, same fix
  shape (the feed carries no page size; supplying one is backend + card UI).
- **G-C / G-D / G-F** — still queued. G-D owns the loading/error frame copy that AD2.3 deferred.

## Deferred minors, with owners

| Item | Owner |
|---|---|
| The four static ad schemas — **auto-layout, rectangle, ellipse, group** — read no controller state at all; their section values are literals in `ad-dummy-inspectors.tsx`. Verified against the demo doc: rect shows Fill *None* / radius *0* / X 0 Y 0 W 100 H 100 / stroke 1 where the document says a 3-stop linear gradient / radius 5 / (72, 368) / 320×10 / no stroke. Auto-layout shows Gap 0, padding 0/0/0/0, Align X *Space between* where the document says gap 32, padding 40/44/40/44, `align_x: start` (its Direction/Wrap/Align Y literals happen to *coincide* with the document — coincidence, not binding). | **AD4.B** |
| A **token** fill leaves the text-color swatch on the dummy `#00F59B`. Live on the demo ad: `text_headline`'s fill is `$text.inverse`, the swatch renders bright green. | **AD4.B** |
| The image schema's preview thumbnail is the static `/icons/chat-shell/inspector/web/image-preview.png`, not the node's asset (its radii and Mode *are* hydrated). | **AD4.B** |
| 12 hydrated fields still have no state slot (Ruling 14's amended six among them). | **AD4.B** |
| Position X/Y hydrate from `transform`, never a computed box (`computed` is `null` on every node across the dev DB) — so an auto-laid-out child reads (0, 0). Honest, but not where the user sees it. | **AD4.B / AD3** |
| Two AD2.4 rows have no fixture coverage — token `Dimension`, non-empty stroke on a TEXT node — documented in-code, deliberately **not** hand-written. | AD4.B |
| `use-scene-document.ts` hook (eslint bars components from importing `data/**`; same split the web lane uses). Accepted deviation. | AD2.7 absorbed it |
| The brand kit is fetched **twice** per ad load (~103 KB each) on both routes. Pre-existing shape, not an AD2 regression; cheap to dedupe. | AD3 / AD5 |
| Compound-only active classes (`.alignmentControl .alignmentActive`, `.inspectorSegmentedControl .inspectorSegmentActive`) — reparenting silently drops the styling. Re-pointed to AD2.6 at AD0 close; layer rows were not reparented, so it stands unexercised. | AD4.B |
| Lint warnings: `libraryFonts.test.ts:167` unused `input`; `canvasOperations.ts` `snapPosition`/`snapExtent` unused (upstream dead code, not ours to cut). | AD5 |

## What AD3 (the write path) needs to know

- **`documentVersion` is deliberately `null`.** `use-scene-editing-session.ts:337-345` stamps the
  W3.1 addressing triple with `documentVersion: null` — the null contract means "not addressable",
  which is exactly what a half-wired write path must be. **AD3 arms it.** Until it does, nothing in
  the ad lane can mutate a document even by accident.
- **`writes` is a live stub.** `SceneManualEdits` is shaped after the website lane's `WebManualEdits`
  so the eventual controller drops straight in; today the session hands out `NO_EDITS` (inert,
  `busy: false`, `applyEdits` a no-op). The interface, the error precedence and the reload nonce
  (`onWriteReload`, which quietly refetches with no keyed remount) already exist.
- **`editQueue` is extracted and injectable** — `engine/scene/editQueue.ts` came over at AD1.5 on the
  `DesignEditorConfig` seam with a `fetchImpl` (Ruling 12: defaults are the receiver-safe
  `defaultDesignFetch`, never a bare `fetch`). Same for `structuredEdits` and `documentStore`.
- **One fetch, one engine, one scene.** The session receives the scene from the canvas via
  `onSceneChange` rather than fetching a second copy — the scene the inspector reads IS the scene
  `hitTest` answers against. A write path that refetches independently would break that invariant.
- **Selection is multi.** The layers panel already accumulates with shift/⌘ and the inspector follows
  the *anchor*. A write that acts on "the selection" must decide anchor-only vs all-selected.
- **The four static schemas own no state**, so an edit typed into a rectangle's X field today changes
  a literal's neighbour, not the document. AD4.B binds them; AD3 should not assume they are wired.
- **Stack/login traps** (unchanged from AD0/AD2.3): colombo API `:8032`, frontend `:3033`, design API
  `:8010`. A session expiry lands on `/sign-in?reason=session_expired`; if Clerk is also signed out,
  re-run the email flow (`onboarding+clerk_test_20260814@example.com` / `pass@123` / code `424242`)
  → workspace `ws_8040294627e146ae93f753ec0d3e1726`. **Never create a `.env` at the repo root.**
  `?surface=ad&edit=1` typed directly into the chats route collapses to the conversation **by design**
  (no artifact in session yet, documented in `chat-surface.tsx:128`) — reach the ad by clicking its
  gallery card, then press **Edit**.
- **A long-running Next 16 dev server can serve a stale route tree** (both dynamic routes 404 at the
  routing layer with no compile error) — restart fixes it instantly.

## The one fix this audit made

`make check` was **red at the lint stage** before any test ran: `scripts/seed_ad_document.py` (added
at AD2.2) failed `ruff format --check`. AD2.2–AD2.8 ran the frontend gate only, so it went unseen for
seven tasks. Fixed here — `ruff format` applied, plus one SQL literal split to stay under the 100-col
E501 limit that the reformat pushed past. Cosmetic, dev-seeder only, zero runtime paths. **Lesson for
AD3: run root `make check`, not just the frontend gate, on any task that touches a Python file.**
