# Inventory and select a supported motion route

Read this for a source animation/video/canvas region or an interaction that may depend on unavailable runtime code.

## Evidence record

Use the source fragment id/version, source URL and capture time when available. Pair `inspect_cloned_section(fragment_id)` with `view("cloned_section:<id>")`; respect truncation. Available source snapshots may carry motion metadata, but there is no invented `get_motion_inventory` tool. If metadata is not exposed in this turn, name the missing evidence and proceed only with the source and tools actually available.

For each moving region record:

| Evidence | What it establishes | What remains to inspect |
|---|---|---|
| CSS keyframe/transition definitions | A source definition exists | Matching element, computed properties, trigger/state, duration/delay/easing/repeat, transforms/origin, scoped keyframe reference, resulting visible change |
| Saved video/poster bytes and references | The listed dependencies were captured | MIME/decoding, selected source, poster timing, controls/autoplay/mute/loop/inline behavior, browser failures and fallback |
| Canvas tag or count | A canvas element exists | Whether pixels were drawn, by what supported mechanism, source behavior; it does not prove WebGL or recovered program |
| Source screenshot | One appearance at one capture state | Elapsed time, scroll/sticky position, active tab/slide, hover/focus, loaded/lazy media and any transient overlays |
| Script count or framework markers | Source code dependencies existed | Source scripts are not replayable in fragments; markers do not provide an executable React application |

`inspect_cloned_section` also returns `behavior_evidence` when the current registry
provides it. This is a bounded inspection of the sanitized HTML, not a source
interaction recording. `controller_not_retained` means stateful control markers
survived while the source JavaScript did not. The control labels, hidden-state
candidates and captured asset digests help locate the work; they do not establish
which control owns which image, timing, computed visibility, or a playback pass.
`not_assessed` is not a clean behavior verdict. Continue source inspection when
the observations are truncated.

Treat a product switcher as one linked component: selecting each card must change
its associated product view and active state. Four captured pictures with three
at `opacity-0`, a frozen progress bar, and clickable-looking cards do not provide
that behavior. All panels must remain reachable by keyboard and on a phone.
Do not report this as completed with a harmless warning merely because the first
frame looks correct. Reconstruct a supported interaction or present the material
as visibly static, ordered content without dead controls.

The capture metadata lists keyframes, video/poster URLs, missing media and canvas count, with `canvas_runtime_recovered=false` and `source_scripts_replayable=false`. Definitions may be unused; media may have a missing alternate source even when one file exists. Source coverage is not playback coverage. Never rename a canvas observation to “WebGL recovered.”

Describe the behavior's purpose: reveal product detail, step through a story, compare panels, communicate flow, or decorate. Identify the readable state when motion does not run. Distinguish the brand's authored behavior from support/consent overlays or source loading states.

## Reconstruction ladder

1. **Supported source reuse.** Preserve existing HTML/CSS/media dependencies and source timing where the fragment lane actually supports them. CSS scoping namespaces keyframes; it does not restore script-controlled classes, canvas drawing, scroll timelines or event handlers. Raw sanitization strips scripts, handlers and SVG SMIL. Confirm the retained output behaves; do not infer it from the source stylesheet.
2. **Supported equivalent.** Prefer the typed platform component that serves the same purpose: dialog, accordion, marquee, nav menu, carousel, tabs. Inspect existing source and `create-website` contracts before authoring. A manual carousel can preserve access when autoplay is unavailable; an accordion or ordered panels can preserve a multi-step story. Keep the source media, hierarchy, proportions and brand treatment where appropriate. State that the interaction changed.
3. **Governed custom component, when lower rungs fail.** Load `custom-components`. Its versioned write → compile → explicit placement path supports React, selected Visx, `motion/react`, `gsap`, and `@gsap/react`. It can author an independent reconstruction of a verified behavior. Reuse approved components where available; do not paste a third-party bundle, invent endpoints/imports, or call a copied script “captured fidelity.” Essential content must render in the server first frame; clean up listeners/effects and implement reduced motion. Compilation, successful immutable artifact and explicit placement are necessary, not proof of visual or behavioral correctness. **Check asset portability first:** the current custom iframe permits image/media `data:`/`blob:` and font `data:` sources only. It has no automatic bridge from registered `/asset-store/<digest>` URLs or outer-page `@font-face` rules into that iframe. Theme font names alone do not load the font. Do not move a media-heavy source section into TSX expecting those URLs/fonts to work, invent a loading tool, or weaken CSP. Prefer the typed tabs/carousel route when it can retain the registered media, and report the specific portable-media/font gap when exact custom composition is required.
4. **Compact static fallback.** If supported reconstruction is unavailable, preserve the story in visible ordered content, an authentic still/poster if available, or a source-grounded static composition. Remove artificial scroll height, empty canvas boxes, inaccessible hidden content and inactive control affordances. Identify what motion was lost and whether it was essential to the brief. A fallback may be usable while exact-motion fidelity remains unmet.

The first two routes may be small repairs to an existing fragment. Canonical repairs and campaign variants have different lineage intent; apply `repair-cloned-sections` before mutation, preserve human edits, and report the chosen route. This skill grants no new source-write, release or runtime permission.

## Video and reduced-motion boundaries

Reuse captured video in a supported source fragment only when its actual video/source/poster dependencies are present and admissible. The typed image action does not import or generate video. Do not disguise a video id as an image or invent a `play_video` tool. A failed fallback URL remains a custody/coverage defect; use the governed source-repair path, never guess another original or weaken the gate.

Preserve meaningful source controls and an accessible route to content. Do not introduce sound autoplay. Where motion is decorative, a visible poster/static state is a suitable reduced-motion target; where video communicates essential information, keep controls and an equivalent readable explanation. Verify the chosen implementation. The platform's reduced-motion CSS is not evidence that video or custom JavaScript timers stop, and source animation disabling can leave a transform or opacity at the wrong frame.

A missing standard sandbox/compiler/browser is infrastructure failure. Report it and retain honest fallback/unverified status; do not disable the requirement, conceal a compile failure, or make cosmetic revisions just to force retries.
