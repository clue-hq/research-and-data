# Draft skill — account-page-copy (for founder review)

Sources: the Claude 1:1 ABM copy skill (structure: Parts 1, 2, 4, 5, 7, 8, 10), Ploy's copywriting
skill (sentence rules, claim ladder, modal verbs, failure modes), and the Syracuse trial
(`2026-10-06-syracuse-copy-trial.md`, the worked example). Not yet wired into the agent.

Files it would ship as:
- `knowledge_docs/skills/account-page-copy/SKILL.md` (below)
- `knowledge_docs/skills/account-page-copy/references/worked-example-syracuse.md` (the trial)

---

```markdown
---
name: account-page-copy
description: Use when planning or writing the words of a landing page for one named account (a 1:1 page), before building any section.
---

# Account page copy

A 1:1 page is written for one company and one reader. It works when that reader sees, within a
few seconds, that you understand what they are working on, what you offer, and the one thing to
do next. Clear beats clever. Short beats complete.

## 1. Write the message plan first

Before you build or write any visible words, read the account's overview and insights pages, the
seller's files, and the cloned sections you might use. Then write this block at the top of
plan.md:

- **Reader:** the one person the page is for, as a role, never a name. One line on a second
  reader if there is one.
- **Insight:** what the account is working on, in its own words, with its source. One insight.
- **Priorities:** two or three things the reader cares about, each tied to the research.
- **Offer and action:** the one next step, its button label, and its checked link.
- **Proof:** the case studies or studies you will use, with links, and why each one matches
  this account.
- **Sections:** up to five. For each: the one question it answers, the cloned section it starts
  from, and a word budget.
- **Left out:** what you chose not to say, and why.

Read this block again before you write each section and again in your final check. If you change
your mind, change the plan first and write down why.

## 2. Turn research into the insight

- An insight is something the account has said or done that your offer speaks to: a budget
  line, a plan, a project, a hire, a stated goal. Its size or location is not an insight.
- Prefer the account's own documents (budget, plans, filings, its website) over press about it.
- Use their words. Use at most one or two of their own figures on the whole page.
- Say what they did in plain words. Never put file names, line codes or claim ids on the page.
- If a figure needs a condition to be true (it is combined with other costs, it is a reporter's
  estimate), leave it out rather than explain it.

## 3. Find proof on the seller's own site

- Start with the seller's files. Then search the seller's own website for case studies,
  customer stories and studies the seller has published: `web_search` with `include_domains`
  set to the seller's domain.
- Prefer, in this order: the same customer; a customer in the same industry and of similar
  size; a customer in the same situation (same plan type, same system); a study across many
  customers.
- Open the page with `fetch_page`. Take numbers and quotes only from that page, with the
  customer's name.
- Check that the proof fits the claim it sits beside. Read what the customer changed. If the
  page says "no plan change" and that customer changed its plan, the proof does not fit.
- Use only pages the seller published. If nothing fits, use less proof, not weaker proof.

## 4. Build from the cloned sections

- Start every section from the closest cloned section of the seller's site. Keep its layout,
  images and rhythm.
- Keep as much of its original wording as still fits this account. Rewrite only the words that
  are generic or speak to the seller's homepage audience. If a line already fits, keep it.
- Remove sections that do not help this reader decide (brand videos, newsletters, resource
  lists, general testimonials) instead of filling them.
- Write a new section only when no cloned section can carry the point, and record why in the
  plan. This is the last option.

## 5. Write the page

The usual shape is five sections, as short as the decision allows (rarely more than 600 words):

1. **Hero:** what this is, for this account. Say what it is or what it achieves, who it is for,
   and one qualifier. A result in the headline needs attributed proof of that result further
   down the page. One button.
2. **Their priorities:** two to four short cards. Each starts from their situation in their
   words, then says what changes.
3. **How it works:** in their setting, naming their systems where you know them.
4. **Proof:** attributed to the customer or study it came from, next to the claim it supports.
5. **Offer:** what they get and the one button.

For every sentence:

- Use the reader's words for their world. Explain a product name the first time you use it.
- Keep claims at the strength the evidence allows, from strongest to weakest support: a product
  fact; what the product can do; a named customer's result; what it could mean for this account
  ("could"); a forecast for this account (never).
- Use "will" only for what certainly happens ("clicking opens the form"). Use "can" for what
  the product does and "could" for what it might mean for them.
- Say what stays and what improves. Do not tell them their current setup is broken.
- Every button says what happens ("Request the analysis") and goes to the same checked link.
- Never imply the account is already a customer or partner. Never name or describe individual
  people at the account.
- Notes, caveats, strategy and reasons go in plan.md and your final report, never on the page.

## 6. Final check

Read the page as the reader would, then go through each line below. Fix what fails, or record
in the plan why it stays.

- The first screen says what this is and who it is for.
- Each section answers its one question from the plan and stays within its word budget.
- Mystery-box headline: the headline sounds ambitious but does not say what the offer is.
- Investor pitch: the copy talks about the category instead of value to this reader.
- Audience dilution: the page speaks to everyone instead of this reader.
- CTA competition: there is more than one offer or destination.
- Feature dumping: capabilities are listed without tying them to this reader's decision.
- Benefit inflation: a capability is written as a guaranteed result.
- Metric mutation: a source number has been turned into a different claim.
- Unattributed proof: a number appears without whose result it was.
- False relationship: wording suggests the account is already a customer or partner.
- Negative assumption: the page says their current setup is failing without evidence.
- Jargon stacking: several product or industry terms appear without plain explanation.
- Redundant subheadline: the supporting line repeats the headline.
- Generic CTA: a button says "Learn more" instead of what happens.
- Form creep: the form asks for more than the next step needs.
- Buried proposition: the offer appears only below abstract sections.
- Swap test: if a sentence would fit any other account unchanged, make it specific or cut it
  (product facts are the exception).

For a finished example of the plan and the page, read
[worked example](references/worked-example-syracuse.md).
```

---

## Notes for review

1. **Hero result claims (founder ruling 2026-10-07):** the hero may state a result, as the
   trial's "Lower medical spend for SCSD" does, when attributed proof of that result appears
   further down the page (the Aon study). This departs from Ploy's offer-only hero.
2. **What this replaces.** For 1:1 pages it takes over the account parts of
   `conversion-copywriting/references/copy-craft.md`,
   `web-account-personalization/references/account-argument.md` and
   `campaign-landing-page/references/argument-and-shell.md`. The identity and allowed-use limits
   in `web-account-personalization/references/identity-and-evidence.md` stay. Exact changes go
   in the spec.
3. **Not included yet:** the proof qualifier sentence (you said you'd come back to it), and the
   `web_search` tool description, which currently says "use this last" and has to change for
   section 3 to work.
