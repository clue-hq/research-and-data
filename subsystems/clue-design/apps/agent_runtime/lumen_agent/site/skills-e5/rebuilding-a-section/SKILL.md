---
name: rebuilding-a-section
description: Use when you are asked to rebuild one of the seller's captured sections as a component.
---

# Rebuilding a seller's section as a component

The seller's captured sections (clones) are frozen: only some of their words can change. A rebuilt
section is a component that looks like the original but holds all of its content in props, so a page
can change any word, image, link or item.

1. Look at the original with `view_clone`: its desktop and mobile pictures, and its words, images and
   links.
2. Write the component with `write_section` (the writing-a-section skill applies: brand tokens only).
   - Keep the original's layout: columns, order, alignment, where images sit, and the rhythm of
     spacing.
   - Make the content props: every heading, paragraph, button, link and image the original shows.
     Repeated items (cards, steps, logos) are a list, so a page can use more or fewer.
   - Mark every heading, paragraph and button's words with `.meta({ edit: "inline" })`, as the
     writing-a-section skill says, so the marketer can edit them on the page.
   - Use the original's images by default; they are in brand/brand.md. If the original shows a video
     or an image that is not in brand/brand.md, use the closest brand image, and say so in your
     report.
3. Compare with `compare_section`, passing props filled with the original's words. It shows the
   original and yours side by side, with a difference score and any of the original's words yours is
   missing.
4. Fix what looks clearly different, and compare again. Stop when it reads as the same section, or
   after three comparisons.
5. Report: the component's name, its props, and what still differs and why.
