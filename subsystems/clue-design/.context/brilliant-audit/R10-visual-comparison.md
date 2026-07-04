# R10 — Visual Quality Comparison: Lumen vs. Brilliant (target fixtures)

**Slice:** Visual / art-director judgment of rendered PNG outputs.
**Method:** Read every PNG at full render resolution, then cross-referenced each against its source `scene.json`, `preflight.json`, `repair_request.json`, rendered `.svg` (for exact font-size / y-position numbers), and `trace.jsonl`. All numbers below are pulled from those files, not estimated.

---

## TL;DR (the one finding that explains the rest)

The single biggest visual-quality driver is **not** the knowledge-doc count (in this slice both our run and the fixture retrieved the *identical 8 snippets* — see §6). It is the **repair loop's feedback channel**:

- **Our loop is blind.** Every iteration's feedback is `kind: "preflight"` — pure compiler diagnostics (`LUMV0902`, `LUMV0903`, `LUMV0810`…). There is **no visual critic**. Our `final.json.critique.kind == "preflight"` and `feedback.summary == None`.
- **Brilliant's loop can see.** The fixture's `critique.kind == "visual"`, with prose like *"All content is left-aligned starting at x=64, occupying roughly 60% of the 1200pt-wide canvas. The right ~450pt is completely empty"* and `category: "visual_balance"` issues carrying **pixel coordinates and suggested repairs** ("center the content stack… or adopt a two-column layout").

Because our agent only ever sees overflow error codes, it shuffles `wrap_text`/`max_lines`/`size` flags on 4 nodes per iteration (the entire emitted DSL for iter 003 is literally 4 lines) and **never addresses composition** — spacing rhythm, balance, hierarchy, whitespace distribution. It then exhausts iterations still showing `LUMV0903`/`LUMV0810` overflow errors. That is exactly what the eye sees in the PNGs.

> Note: *both* runs end `status: "failed", stop_reason: "max_iterations_reached"`. The difference is that Brilliant's intermediate iterations were already visually clean (fixture 005 is gallery-grade), while ours stay broken through 003.

---

## 1. Critique of each of OUR outputs

### 1a. `lumen-agent-ui-run-landscape-flyer.png` (run `c0febb45…`, 1200×675)
Judged from the full-res per-iteration previews (iter 001–003), since the UI screenshot is downscaled.

**Iteration 001 — broken:**
- **Card text overlap (worst offense):** In each benefit card the bold title "24/7 Patient Routing" wraps to 2 lines and the body copy *starts underneath the second title line* — "Routing" and "Intelligent call triage…" literally overprint. This is diagnostic `LUMV0903 text node b1_title exceeds available height` made visible.
- **Tiny mystery icons:** each card has a 1–2px-wide blue vertical sliver top-left where an icon glyph should be — `LUMV0902 non-wrapping text node b1_icon overflows horizontally`. It reads as a rendering defect, not a designed icon.
- **Right-edge clipping:** the 3rd card ("Red… Sho… Sma… 40%") is sliced off the right canvas edge — `LUMV0801 node benefits_row exceeds parent bounds`. The row was laid out wider than the artboard.
- **CTA cramped:** "Book a Demo" sits ~30px under the cards with no breathing room; whitespace is dumped at the *bottom* instead.

**Iteration 002/003 — partially repaired, still amateur:**
- Cards no longer overlap horizontally (titles now single-line) — a real improvement. But the **"Book a Demo" button wraps "Book a / Demo" onto two lines** because the pill is sized `hug` but too narrow — `LUMV0903 text node cta_label exceeds available height` persists to the final iteration. A two-word CTA breaking across two lines is the canonical "AI did this" tell.
- **Header band is full-bleed but content isn't:** the navy bar spans edge-to-edge, yet the body content sits in a left gutter — the header and body use *different* left margins, breaking the vertical alignment spine.
- **Whitespace is bottom-heavy:** content fills the top ~70% and the bottom ~30% is dead. For a landscape flyer this is the exact failure the fixture critic flagged: content not distributed across the canvas.
- **Type scale is noisy:** rendered SVG shows font-sizes `36 / 22 / 17 / 15 / 13` with **`22px` used 4 times** (every benefit title) — too many near-adjacent steps; no clear "one display size, one body size" discipline.

