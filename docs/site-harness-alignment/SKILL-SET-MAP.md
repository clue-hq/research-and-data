# Site agent · consolidated skill-set map (step 4 blueprint)

> **Revised by S5 (2026-10-28):** the six case skills are one `page-kinds` skill with six reference files, and
> `decision-material` is a seventh reference inside it. Sections 0, 3, 4 and 10 below still name them separately;
> read "`one-to-one-page`" as "`page-kinds` → `references/one-to-one.md`", and so on.

Compiled 2026-10-28 from `RULINGS.md` and the six `HOMES-family*.md` tables. Each line names the rulings a piece
holds; the wording comes in step 4, one piece at a time, shown to the founder first. Skills are listed in the system
prompt and read on demand (S2); a new document reads the base skill, then its case skill, then aspect skills as
needed (S2.4). Ploy is never cited in a skill (S3).

## 0. The set at a glance

| Layer | Piece | Status | Built from | Rough size |
|---|---|---|---|---|
| System prompt | `system_prompt.md` | rewritten | today's prompt | ~ today's minus the pasted skills |
| Base | `planning-a-page` | **new** | site `account-page-copy` part 1; legacy `campaign-landing-page`, `plan-design` | ~900–1,100 words |
| Case | `one-to-one-page` | **new** | site `account-page-copy`; legacy `web-account-personalization` | ~400–600 |
| Case | `contact-page` | **new** | legacy `web-contact-personalization` | ~400–500 |
| Case | `one-to-few-page` | **new** | legacy `audience-modes` (1:few) | ~300–400 |
| Case | `general-campaign-page` | **new** | legacy `audience-modes` (1:many), `argument-and-shell` | ~300–400 |
| Case | `event-page` | **new** | legacy `audience-modes` (event), `action-selection` | ~250–350 |
| Case | `product-campaign-page` | **new** | legacy argument patterns, `action-selection` | ~300–400 |
| Aspect | `decision-material` | **new** | legacy `web-decision-material` | ~400–500 |
| Aspect | `page-copy` | **new** | site `account-page-copy` parts 4–6; legacy `conversion-copywriting` | ~900–1,100 |
| Aspect | `evidence` | **new** | site `account-page-copy` parts 2–3, research-file wording; legacy evidence parts | ~600–800 |
| Aspect | `imagery-and-media` | rewritten (`images-and-logos`) | site skill; legacy media, product-story, motion, generative craft | ~900–1,100 |
| Aspect | `page-design` | **new** | legacy `design-guidance`; Ploy (discussion only) | ~300–400 |
| Aspect | `page-review` | rewritten | site skill; legacy `review-website` | ~400–500 |
| Mechanics | `building-with-puck` | edited | site skill | ~ today's |
| Mechanics | `writing-a-section` | edited | site skill | ~ today's + `kit.Video` |
| Mechanics | `rebuilding-a-section` | edited | site skill | ~ today's |
| Mechanics | `making-a-section-interactive` | edited | site skill | ~ today's + seller-motion part |
| Retired | `account-page-copy` | **retired** | split across base, one-to-one, page-copy, evidence, page-review | — |

16 skills (17 with the interactive one on live sites), against 7 today; none is pasted into the prompt.

## 1. System prompt

- **Line 1**: a seller's landing pages for every page kind, not "one named account" (R1).
- **Workspace lines**: `research/` explained briefly, with its tags and `claims.md` (W5.1); `seller/` = the brand's
  documents, the confirmed ICP and personas (R1.3a, W5.1); tools line — `web_search` also for a little audience
  context (R1.3a).
- **Skill list** (X2.1): each skill's name, when to use it, its path; `making-a-section-interactive` only on live
  workspaces (X2.3). Then the **reading rule** (S2.4): a new document reads `planning-a-page`, then the case skill
  that fits the person's request, then aspect skills as needed; follow-ups read only what they need.
- **How to work**: "Read `brief.md`, the research and `catalog/index.md`. Open clone files and seller files when
  you need them, not all at once." (X2.4, unchanged); validate until valid (Q2.1); render, fix all in one go, **up
  to 3 renders per page** (Q2.2); the final report in Q3's shape — the result and status first, then three to six
  short bullets, open items named plainly, unverified never invented, no internal ids (Q3.1–Q3.4, Q1.3).
