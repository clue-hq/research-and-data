---
schema_version: '1'
kind: skill
name: account-pages
version: v1
summary: Write an account's Overview and Insights pages around one short argument for why this seller should pursue the account now.
roles:
- research_narrative
readiness_requirements: []
tools: []
framework: deepagents
framework_version: '>=0.6,<0.7'
---

# Write the account's Overview and Insights

Follow the shared page-writing rules. You are given the seller brief, the account's findings (ids
like `F012`), and — when person research has finished — findings about the people on the buying
committee (ids like `P2:F007`, where `P2` is the person's number in the committee list). Person
findings often hold the best evidence: what the people who own the problem have said and done.
Use them on the account pages wherever they strengthen the argument.

## Length

A rep should take in the Overview in about a minute. Stay within these numbers; use fewer items
when the evidence is thin:

| Section | Intro | Items |
|---|---|---|
| what-they-do | up to 3 sentences | none |
| why-they-fit | 4 to 6 sentences (the short version) | up to 3, plus the ICP check |
| why-now | up to 1 sentence | up to 3 |
| buying-committee | up to 1 sentence | up to 5 |
| how-to-approach | up to 1 sentence | up to 3 |
| watch-outs | none | up to 5 |
| buying-signals | up to 1 sentence | up to 5 |
| money-and-momentum | none | up to 3 |
| tools-they-already-use | none | up to 4 |
| how-they-sell | none | up to 2 |
| miscellaneous | none | up to 4 |

Give each item at most three sentences (the ICP check takes one line per criterion). Short sentences
read faster than long ones. If you have more good material than fits, keep the strongest and drop the
rest — the research record keeps everything. Opening lines for emails belong on contact pages, so do not put
`send_line` on account sections.

## Overview

The Overview is what most readers will see. It must make the case in under a minute of reading.

### what-they-do — What they do

Two or three sentences: what the company does, for whom, at what scale, in plain words. Nothing about
the seller here. Put this in `intro`; no items.

### why-they-fit — Why they fit

**`intro` is the short version of the whole account**, four to six sentences, written for the rep:

1. why this account matches what the seller sells (the strongest facts, joined);
2. why now (the most recent change that makes outreach timely);
3. who to talk to first and why them;
4. what to lead with.

Write it as an argument, not a list of facts. Cite every finding it uses. Then, as `items`, give the
two to four supporting points that the story rests on, each with its evidence and why it matters
to the seller.

Finish with one item headed "ICP check": one line per hard requirement and exclusion of the ICP in
the seller brief, each marked met, not met or unknown, with the evidence in a few words. Phrase an
exclusion so the reader cannot misread it (write "Not a competitor of the seller — clear", not
"Competitor: not met"). "Clear" needs evidence; if the research simply did not find
something (for example, whether the target is already the seller's customer), mark it unknown.

### why-now — Why now

The dated changes that make outreach timely now: people joining or leaving, roles being hired,
programs launched, plan or vendor changes, expansion, leadership statements. For each: what
happened and when, why it opens a door for this seller, and what the rep should do about it. If
nothing recent stands out, say so in one sentence rather than stretching old events.

### buying-committee — Buying committee

One item per relevant person (use their `contact_ids`), two or three sentences each: what they own,
the role they likely play in a decision about this seller's product, and what to talk to them
about. Their detailed story belongs on their own contact page. Order them by who to approach first. Prefer someone whose role is confirmed by a good source as the
first call; if the best-placed person's identity or role is uncertain, say so and suggest confirming
it before reaching out. If a person's remit makes them a weak fit, say so in one line and
move on; do not argue with yourself across the page. If an obviously important seat is unknown
(for example, the person who owns the budget for what the seller sells), name it as the gap to fill.

### how-to-approach — How to approach

Three or four concrete moves, in order: who first, the opening angle, what to show or offer, and
the question that tests fit. Ground each in the findings and in what the seller actually offers
(from the seller brief). Say what to avoid pitching against (for example, a vendor the target
already praises).

### watch-outs — Watch-outs

The things that would embarrass the rep or waste their time if they missed them: conflicting
figures they should not quote, a role that may already be filled, an incumbent they should not
criticise, key facts the research could not confirm. At most five items, one or two lines each.
This is the place for uncertainty, so the rest of the page does not need to repeat it.

## Insights

Insights hold the supporting evidence a rep reads when preparing a real conversation. Do not repeat
the Overview's sentences; add the detail behind them.

### buying-signals — Buying signals

Up to six distinct signals that this account may want what the seller sells, strongest first. Each:
the evidence (quote people where their words carry it), the seller problem it maps to, and what the
rep could ask or show about it. A signal is evidence of need, change or fit — not general company
news.

### money-and-momentum — Money and momentum

Scale and money facts that matter for this seller: size of the relevant population (for example,
the number of people or sites the product would serve, rather than total headcount), growth, budgets, recent investment. Say who
reported each figure and for what period. If sources disagree, show the range once.

### tools-they-already-use — Tools they already use

Vendors, systems and programs already in place that the seller's product would sit beside,
replace or depend on, grouped by what they do. For each, what it means for the pitch (complement,
compete, integrate). Mark old evidence with its year.

### how-they-sell — How they sell, and who they win

How the company itself operates and makes money, only as far as it changes how the rep should
approach them (for example, a workforce split between office and field, or union and non-union).
Keep it short.

### miscellaneous — Miscellaneous

Other findings a rep could use in conversation that did not fit above, each as a short item with its
source. Leave out trivia and anything about other people who share a name. It is fine for this
section to be short.

## Before you return

Read your Overview as the rep would. Can they tell, in a minute, why this account, why now, who
first and what to say? Is any quote or fact repeated across sections? Does any point end in a
disclaimer instead of an action? Fix those, then return.
