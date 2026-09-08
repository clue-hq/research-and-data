---
kind: icp-definition
icp_key: clue-abm-buyers
version: 1
status: confirmed
hard_gates:
  - key: geography
    rule: "US-headquartered"
    test: "The HQ city and state on the company's own site, its LinkedIn page, or its funding announcement dateline is in the United States."
  - key: stage
    rule: "A named, priced round of Series A or later, announced within the last 36 months"
    test: "A dated announcement (press release, lead investor's post, or the company's own newsroom) that names the round and at least one investor. A seed-only, bootstrapped, public or PE-owned company is recorded as outside the stated stage — a verdict for the human, never a reason to stop researching. A self-funded operator is recorded as unclear pending master plan D9's equivalence clause."
  - key: hiring
    rule: "Actively hiring now, with at least one open go-to-market role"
    test: "At least one requisition listed today on the company's own careers page or ATS board with a GTM title: sales, marketing, growth, ABM, demand generation, SDR or BDR, partnerships, revenue operations."
  - key: intent
    rule: "At least one citable, dated buying-intent signal"
    test: "One Tier-1 signal (Q1 to Q4 below) or two Tier-2 signals (Q5 to Q10 below), each with a verbatim quote and the URL it came from."
exclusions:
  - "Sells to consumers (B2C)"
  - "Pure self-serve product-led growth: public signup, published low-tier pricing, no talk-to-sales path"
  - "An enterprise ABM or personalization platform already installed: 6sense, Demandbase, Terminus, RollWorks, Mutiny, Folloze, Influ2, Madison Logic"
  - "A direct competitor: sells ABM orchestration, AI SDR or GTM agents, personalized-microsite or intent tooling"
  - "Public, PE-owned, or more than 800 employees"
  - "Non-US headquarters"
  - "Below Series A: pre-seed, seed, bootstrapped, grant-funded"
  - "Clue itself and any Clue-affiliated entity"
persona_map:
  economic_buyer:
    titles: ["CEO", "Co-Founder & CEO", "Chief Revenue Officer", "CRO", "Chief Marketing Officer", "CMO"]
  champion:
    titles: ["VP Marketing", "VP of Marketing", "Head of Growth", "Head of Growth Marketing", "Head of Marketing", "Director of Demand Generation", "Senior Manager, ABM", "ABM Manager"]
  user:
    titles: ["SDR Manager", "Sales Development Manager", "Growth Marketing Manager", "Demand Generation Manager", "Marketing Manager", "Business Development Representative", "Sales Development Representative"]
  technical_evaluator:
    titles: ["Co-Founder & CTO", "CTO", "Head of Revenue Operations", "Revenue Operations Lead", "Marketing Operations Manager"]
  blocker:
    titles: ["CFO", "VP Finance", "Head of Procurement", "Chief Information Security Officer"]
