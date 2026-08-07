# Image Slice 0 — Step 10 render-probe

Render-probe evidence for the **Image hero** catalog block
(`knowledge/design/blocks/patterns.md`) — the scrim idiom (full-bleed photo +
dark scrim + legible inverse headline).

- `hero-image-block.lumen` — the shipped catalog block, extracted verbatim.
- `hero-image-block.png` — `render-probe-image.py` output: a real generated photo
  (`apps/api/tests/fixtures/image_baseline/generated_source.png`) ingested, placed
  cover-fit + focal on the image node, brand tokens resolved against the platform
  default Brand Kit, exported to PNG. Confirms the hero photo renders cover-fit under
  the scrim with a fully legible white headline/subtitle/CTA and a crisp brand lockup.

Regenerate:
```
PYTHONPATH=apps/api:apps/agent_runtime LUMEN_CORE_HELPER=$PWD/target/debug/lumen-api-helper \
  <venv> .context/render-probe-image.py \
  .context/image-slice0-probe/hero-image-block.lumen \
  apps/api/tests/fixtures/image_baseline/generated_source.png \
  /tmp/hero.png hero_photo
```
