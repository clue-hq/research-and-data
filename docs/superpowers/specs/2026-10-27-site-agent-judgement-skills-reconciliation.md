# Site agent: reconciling the direction and judgement skills (map for review)

Status: **draft for founder review, 2026-10-27.** No skill text is written yet. This map decides
which skills the site-document agent holds, what each one covers, where its material comes from in
the legacy web-document skills, which contradictions must be ruled on, and how legacy wording is
translated into site-document terms.

Why: the first production site run (Pallet, 2026-10-26) built a careful but thin campaign page. The
site agent's only direction skill is `account-page-copy`, written for 1:1 account pages, so a
segment campaign page got the 1:1 shape (five sections, under 600 words, drop "brand videos"). The
legacy web harness holds richer direction material, written by Shashank in September, that the site
agent never received.

## 1. Ground rules (founder, 2026-10-27)

1. **One fixed skill set.** The site agent always holds the same skills, written in full into its
   instructions every turn. No skill is chosen per request. Judgement for 1:1, segment, product and
   event pages lives inside the same skills; the agent decides which part applies.
2. **Two families.** Mechanics (how a site document is built) and direction and judgement (what
   the page should argue, say and show, including creative and imagery choices).
3. **Bring the direction material over from the legacy web skills**, resolve every contradiction
   explicitly, and rewrite legacy web-document language in site-document terms.
4. Skill text is reviewed in chat first, written uncommitted, and committed only after trials.

## 2. Today

Site agent (7 skills, about 7,150 words with the prompt, all always present in production):

| Family | Skill | Words |
|---|---|---|
| Mechanics | `building-with-puck` | 2,437 |
| Mechanics | `writing-a-section` (skills-e5) | 1,148 |
| Mechanics | `rebuilding-a-section` (skills-e5) | 281 |
| Mechanics | `making-a-section-interactive` (skills-live) | 453 |
| Mixed | `images-and-logos` | 467 |
| Mixed | `page-review` | 247 |
| Direction | `account-page-copy` (1:1 pages only) | 1,302 |

The prompt itself opens with "You build landing pages for one named account".

Legacy web harness: about 21 website skills in
`subsystems/clue-design/apps/agent_runtime/knowledge_docs/skills/`. The direction ones read for this
map (about 30,800 words with references): `campaign-landing-page` (+ `argument-and-shell`,
`action-selection`, `page-directions`), `campaign-page-workflow`, `conversion-copywriting`
(+ `copy-craft`, `website-copy-brief`), `web-account-personalization` (+ `account-argument`,
`audience-modes`, `identity-and-evidence`), `web-contact-personalization` (+ worked example),
`web-decision-material` (+ worked exhibit), `web-product-story`, `web-media-composition`
(+ 2 refs), `web-motion-fidelity` (+ 3 refs), `plan-design`, `review-website` (+ 2 refs),
`clarify-design-brief`, `design-guidance`, `color-and-contrast`, `generative-imagery`,
`brand-imagery`, `reference-image-direction`.

## 3. The proposed fixed set

### Mechanics (kept; small fixes only)

| Skill | Change |
|---|---|
| `building-with-puck` | Move its judgement lines ("leave out clones that do not help this reader decide…", rhythm rules, header choice) into the direction skills; keep the mechanics. Header section updated per ruling R7. |
| `writing-a-section`, `rebuilding-a-section` | Video handling per ruling R3 (today: "if the original shows a video… use the closest brand image"). |
| `making-a-section-interactive` | Unchanged. |
| `page-review` (checking half) | Keeps the render checks: nothing broken, no overflow, words fit, up to 3 renders. |

### Direction and judgement (new or rewritten)

