# Issues captured by the Puck spike (phase 1 and phase 2, to 2026-10-08)

Running the agent and the design system is how these were found. Each issue names where it
lives, the evidence, and its state. "Platform" means our product's data or ingestion; "agent"
means the page agent's behaviour against its skills; "harness" means this spike's own code.

## Platform: capture, ingestion and data

1. **Scroll-driven pages are captured blank (Alt Carbon).** All five Alt Carbon fragments come from
   the home page. The hero fragment holds most of the page, with about 1,500 px of empty space where
   a scroll-animated part of altcarbon.com should be. "How we work" was captured as a heading over
   blank space. The purple announcement bar ("How India Eradicated Polio…") was captured as its own
   section. Evidence: `shots/altcarbon-v0-1440.png` (all three usable clones on one page).
   *Open. Platform capture (the known JS-driven-page limit).*
2. **Alt Carbon's captured sections have no solid button.** The only filled control is in the nav,
   which is not captured as a usable section, so the button could not be measured from the clones.
   *Open (platform); the spike theme now falls back to the kit's button tokens, not yet run.*
3. **Garner's kit is stored as "Doctor Quality Analytics".** `kit.json` → `name`. Any surface that
   shows the kit name shows the wrong brand. *Open. Platform ingestion.*
4. **Captured images carry no descriptions.** In phase 1 a background glow was picked as if it
   were a product shot. Captured images get only alt text or a generic "from the section X".
   *Open. Platform capture (image descriptions).*
5. **Brand kits hold usage rules that generic sections can break.** Each kit's `brief.constraints`
   (8–10 rules) and `grammar_audit` say things like "surface.brand… never a section band", "do not
   alternate section backgrounds", "buttons are pills". Our brand sections offer a `brand` surface
   and `brandSubtle` bands, so on Alt Carbon they would break the brand's own rules unless the rules
   reach the agent. Until now `brand.md` did not include them. *Open; `brand.md` now lists them,
   not yet run.*
6. **Thin research for most accounts.** Atrium: the insights page is not written
   (`refused:insights_not_written`) and the overview holds one fact (838 employees). Volvo (Alt
   Carbon) has 4 claims. Only Syracuse, Dana.AI and Mitsubishi Heavy Industries have full research.
   *Open. Research coverage.*
7. **A customer logo row can imply a relationship.** Alt Carbon's "Trusted by the best" row shows
   Mitsubishi Corporation, a different company from Mitsubishi Heavy Industries. On an MHI page that
   reads as "you are already a customer". *Open. A judgement the agent must make; worth a test.*

## Agent: behaviour against its skills (runs a1, b1, c1)

8. **a1 and a2 (Garner × Syracuse): proof chosen without checking its conditions.** It used Nightingale
   ("kept PPO and HDHP options") and left out that Nightingale's results came with deductible and
   HRA changes, next to a card saying no plan-design change is required. It never ran `web_search`
   on Garner's site, so it did not find the Aon study. a2 (a second run on the current harness)
   made the same choice with the same caveat, so this is consistent behaviour, not chance.
   *Open. A failing case for the copy skill's proof rule (founder to decide the change).*
9. **a1: brand sections over clones without a recorded reason** (proof and offer), against the
   skill's "record why". b1 and c1 recorded their reasons. *Watch.*
10. **a1: unbounded reading.** It opened 18 of 21 clone cards and fetched the privacy and terms pages
    (up to 12k characters each) only to check footer links. b1 and c1 used one search for links.
    *Watch.*
11. **b1 (Conduit × Dana.AI): a known flaw shipped because of the one-re-render cap.** The review
    found "Dana.AI." alone on a line; the fix did not hold, and the cap stopped a second try. The
    agent reported it honestly. *Open (founder decision on the cap).*
12. **b1: the button says "Start a conversation" but goes to the demo-booking page.** The copy
    skill says a button says what happens. *Watch.*