- **Always**: the five sources, one line, pointing to `evidence` (W1.1); notes and research background never reach
  the page, pointing to `page-copy` (W4.1); style comes only from the brand, including the header and footer style
  copied from the seller's own page and motion rebuilt from the seller's site (V5.1); never name people at the
  account except on a contact page (R10.2); never suggest the account is a customer or partner; the brief sets the
  goal, reader and offer, its facts, proof and structure are suggestions (R8, unchanged); the INVALID rule (Q2.1).
- **Asking** (R9.1–R9.3): build by default with stated assumptions; one short question, building nothing, only when
  the page cannot be right without it; never more than one; never to approve a plan (exception: a re-aim, R12.2).
- **Changing an existing page** (R12.1–R12.3, Q2.3): small edits change only what was asked and read only what they
  need; review only the change and its neighbours; a re-aim re-plans only after the person confirms; unclear → make
  the small edit, then ask whether a revamp or small changes are wanted.

## 2. Base · `planning-a-page`

- Purpose and the question sequence (R2.1, R2.3): the task → **who this page is for** and at what scale, which
  names the case (R1.1, R1.4 with R2.5 and R10.1 — one account, one person, a few named accounts, a whole audience,
  an event, a product campaign) → where they arrive from → what they already know → the offer and the one decision
  (R5.1) → the evidence needed and available → the argument → sections and what is left out → **follow your case
  skill**.
- With no account tagged: name the page for its context (R1.3); read the ICP and personas and run a few searches
  for context (R1.3a).
- Length follows the decision; nothing padded, nothing the decision needs cut (R3.1); a word budget per section as a
  planning aid (R3.3).
- Substance before container (R4.1); research is input, not prose — the copy skill turns it into page words (R4.5);
  ground yourself before writing how the product applies (W4.6).
- One primary action, placed at decision points (R5.2); write the chosen header and footer and why (R7.4).
- Sections that do not help the decision come out; embedded press-play videos come out unless a short demo shows
  what the page argues; the seller's ambient motion stays (R11.1–R11.3).
- **The plan format** (W6.4, one short example, not a schema): facts per section with their source (W6.1); bridge
  lines on personalised pages (W6.2); the seller's cadence in one line, pointing to `page-design` (V1.1, S4.2); which
  page's hero section, pointing to `page-design` (V2.1); one-word composition per section (V2.4); two or three
  "done" lines (Q1.2).
- Several directions: one line on what makes this direction different; argument versus layout alternatives
  (R13.2–R13.3).

## 3. Case skills

Each covers its reader, what to read, message and tone, purpose, usual awareness, identity, fitting proof and usual
action (R2.3), and points to aspect skills for the how (S1.1).

**`one-to-one-page`**
- Reader and research: the account's overview, insights and claims; one insight in its own words, two or three
  priorities (R2.3); a page aimed at a role at the account, never naming the person (R10.3). Usually unaware or
  problem-aware: open on their situation.
- Shape: often five to seven sections with decision material, pointing to `decision-material` (R3.2, R4.2).
- Sources: leans on the research (W1.5); clone facts judged before use (W1.2); the research key (W5.4).
- Words: "could" implications, never numbers for the account (W2.2–W2.3, from `page-copy`); the account's own
  phrases verbatim where quoted (W7.5); bridge lines (W6.2); the hero describes the proposed system (W9.3); "How it
  could work at <account>" carries the could, no disclaimer (W4.5); positive framing, never the prospect's product
  negatively, relationship words (W11.2–W11.4).
- Proof: the short line near customer proof — each named customer's own result, not a promise for this account
  (W3.4).
- Action: the next step the brief names, at its real scope; no links away, a cited case study may open in a new tab
  (R5.1, R5.3).
- Identity and shell: "Prepared for <account>" lockup in the header, the account's logo only there, the hero names
  the account (R6.1); the account header template ("one page"), plain footer, no seller menu (R7.1).
- Hero: usually the home page's hero, adapted (V2).
- Review: the account checks — swap test, proof line, no named people (Q1).

**`contact-page`** — as `one-to-one-page` unless stated:
- The person's own sourced professional criterion or documented responsibility drives the material, which must
  differ from the account page; the reader may be named discreetly (an eyebrow), never as a navbar label; never
  private or sensitive interests, inferred pressure or assumed budget authority (R10.1–R10.2).
- Proof line (W3.4); research key and bridge lines (W5.4, W6.2); naming only the reader (Q1).
- Depends on the contact-page mechanics (R10.4, §7).

