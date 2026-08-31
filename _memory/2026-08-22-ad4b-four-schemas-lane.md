# 2026-08-22 — AD4.B: the four new schemas + plain Frame bound (Lane B close-out)

Branch `integration/frontend-design-part-iv-v4`, commits `d3a886f0..dbc7f7a0` (10 commits) on the AD4.R base
`c22f3ef9` (all local, nothing pushed). Plan: Task AD4.B in
`docs/superpowers/plans/2026-08-20-ad-editor-integration-execution-plan.md`; contract §1.4/§1.5/
§1.6 of `docs/specs/ad-editor-integration/ad-inspector-mapping-contract.md`. Regime: fresh Opus
implementer per step under mandatory base attestation (HEAD hash + marker files + exact test
count, the AD4.R-incident protocol — zero anomalies this lane), Opus review per diff, scoped
re-review per fix round, controller-driven browser proofs against the live stack verified against
the design API's document JSON, whole-lane final review (verdict: Approved for founder
presentation), one final fix wave. Ledger:
`.superpowers/sdd/2026-08-20-ad-editor-integration-execution-plan/progress.md` — KEPT (the
workspace serves the whole AD execution plan; lanes C/D/E resume it); this note + git history are
the durable record.

## What shipped (per step; suite 1754 → 1835)

1. **S1 Layout** (`d3a886f0`): schema binding threaded into `AdDummyInspector` (controller with
   `liveHydration`, `inert = locked || inspectorDisabled` G-H treatment); ten state keys promoted
   from `SceneInspectorExtraState` into `InspectorPresentationState` (settles AD4.R ruling 14's
   "final home"; extra-state keeps only `title`/`valignDisabled`); X/Y/W/H/Rotate/Opacity bound;
   Width/Height mode selects (Fixed/Hug/Fill, fill weight pinned 1 per OQ-2, `hug` with no value
   key); Fixed inputs visible only in Fixed mode; new `width`/`height`/`opacity`/mode cases in
   `sceneChangeToOperation` (opacity %→0–1 clamped, OQ-3); W/H semantics verified against the
   MVP's `ObjectSection::emitExtent`. One authorized pin rewrite (the S1 lock literal) — strict
   superset, now pins the live lock.
2. **S2 Auto Layout** (`bb73d43f` + fix `9ff1b158`): direction/wrap (kind-guarded — the engine
   builder throws on non-auto-layout), gap/grow/padding (tuple [t,r,b,l], one slot per commit),
   alignX/alignY (five anchors, one axis per commit, other carried from the node); hydrate went
   UNCONDITIONAL for the auto-layout schema's layout keys incl. align anchors (the fix round —
   conditional anchors were the frozen-at-seed class AD4.R forbids).
3. **S3 Shape/Stroke** (`91c89426` move + `6b4969df` + fix `352aec45`): the §1.6 color machinery
   moved out of `image-inspector.tsx` into shared `inspector-color-row.ts` (byte-verified pure
   move; import-cycle-forced); node-addressed `backgroundColor`/`tokenBackgroundColor` cases
   (gradient/multi-fill-guarded, A9 mint, no-change guard); five radius inputs bound to the
   existing rows; stroke color/width bound; group renders neither section (OQ-6); fixture-path
   radius defaults restated (the fix round).
4. **S4 Arrange** (`1ed3b5c3` + fixes `f3d04d5b`, `5155ff29`): pure `scene-arrange.ts`
   (enablement + z-order index math; move_node proven REMOVE-THEN-INSERT by a real-wasm probe now
   permanent in the suite); session hook `use-scene-arrange.ts` (align/distribute/z-order as ONE
   `applyOps` each; group/ungroup on the undo path's structured-edit transport via the
   `runDocumentStep` generalization inside `use-scene-manual-edits.ts`); ⌘G/⇧⌘G (+ final-wave
   ⌘]/⌘[/⌥⌘]/⌥⌘[); both consumers wired (the text schema's previously DEAD Arrange buttons and
   the dummy schemas'); fix 1: root-frame ungroup excluded (⇧⌘G would have dissolved the
   artboard) + the authored 0.45 disabled treatment on the button grids; fix 2 (Ruling L19, found
   by the live browser proof): align/distribute additionally gate on per-member commit
   reachability (`isNodePinned || isNodeFreehand`) because the ENGINE's `canAlignNodes` is wider
   than its own `alignDistributeCommitOperation` — enabled buttons wrote zero ops for plain-frame
   children (dishonest enablement, §1.5).
5. **Final wave**: §1.5's bracket z-order shortcuts + the authorized source-text mirror guard
   over `ad-dummy-inspectors.tsx`/`inspector-color-row.ts` (zero useState/useRef — the AD4.R
   regression net the lane's ~40 rows lacked).

## Browser proofs (seeded `doc_ad22linkedinsquare00000000001`, both value-restore audits
node-identical; every commit one-intent-one-version, verified against `/documents/{id}/history`)

Highlights: hydration exact per schema (incl. the real corner 5s the static scaffolding faked as
0s); mid-typing and no-op re-types write nothing; `hug` lands with NO value key in the live wire;
Fixed-only input visibility; group shows Fill/weightless (OQ-2/OQ-6); managed-geometry X refused
with panel snap-back; locked = native disabled + 0.45 + focus refusal; gradient fill hex REFUSED
with zero versions; token pick wrote `{kind:"token"}` and hex detached it (§1.6 informed trade);
z-order round-trip exact in the children array; ⌘G one envelope; root-frame ⇧⌘G refused; locked
arrange buttons dim; post-L19 align/distribute honestly OFF on plain-frame children. UNCOVERED in
browser: plain Frame (no non-root frame in the seed — routing + suppression test-pinned only);
the ellipse restore is `#ea2261` vs seed `#EA2261` (hex input lowercases; color-identical).

