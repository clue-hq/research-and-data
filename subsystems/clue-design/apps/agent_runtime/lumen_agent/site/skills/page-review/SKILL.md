---
name: page-review
description: "Read after render_page, to judge the rendered page as its reader and decide what to fix: the five checks (the reader's read, words and claims, buttons, looks like the seller's, nothing broken at either width), the plan's done lines, how many renders, and what to say about what you could not check."
---

# Reviewing the page

`render_page` gives you two pictures, desktop (1440 wide) and mobile (375 wide), with notes about
broken images and overflow. Look at them as the reader would. Then go through the five checks, and
the "Done when" lines you wrote in the plan before building.

## The five checks

1. **The reader's read**
   - The first screen says what this is and who it is for, and the button is visible.
   - Each section adds something; no two make the same point, and the same image does not appear
     twice.
   - The page is not thin: the reader can say what the product does and something they can now judge.
2. **Words and claims**
   - Run the final check in `page-copy` ("The final check on the words") on the visible words.
   - Every number and quote on the page traces to a line in the plan.
   - On a page for one account, one person or a few named accounts: the swap test passes, the short
     line near customer proof is there (one account, one person), and no one at the account is named
     except the reader of a page for one person.
3. **Buttons**: each button's words match where it actually goes and what happens there.
4. **Looks like the seller's** (`page-design`)
   - The hero keeps the seller's hero shape.
   - Headings sit right across the page, the hero's the largest unless the seller does otherwise.
   - Every heading is in the seller's heading font and every body text in its body font, as noted in
     the plan, including the sections you wrote or rebuilt; correct any that are not
     (`page-design`, "The seller's fonts").
   - The rhythm follows the cadence in the plan; a brand section does not look foreign next to the
     clones; not every section is the same grid of cards.
5. **Nothing broken, at both widths**
   - No empty or half-empty section, no broken image, no overflow or sideways scrolling, no clipped
     or overlapping text.
   - Text and logos are readable; headlines wrap well, with no single word alone on a line.
   - A product interface stays readable on the phone.
   - Where the page names the account, the phone's header still shows it.

## Fixing and rendering again

- Fix everything that failed, all in one go, then render again if something visible changed.
  `render_page` checks the page first, so do not validate right before it.
- Up to 3 renders for each page. A site with several pages gets three for each page it changes.
  The page's length does not change the count.
- Never re-render to compare small differences.
- On a change to an existing page, check only the change and the sections around it, and render only
  if something visible changed.

## What you could not check

`render_page` gives still pictures: never claim that motion, a video or an interaction works from
them. Say what you could not check. Report as the system prompt says ("How to work", the report):
anything still open or unchecked, named plainly.
