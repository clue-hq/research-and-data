# A2 — What Clue sells, and who buys it

**Source of every quote below:** `https://www.cluehq.ai`, fetched live 2026-08-31 (HTTP 200) and
independently via Exa `/contents` (identical text). Nothing here is inferred from memory; where I
extrapolate beyond the site I say so explicitly.

---

## 1. What Clue sells — in the site's own words

The one-line positioning:

> **"Agentic ABM for modern GTM teams"**
> "Build every campaign around the account, then carry it from first signal to market without
> losing context, quality, or control."

The category line: **"AI agents for end-to-end ABM execution."**

The problem it claims to solve:

> "ABM was never limited by ambition. It was limited by the amount of work. Genuine 1:1 execution
> requires research, strategy, copy, design, audience creation, media operations, sales alignment,
> and constant coordination. **Agents remove the production bottleneck.**"

The mechanism:

> "**Five specialized agents** turn account context into one coherent campaign — from research and
> strategy through activation and measurement."

**The five agents** (named on the live page's tab strip — note: this strip is one of the few things
Exa's extraction drops, see `comparison-exa-vs-live.md` §4):
**Deep Research · Campaign Brief · Microsites · Paid Media · Direct Mail.**

### The five jobs, quoted

| Agent / job | What the site says it does |
|---|---|
| **Deep Research** — "Know the company, the people and the moment" | "Clue brings together **50+ company, market, intent, leadership and personal signals** plus the custom data points your team cares about into one sourced account. It reveals what is changing, who matters and where the strongest campaign opportunity exists." |
| **Campaign Brief** — "Turn the research into one campaign idea" | "Clue defines the central angle, message hierarchy, stakeholder narratives, offer and creative direction that every campaign asset will follow. One clear brief keeps the entire campaign grounded in why this account should care now." |
| **Microsites** — "Give every account a destination built around its priorities" | "Clue creates a dedicated microsite with the right story, proof, offer and call to action for the company and every person involved in the decision. **Not a page with the company name swapped in**, an experience shaped around the account." |
| **Paid Media** — "Carry one campaign idea across every stage of attention" | "Clue builds coordinated **LinkedIn and Meta** campaigns for awareness, consideration and conversion, with every ad connected to the same account strategy." |
| **Direct Mail** — "Turn account insight into something they will remember" | "Clue creates the concept, copy and package for direct mail from **founder letters and executive reports to hand written notes** tied directly to the campaign story." |

### The six capabilities (the platform's own feature vocabulary)

> "**Custom research** — Define the questions, sources, and signals Clue investigates for every account."
> "**Buying committees** — Map the people behind each decision and build precise role-based audiences."
> "**Brand intelligence** — Keep every campaign aligned to your positioning, voice, proof, and visual system."
> "**Native activation** — Sync audiences and creative across LinkedIn, Meta, CRM, sales, and direct mail."
> "**Human in the loop** — Review the strategy, refine the creative, and approve what goes live."
> "**Engagement intelligence** — See how each account responds and where marketing or sales should act next."

### The promise, stated as an economic claim

> "The depth once reserved for **ten strategic accounts** can now extend across the entire market
> without adding the team required to produce it."
> "**More accounts, same standard.** … **More relevance, less production.** … **More output, same headcount** — Scale research, strategy, and execution without scaling the organization behind it."

And the before/after, which is effectively Clue's own statement of who hurts:

> **Before:** "Your best marketers spend their time assembling campaigns" — "Days lost gathering
> account context" · "Strategy scattered across teams and tools" · "Creative rebuilt for every
> channel" · "**High-touch work capped by headcount**"
> **With Clue:** "They spend it deciding how to win" — "Deep account research arrives ready to
> use" · "One campaign direction stays intact" · "Agents build and adapt every touchpoint" ·
> "**The same team covers far more accounts**"

### What the site does *not* say (honest gaps — do not fabricate these in outreach)

No pricing, no customer logos, no case studies, no named team, no funding disclosure, no
integrations list beyond "LinkedIn, Meta, CRM, sales, and direct mail", no security/compliance
page. The only CTA anywhere is **"Get Early Access"** — repeated 3×. **Clue is pre-GA / waitlist
stage.** That is a real constraint on the ICP: the buyer must be someone who will take a bet on an
early product, which pushes toward *acute, quantifiable pain* over *procurement-driven* buying.

---

## 2. Who buys — 4 personas

Mapped to the platform's committee vocabulary (`economic_buyer` / `champion` / `user` /
`technical_evaluator`) per Doc A / the buying-committee model.