## Environment / parallel-session notes

- A PARALLEL session (or the user) exercised on-canvas drag/resize/lock on the SAME seeded
  document throughout (fractional-coord transforms + envelope-less undo/redo version bumps in
  history; all net-reverted). Attribution each time via the `/history` endpoint; my writes each
  produced exactly one envelope. Anyone proofing against this doc should expect interleaving.
- The browse daemon restarted mid-lane (session lost; `open-ad-editor.sh` re-auth works). The
  `?surface=ad&edit=1` URL collapses on reload — re-enter via gallery card → Edit.
- The collapsed-section trap bit twice more: a freshly mounted schema's Layout/Stroke/Arrange
  sections start COLLAPSED (`DEFAULT_OPEN_SECTIONS`), inputs stay in DOM but unfocusable, and a
  Playwright fill on one leaks keystrokes into the focused field. Expand before typing.
- Radix select triggers resist real clicks in headless (hit-test returns the section); the
  working recipe: dispatch `keydown ArrowDown` on the trigger, then walk options via
  `ArrowDown`/`Home` on `document.activeElement` and `Enter` (see the ledger's pick scripts).

## Founder-decision list (accumulated; none block the lane)

1. **Grow row writes a render-dead field**: engine `flex_grow` derives from
   `Dimension::Fill{weight}`; `AutoLayoutProps.grow` is read by nothing in layout.rs/skia — §1.4's
   Grow control duplicates the OQ-2-hidden fill-weight mechanism. Either the engine consumes
   `grow` or the row moves to §5-hidden.
2. **Engine align/distribute gate-vs-commit inconsistency** (upstream of L19): `canAlignNodes`
   admits plain-frame children whose commits are null — every other consumer inherits it; a canvas
   DRAG writes those same transforms fine. Product fix: tighten the engine gates or teach the
   commit a plain-frame branch. Consequence today: align/distribute honestly OFF for the seeded
   artboard's children — a visible capability loss.
3. **Group/Ungroup button row renders only on the group schema** (scaffolding preserved): a
   2-rect selection has working ⌘G but no visible button — render-the-row-when-enabled needs a
   founder placement ruling (dummy is presentation truth).
4. **⌘Z/⇧⌘Z/⌘G/⇧⌘G/brackets all bypass the mid-turn G-H gate** (keyboard class, exact ⌘Z parity;
   L18) — gate all or none, needs threadBusy → session plumbing.
5. **Token-vs-literal on gap/padding**: a numeric Gap commit preserves `gap_token`/`padding_token`
   (correct), but `brand.rs:3639-3646` shows a preserved `padding_token` overwrites all four slots
   at the next brand resolve — which wins at render needs an engine answer before Auto Layout
   ships to users.
6. **Sections ship collapsed** (Layout/Stroke/Arrange) per the panel-wide default — pre-existing
   policy, AD5.1 visual-parity item.
7. §1.5 "all schemas" vs §1.3's image-schema table (no Arrange section → image_hero not
   z-orderable from the panel); §1.5's bracket shortcuts now exist but the IMAGE schema has no
   Arrange either way.

## Deferred minors

All triaged OK-TO-DEFER by the final review; the full annotated list lives in the lane section of
the git-visible record (this note) and each carries its site comment where applicable. Notables:
write-half garbled-anchor passthrough (type-unrepresentable); auto-layout write guard stricter
than hydrate's (benign via OQ-1); two can't-fail-for-stated-reason assertions; one-render-stale
`depsRef` (worst case silent non-event); duplicate `AdSchemaBinding` type; per-render `initial`
literal defeats a memo; same-value select re-picks write same-value versions (pre-existing
class); `setRadiusAll` fixture-path NUMERIC divergence; width vs widthFixed rounding.

## For AD4.C/D/E and AD5.1

Bind on the AD4.R rules (parent plan's AD4 preamble); the dummy-schema mirror guard now fails any
reintroduction in these two files. AD5.1's contract walk: §1.5 bracket shortcuts are in; plain
Frame needs a seeded non-root frame to walk; the §5 grep-proof list unchanged by this lane.

## Final wave addendum (dbc7f7a0)

The bracket shortcuts match on `event.code` (⌥ rewrites `event.key` on macOS) — and the MVP
editor's own `keyboardArrangeAction` (editorKeyboard.ts:44-60) matches on `key`, so **the MVP's
⌥⌘]/⌥⌘[ can never fire** — a latent upstream bug found here, worth an MVP-side fix someday. Live
wiring evidence: one clean attributed ⌘] write (history seq189); the fuller keyboard walk was
confounded by headless Chromium's own Cmd+bracket history accelerators plus the artifact panel
being closed under the walk (suspected: the parallel session driving the same thread's
server-side surface state) — the definitive keyboard pass (incl. the recorded ⌘[-at-edge
browser-Back fall-through and code-first matching on QWERTZ-class layouts) is an **AD5.1
real-hardware residual**. The L20 mirror guard strips comments before counting (one legitimate
`useState` mention in prose) with per-file non-vacuity anchors, red-proved four ways.
Final gates: frontend 1835/1835 (0 skipped — the wasm probe runs), lint 0 errors, build clean;
root `make check` = exactly the five documented pre-existing reds. Document restored to baseline
(v206 audit; one sanctioned API move_node used for the last z-order restore after the panel
started closing under the walk — restoration, not proof).