**`one-to-few-page`**
- From the brief, plus the ICP and personas and a few searches; no account set tagged (R2.5).
- A thesis the named group shares; never one member's facts projected onto all (R2.3).
- Shape five to seven (R3.2); action as one-to-one (R5.1, R5.3); header line names the group or is hidden, no single
  logo, the hero names the group (R6.2); account template, plain footer (R7.1); bridge lines, hero describes the
  system, relationship words (W6.2, W9.3, W11).

**`general-campaign-page`** (a whole audience)
- The audience's shared problem, broad language, from the ICP, personas and a few searches (R1.3a); often
  solution-aware from an ad: open on the approach.
- Shape like one-to-one (R3.2); sources lean on the seller's files and clones (W1.5); the segment's vocabulary
  (W7.5); a generated setting for the segment's industry is normal (M2.2).
- No account line or logo; the hero names the audience (R6.3); the shell is a judgement — minimal for one offer from
  one campaign, the seller-styled header with a few links when visitors will vet the seller (R7.2).
- Action: the demo, trial, contact or resource the brief names; a few relevant secondary links (R5.1, R5.3).
- Hero: usually the home page's hero (V2).

**`event-page`**
- Shape: what it is, why attend, agenda or speakers, the details, register (R3.2).
- Dates, times, places and speakers only from the brief or the seller's own event page (W1.5); register wording next
  to the real date, time and place (W10.6); ask if there is no date or place (R9.2).
- Minimal header with the seller's logo and the register button, plain footer (R7.3); no account markers (R6.3).
- Hero: an event or webinar page's hero when one exists (V2).

**`product-campaign-page`**
- Shape, the shortest: the promise, proof, product-specific case studies or testimonials, the action; for a
  one-product company also a customer logo wall and similar proof (R3.2).
- Match what the reader clicked: the offer and wording of the ad or email (R5.1, W7.5, W10.6); usually product-aware
  or ready to act.
- Pair each screenshot with what it shows (M4.3).
- Minimal header matching the ad, plain footer, one or two links to the product page or pricing when they help
  (R5.3, R7.3); no account markers (R6.3).
- Hero: usually the product page's hero (V2).

## 4. Aspect skills

**`decision-material`** (R4.2, R4.4): what to show for each reader question — a walkthrough, criterion → mechanism →
proof, a worksheet only as an optional later aid, attributed proof; explain before asking the reader to evaluate
*(moved here from the base skill; it is decision-material method)*; the utility test.

**`page-copy`**
- Clear beats clever (R3.4); a rewritten line not overly verbose (R4.3); no over-explaining, paragraphs of at most 20
  words (R4.6–R4.7); scannability, positive specificity, explain the product, no slogans (W8.1–W8.4).
- The claim ladder and verbs; conditional implications; never numbers or certainty for the reader; transformation
  words made concrete (W2.1–W2.5); numbers with short conditions, whose result in the line (W3.1, W3.3).
- Voice: sources in order, tone tuned to the seller's buyer, the buyer's words, the account's figures sparingly
  (W7.1–W7.4).
- Headlines: six tests and the formula; no slogans, puns or repeated account names (W9.1–W9.2, W9.4).
- Buttons and the offer: what the buyer receives in 2–5 words; the offer's five questions; wording may vary while the
  offer stays the same; no unestablished promises (W10.1–W10.4).
- The prospect: positive framing, never their product negatively, no committee labels, relationship words
  (W11.1–W11.4).
- Off the page: the one list, write your own words, the leaked-note test (W4.1–W4.3).
- **The final check on the words**, run from `page-review` group 2: the reworded final-check items, swap test, one
  primary offer, feature dumping (R4.4, R5.5, W rulings).
- *No text* on product limits (W4.4), forms (W10.5), exact wording (W12).

**`evidence`**
- The five sources at their strength; clones last and judged before use; web results shape the argument, facts
  only after `fetch_page`; never memory or skill examples (W1.1–W1.4).
- The research key — plain statement, quote, qualified, inference, gap, value narrative; facts versus
  interpretations; a signal is not a conclusion (W5.2–W5.3); the ICP is the seller's view of an audience (W5.4).