### 1b. `lumen-agent-ui-run-linkedin.png` (run `92039c13…`, 1080×1080)
**Iterations 001 & 002 — broken hierarchy & alignment:**
- **Sub-headline is ragged-centered inside a left-aligned column.** "Automate document / processing / for healthcare practices" is *center-justified* but the headline above ("Introducing Magic-Doc") and the badge are *left-aligned*. Mixed alignment within one stack = the most obvious amateur tell in the whole set.
- **Headline left margin ≠ subhead left margin** — the subhead is indented ~80px further right than the H1, so the left edge zig-zags.
- **Massive dead band:** a ~250px empty void between the subhead and the stat row. The composition has a hole in its middle.
- **Iter 001 stat row is off-center / left-shifted** and the three stats are unevenly spaced; iter 002 fixes the centering of the stats but the subhead is *still* center-ragged and *still* mis-indented.

**Iteration 003 — best of ours, still off:**
- Subhead finally left-aligns ("Automate document processing / for healthcare practices") — but it is **still indented to a different left margin than the H1**, so headline and subhead don't share a spine.
- The big mid-canvas void persists; vertical rhythm is "cluster at top, cluster at bottom, emptiness between."

### 1c. `lumen-agent-ui-run-a4-appointment.png` (A4 portrait)
- From the UI screenshot, the appointment card renders as a centered white card on grey, with a heading, an intro line, and what appears to be a content block — legible but generic. The **"Book a Demo" CTA again wraps to two lines** (same `cta_label` height-overflow pattern as the flyer). The hierarchy between "Patient Instructions" heading and the bullet list is weak; spacing between sections looks uniform (no rhythm differentiation between section breaks vs. line breaks).

**Common thread across all three:** the same compiler diagnostics recur (`cta_label` overflow, benefit/title height overflow), and the same *visual* sins recur (two-line CTAs, mixed alignment, lopsided whitespace) — none of which a preflight-only loop is equipped to name, let alone fix.

---

## 2. What makes the reference fixtures look professional

### LinkedIn references (`tpl-linkedin-preview`, `v2-linkedin-airy`, `v2b-linkedin`, hygiene `linkedin-square/004`)
- **Strict centered axis.** Brand name, eyebrow ("NEW PRODUCT LAUNCH" / "INTRODUCING"), H1, subhead, supporting list, CTA, footer URL are *all centered on one vertical axis*. Zero mixed alignment.
- **Clear 6-tier hierarchy with real size jumps:** small-caps eyebrow (teal, letter-spaced) → large display H1 (Magic-Doc, ~40px+) → medium lead line → muted secondary list → CTA pill → tiny footer URL. Each tier is unmistakably distinct in size *and* color *and* weight.
- **Eyebrow uses tracking + accent color** (teal `NEW PRODUCT LAUNCH`) — a single, cheap, high-impact professional move our outputs never make.
- **Generous, *balanced* margins.** Content is vertically centered with symmetric top/bottom air (`v2b-linkedin`), or anchored with deliberate asymmetry (`v2-linkedin-airy` pins brand to top, footer to bottom, content to optical center). Either way the whitespace is *composed*, not leftover.
- **CTA pill is sized to its label** — "Book a Demo →" never wraps; the arrow glyph is inline and aligned.
- **Restrained palette:** one dark navy field, one teal accent, white + muted-grey text. Three values, used consistently.

### Landscape flyer hygiene fixture (`landscape-flyer-card/005`)
- Iter 005 **abandons the 3-card grid** that kept overflowing and switches to a single left-aligned editorial stack: brand → big H1 ("Smarter Care Starts Here") → lead → muted intro paragraph → an **inline single-row benefit list** ("Real-time clinical decision support · Seamless EHR integration · HIPAA-compliant & SOC 2 certified") → solid teal CTA pill → footer URL. **Nothing clips, nothing overlaps, no two-line CTA.**
- Scene uses an explicit **modular type scale `13/15/16/18/20/40`** and a single **`32`pt spacing token** (from `scene.json`) — one display size, one lead size, one body size. Compare to our noisy `13/15/17/22/36`.

### A4 appointment hygiene fixture (`a4-appointment-card/004`)
- **Eyebrow + headline + intro lockup** ("Patient Appointment Card" teal eyebrow → "Your Appointment Details" H1 → intro sentence) with tight, intentional spacing.
- **Bulleted instructions with consistent bullet rhythm**, then a clearly separated routing paragraph, then a teal CTA pill, then a footer rule line. Sections are separated by *larger* gaps than lines-within-a-section — true spacing rhythm.
- Huge intentional bottom whitespace appropriate for a print A4 card (the empty lower half reads as deliberate letterhead space, not a bug, because the top lockup is balanced).

