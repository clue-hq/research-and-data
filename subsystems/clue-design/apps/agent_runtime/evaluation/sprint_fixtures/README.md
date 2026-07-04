# Sprint fixtures — editor + imagery set (next sprints)

A small, **separate** fixture set (3 briefs) for the upcoming sprints, which focus on the
**editor** — the common human↔agent surface (see `.context/editing-research/MODA-EDITOR-PLAN.md`).
Kept out of the main `evaluation/fixture_prompts.json` (26) and
`evaluation/imagery_fixtures/briefs.json` (16) on purpose, so this set evolves independently
and the existing regression counts (`len(sidecar)==16`, 6/4/6) stay stable.

Each brief is dual-purpose:
- **imagery gate** — same `{artifact, expected_decision, role, risks}` schema the imagery
  judge reads via `merge_briefs()`; and
- **editor scenario** — an extra `editor` block (ignored by the imagery runner) that ties the
  fixture to specific editor-plan phases/mechanisms, so the same 3 designs drive the editor
  round-trip work (freehand vs managed layout, text toolbar + tokens, image inspector/crop/AI-edit,
  components/reorder/align, per-turn Compare/Revert).

## The three fixtures — one per orientation, one per decision, one per editor surface

| id | orientation | artifact (px) | decision | idiom (`role`) | primary editor surface |
|----|-------------|---------------|----------|----------------|------------------------|
| `pricing_living_type_portrait_none` | portrait 4:5 | 1080×1350 | **none** (typographic) | `living_type_statement` | text toolbar + token-aware overrides + freehand text (Phases 4.1, 1) |
| `how_it_works_square_icons` | square 1:1 | 1080×1080 | **icon** (2×2 grid) | `icon_grid_2x2` | managed auto-layout + components/reorder + align/group (Phases 1, 4.2, 4.3) |
| `platform_launch_deck_hero_photo` | landscape 16:9 | 1920×1080 | **photo** (full-bleed hero) | `full_bleed_hero_scrim` | image inspector/crop + AI image-edit + z-order stack (Phases 3, 4.2) |

**Decisions are diverse (none / icon / photo)** — not all photo — and the square + landscape both
compose imagery (icon system for the square, a raster hero for the landscape); the portrait is the
image-free type case. Together they cover the editor plan's three big surfaces: text/tokens,
auto-layout/components, and image-editing/z-order. Each `editor` block lists `managed_layout`
(the agent's composition), `freehand_targets` (what a human would drag/detach), `targeted_edits`
(§1.6-style human→agent revision prompts to test round-trip), and `exercises` (the plan mechanisms).

## Run the imagery gate (live, costs credits)

From `apps/agent_runtime/`:

```
python -m evaluation.run_imagery_evals --run \
  --prompts evaluation/sprint_fixtures/prompts.json \
  --briefs  evaluation/sprint_fixtures/briefs.json \
  --model   anthropic:claude-opus-4-7 \
  --out     <capture-out-dir> \
  --tag     <sprint-tag> \
  --trace-root <abs-trace-dir>
```

**Prerequisite for the photo fixture:** the deepagent photo path currently crashes on `LUMV0100`
("document must contain at least one page/artboard") — the coordinator GENERATEs the hero before
authoring a page, and `generate_image`'s unguarded `apply_operations(upsert_asset)` hits an empty
scene. Land that fix before running `platform_launch_deck_hero_photo` end-to-end. The `none` and
`icon` fixtures don't generate a raster asset, so they run today.