13. **c1 (Conduit × Atrium): seller-proof search not limited to the seller's domain**
    (`include_domains` unset). *Watch.*
14. **c1: review missed an empty gap before the closing section and the closing band touching the
    footer.** *Watch.*
15. **a1: final report said "did not re-render" although it did.** *Watch (report accuracy).*

What went right in all three runs: zero Puck mistakes (every page valid at its first validation),
small edits rather than rewrites, plan before page, honest left-out lists, and c1 kept to the
name-only brief over the research.

## Harness: this spike's code

16. **Mobile screenshots reached the model about 132 px wide** (long side capped at 2000 px).
    *Fixed after a1: pieces that keep their width.*
17. **Lost prompt cache mid-run.** a1's last call lost the whole cache right after context clearing
    first cleared ($0.16 of $0.82), so clearing was turned off. **Correction:** a2 lost the cache at
    call 9 with clearing off ($0.13 for that call), so the misses look provider-side (xAI through
    OpenRouter), not caused by clearing. *Open: measure misses across runs; clearing stays off.*
18. **read_file showed 100 lines by default** and cut a skill. *Fixed: whole files.*
19. **The validator held judgement checks** (numbers in evidence, named people, notes wording).
    *Removed by founder ruling 2026-10-08; one destination stays blocking for now.*
20. **No check that an internal `/route` link goes to a real page; no nav links in the shell; the
    workspace holds one page.** *Open; needed before multi-page edits.*
21. **The one-re-render cap trades a known flaw for cost** (see 11). *Open.*
22. **A clone's own links pointed at pages of our site.** Captured links are mostly relative to the
    seller's site (Garner 24 of 28, Conduit 51 of 53, e.g. `/book-a-demo`); any the agent did not
    replace became broken links on our pages (a1, b1, c1 likely have some), and with several pages
    they could collide with our page names. *Fixed: the clone renderer makes untouched captured
    links absolute against the clone's source page; links the page writes stay ours.*
23. **Multi-page support for the agent.** *Built: `pages/<name>.json` beside `page.json`, nav links in
    the shell (and in the human shell editor), every page validated, links the page writes to
    `/<name>` must go to a page that exists, one destination checked across the whole site,
    `render_page(route)`, versions and restore cover every page. Skill and prompt text pending
    founder review.*

## E2: ten edits in one session (run a3, 2026-10-08)

24. **Edit 7 invented a change.** Asked to shorten "the four cards" on a page that had none, the agent
    added Garner's four-card clone with new text instead of saying so (as it did for the logo row in
    edit 6). The clone brought back the customer-logo row edit 6 had asked to hide; the agent knew
    and went ahead. *Open. A failing case for "change only what was asked" (candidate prompt rule:
    when the request names something not on the page, say so and ask).*
25. **Edits removed earlier work without asking.** Edit 10 ("more premium") dropped the four cards
    and the offer-area link to /analysis that edit 9 added (the page stays reachable from the header
    nav). Edit 4 also changed the closing band's surface to keep the rhythm rule. Both explained.
    *Open (judgement).*
26. **One growing session makes edits slow and expensive.** Input per call grew from 83k to 214k
    tokens over the run; calls took 50–160 s; edits cost $0.21–1.65 (average $0.60) and about 7
    minutes each, against the plan's $0.05 and one minute. One cache miss on a 208k-token call cost
    $0.83 alone. *Open: test a fresh session per edit with the files as memory.*
27. **The agent cannot see images.** It tried `read_file` on asset paths, failed, and picked an image
    blind (a Garner graphic with its own baked-in text). *Open: a way to view an asset, or a contact
    sheet of the brand's images (relates to issue 4).*