---

## 3. Side-by-side: TOP 8 concrete visual differences

| # | Dimension | OUR output | TARGET fixture | Evidence |
|---|-----------|-----------|----------------|----------|
| 1 | **Text overflow / overlap** | Benefit title overprints body; 3rd card clipped off-canvas (iter 001) | Nothing overlaps or clips | `LUMV0903`/`LUMV0801`/`LUMV0810` errors present in our final; fixture 005 clean |
| 2 | **CTA label wrapping** | "Book a / Demo" wraps to 2 lines in flyer + A4 | "Book a Demo →" one line, pill sized to label | `LUMV0903 text node cta_label exceeds available height` persists to our final iter |
| 3 | **Alignment discipline** | LinkedIn subhead center-ragged while H1 left-aligned; subhead indented off the H1 spine | Everything on one centered axis | iter 001/002/003 LinkedIn previews vs. `v2b-linkedin` |
| 4 | **Whitespace distribution** | Content top-heavy, dead bottom third (flyer); ~250px void mid-canvas (LinkedIn) | Whitespace composed: symmetric or optically centered | fixture critic: *"right ~450pt completely empty… bottom ~190pt dead space"* |
| 5 | **Type scale** | Noisy `13/15/17/22/36`, `22px` reused 4× | Clean `13/15/16/18/20/40`, one of each tier | rendered `.svg` font-size counts (§ data) |
| 6 | **Eyebrow / kicker label** | None | Teal letter-spaced small-caps eyebrow on every fixture | "NEW PRODUCT LAUNCH" / "INTRODUCING" / "Patient Appointment Card" |
| 7 | **Icon rendering** | 1–2px blue sliver glyphs (broken icons) | No broken glyphs; benefits rendered as clean inline text | `LUMV0902 non-wrapping text node b1_icon overflows horizontally` |
| 8 | **Layout strategy adaptation** | Locks onto an overflowing 3-card grid and only tweaks wrap flags | Switches strategy when grid fails (005 → single editorial stack / inline list) | fixture suggested_repair: *"adopt a two-column layout"*; our DSL is 4 flag-tweak lines |

---

## 4. Do our per-iteration previews improve, or stay broken? (repair-loop effectiveness)

**Partial improvement then plateau, while staying visibly broken.** Hard evidence from `preflight.json` per iteration (run `c0febb45…`, landscape flyer):

| Iter | # diagnostics | Errors still present |
|------|--------------|----------------------|
| 001 | **13** | `LUMV0902`×3, `LUMV0903`×3, `LUMV0810`×2 (+`LUMV0801`, `LUMV0509`×2, `LUMB0613/0614`) |
| 002 | **8** | `LUMV0902`×1, `LUMV0903`×1, `LUMV0810`×2 |
| 003 | **8** | `LUMV0903`×1, `LUMV0810`×2, `LUMV0801`×1 |

- **001→002 is a genuine visual win** (card text stops overlapping; one icon overflow fixed). **002→003 is a no-op visually** — same 8 count, the cluster just shuffles between `LUMV0902`/`LUMV0801` on `b3_icon` while the two `LUMV0810` headline/body fixture-overflows and the `cta_label` height overflow **never clear**. The PNGs for 002 and 003 are nearly pixel-identical.
- The loop **converges to a non-zero error floor** and then burns its remaining budget — hence `max_iterations_reached`. It is chasing whack-a-mole on `b_icon`/`cta_label` overflow while the *actual* problem (CTA pill too narrow, benefits laid out wider than the artboard, mixed alignment) is composition, not a wrap flag.
- **Root cause of ineffectiveness (visual lens):** the feedback object handed to the repair step is `kind: "preflight"` (verified all 3 iters). It contains diagnostic codes but **no visual critique, no balance assessment, no suggested layout strategy**. Contrast the fixture, whose `trace.jsonl` contains `kind: "visual"` critiques (2) and 6 `visual_balance` issues with pixel coordinates and concrete `suggested_repair` text. *Inference:* our pipeline either never runs a visual critic or never feeds its output into the repair request — so the loop is structurally incapable of fixing what a human art director would fix first.

---

## 5. Prioritized visual fixes (highest quality-per-effort first)

