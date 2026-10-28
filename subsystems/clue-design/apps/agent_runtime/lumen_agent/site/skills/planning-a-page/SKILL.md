---
name: planning-a-page
description: "Read first on every new site, before you write plan.md: the eight questions that turn the brief into a plan (the task, who the page is for, where they arrive from, what they know, the offer, the evidence, the argument, the sections) and the format plan.md takes."
---

# Planning a page

A landing page works when its reader sees, within a few seconds, what this is, why it matters to
them and the one thing to do next, and when every section after that answers a question they still
have. This skill walks you through the questions that get you there, in order. Work through them
before you build, and write the answers in `plan.md`.

Research is input, not prose. The brief, the research and the seller's files decide what the page
argues. The words on the page are your own, written with `page-copy` once the plan is done.

## The eight questions

### 1. What is the task?

Read the person's message, the brief and the artifact's note. Say in one line what you were asked
to make.

When the note names a direction (one of several pages for the same aim, each its own document),
add one line on what makes this direction different: its reader or decision, its opening message,
its decision material, its section order or its visual emphasis.
- A direction with a different argument makes a genuinely different case, not the same case in
  other words.
- A direction with a different layout keeps the agreed words and changes the composition: the
  hero's arrangement, what each section does, visual weight, media.
- The brand stays the same either way. Shuffled sections, new colours or new icons are not a new
  direction.

### 2. Who is this page for, and at what scale?

This names the kind of page. Decide it from the brief, the artifact's note, the person's message
and whether `research/` holds research for an account:

- **One account**: a page for one named company (or a role at it).
- **One person**: a page for one named person at an account.
- **A few named accounts**: a page for a small group the brief names.
- **A whole audience**: a segment such as freight brokers, or finance leaders at mid-size retailers.
- **An event**: a page people register from.
- **A product campaign**: one product or offer, for anyone arriving from an ad or an email.

Write it as the first line of your plan: "Who this page is for: …", as a role and a scale. Then
read `page-kinds` and the reference for your kind: it says what to aim for on that kind of page.

When no account is tagged (`research/` has no research for one):
- Name the site and its headings for the page's real context (its audience, event or offer), never
  as if it were for an account.
- Read the confirmed ICP and personas in `seller/` (`seller/index.md` names them), and run a few
  `web_search`es for a little context about the audience. What such context may put on the page is
  in `evidence`.

If nothing in your workspace tells you who the page is for, that is a reason to ask (the system
prompt, "When to ask").

### 3. Where do they arrive from?

An email, an ad, an event invite, a sales follow-up, a link from the seller's site. The brief
usually says. When it doesn't, assume a cold reader arriving from an email or an ad, and write that
down as an assumption. Where they come from sets what they expect to see first: a page reached from
an ad continues the ad's offer and wording.

### 4. What do they already know?

How aware they are of their own problem, of this kind of solution, of the seller and of this offer.
A reader who does not see the problem yet needs the page to open on their situation. A reader who
clicked an ad for a product needs the product and the offer straight away. The reference for your
kind says what is usual.

### 5. What does the page offer, and what is the one decision?

Choose the action from the reader's decision, never from the seller's homepage button and never
because a booking link happens to exist.

| The reader's next job | A fitting action, when it really exists |
|---|---|
| Understand why this matters to them | Reading on: a walkthrough on the page itself |
| Compare fit, or prepare an internal review | An evaluation section, or a resource the seller has published |
| Move an active opportunity forward | The next step the brief names (a meeting, an assessment, a proposal), at its real scope |
| Attend an event | Register, with the real date, time and place |
| Try or buy | The real trial, demo or purchase flow |

Write four things: the reader's decision, what they receive, the button's words and its
destination. The page has one primary action. Every button for it leads to the same offer and the
same destination, the header's button too, and it sits at the decision points (after the promise,
after the explanation, at the close), not in every section. How to word it: `page-copy`
("Buttons and the offer").

### 6. What evidence does the page need, and what is there?

For each thing the reader must believe, find what supports it before you write it. `evidence` says
where facts may come from, how strong each source is, how to read the research and how to find
customer proof on the seller's own site.

