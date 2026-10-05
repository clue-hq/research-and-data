---
name: reference-image-direction
description: Use when a scene creative uses references, needs a close companion or new concept, or misses the sources despite matching their palette.
---

# reference image direction

Read `knowledge/scene/references.md`. It owns source roles, preserve/vary, image conditioning and final-composite contrast checks. Put those decisions in `creative-direction.json`; do not create an additional imagery-direction document.

**Generated imagery.** Before writing any `generate_image` call, read
`/.deepagent/skills/generative-imagery/SKILL.md` if you have not read it this
turn. In short: decide what the image is for, take its look only from the
seller's own imagery, and ask for nothing those references do not show.