28. **Theme bug: on the `inverse` surface, ProofCard's heading and metric use the brand heading ink**
    (Garner's forest green on near-black, nearly unreadable). The agent spotted it in the render and
    switched surfaces. *Open (harness theme).*
29. **A FeatureSplit with no image looks like an empty frame** (edit 9's "see the analysis" band;
    edit 10 removed it). *Open (component: a text-only layout when there is no image).*
30. **Defensive copy on the proof heading** ("Another employer's result — not SCSD's"), against the
    copy skill's positive framing. *Watch.*

What went right in E2: zero validation errors in 79 calls; edits 1, 2, 3, 5, 6, 8 and 9 exact or
sound; edit 2 chose Metal Exchange for the right reason (same plan and network as the new hero);
edits 6 and 8 correctly said there was nothing to change; multi-page (a new page, header nav, a
link) worked first time.

## E2b: the same ten edits, a fresh session each (2026-10-08)

Edits cost $2.73 in total ($0.27 average, 2.7 minutes average) against a3's $6.03 ($0.60, 7
minutes). 8 of 10 exact or sound, 2 partial (edit 4 again lightened the closing band; edit 9
re-pointed the offer's main button to /analysis, adding a click before the request), 0 failed.
Edit 7, a3's failure, now correctly says there are no four cards and asks. 0 validation errors in
102 calls.

31. **Context clearing costs more than it saves in short sessions.** Each clearing (planning over,
    a new render) made the next call miss the whole cache (128 tokens cached): $0.76 of E2b's $2.73
    went on those calls, while clearing saved about 10k tokens a call. Grok reuses only an unchanged
    prefix, so stubbing an early message invalidates everything after it. *Open: clear only once a
    session passes about 60k tokens.*
32. **`plan.md` upkeep takes many calls in edit sessions** (edit 2: 9 of 15 calls, including a
    refused full rewrite; edit 5: a mixed-up plan repaired). *Open: with history.md written by code,
    small edits may not need plan.md updated.*
33. **site.md does not say what is inside the seller's sections** (edit 6 spent 9 calls looking for
    a logo row in clone cards and an old screenshot). *Open: a one-line "contains" note per clone.*
34. **Skills are re-read in every session** (about 6k tokens each time). *Open: carry them in the
    cached system prompt.*

## E5: the agent writes a new section (2026-10-08)

The agent checked the catalog first, recorded that no clone or brand section carries a three-step
process, wrote `AnalysisSteps` with write_section (passed the brand-token check and type check on
the first attempt), placed it on the light page surface between the proof and the close, and it
validated first time. 13 calls, $0.35, 3 minutes, 1 render. On the render it reads as Garner's: the
brand serif heading in its heading ink, the brand eyebrow, card corners, body type and spacing match
the sections around it; the steps' facts come from Garner's analysis page.

35. **The agent cannot see the exact token class names** (which `text-ink-*`, `border-line-*`,
    `rounded-*` exist). It probed with grep and listed folders outside its workspace. *Open: a short
    list of allowed token classes for E5 (from the generated theme).*
36. **Flat props** (`step1Title`, `step2Title`, `step3Title`) instead of a list of steps, so the section
    holds exactly three. The skill's example has no list prop. *Watch.*
37. **Step titles use the body size** (`font-body text-body brand-heading`), so the hierarchy inside
    the cards is weak. *Watch (taste).*

## E5b: the same request, the skill without its example, theme and kit to read (2026-10-08)

It read brand/theme.css and brand/agent-kit.tsx without searching, wrote AnalysisSteps (passed the
check first time), valid first time; 14 calls, $0.34. Compared with E5:

38. **Props stayed flat** (`step1…step3`) without the example, so the example was not the cause; the
    request naming three steps is the likelier one. (Founder hypothesis tested; not confirmed.)
39. **The example had carried two conventions the references do not:** `brand-heading` (the class that
    gives headings the brand's measured heading ink: E5b's heading is near-black, rgb(14,17,16),
    beside Garner's green, rgb(1,64,54)) and "kit.Shell already sets the width and padding" (E5b added
    its own container: the cards sit 24 px in from the proof card's edges and the section is 154 px
    taller). Its render review did not catch either. *Open: list brand-heading in theme.css and show
    what Shell does in the kit's source (input data, not rules).*