qualifier_fields:
  - field_key: account.open_requisitions
    description: "Every open requisition on the company's own ATS board or careers page, read today: title, department, publish date, days open, salary band if published, whether still listed, URL. GTM roles matter most; quote the parts of a GTM job description that describe how the company finds and reaches target accounts."
    display: section:buying-signals
  - field_key: account.abm_program_maturity
    description: "Evidence of the company's own ABM motion: open ABM or integrated-campaigns roles, named ABM tooling, an account list size stated anywhere, a stated named-account or outbound strategy. Quote it."
    display: section:buying-signals
  - field_key: account.gtm_tooling_stack
    description: "CRM, outbound, sales-engagement and ABM tools the company demonstrably uses (present), and tools explicitly named as not used or conspicuously missing from job requirements and the site (absent). Never infer presence; write NOT FOUND per tool you cannot evidence."
    display: section:tools-they-already-use
  - field_key: account.recent_funding
    description: "The most recent priced round: amount, date, round name, lead and participating investors, stated use of proceeds, with the announcement URL."
    display: section:money-and-momentum
  - field_key: account.hiring_velocity
    description: "How fast the company is adding people: open role count now, GTM share of it, roles newly posted in the last 90 days, roles open unusually long."
    display: section:money-and-momentum
  - field_key: account.named_customers
    description: "Customers the company itself names publicly (logos, case studies, press) and every outcome metric it claims for them, with who claimed it."
    display: section:how-they-sell
  - field_key: account.operational_pain
    description: "The constraints the company describes about its own business: growth, hiring, category competition, partner motion, product gaps. Its own words, not its customers' pain."
    display: section:why-now
  - field_key: account.strategic_moves
    description: "Dated moves in the last nine months that change buying posture: new GTM leader, new market or segment, partnership, product launch, geographic expansion."
    display: section:why-now
  - field_key: account.reputation_risk
    description: "Negative or contested public items: acquisition rumours, founder departures, layoffs, down-rounds, incidents, lawsuits, critical reviews. State who reported it, whether the company responded, and whether it is confirmed, refuted or unresolved."
    display: section:watch-outs
  - field_key: account.resonance.buying_culture
    description: "How the company buys and evaluates vendors, in its own or its leaders' words: procurement style, pilot appetite, build-versus-buy stance, tooling philosophy."
    display: section:how-to-approach
---

# ICP — Clue's ABM buyers (stand-in v1, answer-key workspace)