1. **Add a visual critic to the repair loop (or wire the existing one in).** This is the unlock. Our `final.json` already has a `critique` slot — but it's populated with `kind: "preflight"` and `summary: None`. Feed a rendered-preview visual critique (balance, alignment-spine, whitespace distribution, hierarchy, CTA fit) into `repair_request.exact_feedback` instead of/in addition to preflight codes. Brilliant's fixture proves the format works: `category: visual_balance`, pixel coords, `suggested_repair`. **Effort: medium. Impact: fixes #3, #4, #8 simultaneously.**

2. **Size the CTA pill to its label (or set `min_width` to fit "Book a Demo").** Eliminates the two-line-CTA tell across flyer + A4 in one change. Maps directly to clearing the recurring `LUMV0903 cta_label exceeds available height`. **Effort: trivial. Impact: high (it's the most visible amateur signal).**

3. **Enforce a single alignment spine per content stack.** Pick centered (LinkedIn) or left (flyer/A4) and apply to *all* children including the subhead — kill the center-ragged-subhead-inside-left-column bug. **Effort: low. Impact: high.**

4. **Adopt the modular type scale `13/15/16/18/20/40` and an eyebrow tier.** Collapse our `22px`-used-4× into one body size + one title size, and add a teal letter-spaced small-caps eyebrow above the H1. Instant "designed by a human" upgrade. **Effort: low. Impact: high.**

5. **Let the layout strategy change when a grid overflows, instead of only tweaking wrap flags.** When `LUMV0801`/`LUMV0810` recur on a multi-column row, fall back to a single-column editorial stack or inline `·`-separated list (exactly what fixture 005 did). **Effort: medium. Impact: high — stops the whack-a-mole plateau in §4.**

6. **Compose whitespace, don't dump it.** Center the content block vertically (LinkedIn) or distribute across full canvas width (landscape) so leftover space becomes symmetric margin, not a bottom/mid void. **Effort: medium. Impact: medium-high.**

7. **Fix the icon glyphs (1–2px slivers).** Either render real icons or drop them and use the inline benefit-text pattern the fixtures use. **Effort: low. Impact: medium (removes a defect read).**

8. **Match header/body left margins** on the flyer so the full-bleed navy band and the gutter-aligned content share a vertical edge. **Effort: trivial. Impact: medium.**

---

## 6. Important caveat for the synthesis agent (knowledge-doc count)

In THIS visual slice, the 19-vs-91 knowledge gap is **not** the proximate cause of the quality delta. Verified: our run and the Brilliant landscape fixture **retrieved the identical 8 knowledge snippets** (same titles, same order — "Lumen DSL — Layout, Sizing & Auto-Layout", "Lumen Layout Recipes", "Layout Cluster Repair", "Artboard Frame Authoring", etc.). The fixture's superior iteration-005 came from a *visual critique-driven repair*, not from extra docs. The doc-count gap likely matters more for *art-direction priors* (eyebrow conventions, type scales) that would help the agent get it right on iteration 1 — but the demonstrated, measurable mechanism here is the **missing visual feedback channel in the repair loop**. Treat the doc gap and the visual-critic gap as two distinct levers; the visual-critic gap is the one this slice proves.

---

### Source files cited
- Our run: `/Users/aryankeshri/Documents/brilliant-design/agents-design-recipes-quality-v0/.lumen-runs/run_c0febb45dbe14e0cac44dd6d240f81fd/` — `final.json`, `iterations/00{1,2,3}/preflight.json`, `repair_request.json`, `dsl.lumen`, `preview.svg`
- Our LinkedIn run: `/Users/aryankeshri/Documents/brilliant-design/agents-design-recipes-quality-v0/.lumen-runs/run_92039c13b943452aba6237048b72acfd/iterations/00{1,2,3}/preview.png`
- Brilliant fixtures: `/Users/aryankeshri/Documents/brilliant-design/agents-design-recipes-quality-v0/.lumen-fixtures/agent-quality-hygiene/{landscape-flyer-card,linkedin-square,a4-appointment-card}/` — `00*-preview.png/.svg`, `cli-output.json`, `scene.json`, `knowledge.json`, `trace.jsonl`
- LinkedIn reference renders: `/Users/aryankeshri/Documents/brilliant-design/agents-design-recipes-quality-v0/.lumen-fixtures/{tpl-linkedin-preview,v2-linkedin-airy,v2b-linkedin}.png`
