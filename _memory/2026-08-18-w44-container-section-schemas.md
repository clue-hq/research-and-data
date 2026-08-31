# W4.4 — container & section inspector schemas go live (lane A, trunk)

Branch `integration/frontend-design-part-iv-v2`. Commits `84d11eda`, `a7f1c9a6`, `a9b7e0ac`
(base `72ec72fb`). Spec: `docs/specs/website-editor-integration/web-inspector-mapping-contract.md`
rows 19/20/22/23, §2 R3, §4 (item 38).

## What is live now

- **Row 19** container/section Style tokens: both token buttons hydrate from the node
  (`tokenTextColor`/`tokenBackgroundColor`) and write through a theme-token popover built
  from `ColorControl`'s Theme-tab markup (ruling 17's pattern; row 19 says "same as 17").
  `InspectorTokenControl` gained optional `options` + `onTokenSelect`; without them it is
  the dummy button, byte-identical (measured: 432×34 at x=274 in both the untouched button
  schema and the new section schema).
- **Row 20** container Flex/Grid/Hide → `display` facet (block/inline-flex omitted per §6(5)).
  Goes through the facet so W4.9's visibility eye (same facet, `hidden`) composes.
- **Row 22** section Direction/Gap/Wrap → `direction`/`gap`/`flexWrap`. Gap snaps to the
  nearest `SPACING_STEPS` step via the shared `nearestSpacingStep`; new `GapControl` drafts
  locally and commits on blur/Enter (R3). Wrap is a BOOLEAN, so it is handled before
  `apply.ts`'s string coercion.
- **§2 deltas:** section Link-to absent (ruling 23; container keeps its own — containers do
  have links); padding 4 boxes → 2 axis boxes on both schemas.

## Decisions worth remembering

- **Kind guards follow the contract, not the facet's capability.** `tokenBackgroundColor` →
  container/section only (row 17's button joins with lane B); `layoutMode` → container only;
  `direction`/`gap`/`wrap` → section only (container-level direction/gap/wrap is §7 item 1,
  future work). A refused event is deliberate, not a bug.
- The pre-existing `tokenTextColor` case is still **unguarded by kind** (W3.2 owns it, and
  lanes B/C depend on it). The asymmetry is intentional for now — narrowing a shared case
  mid-fan-out would be a cross-lane change.
- The brief said to wire "the container/section views' Background `ColorControl`"; those
  views ship `TokenField`, not `ColorControl`. Resolved from the contract (rows 19 + 17):
  the token BUTTON gets the popover; no ColorControl was introduced.

## Fixture / document state

- `HARVESTED_PAGE_V33` added to `adapter/__fixtures__/web-nodes.ts` — a second wire-true
  harvest of `doc_31126145a0aa4753920629ae323a301b` at v33. The v2 snapshot stays because
  the W3.2 text tests assert against it.
- The hero section had no `anchor_id`; one `set_node_props` call added `"hero-anchor"`
  (document 32 → 33) so the §4 test runs on real bytes. Browser verification then walked the
  document to v44 (style/direction/gap/wrap/padding edits) — expect those classes, not the
  original ones, on the next harvest.

## Open observations (not fixed here)

- A section with no `flex-wrap` utility displays **Wrap = Yes** (the dummy default) although
  the rendered behavior is nowrap. Hydrate deliberately omits absent wrap (W2.2 decision,
  asserted by a test) while the padding case uses a truthful zero. Founder/W2.2 call.
- §5's "unknown kinds show Layout only" is not enforced in the UI (`layoutOnly` is only a
  data attribute), so an embed renders the container schema's Style/Alignment. The new kind
  guards make those writes refuse, so nothing wrong lands — but the UI still shows controls
  that do nothing for embeds.
- `GapControl`/`PaddingXYControls` drafts do not resync if the hydrated value changes without
  a remount (same accepted drift documented at the inspector's keyed remount in
  `editor-surface.tsx`).