**Provenance.** This document stands in for the ICP artifact the onboarding synthesis agent (Track O,
O4) will author and a human will confirm through the ICP gate (O6). Its content is lifted from the
two proof-of-concept runs that produced the ARV2 answer keys: the Clue smoke test of 2026-08-31
(`.context/arv2-smoke-cluehq/icp.md`, the founder's three hard rules) and the v3 sample run of
2026-08-26 (`.context/arv2-clue-sample-v3/BRIEF.md`, the hiring and intent gates). Both answer-key
accounts pass every gate below: Probook (Series A, June 2026, New York, 13 open roles, the SDR
requisition) and Zafran Security (Series C, December 2025, New York, 27 open roles, the ABM
requisition). The `display:` slugs on the qualifier fields are the kebab-case of the master plan §7
section names; D2 owns the final slug vocabulary and this document follows it when D2 lands.

## 1. Who we sell to, in priority order

1. **A US-headquartered B2B software company that has raised a priced Series A or later** in the
   last three years and is not yet procurement-shaped: roughly 30 to 300 people, a marketing team
   of 2 to 15, a product sold at $25k to $250k a year to a named list of accounts rather than a
   funnel.
2. **Whose go-to-market team has publicly committed to an outbound or account-based motion** and
   is solving throughput by hiring humans: a requisition that describes list-building, account
   research, or "own our ABM program" as the job; several concurrent GTM roles; a new VP Marketing
   or Head of Growth inside nine months.
3. **Whose bottleneck is production, not ambition.** Clue's own promise is a throughput claim
   ("More output, same headcount"), so the account we want can count its pain: a stated target-list
   size against a stated team size, a founder complaining about outbound cost, a round earmarked
   for GTM expansion.
4. **Who has not already installed an enterprise ABM platform.** The seat is open. Absence is
   evidenced from job-requirement tool lists and the site, never assumed.

Vertical priority from the smoke test, kept as guidance rather than gates: (V1) B2B SaaS selling
to enterprise or mid-market on a named-account list, including security, data and fintech
infrastructure; (V2) healthcare- and life-sciences-adjacent B2B software with a finite, enumerable
buyer universe; (V3) fintech and vertical software into banks, insurers, logistics, construction;
(V4) venture-funded, tech-enabled GTM services, admitted only when they clear the stage gate.

## 2. The signals that matter, and how to weigh them

An account satisfies the **intent** gate with one Tier-1 signal or two Tier-2 signals. Every
signal is recorded as a claim with a verbatim quote and a URL.

Tier 1 (each alone satisfies the gate):

- **Q1.** A GTM requisition that describes list-building or account research as the job ("build and
  maintain target account lists", "own our 1:1 ABM pilot for our top 100 accounts").
- **Q2.** A stated account-list size against a stated team size ("our top 250 target accounts" and a
  marketing team of four).
- **Q3.** A founder, CMO or growth leader publicly complaining about outbound or ABM production
  cost, in a post, podcast or talk.
- **Q4.** A recent round explicitly earmarked for go-to-market expansion.

Tier 2 (two are needed):

- **Q5.** No ABM or personalization tooling detected in requisitions or on the site.
- **Q6.** A small marketing team (six or fewer) against a large enumerable market (200 or more
  named targets).
- **Q7.** Two or more concurrent GTM or marketing openings (demand gen, growth, ABM, campaigns,
  content, product marketing).
- **Q8.** An enterprise or named-logo motion evidenced on the site: large-enterprise logos, a "for
  enterprise" page, "request a demo" as the only call to action.
- **Q9.** A VP Marketing, CMO or Head of Growth hired in the last nine months.
- **Q10.** Events and field-marketing spend: booths, dinners, roadshows.

Priority for the research lane: Q1, Q2, Q4, Q9 and any dated timing event under six months old are
**P1** buying signals and lead every view; qualifying firmographics, committee composition and tech
stack are **P2**; history, culture and background are **P3**.

## 3. TAM and list math

Not yet measured. Neither proof-of-concept run counted the universe; discovery produced eight
candidates from three searches (v3) and five selected accounts from eight searches (smoke). The
choice recorded here is **tier**: research depth follows the effort rung on the launch directive
(`full`, `reduced`, `cheap-pass`) rather than widening or shrinking the list. The founder revisits
this choice when the first real onboarding run produces a list-math estimate.

## 4. Disqualifiers and red flags

The eight exclusions in the front matter remove an account outright. Red flags that lower priority
without removing the account: last round older than 24 months with no new round; a marketing team
above 25 (they produce 1:1 work in-house or through agencies); a headcount above 500; a hybrid
product-led motion where the enterprise tier is an afterthought; a heavy events calendar with no
digital follow-through.

## 5. Closed-won and closed-lost patterns

None yet. Clue is pre-general-availability; its only public call to action is "Get Early Access". In
place of deal history, the two answer-key accounts are the pattern: both were picked on a GTM
requisition that spelled out the work Clue automates. Probook's SDR posting reads "We have a
clearly defined target: the top home service operators in America. The list exists. … What we need
now is someone to go get them" (https://www.probook.ai/careers); Zafran's "Senior Manager, ABM &
Integrated Campaigns" was open 77 days at research time and reported to a Head of Growth Marketing
hired four months earlier.

## 6. The client's own phrasing of who they sell to

From https://www.cluehq.ai, fetched live on 2026-08-31:

> "Agentic ABM for modern GTM teams"

> "ABM was never limited by ambition. It was limited by the amount of work. Genuine 1:1 execution
> requires research, strategy, copy, design, audience creation, media operations, sales alignment,
> and constant coordination. Agents remove the production bottleneck."

> "The depth once reserved for ten strategic accounts can now extend across the entire market
> without adding the team required to produce it."

> "Your best marketers spend their time assembling campaigns … High-touch work capped by
> headcount."

## 7. Qualification-floor verdict

**ABM-shaped: yes.** The buyer is a small, senior, finite committee (a founder or CRO, a marketing
or growth lead, the person who runs outbound, a technical or operations evaluator, and finance)
reachable on LinkedIn, and the value is per-account and countable. The floor holds as long as the
stage and hiring gates shape the list at discovery time, before a human approves the cohort;
loosening them there turns the list back into a funnel. Once an account is launched it is
researched in full, and the gates are recorded as lenient fit verdicts for the human, never as a
reason to stop.
