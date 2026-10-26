## Images and placement

Pictures, illustrations, backgrounds and textures are images: a library image
(`search_assets`, then `place`) or a generated one (`generate_image`; see
`/.deepagent/skills/generative-imagery/SKILL.md`), declared with `image asset(id)`.
Use `svg(icon:name)` for a supported library icon. Use `vector path("…")` only for
simple geometry such as a divider, an arrow or a plain shape. Never use it to draw a
picture or an illustration, and generate an icon the library lacks as an image. An
image declaration needs a real asset ID. Logo or product images must remain authentic independent assets.

Fit, focal point and alt text belong to AssetPlacement, set by
`asset(action="place", ...)`; they are not DSL image-leaf properties. Frame
dimensions establish the available geometry. Use contain for a full logo;
choose product/image fit by inspecting the crop. A slot's `image_policy` is the
separate future-binding contract described above, not node placement.

For text over imagery, establish legible contrast in the actual composite.
A tonal region, changed placement or suitable native plate/scrim can provide
it; no scrim or fixed frame pattern is compulsory. Declaration order controls
stacking. Follow `knowledge/scene/components.md` for independent native layers
and `knowledge/scene/references.md` for generation and contrast sampling.
