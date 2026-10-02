---
name: color-and-contrast
description: Use whenever a design places text, a mark, or a control against a colored surface or image and needs a readable brand-approved pairing.
---

# Color & Contrast

Read beside `skills/brand-and-tokens`. That skill identifies available tokens;
this one chooses readable combinations from their actual resolved colors.

## Choose by luminance, not by the token name

Inspect the kit's real foreground and background values before assigning them.
`$surface.brand` can be pale yellow, bright cyan, or deep purple: its name does
not tell you whether it needs dark or light text. Choose an approved foreground
such as `$text.primary` or `$text.inverse` for the actual surface beneath it.
The kit's declared on-color pairing is a starting point to check, not proof.

For example, white on a vivid light field can disappear while dark ink reads
clearly. A dark field may need the reverse pairing. If the available combination
fails, change the foreground, use a quieter approved surface, or add a deliberate
plate/scrim. Check the resulting pixels again.

## Assign visual jobs

Name the ground, the atmosphere, and the focal accent in the direction. A softer
shade can express the brand as well as the full-strength hue. Choose it according
to the reference and message, not a fixed percentage of the frame.

A monochromatic composition can work through differences in lightness, scale,
texture, and spacing. Several same-family areas are not automatically a failure.
The same brand color can appear in more than one role when each local pairing
stays readable and the intended focal point remains clear.

When two saturated areas fight, soften one, put a neutral between them, or give
them more space. Assess the visible hierarchy rather than banning a hue family.

## Measure and look

Check headline/ground, support/ground, CTA label/plate, CTA plate/ground, and
logo/ground. Body copy and CTA labels need at least 4.5:1 contrast. Prefer 4.5:1
for the main headline too; 3:1 is only the absolute large-type floor, followed by
visual inspection at the intended delivery size.

For a photograph or generated image, evaluate the actual region beneath each
text run and logo, including any scrim. A dominant-color average cannot establish
local readability. Keep detailed or changing areas away from required copy.

Open the rendered preview at full size and at feed size. Name the foreground,
background, measured ratio where available, and any visually weak region in the
audit. A legal token or passing preflight does not establish readable artwork.
Repair poor pairings before accepting the creative.

## Override

Explicit user instructions beat every rule above. Record each override with
`record_gap`.