- Numbers: short scoping conditions stay, figures that need explaining go (W3.1–W3.2); relationship claims (R6.4).
- Finding and fitting customer proof (today's `account-page-copy` part 3); grounding before writing how the product
  applies (W4.6).

**`imagery-and-media`**
- The one image list and the order of sources; an image only for a real job; a diagram instead of a fake screen;
  searching well (M5.1–M5.5).
- The seller's image staging (M3.1–M3.3).
- Generation: reuse first; the seller's imagery type; never presented as the account's or as the seller's real logo
  or product; the prompt craft; look and retry once; text on the calm area (M2.1–M2.8; the old "must not show" line
  deleted, M2.3).
- Screenshots: the existing two lines; shows the product, not a result; never altered; readable on a phone
  (M4.0–M4.2, M4.6).
- Sharpness: never enlarged past natural size, search for sharper, the blur or bokeh exception (M6.1–M6.2).
- Logos: right version, unsure → leave out, never drawn or generated, the seller's logo not repeated (M7.1–M7.5);
  no implied partnership, logo walls (R6.4).
- Motion and video: the three-step ladder, no invented motion, still states, honest reporting (M1.2–M1.4).

**`page-design`** (S4): the seller's cadence of surfaces and density, remixed; dark sections as often and where the
seller puts them; a new section's surface between its neighbours; no uniform sections; the fallback (V1.1–V1.5);
which page's hero section, adapted, following the seller's archetype (V2.1–V2.3); headings across the page; never
shrink type (V4.2–V4.3).

**`page-review`**: the five groups (Q1.1) — the reader's read, words and claims (runs `page-copy`'s final check;
numbers trace to the plan, W6.3), buttons, looks like the seller's (V1.4–V1.5, V4.2), nothing broken at both widths
(M4.6); checks the plan's "done" lines (Q1.2); the loop with 3 renders per page and edits reviewing only the change
(Q2); motion honesty (M1.5); points to the system prompt's report shape (Q3).

## 5. Mechanics skills

- **`building-with-puck`**: R4.3's four-step reuse order, said once, with "leave the point out" last (X1.3–X1.4);
  buttons go to the primary action (R5.2); inherited clone buttons decided on purpose (R5.4); `menuExtra` by case
  (R5.3); the header section states the options and relationship-word rules, with the choice per case in the case
  skills (R6, R7, W11.5); image slots and brand-section images follow the one image list (M5.1); the old Rhythm rules
  replaced by a pointer to `page-design` (V1.5, S4.2); the "home page's hero" line goes (V2).
- **`writing-a-section`**: "when to use" per X1.2; `kit.Video` in the kit list (X3.1); the motion line follows M1.3
  (X3.2); props images follow M5.1; own header: relationship words (W11.5), primary action (R5.2); existing fidelity
  rules unchanged (V3.1).
- **`rebuilding-a-section`**: "when to use" per X1.1; keeps the original's video via `kit.Video` (R11.1, X3.4); the
  compare check unchanged (V3.1).
- **`making-a-section-interactive`**: rebuilding the seller's motion, a switcher as one linked component, a switcher
  example, a still state, no sound (M1.2–M1.4, X3.3).

## 6. Tool descriptions

- `web_search`: shapes the argument, also a little audience context; `fetch_page`: a fact needs its fetched page
  (W1.3, R1.3a).
- `view_asset`, `search_assets`: report each image's width × height (M6.3).

## 7. Code and product work (separate plans; ⚑ = architecture decision for the founder first)

| Item | Rulings | Where |
|---|---|---|
| ⚑ Skills listed, not pasted; `skills-e5` always listed; contract test for named paths | S2, X2.1–X2.2 | `lumen_agent/site/harness.py` |
| Untagged pages: honest research note, no title-as-account | R1.3 | `site_workspace_view.py:401`, `workspace.py` |
| Head of ABM's brief opens with who the page is for | R1.2 | `manual-siblings` new version + re-mint (another agent) |
| ⚑ Clarification tool and chat card for the site agent | R9.4 | site harness, design legs, chat |
| ⚑ Contact pages: tag, contact research reads, identity and use gates | R10.4 | design legs, workspace, platform reads |
| `brand/brand.md` motion text rewritten; asset heading corrected | M1.1, M5.1 | `site-kit/src/catalog.ts` |
| Clone cards list videos and motion | R11.4, M1.6 | `site-kit/src/catalog.ts` `cloneFile` |
| ⚑ `kit.Video`, video serving and Safari playback | X3.1, R11.4 | `site-kit/src/agent-kit.tsx`, `check-section.ts`, page origin |
| Image tools report width × height | M6.3 | `site/tools.py` |
| Header and footer style vs the seller's page (check, then fix if needed) | R7.5 | site-kit header/footer |
| Carousel brand section (then tabs) | M1.7 | site-kit sections (product work) |