40. **The token list did help** (stat-style step numbers, subtitle-size titles, no probing for names).

## Run a4 (Syracuse, after the proof bullet and the 3-render limit, 2026-10-08)

41. **The proof bullet did not change the choice.** a4 searched, saw Metal Exchange, and still chose
    Nightingale ("to keep one analog"), next to a page saying no plan-design change is required. The
    skill ranks "same industry and size" above "same situation", and its fit check is a later bullet.
    *Open: make the fit check a gate before the preference order (text proposed to the founder).*
42. **The mobile header truncates a long account name** ("Syracuse City School Dis…"), noted by the
    agent itself. *Open (harness shell: wrap to two lines on narrow screens).*
43. **The 3-render limit worked:** two extra review rounds fixed orphan words. 20 calls, $0.99, 7.1 min.

## Component library spike (run cl3, 2026-10-08)

Our agent rebuilt five Garner clones as components from brand tokens only (`view_clone`,
`compare_section`, the `rebuilding-a-section` skill), then built the Syracuse page from them.
6 turns, 107 calls, $3.66, 58 min; two stopped runs before it cost $0.67.

| Section | Component | Writes (refused) | Difference, first → final (1440 / 375) |
|---|---|---|---|
| Hero (video background) | PhotoHero | 3 (1) | 61% / 65% → 54% / 46% |
| Four cards + logos | AudienceBand | 4 (1) | 4% / 9% → 4% / 9% |
| How it works (3 rows) | AnalyticsFeatures | 4 (1) | 12% / 22% → 12% / 22% |
| Proof band (dark) | ProviderInsights | 4 (0) | 12% / 12% → 12% / 13% |
| Closing panels | SplitCta | 3 (2) | 41% / 72% → 16% / 29% |

44. **Brand tokens carry structure.** Every rebuild matched its original's layout, with repeated
    items as lists. The page used PhotoHero and AnalyticsFeatures (four rows of Syracuse copy, where
    the clone could only change some words) plus four brand sections; it left out AudienceBand,
    ProviderInsights and SplitCta ("brand would be a second dark band"). 23 calls, $1.15, 3 renders.
45. **Fixed during the run: write_section's type check checked nothing** (it inherited tsconfig's
    exclude of agent-runs/). Run cl1 stopped; fix 300af574a. E5's section happens to type-check.
46. **Fixed during the run: Tailwind skipped the agent's section files** (git-ignored; a full scan
    skips them), so a class used only there got no CSS and comparisons were wrong or flaky. Run cl2
    stopped; fix b1f3ab458.
47. **The agent saw 4 of the kit's 12 type roles.** brand.md lists display, headline, title, body;
    the theme maps all 12. `body.small` (14 px) matches Garner's card text exactly; the agent used
    16 px. *Open (spike harness): list every role, measured or derived. Founder 2026-10-08: not
    needed for the spike; required in production.*
