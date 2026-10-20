# Capturing JavaScript-heavy websites: discussion notes (2026-10-08)

Status: **discussion notes, not a spec.** Recorded at the founder's request so we can come back to
this and experiment heavily. Nothing here is decided or built yet.

## Why this came up

The Puck spike (branch `spike/puck-phase1`) prepared a run for the Alt Carbon workspace
(altcarbon.com). Its captured sections were mostly broken:

- **Five sections for the whole site, all from the home page.**
- **The hero section holds most of the page,** with about 1,500 px of empty space where a
  scroll-animated part of the site should be.
- **"How we work" is a heading over blank space.**
- **The purple announcement bar was captured as its own section.**

Evidence: `trials/puck-spike/shots/altcarbon-v0-1440.png` (the three usable clones on one page).
The Puck spike reuses the platform's own captured sections, so the platform editor shows the same
blanks; Puck neither captures nor fixes capture.

## What we verified

1. **The cause.** altcarbon.com is a Next.js site. The "How we work" content is not in the HTML the
   server sends; the browser builds it with JavaScript, tied to scrolling.
2. **How our capture works** (`subsystems/clue-design/apps/api/lumen_ingestion/capture/rendered.py`):
   - Python and Playwright, a real Chromium browser. A static fetch goes first; the quality gate
     switches to the browser for thin, client-built pages.
   - It scrolls to the bottom so lazy content loads, then jumps back to the top, removes overlays,
     and waits for the hero (`reduced_motion="no-preference"`, on purpose, to see animated heroes).
   - Then it saves the page once: HTML, CSS and a full-page screenshot. Sections become frozen
     HTML and CSS with no JavaScript.
   - A small vetted runtime (`crates/lumen-web/src/runtime/lumen-runtime.v2.js`) adds back
     dialogs, tabs, and carousel arrows/autoplay.

   Rust is the renderer that consumes the captured sections, not the capture.
3. **The clone-review gate already catches some of this.**
   - `lumen_api/clone_review/` compares each clone's render with the reference screenshot, band
     by band, and marks bad sections `degraded`.
   - On Alt Carbon it caught the hero (`dead_height`). The spike's export ignored that flag (a
     spike bug).
   - It did **not** catch "How we work": the content never existed at the moment we saved, so
     the reference screenshot was blank too, and both sides of the comparison were wrong.

**The root problem: a modern site is a program with many states** (scroll position, time, open
tabs, viewport). We save one moment, and everything downstream inherits it.

## The idea discussed: capture the JavaScript too

| Approach | What it is | At capture time | As the published page |
|---|---|---|---|
| **Record and replay** | Save every response (HTML, JS, CSS, data) and replay it, so the site's own code runs against saved data. This is how web archives such as Webrecorder work; Playwright can record and replay HAR files. | **Excellent:** faithful, repeatable, offline, any state on demand | **Poor** |
| **Record the page over time** | Save the starting page and every change as you scroll and click (session-recording style) | **Good** for extracting every state of a section: tabs, slides, revealed blocks | Not a page |
| **Read their source** | Fetch the JS files and rebuild components from them | Unreliable: minified, compiled, and bundled with third-party libraries | No |

Why shipping the seller's JavaScript fails for 1:1 pages:
1. **It can't be edited.** In a JS app the words live in code and data files; the app re-renders
   over edits.
2. **It can't be combined with anything.** The app expects exactly the page it built. Removing a
   section, reordering, or mixing in our own sections breaks it, and that is what a 1:1 page does.
3. **Security and privacy.** Their analytics, chat widgets, cookie banners and trackers would run
   on our domain. Our page origin's strict security policy exists to prevent exactly this, and
   there are consent implications for their visitors.
4. **Weight and decay.** Megabytes of JavaScript per page; code that checks its own domain, dates
   or live APIs breaks over time.

**Conclusion: run their JavaScript at capture time, in a sandbox. Ship our own.**

## The recommended pipeline (to test)

1. **Record once, faithfully, in a sandbox.** Save a full recording of the page so capture can
   replay it as often as needed without fetching again (no repeated bot checks, same result each
   time).
2. **Explore the page as a visitor does, in the replay:**
   - Scroll slowly. Save each section while it is in view and its animations have finished.
   - Bake its visible state (final opacity and positions) into the saved section.
   - Open tabs, step carousels, expand accordions, and save each state's content.
   - Screenshot each section in its best state. This gives every section a correct reference
     image.
3. **Choose each section's form by measured fidelity:**
   - **Static or reveal-on-scroll** (most sections): an improved frozen clone.
   - **Known interactive pattern** (tabs, carousel, accordion, dialog, marquee, sticky): a frozen
     clone plus our own vetted behaviour, with the captured states as data (extend
     `lumen-runtime`).
   - **Can't be cloned** (scroll-driven stories, canvas/WebGL, heavy client apps): rebuild as a
     React component checked against the reference (the seller component library follow-up), or
     honestly fall back to a still image of its best state, labelled as such.
4. **Fidelity gate.** The existing clone-review gate, fed the better references. Every section gets
   a score; a low score keeps it away from agents and marks it for rebuild.

Every section ends as a faithful clone, a clone with behaviour, a rebuilt component, or a labelled
still. No site breaks silently. Saving HTML and CSS was not the mistake: frozen clones are still
the right output for most sections. What was missing is more than one moment, and a way out for
sections that can't be frozen.

**Where Puck fits.** Capture is upstream; Puck doesn't capture. All four outputs fit Puck, and a
rebuilt component is a first-class section on Puck, where the current engine treats it as an
add-on inside its page.

## Effort estimates (as discussed)

| Step | Effort | Confidence |
|---|---|---|
| Honour the `degraded` flag in the spike and the agent's catalog | hours | high |
| Save each section in view, with its visible state baked in (inside today's capture) | 1–2 weeks | medium-high; biggest win per effort |
| Record and replay, plus a reference screenshot per section for the review gate | ~1 week | medium-high |
| Interactive states as data, plus runtime additions for the top patterns | 2–3 weeks | medium |
| Rebuild path (seller component library spike) | 2–3 weeks to prove | medium-low until measured |

## The first experiment when we return

A capture prototype in the spike, with **no model spend**:
- **Sites:** Alt Carbon, Garner and Conduit, plus two or three known JavaScript-heavy sites.
- **Steps:** record, replay, scroll-explore, and save sections as they come into view.
- **Measure:** compare against today's captured sections with the clone-review comparison,
  counting blank and missing sections before and after.

About 3–4 days. It tells us how much steps 1–2 solve on their own before committing to
interactive states or rebuilding.

## Open questions for that work

- Recording format: HAR (Playwright, simplest) or WACZ (archive standard, richer replay)?
- How far to explore interactions automatically (which patterns, how many clicks) without
  capture time growing too much?
- How to keep the captured states as data for our runtime without carrying the seller's code.
- How the rebuild path is approved and versioned per seller (screenshot comparison plus human
  approval?).
- Bot protection on JavaScript-heavy sites (the stealth capture backend already exists).