## 8. Consistency check

- Every ruling R0–R13, W1–W12, M1–M7, V1–V6, Q1–Q3, X1–X3, S1–S4 has a home above or is a deliberate "no text"
  ruling (W4.4, W10.5, W12, V3, V6) or a process ruling (R0.2, R2.4, S1, S3).
- Fixed while compiling: **R7.5** is a code check plus the header mechanics (family 1 had said "VISUAL"); **R4.4**'s
  "explain before asking the reader to evaluate" moves from the base skill to `decision-material`.
- One rule, one home: the reuse order lives only in `building-with-puck`; the report shape only in the system prompt;
  the final check on the words only in `page-copy`; the five sources only in `evidence` (the system prompt has a
  one-line pointer).

## 9. Step 4 order

1. System prompt. 2. `planning-a-page`. 3. The six case skills. 4. `page-copy`, `evidence`, `decision-material`.
5. `imagery-and-media`, `page-design`, `page-review`. 6. The four mechanics skills and the tool descriptions.
Each piece is shown in full before anything is written into the repo; skill text stays uncommitted until the trials
(step 5); the code items in §7 get their own plans, the ⚑ ones with the founder first.

## 10. Cross-references (founder 2026-10-28: proper, mature inter-referencing at each stage)

How a reference is written: the exact skill name and, where it helps, the part — e.g. "read `page-copy` (Claims)".
A reference appears at the moment the agent needs it, says why in a few words, and never repeats the other skill's
rule. Every named skill and part must exist (checked by hand until the S2 contract test exists).

| From | At this point | Points to |
|---|---|---|
| System prompt | a new document starts | `planning-a-page` (always first) |
| System prompt | "Who this page is for" is decided | the matching case skill |
| System prompt | building `page.json` / `shell.json` | `building-with-puck` |
| System prompt | a section needs a new or rebuilt component | `writing-a-section`, `rebuilding-a-section` (and `making-a-section-interactive` on live sites) |
| System prompt | the five sources line; the off-page line | `evidence`; `page-copy` |
| System prompt | after `render_page` | `page-review` |
| System prompt | a follow-up edit | only the skill the change touches (S2.4, R12.1) |
| `planning-a-page` | step 2, who and at what scale | the six case skills, one line each on when each applies |
| `planning-a-page` | evidence needed and available | `evidence` |
| `planning-a-page` | the argument, on personalised pages | `decision-material` |
| `planning-a-page` | sections: cadence, hero, composition | `page-design` |
| `planning-a-page` | sections: reuse order, header and footer | `building-with-puck` |
| `planning-a-page` | sections: images and motion | `imagery-and-media` |
| `planning-a-page` | writing the words | `page-copy` |
| `planning-a-page` | the "done" lines | `page-review` (checks them) |
| Each case skill | its decision material (one-to-one, one-to-few, contact) | `decision-material` |
| Each case skill | its claims, voice, headline, proof line | `page-copy`; `evidence` (research key, sources) |
| Each case skill | its hero | `page-design` |
| Each case skill | its header and footer | `building-with-puck` (header section) |
| Each case skill | its logos and screenshots | `imagery-and-media` |
| Each case skill | its account checks | `page-review` |
| `contact-page` | everything not stated | `one-to-one-page` |
| `decision-material` | wording the exhibit; product screenshots; what may be stated | `page-copy`; `imagery-and-media`; `evidence` |
| `page-copy` ↔ `evidence` | a number or a quote: what may be used vs how it is written | each other |
| `page-review` | group 2, the words | `page-copy` (Final check) |
| `page-review` | group 4, looks like the seller's | `page-design` |
| `page-review` | the report | the system prompt's report shape |
| `imagery-and-media` | motion step 2, rebuilding motion | `rebuilding-a-section`, `making-a-section-interactive` |
| `imagery-and-media` | image slots | `building-with-puck` |
| `page-design` | surfaces by name | `building-with-puck`, `brand/brand.md` |
| `building-with-puck` | reuse steps 2 and 4 | `rebuilding-a-section`, `writing-a-section` |
| `building-with-puck` | rhythm; images; button words | `page-design`; `imagery-and-media`; `page-copy` |
| `writing-a-section` | look and motion | `page-design`, `imagery-and-media`, `making-a-section-interactive` |
| `rebuilding-a-section` | the original's video | `imagery-and-media` (Motion and video) |
| `making-a-section-interactive` | which motion to rebuild | `imagery-and-media` (Motion and video) |
