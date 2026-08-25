---
name: color-and-contrast
description: Judge a color combination after you pick it — the on-color pairing law, choosing a shade rather than defaulting to full strength, separating two saturated hues, the structure/atmosphere/accent role split, and checking the pairs that matter by looking at the render. Use on every design that fills a surface and puts text on it.
---

# Color & Contrast

Picking a legal token is the START of color thinking, not the end. A token
resolves to a real color. That color then has to sit next to every other color
you chose. This skill is the second look.

Read it beside `skills/brand-and-tokens`. That skill tells you WHICH tokens
exist. This one tells you which COMBINATION reads.

## The on-color pairing law

This rule prevents the most common color failure in this system.

**A saturated brand surface takes light text.** Paint the text with
`$text.inverse`, or with the on-brand text role the kit declares for that
surface.

**Dark ink text belongs on light grounds.** `$text.primary` goes on
`$surface.page`, on `$surface.card`, or on `$surface.brand.subtle`.

Never put `$text.primary` on `$surface.brand`. Never put `$text.inverse` on
`$surface.page`. Both pairings are wrong every time.

### Worked example — the failure this rule exists for

A LinkedIn square ad filled its artboard with `$surface.brand`, which resolved
to `#533AFD` — a strong purple. It then painted the headline and the body copy
with `$text.primary`, which resolved to `#000000`.

Black on that purple measures 3.39:1. The engine flagged the 16pt body with
`LUMB0807`. The 77pt headline was flagged by nothing at all, because anything
at 24pt or above only has to clear 3:1. The headline still looked broken.

The fix is one token on each text node:

```text
headline text "Clinical notes write themselves." s(888,hug) style($type.display) fill($text.inverse)
body text "Stop documenting after the visit." s(888,hug) style($type.body) fill($text.inverse)
```

There is a second fix. Move the text instead of recoloring it. Put the same
black headline on `$surface.brand.subtle` and it reads immediately.

Either answer is correct. Leaving black on full-strength purple is not.

## Choose the shade, not just the token

Kits often ship more than one step of the brand hue. `$surface.brand` is the
full-strength color. `$surface.brand.subtle` is the soft step of the same hue.

**A softer shade is on-brand too.** Reaching for full strength every time is a
default, not a decision. Say in your direction which step you chose and why.

**Full strength is for the GROUND or for the ACCENT — never both.** If the whole
canvas is `$surface.brand`, the accent has to be something else. If the accent
is the brand color, the ground has to be quiet.

The quiet ground options are `$surface.page`, `$surface.card`,
`$surface.brand.subtle`, and `$surface.inverse`. All four leave room for one
loud element.

## Saturated on saturated needs a separator

Two full-strength hues touching each other vibrate. The edge between them
shimmers and neither color looks like itself.

The same ad put an `$surface.accent` plate (`#EA2261`, a strong pink) directly
on the `#533AFD` purple ground. Both colors are legal kit colors. Together they
fight.

Three ways to separate them. Pick one:

1. **Change one to a softer shade.** Put the pink plate on
   `$surface.brand.subtle` instead of `$surface.brand`.
2. **Put a neutral between them.** An `$surface.inverse` or `$surface.card`
   plate under the accent gives the eye a place to rest.
3. **Give the accent room.** A scrim or a wider gap stops the two edges from
   touching.

## Roles and families

Every composition assigns colors to three jobs. Name yours before you author.

- **Structure** — the grounds and surfaces. These must sit comfortably under
  text. This is where a quiet color belongs.
- **Atmosphere** — the mood. Tints, washes, and secondary panels live here.
- **Accent** — exactly ONE concentrated color for the thing you want clicked or
  read first.

**An accent color is never a base color.** The color you reserved for the CTA
cannot also be the canvas. Once it covers most of the frame it is no longer an
accent. The CTA then has nothing left to be loud against.

**The hard reject test.** Count the major colored areas — the ground, any
panels or plates, and the accent. If three or more of them read as one family
or one temperature, the assignment has failed. Rebuild it rather than tweak it.
A frame that is purple ground, purple panel, and purple button has no hierarchy
left to repair.

## Contrast before harmony

Harmony is what you want. Contrast is what you check first. A pretty palette
that cannot be read is not a design.

Check these four pairs on every frame:

1. Headline against its ground.
2. Body copy against its surface.
3. The CTA label against its plate.
4. The CTA plate against the ground behind it.

**Check them by LOOKING at the render.** The numeric floors are real: 4.5:1 for
body text, and 3:1 for anything at 24pt or above. But a floor is not a verdict.
Black on a medium purple can clear 3:1 and still read as a clash.

That gap matters. The looser floor applies to your biggest type. Big type is
also where a bad pairing shows most. So the headline is the one pair the numbers
are least likely to catch for you.

Run the numbers, then open the preview and look. If a pair clears its ratio and
still looks wrong, it IS wrong. Fix it.

## Override

Explicit user instructions beat every rule above. Record each override with
`record_gap`.