Before you write how the product would apply to this reader, ground yourself in the product: read
the seller's product documents in `seller/`, open the relevant pages of the seller's site with
`fetch_page`, and run a few searches until you can say plainly what the product does and how it fits
together. Then write.

### 7. What is the argument?

The chain from the reader's situation to the action: what they are working on → what the seller
does about it → how it could work for them → why they should believe it → what to do next.

On a page for one account, one person or a few named accounts, read `page-kinds`
(`references/decision-material.md`): it says what to show for each question the reader has.

### 8. Which sections, and what is left out?

Substance before container: first write what each section must explain, then choose the section
that can carry it. Each section answers one question this reader still has, and no two sections
make the same point.

Length follows the decision. There is no fixed number of sections or words: nothing is padded to
look complete, and nothing the decision needs is cut. Give each section a rough word budget, set by
what it has to explain rather than by the clone's original slot. It is a planning aid, not a limit.

Leave out what does not help this reader decide: navigation, newsletters, resource lists, general
testimonials, whole case-study articles, and embedded press-play videos (a video player, a brand
film). Keep a short demo player only when it directly shows what the page argues. Keep the seller's
ambient motion (background loops, animated heroes, motion used for the look): it is part of the
seller's design (`imagery-and-media`, "Motion and video").

For the sections themselves:
- Which sections to reuse, rebuild or write, and the header and footer you can use:
  `building-with-puck` ("Reuse first", "The header and footer"). Write which header and footer you
  chose, and why, in the plan. The person's explicit request wins, and a shorter header or footer
  never removes something the decision needs.
- The seller's cadence of surfaces and density, which of the seller's heroes opens the page, and
  each section's composition: `page-design`.
- Images, logos and motion: `imagery-and-media`.
- The words: `page-copy`.

## The plan format

Write the plan at the top of `plan.md` before you build. It is a short working note, not a form to
fill: write what this page needs and leave out what it doesn't.

The example below is made up, to show the shape of a plan: an imaginary seller, Northwind, whose
software matches and approves supplier invoices, planning a page for an imaginary account, Lakeside
Group. Take inspiration from its shape; never copy its words, and never use it as facts. Your facts
are in your workspace.

```markdown
Who this page is for: the finance operations lead at Lakeside Group (one account). Cold, from a sales email.
They know: their own late supplier payments; little about Northwind.
Decision: whether an invoice review is worth 30 minutes.
Action: "Request the invoice review" → https://northwind.example/review
Seller's cadence (home page): light hero, dense detail, product visual, proof, one dark band, light close.
Hero: the home page's hero, words changed.
Fonts: headings in the seller's serif, regular weight; body in its sans.
Header and footer: account header (one page) and the plain footer; one account, so no links away.

## Sections
1. hero (split): what this is, for Lakeside. ~25 words.
   - Lakeside is moving its 12 regional offices onto one finance system in 2026 [c3]
2. priorities (three cards): their two priorities, in their words. ~70 words.
   - Bridge: Lakeside wants fewer late supplier payments [c5] → Northwind sends each invoice to its
     approver automatically [seller/product.md] → "could help Lakeside pay suppliers on time"
3. proof (proof strip): a similar company's result. ~40 words.
   - Harbor & Co. cut invoice approval from 9 days to 3 in 2025 [https://northwind.example/harbor, fetched]

Left out: the newsletter band; the brand film (a press-play video).
Assumptions: a cold reader from email (the brief does not say).
Done when:
- the hero names Lakeside and the review, with the button on the first screen at both widths
- each priority is in Lakeside's own words, with proof beside it
- one dark band, where the seller puts it
```

- **Facts for each section**: the facts it uses, one line each, with where each came from (a claim
  label, a seller file, the address of a page you fetched, a clone) and any short condition that
  goes with it (a time window, a plan, a region).
- **Bridge lines**: on a page for one account, one person or a few named accounts, each benefit
  statement gets one line: their priority [source] → the seller's capability [source] → the
  sentence on the page.
- **Cadence, hero and fonts**: one line each, as `page-design` says.
- **Composition**: one or two words for each section (split, centred statement, editorial stack,
  proof strip, three cards).
- **Done when**: two or three lines saying what this page must have to be finished. Write them
  before you build; `page-review` checks them.

Read the plan again before you write each section, and when you review. If you change your mind,
change the plan first and say why.
