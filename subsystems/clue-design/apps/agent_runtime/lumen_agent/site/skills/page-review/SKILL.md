---
name: page-review
description: Use after render_page, to judge the rendered page as the reader and decide what to fix.
---

# Reviewing the page

`render_page` gives you two pictures: desktop (1440 wide) and mobile (375 wide), with facts
about broken images and overflow. Look at them as the reader would, then go
through this list.

1. **First screen.** It says what this is and who it is for, and the button is visible.
2. **Nothing broken.** No empty or half-empty section, no broken image, no sideways scrolling,
   no cut-off text. On mobile, the header still shows the account's name.
3. **No repeats.** The same image does not appear twice, and two sections do not make the same
   point.
4. **Words fit their space.** A rewritten headline should not wrap much worse than the original,
   or leave one word alone on a line. If it does, shorten it.
5. **Rhythm.** No two dark sections in a row. A brand section should not look foreign next to the
   clones; if it does, choose another surface.
6. **The words.** Run the final check in `account-page-copy` (part 6) on the visible words.

Then fix only what failed, all in one go, and render again if something visible changed
(`render_page` checks the page first, so do not validate before it). Repeat until the review
passes, up to 3 renders in all. Do not re-render to compare small differences.

In your report, say what you checked and anything you could not fix.