| Proposed skill | Covers | Built from |
|---|---|---|
| **`page-argument`** (new) | Who the page is for and in which mode (the audience-modes table: 1:1 account, 1:few, segment or 1:many, event, product page); the brief elements (traffic, audience, offer, action, evidence); the reader's awareness stage; the argument patterns with their failure modes (search-intent mirror, conversion scent, radical simplification, complex made simple, proof stack, real deadline, video-led, visual product-led, incentive capture); sections derived from the reader's questions; length by decision; header and navigation choice; one primary action chosen from the reader's decision; when to ask a clarifying question; the message plan in `plan.md`. | `argument-and-shell`, `action-selection`, `audience-modes`, `page-directions` (multi-version requests), `plan-design` (anchors only), `clarify-design-brief` (the rule), `account-page-copy` part 1 |
| **`page-copy`** (rewrite of `account-page-copy`) | How every sentence says it, for every mode: the brief is direction and you write every word; notes are not the page; say what it is; the reader's vocabulary; the claim ladder and verb discipline; proof language; calls to action; forms; people and the prospect; copy through slots; tone; positive framing; the final checklist. A short 1:1 part: turning research into the insight, proof on the seller's own site. | `account-page-copy` (most of it stays), `copy-craft`, `website-copy-brief`, `identity-and-evidence` (numbers and attribution) |
| **`decision-material`** (new) | Giving the reader something to examine: the decision map (relevance → mechanism → proposed application → proof or fit question → action); exhibit types by question; explain before asking the reader to evaluate; product stories paired with real product states; the substitution and utility tests. | `web-decision-material`, `account-argument` (decision map), `web-product-story` (its judgement half) |
| **`images-and-media`** (rewrite of `images-and-logos`) | Each image's role; enough pixels for where it is shown; reuse, generate or none per section; generation only for scene or mood, art-directed to the brand (prompt craft, coherence test); logos; **video and motion as a creative choice**: what each moving element is for, keep the content readable when motion stops, no dead controls. | `images-and-logos`, `web-media-composition` (judgement), `generative-imagery` and `brand-imagery` (prompt craft and coherence only), `web-motion-fidelity` (purpose and reduced motion only) |
| **`page-review`** (judgement half added) | After the render checks: read the page top to bottom as the arriving visitor; does every decision-map point have visible material; does the page argue enough, not only render cleanly; brand fit beside the clones. | `page-review`, `argument-and-shell` step 8, `review-website` (its content checks, not its tooling) |