### P1 — VP Marketing / CMO (Series A–C B2B)
- **Committee role:** `economic_buyer` (usually also the signer at this company size).
- **Their pain in one line:** *"I'm carrying a pipeline number against a named-account list, and my
  team physically cannot produce 1:1 work for more than ~20 of them — so the other 180 get a
  generic nurture and convert like it."*
- **What they buy:** coverage without headcount. The site line written for them is literally
  "More output, same headcount" and "High-touch work capped by headcount."
- **What kills the deal:** no proof. They need one reference-shaped artifact (a microsite, a
  research dossier) they can show their CEO.

### P2 — Head of Growth / Head of Demand Gen
- **Committee role:** `champion` (and frequently the loudest `user`).
- **Their pain in one line:** *"Every campaign restarts from zero — I re-research the account, then
  rewrite the same idea five times for five channels, and by the time it ships the trigger that
  justified it is stale."*
- **What they buy:** cycle time. "Days lost gathering account context" → "Deep account research
  arrives ready to use."
- **Why they matter most:** at Series A–B this person usually *runs* the evaluation and does the
  trial. Clue's champion and its user are the same human — that is a fast sales motion.

### P3 — ABM Manager / GTM or Campaign Ops Manager
- **Committee role:** `user`, and the de-facto `technical_evaluator` (there is rarely a real
  technical buyer at this size).
- **Their pain in one line:** *"I am the integration layer — I hand-stitch the list, the LinkedIn
  audience, the CRM sync and the mail merge, and I'm the single point of failure for every launch."*
- **What they buy:** the removal of manual assembly — "Native activation: sync audiences and
  creative across LinkedIn, Meta, CRM, sales, and direct mail", plus "Human in the loop" so they
  keep approval authority rather than being replaced by it. **Sell control to this persona, not
  automation.**
- **Blocker risk:** this is also the most likely `blocker`. If the pitch reads "replaces the ABM
  manager", they kill it. If it reads "you direct five agents", they champion it.

### P4 — Founder / CEO running founder-led sales (Seed–Series A, high ACV)
- **Committee role:** `economic_buyer` **and** `champion` **and** `user` — one person, no committee.
- **Their pain in one line:** *"I have 50 accounts that would each be worth six figures, no
  marketing team to work them, and I'm personally writing every email at midnight."*
- **What they buy:** a marketing function they don't have to hire. Direct mail and founder letters
  are aimed squarely here — "founder letters and executive reports to hand written notes."
- **Caution:** shortest sales cycle, smallest deal, highest churn risk. Good for early-access logos
  and fast feedback; not the durable ICP centre of gravity.

### Committee shape to expect in a target account

| Persona | Committee role | Typical title strings to resolve |
|---|---|---|
| P1 | `economic_buyer` | VP Marketing, CMO, Head of Marketing |
| P2 | `champion` | Head of Growth, Director of Demand Generation, VP Growth |
| P3 | `user` / `technical_evaluator` | ABM Manager, Campaign Manager, Marketing Ops, GTM Ops, RevOps |
| P4 | all three collapsed | Founder, CEO, Co-founder (only in the no-marketing-team case) |
| — | `blocker` (watch for) | RevOps/Sales Ops owner of the existing 6sense/Demandbase contract; Legal/Privacy for personal-data-driven personalization |

**Sequencing implication for Agent B:** in an account with a real marketing team, the entry point
is **P2 (Head of Growth)** — champion-first, because they feel the cycle-time pain daily and can
run a trial without a budget conversation. P1 is the second call, not the first. Only in a P4
(no-marketing-team) account do you open with the CEO.