48. **Kit coverage gaps (platform ingestion):** no role for 18 px serif card titles; 8 of 12 roles
    derived, not measured (subtitle 20 px where the page uses 18); Garner's dark-green bands
    (#004036) are not a surface (brand is #047464, inverse #111210). *Open: production.*
49. **Kit gaps (spike, then production):** no "contain" image fit (logos crop); one button style
    (Garner's outlined button had to be hand-written); links written as plain `<a>` skip the kit's
    link resolution; a two-panel section must still declare one section `surface`; the check does
    not confirm a brand class exists (`bg-surface-brandSubtle` passed).
50. **Every fresh session paid one refused write on kit prop names** (`file` for `src`, children for
    `label`). *Fixed: the kit list shows each piece's props (founder-approved 2026-10-08).*
51. **In 3 of 5 turns the agent wrote a fourth version after its last comparison**, so the final
    version was never compared (I compared them afterwards: no worse). *Kept as is (founder
    2026-10-08).*
52. **The pixel score misleads** when the image must change (hero: 61% → 70% while visibly closer)
    and barely separates dark colours. The pictures carried the judgement.
53. **With fresh sessions only the last session's transcript is saved**, so earlier turns' exact
    comparison props are lost. *Open (harness): save the transcript per turn.*

## R1 (research input) and R3 (images): runs r1a/r1b, 2026-10-10

Syracuse (case A) and Dana.AI (case B), each built twice in one build turn: with the claim labels
and `research/claims.md` (`-claims`) and without (`-base`, `--no-claims`). All four had the brief
as direction, every statement type with its notes, the Watch-outs / Context only sections as
background, `generate_image`, and the account's logo in brand.md.

| Run | Cost | Calls | Time | Renders | claims.md opened | Figures on the page | Untraced | Images |
|---|---|---|---|---|---|---|---|---|
| r1a-base | $0.91 | 20 | 6 min | 3 | — | 6 | 0 | clone images only |
| r1a-claims | $0.98 | 21 | 7 min | 3 | 2× | 9 | 0 | 1 generated (used) |
| r1b-base | $0.86 | 19 | 6 min | 3 | — | 2 | 0 | 1 brand image placed |
| r1b-claims | $0.99 | 20 | 7 min | 2 | 4× | 2 | 0 | 1 brand screenshot placed |

"Figures" are the numbers the agent wrote (years and small counts left out); every one traced to
the research, the claims file, the seller's files or a page it fetched. No run put a quote on the
page.

54. **R1: no fabricated figure in either arm.** With the claims file the agent opened it (2× and
    4×) and wrote more account-specific detail (Syracuse: the plan names, Excellus, the actuaries
    behind the $4.2 million; Dana.AI: "names the same job"), at about $0.07–0.13 more per build.
    Two accounts are too few to call it; the difference is detail, not accuracy.
55. **r1b-base put the seller's private strategy on the page.** Its closing line reads "overlap,
    coexistence, a geographic split, or a referral into hotels", taken from a research inference
    (`overview.md:44`, how to approach Dana.AI) and the brief's referral note. The claims arm did
    not. *Open: worth a line in account-page-copy (an inference about how to approach the account
    is for you, not for the page), founder to approve wording.*
56. **R3: one image generated in four builds.** r1a-claims made a school-campus exterior (1536x864;
    no people, no words, no logos) for a section headed "For Syracuse City School District". It
    follows the rules, but beside that heading it can read as SCSD's own building, which the skill
    forbids. *Open: judge with the founder.* The Dana.AI runs looked at one brand image each
    (`view_asset`) and placed it; r1a-base changed no image.
57. **R3: the account's logo.** Dana.AI's symbol (`light_mark`) sits in both Dana.AI headers;
    Syracuse has none (Brandfetch identity mismatch, and the district's domain does not resolve from
    this machine).
58. **Image cost not yet measured.** The spike opens no spend scope, so the provider records no cost;
    the OpenRouter key's usage rose by exactly the four builds' model cost ($3.74) right after the
    runs, so the image charge had not landed yet. *Open: re-read the key's usage later.*

## Changes made for an Alt Carbon run, not yet run (uncommitted)

- `export/export_brand.py`: Alt Carbon added (kit `brand_kit_ing_28663a…`, version 1).
- `scripts/build-catalog.ts`: `brand.md` gains a kit-name column for surfaces and the kit's own
  rules (issue 5). This changes the input for every brand, so later runs of A–C are not directly
  comparable to a1, b1 and c1.
- `lib/theme.ts`: the kit's button when none was measured (issue 2).
- `agent/run_agent.py` and `agent/cases.json`: a case from a workspace with no design run (case D,
  Alt Carbon × Mitsubishi Heavy Industries, which has full research). No brief written.