Estimated size of the whole set: 10,000 to 12,000 words, always present (cached after the first call;
the Pallet run's context was about 61k tokens per call, 95% cached).

### Not brought over

- **Legacy web mechanics:** `create-website`, `edit-website`, `repair-cloned-sections`,
  `web-source-readiness`, `custom-components`, `campaign-page-workflow` (its strategy steps are
  folded into `page-argument`), the tooling half of `review-website`, `web-motion-fidelity` and
  `web-product-story`.
- **Per-section status tracking in the plan** (`plan-design`: planned / built / verified). It caused
  six status-only edits at the end of the Baseten run.
- **The measured typography audit** (`plan-design`, `design-guidance`): the site agent styles only
  through brand values by name; type is not measured by hand.
- **Ad and print skills:** `a4-poster`, `linkedin-banner`, `linkedin-square-ad`, `story-ad-9x16`,
  `web-display-banners`, `print-bleed-marks`, `reference-conditioned-ads`, `effects`, `create-design`,
  `repair-design`, `visual-review`, `brand-and-tokens`, `tools`, `reference-image-direction`.
- **Contact (named-person) pages:** see ruling R5.

## 4. Contradictions to rule on

| # | Site skills today | Legacy skills | Proposed resolution |
|---|---|---|---|
| R1 | Prompt: "You build landing pages for one named account". | Audience modes: 1:1, 1:few, segment/1:many, event, product pages. | The prompt says landing pages for an account, a group, a segment, an event or a product; `page-argument` decides the mode. |
| R2 | "The usual shape is five sections… rarely more than 600 words". | "Page length follows decision complexity: a considered enterprise purchase may justify seven sections; a high-intent giveaway justifies three… A minimal shell is not a reason to produce a thin page." | Length follows the decision; never pad, never cut what the decision needs. The 1:1 five-section shape stays as the usual 1:1 example, not a cap. |
| R3 | `account-page-copy`: drop "brand videos"; `rebuilding-a-section`: replace a video with the closest brand image; brand file: "Do not imitate" motion that needs a script. | Video-led pattern; reuse captured video when present; decorative motion may go, explanatory motion stays. | Keep a video when it explains the product or carries the argument (a captured section keeps its video); drop decorative or off-topic ones. Mechanics follow-ups: show videos on catalog cards, correct the brand-file note, let rebuilt sections show a video. |
| R4 | Light and dark brand sections alternate; at most one dark brand section; no two dark sections in a row. | "Neither a universal alternating-band pattern nor a one-chromatic-peak limit applies to every brand." Follow the brand's observed rhythm. | Follow the seller's observed rhythm (from its captured pages); the alternating rule is the default only when the seller's pages give no evidence. |
| R5 | "Never name people at the account." | Contact pages may identify their reader discreetly (an eyebrow), built from contact research. | Keep "never name people" for now: the site workspace holds account research only (overview, insights, claims), no contact research. Named-person pages become a later capability. |
| R6 | "Every button goes to the one destination the brief names for the offer." | Choose the action from the reader's decision; don't default to a demo; one primary action plus genuinely useful secondary links (resources, in-page links) on segment or product pages. | One primary action, from the brief when it names one, otherwise chosen from the reader's decision; secondary links allowed only on segment, event and product pages, never on a 1:1 page. |
| R7 | Header templates default to the one-page template with "Prepared for <account>" and the account's logo. | Shell judgment: native navigation, a minimal campaign header, or a hero-led page, decided by whether navigation builds trust or offers exits; no account line on non-account pages. | Map the judgment onto the site's options: 1:1 → one-page template with the account line; group or segment → hide the account line and logo or write a group line; segment or product page where orientation helps → page-menu template with `menuExtra`; otherwise the agent's own header. |
| R8 | `plan.md` holds the message plan and section list. | `plan-design`: anchors (user requirement / working choice / evidence), a brand audit naming the hero archetype, per-section status tracking. | Keep the site's light plan; add the anchors split and a one-line hero and rhythm note from the seller's pages (answers "why a centred hero?"); no status tracking. |

Not a contradiction, but clarified in `page-copy`: `account-page-copy` says keep as much of a clone's
original wording as fits; `copy-craft` says write every word yourself. They refer to different text:
the clone's published words may stay, the brief's sentences may not be lifted onto the page.

## 5. Translating legacy wording into site-document terms

| Legacy web-document term | Site-document term |
|---|---|
| `search_cloned_sections`, `inspect_cloned_section`, `view("cloned_section:…")` | `catalog/index.md`, the clone cards in `catalog/clones/`, `view_clone` |
| `assemble_cloned_sections`, `insert_cloned_section`, slot rebinding via `set_node_props` | a `ClonedSection` entry in `page.json` with `slots`, `replacements`, `links` |
| repair ladder, campaign variants, `repair_cloned_section`, compose raw or vocabulary | rebuilding a clone as a component (`rebuilding-a-section`), a brand section, or a new section (`writing-a-section`) |
| custom components (`.tsx` iframe) | `write_section` sections; `making-a-section-interactive` for state |
| `render_web_preview` at 1440/768/375, `view("preview:…")`, `view("review")` | `render_page` (1440 and 375) |
| `finalize_web_run` and outcomes | the final report |
| `workspace/plan.md` | `plan.md` |
| brand card (`brand_card.json`), `view("brand")` | `brand/brand.md`, `catalog/sections.md` |
| `read_account_research`, `read_claims`, `provenance(action="cite")` | `research/` files and `research/claims.md`; claim labels noted in `plan.md` |
| `asset(action="generate_image" / "use_library_asset")`, `view("asset:…")` | `generate_image`, `search_assets`, `view_asset` |
| `fetch_logo`, `bind_account_logo` | `fetch_logo`; the header's `account_logo` slot |
| `request_clarification` | not available to the site agent yet (see 6) |
| noindex, derived pages, `{{account.name}}` markers | not part of the site agent's work; leave out |

## 6. Mechanics and code follow-ups these rulings imply

- Catalog cards list a section's videos (`apps/frontend/packages/site-kit/src/catalog.ts`).
- The brand file's motion note ("Do not imitate them") corrected for videos.
- Rebuilt and new sections can show a captured video (a kit piece for video, or keep the clone).
- A clarification tool for the site agent, reusing the design leg's clarification cards.
- Video playback on published pages checked (the page origin serves whole files; Safari usually needs
  partial downloads).

## 7. Order of work

1. Founder rulings on R1–R8.
2. Draft each direction skill's substance in chat, one at a time: `page-argument`, `page-copy`,
   `decision-material`, `images-and-media`, `page-review`. Then the prompt and `building-with-puck`
   edits.
3. Write them uncommitted, with the site package tests' pins updated.
4. Trials, one page per mode (1:1 account, segment campaign, product page) on Conduit, Garner, Clue and
   Pallet; compare with the Pallet run of 2026-10-26.
5. Commit after the trials; the mechanics follow-ups in section 6 as separate changes.
