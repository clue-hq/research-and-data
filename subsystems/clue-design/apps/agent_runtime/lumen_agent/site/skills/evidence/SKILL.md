---
name: evidence
description: "Read when you decide which facts the page may use: the five sources and how far to trust each, web search versus fetched pages, reading the research files and their tags (quote, qualified, inference, gap), numbers and their conditions, relationship claims, finding customer proof on the seller's site, and grounding yourself in the product."
---

# Evidence

A fact reaches the page only from a source you can point to, at the strength that source gives it.
An empty section is a correct result; an invented fact is the only real failure. How to write a fact
once you have it is in `page-copy` ("Claims").

## Where facts come from

Five sources, each used at its own strength:

1. **The seller's files** (`seller/`): its products, proof and audience, and the project's confirmed
   ICP and personas.
2. **Pages you fetched** with `fetch_page`: the seller's published case studies and pages, the
   account's own site. Numbers and quotes come only from the page itself.
3. **The account's research** (`research/` and `research/claims.md`), claim by claim (below).
4. **The brief's facts**, at the strength the brief gives them and with their source when it names
   one. Never make one stronger than the brief does. When the research or the seller's files hold the
   same number, check it against them.
5. **The seller's own sections** (the clones in `catalog/clones/`) come last. Their words, figures,
   customer names and quotes are the seller's published claims, but before you use one, decide while
   you write whether it fits this page as it is or needs rewording; take most care on a page for one
   account. A number moved into new words keeps the clone's figure and whose result it is.

**Web search** shapes the argument: what a product does, what an audience cares about, where a case
study might be. A fact from a search reaches the page only after you open its page with `fetch_page`
and read it there. A search snippet is never evidence.

**Never a source**: your own memory of a company, and the examples written into these skills.

## Reading the research

The research files (`research/overview.md`, `research/insights.md`) are statements about the account,
each ending with the labels of the claims behind it, like `[c4, c9]`. `research/claims.md` lists each
claim: what it says, its source link and any notes.
- **A plain statement** `[c4]` is a sourced fact. Check its claim in `claims.md` before you use it,
  use the figure as the claim states it, and read its notes.
- **(quote)** is the account's own words. You may use them word for word.
- **(qualified)** is true only with its note. Use it with its condition (see "Numbers"), or not at all.
- **(inference)** is the research's own reading. It may shape your angle, at most as a "could"
  statement, and is never stated as a fact.
- **(gap)** is unknown. Never fill it.
- **A value narrative** in `claims.md` (Says, For, Angle) is the research's argument for a persona:
  input for your angle, never a fact on the page.
- **Watch-outs** and **Context only** are background for your judgement and never reach the page.

Keep three things apart: facts, interpretations, and the page's angle. A signal is not a conclusion:
a job opening is not a staffing problem, an initiative is not a budget, and a technology seen on
their site is not an integration.

**The ICP and personas** in `seller/` are the seller's view of an audience. On a page with no account
research they shape the angle and the vocabulary; they are interpretations, never facts about a
particular company.

## Numbers

- A short condition that scopes a number (a time window, a plan, a region, a company size) stays with
  it: in the same sentence, or the proof's source line.
- A figure that needs explaining to avoid misleading (combined with other costs, a reporter's
  estimate, one that needs a second clause) is left out.
- A customer's result always says whose result it is, in the same line.

## Relationship claims

Placing the account beside the seller never implies a partnership. Say a company is a customer or
partner only when a source establishes it, and at the scope it establishes. A customer logo wall
never includes the account or a company that looks like it (a similar name, a parent, a subsidiary);
`imagery-and-media` ("Logos") says how to check.

## Customer proof

The brief may suggest proof; treat it as a suggestion and look for the best fit.
1. Start with the seller's files.
2. Then search the seller's own site for case studies, customer stories and studies it has
   published: `web_search` with `include_domains` set to the seller's domain.
3. Prefer, in this order: the same customer; a customer in the same industry and of a similar size; a
   customer in the same situation (the same plan type, the same system); a study across many
   customers.
4. Open the page with `fetch_page`. Take numbers and quotes only from that page, with the customer's
   name.
5. Check that the proof fits the claim it will sit beside: read what the customer actually changed.
   If your line says "no change to your plan" and that customer changed its plan, the proof does not
   fit.
6. Use only pages the seller published. If nothing fits, use less proof, not weaker proof.

Record each fact you use in the plan with where it came from (`planning-a-page`, "The plan format").

## Grounding yourself in the product

Before you write how the product would apply to this reader, read the seller's product documents in
`seller/`, open the relevant pages of its site with `fetch_page`, and run a few searches until you
can say what the product does and how its parts fit together. Write only what that grounding
supports.
