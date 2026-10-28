---
name: rebuilding-a-section
description: "Read when one of the seller's sections is right for the page but its slots cannot carry what the page needs (more words or items, a changed layout), when its motion must be carried into an editable section, or when the person asks: rebuilding a clone as a component with view_clone, write_section and compare_section."
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
   - Use the original's images; they are in brand/brand.md. If one is not there, find it with
     `search_assets` before choosing another (`imagery-and-media`, "The images a page may use").
   - Keep what the section does: its motion moves the way the seller's does (`imagery-and-media`,
     "Motion and video"). A rebuilt section cannot play a video yet: when the original's video matters,
     keep the clone as it is instead of rebuilding it.
3. Compare with `compare_section`, passing props filled with the original's words. It shows the
   original and yours side by side, with a difference score and any of the original's words yours is
   missing.
4. Fix what looks clearly different, and compare again. Stop when it reads as the same section, or
   after three comparisons.
5. Report: the component's name, its props, and what still differs and why.
