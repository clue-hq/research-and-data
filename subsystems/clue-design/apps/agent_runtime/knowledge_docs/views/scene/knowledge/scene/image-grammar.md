## Images and placement

Use `image asset(id)` for a real raster, `svg(icon:name)` for a supported library
icon, and `vector path("…")` for a native path. An image declaration needs a real
asset ID. Logo or product images must remain authentic independent assets.

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
