# What Good ABM Looks Like — 2024–2026 Practitioner Consensus

**Purpose.** Corpus seed material for the domain-expertise layer of Clue's "Head of ABM" deepagent. This is not a textbook. It is the working consensus of people who run account-based programs for a living, quoted verbatim wherever possible, with every factual claim carrying a source URL and a retrieval marker.

**Retrieval markers used throughout:**
- `[FETCHED]` — the full page was retrieved and read.
- `[SNIPPET]` — search-result text only; the claim is real but unverified against the full page.
- `[BLOCKED]` — paywalled, 404, 504, JS-rendered, or auth-walled. The block is noted and an alternate route recorded where one was found.

**Research date:** 2026-08-31. Web search budget was exhausted mid-run; the majority of this corpus is direct-URL fetching. See the Fetchability Register (final section) for what that cost.

---

## Executive Summary

1. **ABM is not a campaign type; it is a go-to-market motion with an entry gate.** The consensus qualification bar across independent practitioners: ACV ≥ $30–50k, sales cycle > 180 days, TAM < 1,000–20,000 companies, a real buying committee, and a dedicated sales team. Below that bar, practitioners actively tell clients *not* to do ABM.
2. **The canonical ITSMA three types (Strategic / Lite / Programmatic) have been superseded by five.** Bev Burgess — who coined "account-based marketing" at ITSMA in 2003 — expanded to **Strategic, Scenario, Segment, Programmatic, and Pursuit Marketing** in her 2025 handbook. The 2026 Inflexion benchmark found leaders now blend all five rather than picking one.
3. **The center of gravity moved from acquisition to expansion.** 91% of programmes name "grow existing accounts" as an objective; 63% rank it most important; only 13% rank winning new business first. Scenario ABM (breaking into new buying centers inside existing customers) is at 81% adoption.
4. **Tiering is being replaced by awareness-and-evidence segmentation.** Fullfunnel's three-list model — Cluster ICP (<5% opportunity likelihood) / Future Pipeline (<30%) / Active Focus — sorts by *vendor awareness plus product-need evidence*, not by revenue band alone.
5. **The single most cited operational number of 2025–26:** HockeyStack's analysis of 1.5M contacts across 50+ B2B SaaS companies found enterprise deals >$100k require **417 touchpoints** to close. Standard ABM playbooks contain 7–10. "If your playbook doesn't account for 417 touchpoints across 18 months, you don't have a playbook."
6. **The buyer is gone before you arrive.** 6sense's 2025 Buyer Experience Report: buyers make first contact **61% of the way** through the journey; **95%** buy from a vendor on their Day One shortlist; **77–81%** of deals go to the first vendor contacted.
7. **Failure rates are high and self-reported.** Fullfunnel's poll of 300+ (elsewhere 450+) B2B marketers: **98.5% not satisfied** with ABM performance, 49% frustrated. Scrappy ABM: "roughly 78% of ABM programs have failed" since 2020. Both are house statistics with soft provenance — cite carefully.
8. **The named failure modes converge hard.** Across every independent source: too many accounts; no sales buy-in; treating ABM as a tool purchase; wish-list targeting with no intent evidence; single-threading; measuring MQLs; quitting before leading indicators mature; no dedicated owner.
9. **Measurement that survives scrutiny is the ITSMA 3Rs** — Revenue, Relationships, Reputation — plus account *progression* between stages. "Movement > engagement."
10. **The mocked metrics are MQLs, impressions, clicks, and attribution dashboards.** Kerry Cunningham's term for the incumbent system: the **"MQL-Industrial Complex."** Chris Walker's: the **"attribution Mirage."**
11. **Personalization depth is a function of tier, and shallow personalization is worse than none.** 1:many = cluster-level relevance; 1:few ≈ 15–30 accounts sharing one strategic challenge; 1:1 = a dedicated marketing plan for one customer, "not a campaign with their logo dropped in."
12. **The winning plays in 2026 are relationship-shaped, not ad-shaped:** account-based podcasts, executive dinners, peer-to-peer (CISO-to-CISO) engagement, closed-lost re-engagement, webinars as ABM triggers, and engagement-based outreach on LinkedIn. Programmatic display is explicitly named as a failure pattern.
13. **The stack is smaller than vendors claim, and the ABM platform category is being unbundled.** 42 Agency's 2026 sentiment data: 6sense at 3.0/5 and falling; Clay, Warmly, Common Room at 4.0/5 and rising. "In 2026, ABM-the-strategy is alive. The ABM platform is on life support." Average feature usage on $100–150K contracts: **~30%**. Fullfunnel runs its own program on <$1,000/month.
14. **The diagnostic phrase the whole field uses is "that's not ABM, that's targeted demand gen."** It recurs independently at Snowflake, Ramp, Hightouch and Fullfunnel. The hard caps practitioners enforce: **20 accounts per person** (Hightouch), **~10 per rep** when expecting 4 meetings (Snowflake), **10 max for a pilot** (Fullfunnel).
15. **The binding constraint is verifiable account intelligence, not orchestration software.** 60% of ABM programmes lack a single source of truth for data; only 16% use predictive scoring; 97% prioritize on "future growth potential" — a human judgment. The black-box failure, from a RevOps leader: *"why is this account a 92, and what actually fired. Nobody on the floor could answer it."* And the risk of getting it wrong, from Mason Cosby: **"if your data source is incorrect, you are specifically incorrect."**
16. **The measurement method that survives every critique is a held-back control group,** not an attribution model. Hightouch publishes the result: treated accounts convert to stage-one opportunity at a **32% higher rate** than the general population. "Fighting over attribution is the biggest waste of time in a B2B company. Just don't do it."
17. **Time-to-signal is 3–6 months; time-to-revenue is 6–18 months.** Programs killed at month 3 are killed before their leading indicators mature. This is the single most common cause of death. The best-sourced failure statistic is not the widely-quoted "78%" or "98.5%" house numbers — it is Momentum ITSMA's finding that **only 17% of programs ever reach full "Embedded" maturity.**

---

## 1. The Canonical Frameworks

### 1.1 Origin and the three types (and why they are now five)

Bev Burgess coined the term "account-based marketing" at ITSMA in 2003. `[SNIPPET]` — https://inflexiongroup.com/ `[FETCHED]`

The original taxonomy, which every vendor still repeats:

| Type | Alias | Scale | Personalization |
|---|---|---|---|
| **Strategic ABM** | One-to-one | 1–5 accounts per marketer | Fully custom programmes |
| **ABM Lite** | One-to-few | Clusters of 5–20 accounts sharing challenges | Lightly customised |
| **Programmatic ABM** | One-to-many | Hundreds to thousands | Technology-tailored at scale |

Source: https://www.madisonlogic.com/blog/uncovering-the-three-types-of-abm-and-why-they-matter/ `[SNIPPET]`; https://en.wikipedia.org/wiki/Account-based_marketing `[SNIPPET]`

**The 2025 update that most agents will get wrong.** Burgess expanded three → **five** in *Account-Based Marketing: The definitive handbook for B2B marketers* (Kogan Page, 2025, ISBN 9781398619135). The five, named verbatim on the Inflexion page: **"Strategic, Scenario, Segment, Programmatic and Pursuit Marketing."**

https://inflexiongroup.com/resources/introducing-account-based-marketing-the-definitive-handbook-for-b2b-marketers/ `[FETCHED — names the five, defines none]`

> **`[BLOCKED]` — the per-type definitions are not on any public Inflexion page.** They are gated behind the book. This is the single most significant unfilled gap in this brief. What follows is reconstructed from the 2026 benchmark research summaries, which *use* the taxonomy operationally.

### 1.2 The five types as the 2026 benchmark uses them

**Strategic ABM** — depth over breadth. Concentrated on Tier 1. Verbatim:

> "Strategic ABM works when it's treated like account-based marketing should be treated: as a dedicated marketing plan for one customer, not a campaign with their logo dropped in."
>
> "this is a discipline built on depth over breadth"

https://inflexiongroup.com/resources/2026-abm-benchmarking-study-research-summary-strategic-abm/ `[FETCHED]`

**Scenario ABM** — the newest and fastest-adopted type. Penetrating *new pockets inside accounts you already serve*: new business units, new buying centers, new stakeholders. **81% adoption.** Distinguished from Strategic ABM by mandate scope:

> Strategic ABM operates with a "be the CMO of the account" mandate, while Scenario ABM is narrower: "a specific outcome, a defined plan to get there, faster"

https://inflexiongroup.com/resources/2026-abm-benchmarking-study-research-summary-scenario-abm/ `[FETCHED]`

**Segment ABM** — verbatim definition:

> "Building one plan for a small group of accounts that share a similar context, typically around 30 at a time. It's about applying focus and tailoring at some scale, rather than treating every account as a one-off."
>
> "Like Scenario ABM, it's mostly aimed at existing customers rather than new logos, though 43% are starting to apply it to prospects too."

https://inflexiongroup.com/resources/2026-abm-benchmarking-study-research-summary-segment-abm/ `[FETCHED]`

**Programmatic ABM** — technology-mediated targeting at scale. Retained from the original taxonomy.

**Pursuit Marketing** — deal-specific marketing wrapped around a single major opportunity, typically a competitive bid or RFP. 48% of programmes use it for new business; 39% rank it their second most important objective.

**The blending finding, verbatim:**

> "Programme leaders are no longer relying on one or two types of ABM in their strategy, they are blending all five in use today to maximise return across the accounts that matter most."

https://inflexiongroup.com/resources/2026-abm-benchmarking-study-research-summary-a-look-at-abm-strategy-and-account-coverage/ `[FETCHED]`

### 1.3 The older tier definitions, verbatim — still the clearest language available

From strategicabm's "ABM in the House" series (Declan Mulkeen, CMO strategicabm; Alex Olley, co-founder Reachdesk), 2020. Foundational rather than current, but nobody has said it more cleanly since:

> **Declan Mulkeen:** "One-to-few campaigns are particularly suited, when you're looking at clusters of 15 to 20 accounts where they have something in common"
>
> **Declan Mulkeen:** "One-to-one this is reserved for a hand-picked group of accounts, no more than, typically, 1 to 5 accounts"
>
> **Declan Mulkeen:** "These are accounts that warrant an increase in resources in both people, time and, obviously, financial resources...because they're going to deliver a significant return"
>
> **Declan Mulkeen (the research-depth line):** "One-to-many is little to no personalisation whereas you need to, obviously, dig deep and carry out research at the industry level, at the account level"
>
> **Alex Olley:** "At the One-to-one level...you could literally do something so unique for that account...You could literally do something unique"
>
> **Alex Olley:** "These accounts could also be your existing clients and customers...prospects you're looking to win, or indeed both maybe as well"

https://insights.strategicabm.com/abm-playbook-one-to-few-one `[FETCHED]`

> **Declan Mulkeen:** "We deploy One-to-many for our Tier 3 accounts. We deploy One-to-few for our Tier 2 accounts, typically in clusters of 15 to 20 accounts."
>
> **Declan Mulkeen:** "Tier 1 accounts for us are, these are hand-picked accounts...typically no more than 3, 4, 5 accounts"

https://insights.strategicabm.com/account-based-marketing-playbook `[FETCHED]`; https://insights.strategicabm.com/account-based-marketing-goals `[FETCHED]`

**The four valid reasons to run ABM at all** (Mulkeen, same series):
1. Account penetration — cross-sell, up-sell, entering new markets inside the account
2. Pursuing a major opportunity — "that kind of typical big deal"
3. Developing a new account / winning a new logo
4. Changing perceptions or market position

### 1.4 Account selection and tiering

**The revenue-band tier model (Fullfunnel, pre-3.0):**

| Tier | Revenue contribution | Treatment |
|---|---|---|
| Tier 1 | Highest ACV/LTV; >10–15% of segment revenue | Highly personalized 1:1 |
| Tier 2 | Medium ACV/LTV; 4–10% of revenue | Vertical + job-role personalization |
| Tier 3 | Lowest | Sourced through demand gen and capture |

https://fullfunnel.io/abm-strategy/ `[FETCHED]`

**The model that replaced it — Fullfunnel's three lists.** This is the most important structural shift in account selection between 2023 and 2026, because it sorts on *awareness and evidence* rather than revenue band:

| List | Opportunity likelihood | Posture |
|---|---|---|
| **Cluster ICP** | "<5%" | Build vendor awareness via demand gen |
| **Future Pipeline** | "<30%" | Validate challenges through profiling |
| **Active Focus** | Strongest engagement + relationship + product-need evidence | Drive opportunity development |

https://fullfunnel.substack.com/p/selecting-accounts-for-the-abm-program `[FETCHED]`

**The four selection pillars, verbatim** (Andrei Zinkevich) — this is the cleanest scoring rubric in the corpus and maps directly onto a claim-backed research model:

> 1. **Revenue Potential** — "Are you hunting antelope or field mice? Not all accounts are equal."
> 2. **Vendor Awareness** — "Are the accounts that we want to target already aware of our product?"
> 3. **Relationship** — "Do you know anybody who works for the target accounts? Someone closely connected to the buying committee?"
> 4. **Product Need Evidence** — "Are there facts that tell you the account might have a challenge your product solves?"

> "Prioritize tier 1 and tier 2 accounts with the highest and medium revenue potential."

**Engagement signal triangulation** (same source): the most responsive accounts matched **all three** of — connected/following on LinkedIn; newsletter subscribers **6+ months**; event attendees.

**What the enterprise actually prioritizes on** — 2026 Inflexion benchmark, n=40 companies (80% >5,000 employees):

| Criterion | % of programmes |
|---|---|
| Future growth potential | **97%** |
| Current revenues | 77% |
| Competitive strength | 68% |
| Executive engagement strength | 65% |
| **Predictive scoring** | **16%** |

> "human judgement and relationship context still dominate"

https://inflexiongroup.com/resources/2026-abm-benchmarking-study-research-summary-a-look-at-abm-strategy-and-account-coverage/ `[FETCHED]`; https://inflexiongroup.com/resources/new-inflexion-group-research-reveals-how-account-based-thinking-is-shaping-b2b-marketing-transformation/ `[FETCHED]`

**Where the list should come from.** Mason Cosby (Scrappy ABM), verbatim:

> "Not a purchased database or a brainstorm in a conference room."
>
> "The best place to start is your own CRM, specifically your closed-won and closed-lost deals."
>
> "If nobody shows up, that's just a list of who you'd _like_ to work with."
>
> "A target account list built on an idealistic profile will send an ABM program chasing accounts that were never a fit to begin with."
>
> "Closed-won deals show you who you're winning, while closed-lost deals show you where your assumptions might need a second look."

https://scrappyabm.com/blog/where-your-target-account-list-should-come-from/ `[FETCHED]`

Fullfunnel's four qualified sources, replacing wish lists: intent data from website engagement (pricing, case studies, demos); demand-gen program participation; senior executives' and sales' personal networks; industry associations and communities. **"Never take a wish list or list of lost deals from sales."** https://fullfunnel.io/abm-strategy/ `[FETCHED]`

**The three-tier alignment test** (Cosby) — a diagnostic, not a taxonomy. Sales and marketing independently sort the full list into must-win / nice-to-win / not-a-focus-this-quarter, then compare:

> "Agreeing on a profile isn't the same as agreeing on a priority, and mixing the two up is one of the reasons alignment can fall apart once the work starts."

https://scrappyabm.com/blog/three-tier-test-team-alignment/ `[FETCHED]`

### 1.5 The FIRE model

**Fit, Intent, Recency, Engagement.** Authored by **Matt Amundson**, then VP of Marketing and Sales Development at EverString, published 7 Sept 2018.

- **Fit** — accounts that "look like your current customers"
- **Intent** — a company "starting to research your space"
- **Recency** — "timestamp when a company is exhibiting intent, so you can determine the recency"
- **Engagement** — activity from marketing automation showing brand interaction

Tiering output:
- **Tier 1:** meets all four FIRE criteria
- **Tier 2:** "fit and intent with recency"
- **Tier 3:** "high fit but have not shown intent or engagement"

> "You now have an understanding of *whom* you should be targeting, *why* you should be targeting them and *when* you should be targeting them."

https://www.demandgenreport.com/demanding-views/how-to-use-fit-intent-recency-engagement-f-i-r-e-for-go-to-market-strategies/5265/ `[FETCHED]`

Also rendered as **Fit, Intent, Relationship, Engagement** by some sources (Foundry, Bombora, Triblio). Both variants circulate; Recency is the original. https://foundryco.com/blog/blog-dont-play-with-fire-unless-youre-a-b2b-marketer/ `[SNIPPET]`

**Agent note:** FIRE is a *2018* model built for an intent-data-vendor world. Its weakness against the 2026 consensus is that "Fit" is firmographic and "Intent" is third-party — the two things practitioners now trust least. Fullfunnel's four pillars (revenue potential / awareness / relationship / need evidence) are the modern equivalent and are more research-shaped.

### 1.6 Entitlement, ambition and account planning

**Entitlement** in the ITSMA/Inflexion lineage means the share of an account's addressable spend you have a legitimate claim on — the gap between current revenue and potential. Momentum ITSMA's account selection matrix maps *account attractiveness* against *relative business strength*, focusing on accounts with "both genuine potential to turn into stars and strong existing relationships." https://momentumitsma.com/solutions/grow-key-accounts `[SNIPPET]` (site returned 504 on direct fetch — see register)

**The ambition-setting step.** Bev Burgess, verbatim:

> "The first step in the process of creating and executing an ABM plan – especially for a strategic account – is to define your ambition for that account."
>
> "Creating a clear ambition demands strong leadership and, ideally, collaboration with the customer, to build a shared vision of where the business partnership could go and the areas where you can build mutual value."

The interview guide covers four areas: current state with the customer; **target state in three years**; key relationships needed; competitive landscape within the account. Strategic accounts use a **three-year planning horizon** to "allow the team to consider the art of the possible."

https://inflexiongroup.com/resources/the-abm-ers-toolkit-an-interview-guide-for-clarifying-ambition/ `[FETCHED]`

**The account planning artifact chain** (Inflexion's ABM-er's Toolkit — this is the most complete public account-planning spec available and maps almost 1:1 onto what a research agent should produce):

1. **Confirm the account's priorities** → environmental factors, market conditions, customer priorities
2. **Respond to those priorities** → capability mapping + account-specific SWOT
   > "Responding to your account's priorities is where insight becomes strategy."
   > "The goal is not to map every capability onto every priority – it is to find the most credible and compelling intersections."
   > "Taking the time to do this well is what separates ABM that delivers outcomes from ABM that simply generates activity."
   https://inflexiongroup.com/resources/the-abm-ers-toolkit-responding-to-your-accounts-priorities/ `[FETCHED]`
3. **Confirm the target audience (DMU)** → named individuals, roles, seniority, relationship to the decision. DMU roles: economic buyers, technical evaluators, end users, influencers — plus "people outside it who have an influence over decision-making, such as third-party advisors, analysts, or board-level connections."
   > "Taking a structured approach to mapping your target audience helps you identify gaps – people you should be engaging but are not."
   https://inflexiongroup.com/resources/the-abm-ers-toolkit-confirming-your-target-audience/ `[FETCHED]`
4. **Build stakeholder profiles** → four dimensions: professional background (role, scope, tenure, previous roles, non-exec positions, memberships, speaking engagements, published articles); education and interests; DMU role + relationship rating; relationship ownership (account team owner + executive sponsor).
   > "To engage them effectively, you need to understand them as individuals: their professional background and current priorities, their role in the decision-making unit, and the nature of your existing relationship."
   >
   > Direct knowledge — "conversations, meetings, and shared history" — remains "the most valuable input"; AI-assisted research works from "publicly available sources – LinkedIn profiles, company websites, conference programmes, published articles, and press coverage."
   https://inflexiongroup.com/resources/the-abm-ers-toolkit-building-a-stakeholder-profile/ `[FETCHED]`
5. **Craft a messaging house** → **Roof** = what you want the customer to believe about you in three years; **Pillars** = "a small number of big bet themes or propositions, each addressing a priority issue for the customer"; **Foundation** = stakeholder profiles, proof points, differentiators, business outcomes linked to customer KPIs.
   > "A messaging house matters because it forces discipline. Rather than each business unit or region developing its own take on the account, everyone works from the same foundation: a shared promise, a shared story."
   https://inflexiongroup.com/resources/the-abm-ers-toolkit-crafting-a-messaging-house/ `[FETCHED]`
6. **Craft the value proposition** → five-part template: (1) target audience, specific to an executive ("as CMO of the world's largest bank"); (2) issues and priorities, *in their language, not yours*; (3) response — one clear description avoiding internal product names; (4) benefits — business outcomes, quantified; (5) differentiation.
   > "A strong value proposition translates your messaging house into a story that speaks directly to an individual executive's world"
   > "The more you can quantify the value of the tangible benefits on offer, the greater the interest generated"
   > "It's their judgement about what will resonate with this executive that makes a value proposition land"
   https://inflexiongroup.com/resources/the-abm-ers-toolkit-crafting-your-value-proposition/ `[FETCHED]`
7. **Set aligned objectives** → SMART targets agreed with the account team, organised into Relationships / Reputation / Revenue.
   > "marketing's influence over revenue growth is less direct" — the 3R structure protects marketing from being "reduced to a single, often lagging, revenue figure."
   https://inflexiongroup.com/resources/the-abm-ers-toolkit-setting-aligned-objectives/ `[FETCHED]`
8. **Build a campaign flight path** → "an integrated plan that turns your messaging house and value proposition into a coordinated plan of activity, showing what happens when, and by whom, across every stage of the customer lifecycle (not just the pre-sales journey)." Four lanes: **Executive Engagement** (sponsorship, advisory boards, hospitality, briefings, roundtables, governance meetings); **Strategic Campaigns** (tailored thought leadership, industry/solution campaigns, bespoke value-prop campaigns); **Brand Activities** (positioning, flagship events, sponsorships); **Internal Activation** (strategy briefings, talking points, battlecards, pitch rehearsals).
   > "don't start from scratch. Consider what other marketing teams are doing that you can leverage for the benefit of your account, then identify the gaps and decide what else you should create as a bespoke activity for your account."
   https://inflexiongroup.com/resources/the-abm-ers-toolkit-building-a-campaign-flight-path/ `[FETCHED]`

**Fullfunnel's 6A account-plan model** (the SMB/mid-market equivalent, applied per account):
Account **Qualification** → Account **Segmentation/Prioritization** → Account **Research** → Account **Awareness** → Account **Development (Nurturing)** → Account **Activation**.
Research splits into **desk research** (publicly findable) and **1-1 research** (conversations with the buying committee). Their research-template shape is a triple: *specific research question* → *what this insight tells you* → *how to use it*. 1:1 planning assumes **12–18 month cycles**.
https://fullfunnel.substack.com/p/how-to-create-1-1-account-plans-in `[FETCHED]`

### 1.7 Buying-committee orchestration

**The size, from multiple independent sources:**

| Source | Figure |
|---|---|
| Gartner (2024) | 11 stakeholders average enterprise committee, up from 7 in 2017 |
| Gartner (larger deals) | 11–20 stakeholders |
| 6sense 2025 Buyer Experience Report | **10+ members on average** |
| Kerry Cunningham / 6sense | **10–11 individuals** in average B2B solution evaluation |
| strategicabm / LinkedIn research | "at least 10 people" |
| Trend 2015→2025 | 5.4 → 8–13 stakeholders |

https://www.thestarrconspiracy.com/insights/benchmarks/b2b-buying-committee-benchmarks-2025 `[SNIPPET]`; https://6sense.com/science-of-b2b/buyer-experience-report-2025/ `[FETCHED]`; https://insights.strategicabm.com/peer-to-peer-abm `[FETCHED]`

Also: "each additional decision-maker reduces purchase probability by roughly 10 percentage points" `[SNIPPET]` and **40% of buying journeys collapse due to inability to reach consensus** (Cunningham) `[FETCHED]`.

**The four canonical roles** (Fullfunnel's ICP pillar 2): **Champions** (conduct initial research, prepare comparison reports) / **Decision-makers** (approve budgets, sign) / **Influencers** (provide critical feedback without direct participation) / **Blockers** (oppose the solution or perceive personal threat). https://fullfunnel.io/ideal-customer-profile/ `[FETCHED]`

**The engagement geometry — two concentric circles per account.** Fullfunnel's Account-Based Engagement Playbook: **8–10 people** for visibility amplification, plus **2–3 core decision makers**. Focus on "what they care about: Jobs-to-be-done and daily challenges." Small batches of **7–10 priority accounts**.

> "No automated cold outreach and follow-ups. No mass targeting, small batches of 7–10 priority accounts."

https://fullfunnel.substack.com/p/account-based-engagement-playbook `[FETCHED]`

**Multithreading depth:** "multithreading across 5+ stakeholders — power users, economic buyers, technical evaluators, internal champions," expanding to a broader "B2B buyer ecosystem" of thought leaders, communities, industry associations. https://fullfunnel.substack.com/p/how-to-create-playbooks-for-long `[FETCHED]`

**Why single-threading kills programs.** Fullfunnel failure mode #8: "Targeting decision-makers only. Your message is likely to be bulk deleted and call blocked by a gatekeeper." Scrappy mistake #4: "Only Engaging One Person in the Account."

**Peer-to-peer ABM — the 2026 committee play.** Connect your executives and SMEs to their functional counterparts (CIO↔CIO, CFO↔CFO) rather than routing everything through sales.

> **Richa Pande, Global Head of ABM Campaigns, HP:** "Decision Makers - like CISOs, CTOs, etc. don't want to talk to Marketing. No offense! They don't want to talk to Sales. They really want to talk to their peers."
>
> **Declan Mulkeen:** "Today's buyer is self-educated. Today's buyer is informed. Today's buyer does not need a Salesperson to tell them the what, when, how, why, etc."

Mechanics: marketing builds targeted account experiences for the committee; sales develops decision-maker relationships; SMEs connect with prospect counterparts. Requires formalising expert engagement and rationing their time. Deals stall "one step below the person who actually signs off."
https://insights.strategicabm.com/peer-to-peer-abm `[FETCHED]`

**ICP vs BCP.** Cosby distinguishes the *Ideal* Customer Profile (forward-looking: "your best future customers" given where product/team/delivery will be in 1–2 years) from the *Best* Customer Profile (backward-looking: "customers who've created the most value for your business (not just the ones you were excited to close)"). BCP is built from revenue consistency, profitability, delivery cost, retention, plus soft signals — drawn from Sales, CS, and Finance.

> "The goal isn't to look impressive. The goal is to repeatedly win with the right customers."

https://scrappyabm.com/blog/icp-bcp-targeting/ `[FETCHED]`

### 1.8 Personalization depth per tier

**Fullfunnel's three-level content model, mapped to journey stage:**

| Level | Stage | Content |
|---|---|---|
| **1:MANY** | Awareness / no-low intent | Entire ICP clusters regardless of intent. "Challenging the status quo of inefficient processes." Industry trends, best practices, daily LinkedIn thought leadership, weekly newsletter, weekly podcast, quarterly webinars, annual summit |
| **1:FEW** | Consideration / medium intent | Cluster and Jobs-To-Be-Done specific. "Step-by-step solutions" for specific operations. Playbooks, templates, detailed case studies with video interviews, deep-dive webinars and workshops. Avoids direct product promotion |
| **1:1** | Decision / high intent | "Fully personalized content for a specific account." Business cases, implementation plans, process maps, stakeholder-specific arguments (executive ROI, IT security), account recommendations — built to **support internal selling** |

https://fullfunnel.substack.com/p/account-based-content `[FETCHED]`; https://fullfunnel.io/abm-content/ `[FETCHED]`

> "Most of your buyers aren't in-market today. Your job is to make sure that when they are, they think of you first."
>
> "Content is the most undervalued area of ABM and a frequent cause of failed programs."
>
> "The goal is not volume—it's about creating high-impact, relevant content."

**The dissenting view on personalization — worth holding.** Cosby argues heavy per-account personalization does not scale and is usually the wrong lever:

> "A lot of teams assume great ABM campaign ideas come down to personalization. So they try to create something unique for every account. But that approach doesn't scale."
>
> "Content is a vehicle. Its only job is to answer a question and help [someone progress toward a decision]."

His alternative organizing principle is *relevance to a buyer question*, not account identity: capture every customer question in a shared channel → convert to multi-format assets with SMEs → centralise and make searchable by problem → drive adoption through co-creation with Sales/CS/Product.
https://scrappyabm.com/blog/framework-for-better-abm-content/ `[FETCHED]`

Also, Scrappy mistake #5: **"Personalizing Without Permission"** — using researched personal detail the recipient did not knowingly make available reads as surveillance, not relevance. https://scrappyabm.com/blog/abm-mistakes-to-avoid/ `[FETCHED]`

**Proof over pain — the 2026 messaging posture:**

> "An audience that's been fear-mongered enough times stops feeling urgency and starts feeling numb."
>
> "lead with proof instead of pain. Show people what's possible, so you can build trust before urgency."
>
> "being the brand that treats people like humans instead of pipeline is a differentiator."

https://scrappyabm.com/blog/proof-over-pain/ `[FETCHED]`

**Activation tactic effectiveness — 2026 Inflexion benchmark:**

| Tactic | Effectiveness rating |
|---|---|
| Bespoke landing pages | 87% |
| Paid social media | 87% |
| Executive engagement | 84% |
| VIP event experiences | 84% |
| Innovation workshops | 81% |
| Bespoke videos | 77% |
| Digital advertising | 77% |

86% create custom content for Strategic ABM campaigns. 37% handle all activation internally; 47% use copywriters or digital agencies; 37% use multiple regional/specialist ABM agencies; 10% use a single global specialist.

> "Our relationship with our agency is changing as AI can do much of what we relied on them for, so now it's about using them to plug gaps, such as complex messaging."

https://inflexiongroup.com/resources/an-insight-into-activation-from-our-2026-abm-benchmarking-study-research-summary/ `[FETCHED]`

### 1.9 Signal-based / "allbound" GTM

**The 2026 GTM baseline** (Kyle Poyar, Growth Unhinged):

> "The GTM playbook has changed more in the past two years than in the decade before." — Kyle Poyar

Six primary motions have consolidated: inbound (23% adoption as primary), outbound, product-led, account-based, paid digital, partners. Critically: **"no single motion correlates with better growth rates — the right choice depends on ACV, stage, and product type."**

Account-based is gaining because "AI makes generic outreach cheap and ubiquitous, [so] differentiation comes from precision, relevance, and deep context around a small set of high-value accounts." Fit criteria: **$50k+ ACV and addressable markets under 20,000 companies.**

Benchmarks from the same piece (Oct 2025 data):
- GTM channel adoption: LinkedIn 66%, SEO 53%, **warm outbound 48%**
- AI search ≈ **one-third of all searches** (incl. Google AI Overviews)
- Average **5 core channels + 5.5 experiments** per company
- **GTM Engineer population: 400+** at US digital-native companies
- Forward-deployed role comp: **$213k–$370k+**

https://www.growthunhinged.com/p/b2b-gtm-playbook-for-2026 `[FETCHED]`

**Signal taxonomy.** Signals are first-party (product usage, website visits), second-party (partner events), or third-party (job changes, funding, competitor engagement). Warm outbound "converts at meaningfully higher rates because timing and relevance are already established." Named plays: customer alumni, website visitor de-anonymization, LinkedIn content engagement outreach.

**The awareness-scoring progression** (Poyar): Identified (default) → Aware (surface engagement) → Interested (repeated high-intent engagement) → Considering (pre-meeting) → Selecting (active deal cycle).

**Cosby's signal taxonomy — the most operationally useful one found**, because each tier carries a prescribed *action*:

| Signal class | Examples | Meaning | Action |
|---|---|---|---|
| **Awareness** | LinkedIn follows, connection requests, light content engagement | "They know you exist (or are starting to)" | Keep messaging educational; **avoid premature outreach** |
| **Initial Engagement** | Webinar registrations, problem-focused content, repeat early-stage visits | "They're exploring a problem" | Deepen problem understanding |
| **Meaningful Engagement** | Deeper event attendance, tactical content, consistent interest over time | "They're actively exploring ways to solve the problem" | Tailored messaging + light outreach |
| **MQA / High-Intent** | Pricing page, product pages, booking calls, repeated high-intent behavior | "They're likely evaluating solutions" | Prioritize for direct sales outreach |
| **Re-engagement** | Previously active account returns after quiet period | Timing or priorities shifted | Reconnect with fresh context, don't restart |

Three qualifying questions before any outreach: (1) Does the account fit the ICP? (2) What stage are they in? (3) Does this signal justify immediate outreach?
> **"Prioritize progression, not just activity."**
> "A quick, relevant follow-up within a day will outperform the perfectly crafted message two weeks later."

https://scrappyabm.com/blog/prioritize-outreach-abm-signals/ `[FETCHED]`; https://scrappyabm.com/blog/4d-framework/ `[FETCHED]`

**Jon Miller's 2026 prediction #9 — the most strategically important signal claim in the corpus:**

> **"Public intent signals will commoditize; proprietary signals generate 'alpha'"** — first-party and uniquely combined signals create competitive advantage.

And #4: **"Context engineering will emerge as a recognized practice across GTM teams"** — teams must capture "operational knowledge that makes AI useful rather than generic."
https://www.jonmiller.com/blog/2026/1/18/11-predictions-for-b2b-go-to-market-in-2026 `[FETCHED]`

**Named signal taxonomies, four of them.** These are the most reusable artifacts in the whole corpus for a research agent.

**(i) Autobound — 60 signals, 6 categories, impact-scored 1–5 with action windows.** Derived from "100,000+ signaling events." https://www.autobound.ai/guides/sales-signals `[FETCHED]`

*Highest-impact signals (Impact 5) with their action windows:* SDR/BDR Team Expansion (30–60d) · VP of Sales Hire (30–90d) · Series A/B/C (30–90d) · IPO Filing (90–180d) · M&A as Acquirer (30–90d) · CRM Implementation/Switch (30–90d) · Cloud Migration (60–180d) · Data Warehouse Adoption (30–90d) · New CRO Appointment (30–90d) · CEO Transition (60–180d) · VP Marketing Hire (30–90d) · Head of Data Appointed (30–90d) · **Contact Job Change (14–60d)** · **Pricing Page Visits (7–14d)** · Competitor Research Activity (7–30d) · M&A as Target (30–90d) · Competitive Displacement (7–30d).

*Shortest windows (act now):* Chatbot Engagement (1–7d) · Competitor engagement (1–7d) · Pricing page visit (7–14d) · **Tech Stack Downgrade (14–30d)** · Cost Restructuring (14–60d) · Product Launch (14–60d).

**The compounding law — the single most useful quantitative claim about signals:**
> "Each additional signal from a different category increases meeting conversion by roughly 40-60% over baseline."

Three-signal combinations convert at **3–5× baseline**. An account showing funding + hiring + technology simultaneously converts at 3–5× a single-signal account.

**(ii) Apollo — three confidence tiers.** The cleanest good-vs-bad framing. https://www.apollo.io/insights/signal-based-selling `[FETCHED]`
- **Tier 1: First-Party (Highest Confidence)** — website behavior, product usage, CRM engagement history, support ticket trends
- **Tier 2: Second-Party (High Confidence)** — job changes and hiring, tech stack installations, growth indicators, department expansions, funding
- **Tier 3: Third-Party (Medium Confidence)** — category intent, review-site activity, content consumption networks, competitor comparison research

> **Operating rule:** "Require minimum two independent signals from different sources before triggering outreach to prevent false positives."

Five-step model with owners: Signal Discovery (RevOps/GTM Engineer) → Scoring (daily) → Routing (real-time) → Execution (**30-minute SLA**, SDR/AE) → Optimization (monthly weight adjustment). Role split: SDRs on early-stage signals; AEs on product usage/support themes/stakeholder changes; CS on churn risk.

**(iii) Clay — default vs custom, i.e. where the moat is.** https://university.clay.com/lessons/types-of-signals-in-clay-signals-abm `[FETCHED]`
- **Default** ("Clay's greatest hits"): career movement, news and fundraising, job postings, brand mentions, website intent, customer sentiment (G2/Capterra/TrustRadius)
- **Custom** (competitive advantage): tech stack changes, compliance and certifications, geographic expansion, website content monitoring (pricing/feature/blog changes), executive social posting patterns, **SEC filings intelligence**, **engineering density metrics (GitHub activity + technical hiring)**

**(iv) Amplemarket — signal → play → window, with reply rates.** https://www.amplemarket.com/blog/signal-based-selling `[FETCHED]`

| Signal | Play | Window |
|---|---|---|
| Pricing page visit | Immediate follow-up | **2–4 hours** |
| Competitor engagement | Re-evaluation messaging | 1–7 days |
| Job change | Personalized outreach on the new role | 7–14 days |
| Technology adoption | Integration-focused outreach | 14–30 days |
| Funding announcement | Budget-driven sequence | 30–60 days |

Reply rates: signal-triggered **8–15%** vs cold **2–5%**; **job-change signals 20–30% reply**; pricing-page visits 15–25% engagement. Deel achieved **87% account engagement** with signal-triggered sequences.
> "Timing determines reply likelihood, not ICP refinement or subject lines."

### 1.9a What counts as a *bad* signal

This is the part most vendors skip and it matters more than the taxonomies.

**Demandbase's three failures of signal-based selling** — the best articulation found, and notable for coming from a signal vendor. https://www.demandbase.com/blog/signal-based-selling/ `[FETCHED]`
1. **Not all signals are equal.** The canonical example: *a student downloading a cybersecurity eBook for a class assignment registers identically to a CISO actively evaluating solutions.* Without context both look equally valuable.
2. **Source quality varies invisibly.** Third-party intent has inconsistent accuracy and coverage; freshness varies by provider; collection methods are black-box.
3. **The "more is better" fallacy.** "Signals don't scale linearly in value." Teams accept weak signals to increase coverage, diluting effectiveness.

Their prescription: target the **10–20% of accounts showing deepest signals**, not hundreds showing shallow ones. Scale context: a typical ICP is 5,000–10,000 accounts × buying committees of ~15 = **~150,000 contacts that matter**.

> **Ankush Gupta, founder of Eventible.com:** "It's not about finding the perfect signal. It's about matching the right kind of insight to the job you're trying to do."

**Autobound's three properties of a high-value signal** — **Specificity** (a particular event, not "company is expanding") · **Timeliness** (a defined window when receptiveness peaks) · **Relevance** (connects to your value prop and their stated priorities). And their definition of noise, which is the sharpest in the corpus:

> Noise is **"obvious, widely-broadcasted signals (funding rounds trending on LinkedIn) that trigger simultaneous outreach from competitors, reducing differentiation value."**

That is: *a signal everyone can see is not alpha.* https://www.autobound.ai/blog/signal-based-selling-complete-guide `[FETCHED]`

**The three-property test** `[SNIPPET]`: "A sales signal has three properties: a timestamp (when it happened), a source (where it was verified), and commercial context (why it creates a selling opportunity). If it lacks any of those three, it is not a signal." And on the failure pattern: "Teams often just connect to a data tool, see that a company raised a Series A and fire a sequence, spot a new CRO hire and send a 'congrats' email… none of that is signal-based selling, it's just noise with a smarter label." Architecture guidance: **3–5 signals maximum**, each with distinct detection logic and an actionable lifespan. "A funding announcement that's 72 hours old is high-value, but the same signal at 3 weeks old is noise."

**Decay curves.** Tier-1 signals: act within **24–48 hours**. The "five-minute rule" — contact within the first five minutes = **21× more likely to convert** vs 30+ minutes later. A 48-hour funded-company play reports **400% higher conversion** than delayed outreach. Reply benchmarks along the personalization ladder: generic cold email **3.43%** → signal-based personalization **18%** (5.2×) → **multi-signal stacking 25–40%**. Small targeted campaigns **5.8%** vs **2.1%** for larger lists. `[FETCHED]`

**First-party as the moat.** Cody Leovic, Senior Growth Manager at **Verkada**, via Clay:
> "the best GTM teams won't win by buying more intent data…They'll win by remembering what their buyers already told them."
> Third-party data "tells you what anyone can know." First-party data "tells you what only you can know."

*Rented* (non-exclusive, vendor-controlled, decays as the market saturates): contact databases, firmographics, technographics, scraped web activity, job-change alerts, funding announcements, intent feeds. *Owned* (proprietary, compounds): CRM notes, email replies, call transcripts, product usage, event attendance, website behavior. Verkada's "future reach out" sequence produced a **33% reply rate with nearly 50% of replies converting to demos**. Governing principle: **"audience > copy."** https://www.clay.com/blog/how-first-party-signals-become-your-gtm-moat `[FETCHED]`

**Clay's three laws of GTM** — why any signal advantage is temporary. https://www.clay.com/blog/the-three-laws-of-gtm `[FETCHED]`
1. **You need to be unique.** "Generic outreach is just noise. You win by knowing something about your customers that competitors don't." Their example: a logistics company used Google Maps satellite imagery to **count parking spots to infer warehouse size** — more accurate than any database and hard to automate.
2. **No creative advantage lasts forever.** "Every GTM winning strategy contains the seeds of its own destruction." … "Your brilliant outreach strategy is likely being automated by your competitors before you've even finished your quarterly review."
3. **The fastest to iterate wins.** "Your only sustainable advantage is your ability to discover new advantages faster than competitors."

**"GTM alpha"** — Clay's term for edge built on unique data. Method: interview sales about the manual research they do before calls → map the customer's digital footprint → deploy agents to collect qualitative unstructured signals at scale. Real alpha signals from named customers: **Certemy** — OSHA violations indicating compliance problems · **Supermetrics** — brand vs agency distinction for routing · **Rutter** — conference attendee lists · **Intercom** — breadth of a company's support documentation · **Cake.ai** — AI engineering teams with 2–5 developers. https://www.clay.com/blog/gtm-alpha `[FETCHED]`

**Vertical-specific signals beat general providers** — the strongest evidence for an industry-pack model. In Fullfunnel's four-program case set, the differentiated signals were not in any general database:
- **Certn** monitored hiring trends
- **Charlesgate** tracked city planning and land filings ("Developers don't announce their projects on LinkedIn—we had to find them through public filings and industry data." — Amy Loesch)
- **Cardata** monitored regulatory updates affecting compliance needs

https://fullfunnel.io/four-abm-programs/ `[FETCHED]`

### 1.10 The shift from MQL waterfall to account-based measurement

**The strongest single articulation** is Kerry Cunningham (ex-SiriusDecisions/Forrester, now 6sense):

> "The lead-based demand generation model was not a victim of poor execution. It is simply out of date"
>
> "Sellers are not guiding the journey. They are being invited to validate decisions that have already been made."
>
> "What has stalled progress in B2B revenue production practices are the deeply embedded systems, processes, misattributions, and institutional narratives — what we call the **MQL-Industrial Complex**."
>
> "B2B professionals consume category-relevant content continuously, which means most visitors to vendor websites are curious professionals, not active buyers."
>
> "Buyers are not seeking new ideas; they are seeking reassurance."
>
> "Most intent data isn't a buyer saying pitch me. But, it is something just as valuable: a buying group in the early stages of building preference, when they're most persuadable."

**Metrics to abandon:** lead volume and conversion rates; individual buyer activity tracking; form fills as intent signals; speed to first contact; content as capture mechanism; traffic growth; first/last-touch attribution.
**Replace with:** opportunity creation; buying-group engagement; account-level patterns; lift analysis; opportunity influence; buying-stage progression.

Supporting statistics from the same piece: 60% of target accounts not in-market at any time; fewer than 30% of eventual buyers fill out forms on the winning vendor's site; vendors see only 10–15% of total research activity; 16–17 interactions per person per vendor; four of five vendors shortlisted on Day One; 80% of buyers select a preferred vendor before engaging sales; 95% purchase from the Day One shortlist; 89% of solutions purchased included AI components; 77% likelihood the Day One favorite wins during Validation; 94% of buyers picked a favorite before the Validation Phase starts.

https://6sense.com/science-of-b2b/the-leadbased-approach-has-failed-us-its-time-to-move-on/ `[FETCHED]`

**Jon Miller's replacement model — three tiers, not one MQL:**

- **Tier 1 — Hand-Raisers:** "Demo requests, pricing inquiries, 'contact me' forms, explicit requests for sales engagement." Route immediately. No scoring required.
- **Tier 2 — MQX (Marketing Qualified Lead/Account/Buying Group):** "Marketing's informed judgment, based on signal combinations, that there are meaningful indicators of in-market behavior." Signals: pricing page visits, competitor comparison downloads, review-site activity, *multiple people from the same account* engaging with solution-oriented content, third-party intent surges, patterns matching past won deals. Action: proactive consultative outreach with realistic conversion expectations communicated to sales.
- **Tier 3 — MEX (Marketing Engaged):** "Right ICP firmographics, engaging with your brand and ideas but no buying signals." Action: value-driven human engagement to help them recognise a latent problem — "lead with reference stories, diagnose before prescribing, quantify status quo costs."

> "B2B buying involves accounts and buying groups, not just individual leads."

Expected-value threshold: a ~9% probability of in-market status justifies engagement on a $100k ACV / 20% win-rate basis.
https://www.jonmiller.com/blog/2026/3/16/beyond-the-mql-a-three-tier-model-for-b2b-qualification `[FETCHED]`

**Miller on the incumbent system:**

> "Companies will slowly break from their 'gumball machine' MQL addiction" — **"in goes budget, out comes leads"**
>
> "rigid attribution models dividing opportunities sourced by marketing vs. sales are archaic."
>
> "our buyers are staying unknown and anonymous for longer."

https://www.jonmiller.com/blog/2025/1/9/the-future-of-b2b-marketing-new-playbooks-strategic-brands-and-ai-agents-11-predictions-for-2025 `[FETCHED]`; https://www.jonmiller.com/blog/2024/1/20/the-marketing-playbook-i-helped-create-doesnt-work-anymore-heres-the-new-b2b-marketing-playbook `[FETCHED]`

**Fullfunnel's version:**

> "LEADS are a lagging indicator of your marketing & sales efficiency."
>
> "Your buyer pre-selects you or your competitor way before you become aware of it."
>
> "Cold outbound produces <1% discovery to closed won opportunities"
>
> "To compete and grow in 2025, you must replace the lead gen with multithreaded full-funnel marketing."
>
> "not every click or email should produce a meeting"

https://fullfunnel.substack.com/p/leads `[FETCHED]`

**The account progression model that replaces the MQL waterfall** (Cosby): Awareness → Initial Engagement → Meaningful Engagement → **MQA (Marketing Qualified Account)** → SQA → Opportunity → Re-Engagement.

> "Accounts don't jump from 'never heard of you' to 'booked a demo' in one clean move. They progress."
>
> "Once you can see those stages clearly, three things get way easier: You stop running random tactics and start running real ABM plays."

Brand recall requires "roughly 3-6 months."
https://scrappyabm.com/blog/account-progression-model/ `[FETCHED]`

### 1.11 The 95-5 rule and the in-market base rate

Per Ehrenberg-Bass Institute surveys, typically only **3–5%** of a market is in-market at any given time. Jon Miller: "only 5% of B2B buyers are in-market to buy right now – leaving a massive 95% out-of-market"; "during a downturn like today, that can be as low as just 1%"; "everyone is fighting over the same 5% of in-market buyers." His budget prescription moved across two years: **60% direct demand gen / 40% brand** (2024) → **54% demand gen / 46% brand** (2025).

Dale Harrison's critique `[SNIPPET — LinkedIn is not fetchable]`: over 95% of potential buyers are not open to learning about products and their features; he attacks "the so-called 'demand generation' delusion, where marketers imagine that they're conjuring up demand out of thin air." Source of record: https://www.linkedin.com/posts/dalewharrison_the-95-5-rule-95-of-your-potential-buyers-activity-7099099207256440832-tK3N `[BLOCKED]`

Counter-position (David Kirkdorffer, same thread) `[SNIPPET]`: introduce novel ideas to alter buyers' evaluation of their problems, transitioning people *from* the 95% *to* the 5%.

**Agent note — this is the central strategic tension in ABM.** If 95% are out-of-market, an ABM program targeting only in-market accounts is fishing in a puddle; but a program that ignores intent entirely burns budget on the unreachable. The resolution every serious practitioner reaches: **run awareness against the cluster, run activation only against evidenced need.** That is exactly what Fullfunnel's three-list model encodes.

---

## 2. How Elite Practitioners Actually Run ABM Today

### 2.1 Team shapes

**Enterprise (2026 Inflexion benchmark, n=40, 80% >5,000 employees):**
- ABM budget: **17–20% of total marketing budget** (the two research summaries report 17% and ~20%)
- ABM headcount: **14% of marketing headcount**
- 86% maintaining or increasing ABM budget vs 2025; 59% expect increases in 2027
- 96% maintaining or growing headcount; 56% anticipate growth next year
- Operating model: **centralised 38% / decentralised 43% / hybrid 19%**
- **54%** of ABM practitioners have blended field roles

Verbatim structural quotes:
> "We have one team globally...so we have a centralised model"
> "Our ABM-ers are decentralised, reporting to their local CMO"
> "Our field marketers spend 40-50% of their role on ABM"
> "The centralised, global team does global accounts and local ABM-ers look after local priority accounts"

Skills: collaboration ranks as the top soft skill; **"AI literacy and commercial acumen lag"** across most technical marketing skills.
Governance: CMOs partner with sales/business to sponsor ABM in **59%** of programmes. Support mechanisms: Communities 41%, Centers of Excellence 38%, steering groups 38%.
https://inflexiongroup.com/resources/2026-abm-benchmarking-study-research-summary-an-insight-into-operating-models-and-funding-in-abm/ `[FETCHED]`; https://inflexiongroup.com/resources/2026-abm-benchmarking-study-research-summary-a-look-at-programme-objectives-metrics-and-governance/ `[FETCHED]`

**Series A–C / lean teams (Fullfunnel's five core functions):** Senior ABM Manager (orchestration, playbooks); **Researcher** (intent data management, account qualification, research); Content Marketer; Designer; SDR. Readiness gate includes a **dedicated ABM team with 70% time commitment**. https://fullfunnel.io/abm-strategy/ `[FETCHED]`

**The actual pilot team that produced results** (Fullfunnel, across four client programs): ABM lead + content marketer + sales rep (SDR or AE), supported by SME and RevOps. Their own three-person team: Andrei Zinkevich (ABM lead/marketing), Vladimir Blagojevic (sales), Dagmara (PM/RevOps). **"Nobody else was involved. No other freelancers or agencies."** https://fullfunnel.substack.com/p/our-abm-program-breakdown-case-study `[FETCHED]`

**CrossKnowledge pilot team:** ABM Lead, SDR/Inside Sales, Content Marketer, later an Expansion Marketer; supporting cast of AEs, SME, RevOps. https://fullfunnel.io/abm-pilot-program/ `[FETCHED]`

**BenchPrep pilot team of three:** Briana (ABM lead/SME), Megan (content/design), Jalynn (account engagement). https://fullfunnel.substack.com/p/who-owns-abm `[FETCHED]`

**The dedicated-sales-rep effect — the hardest team number in the corpus:**

| | Without dedicated sales rep | With dedicated SDR |
|---|---|---|
| Meeting booking rate | **1.77%** | +40% enterprise meeting conversion |
| No-response rate | **70.51%** | — |
| Accounts entering opportunity pipeline | **0** | 7–15 strategic conversations in first 90 days |
| Sales cycle | — | −25% length |

> "Sales often think that ABM is a fully owned marketing program. They should only pick the cherry from the cake by showing up on discoveries."
> "While marketing owns program orchestration, sales own critical execution areas."

https://fullfunnel.substack.com/p/who-owns-abm `[FETCHED]`

**SDR role redefined for ABM** — five functions: account qualification; account research and buying-committee mapping; buying-committee engagement & profiling; account nurturing; activation.
KPIs kept: "account-to-conversation ratio", "account penetration", "account-to-pipeline ratio", "sales pipeline velocity".
KPIs explicitly rejected: **"Lead generation KPIs (cold dials, cold emails)"** and **"Meetings booked"**.
> "Ask profiling questions to understand where the buyers are in the buying process."
https://fullfunnel.substack.com/p/sdrs-abm `[FETCHED]`

**Center of Excellence — when and why.** IBM runs ~**60 ABMers globally** supported by a CoE based in New York, with ABMers embedded in local markets (standards central, execution local). Kyndryl runs a smaller equivalent using a **proprietary account scoring engine combining firmographic, technographic and intent data**.

> **Avishek Chakrobarty, Head of Global ABM CoE, Kyndryl:** "A CoE acts as the glue between different functions, both within and outside Marketing."
> **Avishek Chakrobarty:** "It's not something you can do at any point of time. The moment is right when you reach a certain level of ABM maturity."
> **Cheryl Caudill, Global ABM and Demand Marketing Leader, IBM:** "We really needed to have a Center of Excellence—somewhere we can set standards"
> **Cheryl Caudill:** "You have to earn your seat at the table with Sales—build belief deal by deal."
> Editorial: "If your ABM is still experimental...an ABM Center of Excellence is premature. If ABM is working and spreading—an ABM CoE is a must."

https://insights.strategicabm.com/what-is-an-abm-center-of-excellence-in-2026 `[FETCHED]`

**Rules of engagement — the alignment mechanics that actually get written down** (Cosby). Core principle: **"ABM orchestrates, Partners execute. Authority follows the account's stage."**
- **Handoff trigger:** "when a qualified meeting gets booked with a stakeholder"
- **Pre-handoff:** "ABM owns strategy early...They're deciding what runs, when, and why. Other teams are consulted and often execute specific channels, but ABM calls the strategic shots."
- **Post-handoff:** "the sales rep has the final say on when plays go out"
- **ABM↔Sales SLA:** "A weekly sync between the ABM team and the sales rep for each priority account"
- **Email/MAP agreement:** "ABM provides the account list, copy, and window for when the send should go out. The execution team handles the rest."
- **Events agreement:** major conferences — "ABM needs to be looped in at least 90 days out"; smaller events and webinars — **60 days**
- **Cadence:** weekly ABM↔rep syncs; bi-weekly regional marketing overlap reviews; monthly check-ins with email/PMM/events; quarterly reviews with sales leadership

https://scrappyabm.com/blog/rules-of-engagement-for-abm/ `[FETCHED]`

**The weekly meeting agenda that runs a program** (Fullfunnel, verbatim): "what's working and why, what's not working and why, what bottlenecks do we have and how to unblock them." Their Weekly ABM Pipeline Review covers account insights and engagement data; account planning and next steps; leading-indicator assessment; retrospective; account list additions/removals.

**Alignment failure statistics** (strategicabm): 25% of sales/marketing teams operate as independent silos; only **17%** report complete alignment; **10%** potential revenue slippage from misalignment; **40%** of sales time wasted on unproductive prospecting; 31.8% of reps/marketers align on analytics/metrics; 43% cite lack of communication as the barrier.
> **Amy Hall, Global ABM Manager, Hitachi Vantara:** "Make sure that you have that Marketing and Sales alignment because if you don't have that at the very beginning, you're never going to have it"
> **Samantha Mayer, Salesforce Pardot:** "When the Sales and Marketing teams are looking at the same metrics and trying to hit the same North Star, lots of other pieces of ABM fall into place"
https://insights.strategicabm.com/sales-marketing-alignment `[FETCHED]`

### 2.2 Budgets and program economics

| Figure | Source |
|---|---|
| ABM = **17–20%** of marketing budget; **14%** of marketing headcount | Inflexion 2026 `[FETCHED]` |
| **"ABM investments typically range from $50,000-$200,000"** | Declan Mulkeen, strategicabm `[FETCHED]` |
| Scrappy ABM Pilot retainer: **"$13,875 every four weeks"**; "Most clients graduate within about 18 months"; six-week framework build; six-month initial commitment | scrappyabm.com `[FETCHED]` |
| Account-based podcast programs: **$2,975/mo** (production) → **$4,675/mo** (full account-based podcast incl. guest sourcing) | scrappyabm.com `[FETCHED]` |
| Fullfunnel's own program stack: **under $1,000/month** — Leadfeeder, Apify, FullEnrich, Aligned, Goldcast, Encharge, Attio, Granola, Claude. "there are no enterprise platforms. The stack is lean." | fullfunnel.substack `[FETCHED]` |
| Full TAM mapping with account research: **$2,000+**; HubSpot Data Hub Pro webhooks **$800/month** | Dan Rosenthal, Growth Unhinged `[FETCHED]` |
| **$10K/month** LinkedIn creator pilot (4 creators, 3 posts each, monthly) → 500K–1M impressions/mo at **40% lower CPA** than paid social | Brianna Doe, Verbatim (Exit Five) `[FETCHED]` |

**The all-in program cost model** — the most granular public breakdown, from Userled:

> "A complete ABM program in 2026 typically costs between **$40,000 and $500,000+ per year**, all-in."

| Company stage | All-in annual |
|---|---|
| Early-stage pilot (<50 accounts, first year) | **$50k–$120k** |
| Mid-market ($50M–$250M revenue) | **$120k–$400k** |
| Enterprise ($250M–$1B) | **$400k–$1.5M+** |
| Global enterprise ($1B+) | **$1.5M+** |

*Cost split:* People **30–40%** · Platform fees **20–30%** · Content/creative **15–25%** · Media/data **15–25%**.

**Per-account production cost by operating model — the single most useful number for a platform pitch:**
- Legacy services-heavy: **$5,000–$15,000 per account per quarter**
- In-house team: **$2,000–$5,000 per account per quarter**
- AI-native platform: **$200–$500 per account in platform-time**

*Minimum mid-market team:* 0.5–1.0 FTE ABM program manager (**$90–140k loaded, US**) · 0.25–0.5 FTE marketing/RevOps · 0.25–0.5 FTE designer or content producer · sales partnership ≈ **10–15% of involved reps' time**.
*Return target:* "ABM budget should produce **5–10× its cost in influenced pipeline within year one, and 15–25× by year three**."
*Media:* LinkedIn CPMs **$40–$100**; a **100-account 1:1 LinkedIn campaign typically runs $5k–$20k/month**.
https://www.userled.io/articles/abm-pricing-budgeting-what-b2b-teams-actually-spend-in-2026 `[FETCHED]`

**Tier economics — accounts, spend, motion, and unit cost per tier.** The crispest tier taxonomy found:

| | **Tier 1 — Strategic** | **Tier 2 — Named** | **Tier 3 — Programmatic** |
|---|---|---|---|
| Accounts | 5–50 | 50–500 | 500–5,000 |
| Spend per account | **$50K–$500K** | **$5K–$25K** | **$200–$1,500** |
| Motion | 1:1 custom playbooks, executive sponsor | Persona-led segment campaigns | Automated multichannel, intent-prioritized |
| Sales coverage | **Dedicated AE per 5–10 accounts** | AE covers 20–50 accounts | SDR per 300–500 accounts |
| **Cost per meeting** | **$4K–$8K** | **$1.2K–$2.4K** | **$300–$800** |
| Avg ACV | $150K–$500K | $40K–$120K | $8K–$25K |
| **Win rate** | **25–40%** | **12–22%** | **4–8%** |
| **Time-to-pipeline** | **9–15 months** | **4–8 months** | **6–12 weeks** |
| ROI ratio | 5–12× | 3–7× | 2–4× |

*Recommended portfolio mix:* **70% Tier 3 · 25% Tier 2 · 5% Tier 1** for B2B SaaS above $20M ARR.
https://grouglobal.com/blog/abm-tiers-explained `[FETCHED]`

**Inflexion's separate spend/headcount cut** (differs slightly from the 2026 study summaries — both are reported here): **22% of marketing budget** to ABM · **16% of marketing headcount** · 88% maintained allocation YoY · 54% expect increases · **40% employ dedicated full-time ABM teams** · org models **50% decentralized with local reporting / 39% centralized under a Head of ABM / remainder hybrid**.
> "Our ABM-ers are decentralised across 10 major markets. They are based where the account is, and have a dotted line to the CoE, forming a community of interest."
> "Global ABM is centralised, local ABM is decentralised"
https://inflexiongroup.com/resources/reorganising-for-abm-trends-in-spend-headcount-and-team-roles/ `[FETCHED]`

**Org design by stage:**
- **Lean (2–4 people):** head of marketing (strategy + content) · demand gen/growth marketer (execution + reporting) · one AE or founder · fractional RevOps for CRM hygiene. **Constraint: one ICP segment and 20 target accounts maximum.**
- **Mid-market (5–10):** Head of ABM or senior demand gen lead · ABM campaign manager · content marketer · marketing ops/RevOps analyst · 2–3 named AEs + a dedicated BDR. *Attribution becomes the bottleneck at this stage.*
- **Enterprise (10+):** **pod model over pure specialization** — self-contained units of **1 marketer + 0.5 FTE RevOps + 2 AEs + 1 BDR per segment**, each pod sharing a single pipeline number, with mandatory weekly account reviews.

> **"RevOps is the most underweighted hire"** — without it "the target account list lives in a spreadsheet" and engagement data dies in dashboards. It should be the **second** hire after the strategy lead. The **weekly 45-minute account review** is "the operational ritual that holds the structure together."
https://zenabm.com/blog/abm-team-structure `[FETCHED]`

Counter-trend `[SNIPPET]`: "For 2026, winning teams are running ABM with **1-2 dedicated headcount instead of 5-8**, as modern platforms have absorbed production work."

**Snowflake — the reference enterprise program.** **21-person ABM team** in four divisions: Emerging Markets · Enterprise · Industries · **Center of Activation** (owns tech stack and data hygiene across all teams).

> **Ratio: "Our ratios cap at about 1 ABM for every 35 Account Executives (AEs)."**
> **Primary metric: "The primary goal [of Snowflake's ABM] is the percentage of accounts with meetings booked."**
> **Attribution philosophy:** rather than crediting teams, measure **"lift"** by comparing engagement between target and non-target accounts.
> **Cadence:** bi-weekly alignment meetings between ABMers, AEs and SDRs — territory rundown, account engagement, sales-call insights.
> **Personalization rule:** account name + public pain points; **avoid first names unless contextually relevant**.
> **Casey Patterson, Sr. Manager of ABM:** "ABM is the bridge between marketing and sales." · "Personalization should never be a distraction."
> **Denise Persson, CMO:** the team must be **"unreasonably aligned with sales."**

https://www.mutinyhq.com/blog/snowflake-abm-structure `[FETCHED]`; https://www.mutinyhq.com/blog/abm-question-answer-snowflake `[FETCHED]`

**The hard account caps practitioners actually enforce:**
> **Casey Patterson, Snowflake:** "We will add too many accounts. Each of my team members now has an account limit so that we're not going to two hundred accounts." … **"One person cannot know two hundred accounts intimately. That's not ABM anymore that's kind of targeted demand gen."**
> **Brian Kotlyar, Hightouch:** "We just don't believe that a human being, even with AI tools, can do a good job working more than **20 accounts**."

Snowflake's own numbers: ~10 accounts per rep when expecting 4 meetings; major accounts ~20 per manager; prospect work 2–3 ABM accounts per rep (120–150 per manager).
https://exitfive.com/podcast/abm-what-ramp-snowflake-and-hightouch-are-doing-in-2026/ `[FETCHED]`; https://exitfive.com/newsletter/how-ramp-snowflake-and-hightouch-run-abm-daves-newsletter/ `[FETCHED]`

### 2.2a The GTM engineer — the role that now carries ABM execution

This role did not exist in 2023 and is now the operational spine of signal-based ABM.

> **Kyle Poyar:** "GTM engineers – sometimes called GTM Ops, Growth Ops, AI Ops, RevOps Engineers, GTM Ops Engineers, or even Lead to Opportunity Systems Engineers – are meant to bring technology and automation to solve hard GTM problems"
> "I think of GTM engineers as people who can both identify friction points across the buying journey (ICP targeting, ICP pipeline, conversion, CAC, etc.) and then quickly run automated, 1:many experiments to eliminate them."

*Scarcity ratios (Poyar):* 45 GTM engineer job posts in the past month; 128 in the past three months; **fewer than 10/month in 2024**. Ratio of GTM engineering roles to others: **1 per 5 RevTech/MarTech · 1 per 14 RevOps · 1 per 35 SalesOps · 1 per 92 SDR positions.** And a caution: **"45% of those with a GTM engineer title are actually agencies or consultants."**
https://kylepoyar.substack.com/p/do-you-need-a-gtm-engineer `[FETCHED]`

*Market data (Bloomberry, 1,000 postings analyzed):* median salary **$127,500/yr**; average experience required 4.11 years; **YoY job growth 2024→2025: +205%**. Top payers: Vercel $252K · OpenAI $250K · LILT AI $221.5K · Ramp $184K · Clay $175K. Tool adoption in postings: **Clay 56% · HubSpot 52% · Outreach 49% · Salesforce 45% · Zapier 39% · SQL 38% · Python 38%**. Of 100 LinkedIn profiles of current GTM Engineers, **"90%+ of profiles" featured Clay experience**.
https://bloomberry.com/blog/i-analyzed-1000-gtm-engineering-jobs-here-is-what-i-learned/ `[FETCHED]`

*The most rigorous salary dataset* (Steven Moody: 491 hand-checked US postings, 235 with salary, 28 hiring-team interviews, May 2026) — median base by archetype: **Pure SWE $218,750 · Data $166,195 · Embedded SWE $156,000 · RevOps $150,000 · Outbound/Growth $135,000**. Overall median ~$150,000. By level: Staff $200,950 · Senior $170,000 · Mid $150,750. SF premium ~14%.

**Two counterintuitive findings:** roles mentioning **Clay** pay **$148,174** median vs **$165,000** for roles that don't — a **$17,000 discount**. And AI skill intensity shows **no pay correlation (Pearson r = +0.07)**. Scarcity ratios (annual openings per available candidate): TypeScript 5.85:1 · AI agents 5.43:1 · Python 3.54:1 · Salesforce 2.85:1 · "All of Marketing" baseline **0.02:1**.
https://stevenmoody.com/benchmarks/gtm-engineer-salary `[FETCHED]`

*The JD test that defines the role:*
> "Can this person look at our current GTM motion, identify where we are losing pipeline, and build a system to fix it — without waiting for a product team or engineering sprint?"

Requirements phrasing: "owned CRM data architecture or enrichment pipeline"; built "outbound automation that ran at scale (1,000+ contacts/month)"; "can cite attribution numbers tied to systems they built." https://syncgtm.com/blog/gtm-engineer-jobs `[FETCHED]`

*Clay's interview questions:* "Tell me about the last process you built from scratch" · "Walk me through how you'd diagnose why our email reply rates dropped 30%" · "If I asked you to run an experiment with no clear playbook, how would you get started?"
> **Robert Jones (Canva):** "The best GTM Engineers think like product designers…You want someone who gets excited about diagramming complex processes."
> **Noah Adelstein (Rippling):** "What I look for in a strong GTM Engineer candidate is someone who's deeply curious about technology and can give you specific examples of going down interesting rabbit holes."
https://www.clay.com/blog/how-to-hire-a-gtm-engineer `[FETCHED]`

**The "death of the SDR" debate, with receipts.** The strongest pro-replacement data point is Vercel, via Tomasz Tunguz interviewing **Jeanne Grosser (Vercel COO)**:
> "For us, we had **10 SDRs** doing this inbound workflow, & now we just have **one** that is effectively QAing the agent."
> "It was **six weeks** before we felt confident going from 10 to 1."
> "We were able to hold that lead to opportunity conversion rate flat."
> "The person who built the lead agent was **a single GTM engineer**. He spent maybe 25, 30% of his time on this."

The other nine SDRs were **redeployed to outbound, not laid off**. https://tomtunguz.com/vercel-ai-sales-agents-jeanne-grosser/ `[FETCHED]`

The counter-case `[SNIPPET, Bain Capital Ventures]`: "the autonomous AI SDR narrative peaked in 2024-2025 and by early 2026, fully autonomous AI SDRs have not replaced human sales teams at any meaningful scale." **36% of B2B companies cut SDR teams in 2025**, but "most reductions came from attrition rather than layoffs." … **"The SDR of 2026 is closer to a quality assurance engineer for outbound pipelines than to the phone-jockey archetype of five years ago."**

Gartner, via GTM News `[FETCHED]`: **40% of enterprise applications** will feature task-specific AI agents by end of 2026 · **10× more AI agents than human sellers** by 2028 · but **40% of agentic AI projects will be cancelled by end of 2027**. Reps spend only **28% of their week actually selling**; **~70% feel overwhelmed** by tool count.

**The payback math that sets the ACV floor.** Mason Cosby, on why $50k ACV is the gate:

> "Three to four months of setup time...three to six months of education...90 to 120 days sales cycle...twelve months"

i.e. the horizon to first revenue is about a year, which is why the ACV has to clear $50k for the program to pay back.
https://exitfive.com/podcast/how-to-simplify-abm-with-mason-cosby-founder-of-scrappy-abm/ `[FETCHED]`

### 2.3 The tech stack, honestly assessed

**The minimum viable stack** (Cosby): CRM + marketing automation platform + sales outreach platform. That's it.

> "Most successful ABM programs don't start with a sophisticated tech stack. They start with three tools, a smart strategy, and focus."
> "Tools don't create an ABM strategy. They support one."
> "Everything else is a nice-to-have until you've validated that the core ABM program is working."
> "Sales is distribution in an ABM program, and distribution needs to be coordinated."
> "Start lean means you learn faster, waste less budget."
> **Dave Gerhardt (Exit Five):** "You don't need 200k in tech spend to go and do ABM."

https://scrappyabm.com/blog/tools-behind-successful-abm-program/ `[FETCHED]`

**Fullfunnel's stack-by-maturity ladder:**
- **Pilot:** website visitor ID, LinkedIn Sales Navigator, account enrichment
- **Operations:** additional intent sources, marketing automation
- **Scaling:** advanced enrichment, programmatic ads, gift delivery, sales cadences

> **"Software ≠ ABM. No expensive stack will help to fix a broken playbook."**
> "Software can't replace the process, it only helps to refine it."
> "Buying an expensive ABM stack for the pilot" is failure mode #2 of 11.

https://fullfunnel.io/abm-strategy/ `[FETCHED]`; https://fullfunnel.substack.com/p/killing-abm `[FETCHED]`

**The 2026 AI-native ABM stack, as actually built** — Dan Rosenthal (co-founder, Workflows.io; bootstrapped to $2.5M ARR in 10 months; "implemented dozens of modern ABM engines"), writing in Growth Unhinged:

*Step 1 — TAM and stakeholder mapping.* Goal: a target account list capturing **90%+ of TAM**. Four data-source categories:
1. General prospecting databases — Apollo, ZoomInfo
2. Lookalike databases — Ocean.io, Discolike
3. Specialized niche databases — Storeleads, influencers.club
4. Web scraping — Apify, Claude Code

Process: build a data-supported ICP model → simple tiering → pull multiple lists and merge/dedupe (**"recently shifted from Clay to Claude Code"**) → deploy AI research agents to qualify companies from website analysis → map contact titles into decision-makers / champions / influencers / end-users.

*Step 2 — Account research.* Goal: **30+ custom data points** per account for personalization and sales enablement. Examples cited, simple to complex: engineering headcount; custom sub-industry classification; e-commerce hosting platform; competitor tech usage; geographic proximity; clinical trial data; parent-child company relationships; media-buying activity composite scoring. Tools: Claygent, 150+ Clay providers, significant prompt engineering, account scoring in HubSpot with auto-reassessment triggers.

*Step 3 — CRM cleanup and enrichment.* Hard domain/email dedupe; property audit; re-enrichment windows (typically 1 year); "Enriched by Clay" date fields; on-demand enrichment buttons. The goal state: **"reps don't ever need to login to Apollo or ZoomInfo themselves."**

*Step 4 — Signal tracking.* `[BLOCKED — paywalled beyond this point]`

Verbatim:
> "AI agents and data enrichment make it way more accessible."
> "The technical implementation is still far harder than most expect. But the results are also far more impressive."
> "Simple usually means more accuracy and clarity for the sales team."
> "The only way to maximize coverage beyond a certain point is to pull a higher volume of lists."

https://www.growthunhinged.com/p/how-to-build-a-modern-abm-engine `[FETCHED to paywall]`

**Named tools observed in real programs** (aggregated across sources): HubSpot, Salesforce, Attio (CRM) · Clay, Claygent, FullEnrich, BetterContact, Findymail (enrichment) · Apollo, ZoomInfo, LinkedIn Sales Navigator, Cognism (prospecting) · Ocean.io, Discolike, Keyplay (lookalike) · Apify, Claude Code (scraping/research) · Leadfeeder, RB2B, Warmly (visitor ID) · 6sense, Demandbase, Bombora (intent) · HockeyStack, Dreamdata (attribution) · Goldcast (events/webinars) · Encharge (automation) · Aligned (digital sales rooms) · Granola (call notes) · Sendoso, Reachdesk, Alyce, PFL, Postal (gifting/direct mail).

### 2.3a The ABM platform category is being unbundled — the honest 2026 assessment

The single highest-signal source on tooling is 42 Agency's **ABM Intel Report 2026**, which aggregates practitioner sentiment. Its thesis:

> **"In 2026, ABM-the-strategy is alive. The ABM platform is on life support."**

**Vendor satisfaction and trend:**

| Vendor | Rating | Trend |
|---|---|---|
| 6sense | **3.0/5** | ↓ Down |
| Demandbase | 3.5/5 | → Stable |
| RollWorks | 3.5/5 | → Stable |
| Terminus | 3.5/5 | ↓ Legacy |
| Foundry | 3.0/5 | ↓ Declining |
| **Clay** | **4.0/5** | ↑ Rising |
| **Warmly** | 4.0/5 | ↑ Rising |
| **Common Room** | 4.0/5 | ↑ Rising |
| Mutiny | 4.0/5 | → Stable |
| UserGems | 4.0/5 | → Pressured |

**Six things practitioners say are broken:** (1) black-box scoring — sales don't trust opaque account scores, they want explainable signals; (2) false-positive alerts; (3) **~30% average feature usage across $100K–$150K annual contracts**; (4) slow model updates — enterprise platforms take months, practitioners need daily/weekly; (5) identity match quality varies 40–80% with no clear winner; (6) bundled bloat — paying for 10+ features when 2–3 are needed.

**The emerging consensus stack (2026):** Clay (enrichment) + Common Room (community signals) + RB2B/Warmly (website ID) + UserGems/Champify (job changes) + Mutiny (personalization) — **$3K–$8K/month vs $10K–$15K/month for legacy platforms.**

**The catalytic event:** Adam Schoenfeld (PeerSignal/Keyplay) posted in Sept 2025 about discontinuing 6sense; it "drew 96+ comments and triggered a wave of copycat posts." By October:
> **"The blackbox overpromise has run its course."** — Adam Schoenfeld

https://intel.42agency.com/abm-sentiment/ `[FETCHED]`. Schoenfeld's own post, https://www.peersignal.org/p/i-just-churned-6sense, is `[BLOCKED — SSL handshake failure]`; a surviving snippet reads: "These new AI 'columns' (research, enrichment, signals) are key ingredients in the shift from legacy ABM to modern ICP marketing."

**The counterpoint, from the same report** — churn is often strategy failure, not tool failure:
> "Orgs churn from these platforms every year because they bought a technology and then implemented it without an actual strategy."

**Practitioner criticism, verbatim.** These come from Reddit via 42 Agency's aggregation (`[SNIPPET]` — Reddit itself was hard-blocked to every fetcher used):

> "We had it for a year, and canned it for sales teams. We were getting hot lead alerts when people were coming to our website to unsubscribe from marketing." — **u/jezarnold, r/sales (Jun 2025)**
>
> "Demandbase is expensive as hell and the targeting precision is overhyped. Half the impressions go to accounts outside their ICP." — **u/erickrealz, r/b2bmarketing (Oct 2025)**
>
> "$30K for job change monitoring feels unjustifiable. The core logic isn't complex enough." — **u/noobCoder00101, r/SaaS (Apr 2026)** *[on UserGems]*
>
> "October 2025 overhaul split credits into data vs actions; power users now nervous about bills." — **r/gtmengineering (Nov 2025)** *[on Clay]*
>
> "Warmly's identification rates trail RB2B (40-60% vs 70-80%), yet bundled pricing hits $5-10K annually vs RB2B's $1.5K starter." — **u/Competitive-Title793, r/b2bmarketing (Nov 2025)**

**The black-box scoring problem, from a RevOps leader** — the most important sentence in the tooling literature for anyone building an explainable research layer:

> "why is this account a 92, and what actually fired. Nobody on the floor could answer it"
> "reps quietly reverted to gut feel. The scores were doing their job for marketing, but on the sales floor a number with no visible cause does not turn into a first line of outreach"

And another RevOps leader: **"Intent was too unspecific, it was a blackbox."** https://salesmotion.io/blog/6sense-pricing `[FETCHED]`

6sense's own blog concedes the same failure mode: *"When signals pile up without context, they stop being signals and start being noise."* … *"The dashboard says 47 accounts are 'surging.' But which ones actually matter?"* … *"A score of 87 out of 100 tells you almost nothing: Why 87? What's driving it?"* … *"If your current scoring model can't tell your BDRs why an account is worth calling, it may be generating activity — but it's not generating clarity."* https://6sense.com/blog/how-to-prioritize-accounts-with-intent-data/ `[FETCHED]`

### 2.3b What things actually cost

| Tool | Price | Source |
|---|---|---|
| **6sense** | Median **$62,440** (381 Vendr deals, range $11.5K–$175K); average ACV $56,762; Essentials ~$36K / Growth $60–80K / Enterprise $100–200K+. Implementation 10–20% of license; onboarding 4–8 weeks; **2-year agreements**; credits don't roll over; auto-renewal default | `[FETCHED]` |
| **Demandbase** | Vendr median **$68,591** (185 purchases); basic $18–24K to $300K+. Display CPMs cost **30–50% more** than a standard DSP | `[FETCHED]` |
| **Bombora** | Median **$24,750** (range $12.25K–$80.5K); topics $500–$2,000 basic, $5K–$25K premium; API $5–20K/yr; implementation $5–15K. **Average time-to-ROI 17 months (G2)** | `[FETCHED]` |
| **Clay** | Free / Launch $185/mo / Growth $495/mo / Enterprise custom. Median enterprise **$30,400/yr** (range $12K–$154K). Dual currency since Mar 2026: Data Credits vs Actions | `[FETCHED]` |
| **ZoomInfo** | Average **$33,500/yr** (1,012 deals) to $140K+; **renewal escalation 5–10%/yr**; 90–120 day auto-renewal notice; average negotiated saving 21.8% | `[FETCHED]` |
| **Cognism** | Grow (5 users) ~$22,500/yr; Elevate ~$37,500/yr. Platform fee ~$15K + $1.5–2.5K/user | `[FETCHED]` |
| **RB2B** | Free (150 resolutions/mo) · Pro **$149/mo** · Pro+ **$349/mo**. **Month-to-month.** 15–20% person-level on Pro, 35–45% on Pro+, 70–80% with company-level. **US person-level only** | `[FETCHED]` |
| **Warmly** | Free · Startup **$700/mo** · Business $1,440/mo · Enterprise $2,400/mo. **12-month commitment, no free trial.** 20–40% typical identification | `[FETCHED]` |
| **Vector** | $399–$999/mo (Reveal) · $3,000/mo (Target). 15–30% contact-level, US-only. **SOC 2 Type 2 "in preparation"; does not auto-honor Global Privacy Control** | `[FETCHED]` |
| **Common Room** | Essential **$2,500/mo annual** (5 seats, 100k contacts); Vendr median ~$30,000/yr; enterprise $60–100K+. *"The $1,000-per-month Starter tier you'll still find quoted across the web is gone"* | `[FETCHED]` |
| **UserGems** | Core **$36K/yr + $3K implementation** · Advanced $75K + $5K · Elite $150K + $10K. Vendr median negotiated **$30,250** | `[FETCHED]` |
| **Keyplay** | Starter ~$750/mo (5,000 accounts) · Growth ~$1,500/mo · Scale ~$2,500/mo | `[FETCHED]` |
| **Trigify** | Starter ~$49/mo · Growth ~$99/mo · Pro ~$199/mo | `[FETCHED]` |
| **RollWorks** | Starter ~**$975/mo** · Standard $1.5–2.5K/mo · Professional $3–5K/mo. **Monthly contracts available; published pricing** (rare) | `[FETCHED]` |
| **Terminus** | Professional ~$24K/yr · Enterprise $48–72K/yr · Custom $75K+ | `[FETCHED]` |
| **Dreamdata / HockeyStack** | Dreamdata from **$599/mo** (30,000 MTUs); HockeyStack from **$1,399/mo** (10,000 visitors), other sources say $2,200/mo, mid-market $1–2.5K/mo | `[FETCHED]` |
| **Mutiny** | Growth **$50K–$90K/yr**; all-in with enrichment + operator **$230K–$430K/yr** | `[FETCHED]` |
| **Sendoso** | Essential $15–25K/yr · Plus $40–75K/yr · Pro $75–100K+/yr, *plus* gift cost, shipping, storage. Real all-in: small team (30 gifts/mo) ~**$34,400/yr**; mid-market (150/mo) **$80–200K/yr**; enterprise (300+/mo) **$250–400K/yr** | `[FETCHED]` |
| **DIY unbundled stack** | **$150–$1,400/month**: Sales Navigator $99/seat + Apollo/ZoomInfo $49–500/mo + CRM $0–800/mo + ad spend $2–5K/mo | `[FETCHED]` |

**Mutiny's minimum-viability thresholds** — rare and useful: named account list **200+ accounts minimum** ("below this, the per-account cost of running Mutiny does not earn out"); deal size **$50K+ ACV** with multi-stakeholder committees; **0.5 FTE** operator ($60–90K loaded). "Without that operator, the platform fee gets stranded." https://www.conversionwax.com/mutiny-abm/ `[FETCHED]`

**The DIY verdict** — a $150–$1,400/month stack "can replicate 70-80% of what an ABM platform does" for sub-500 account targets with $20K+ deal sizes, and is "directionally correct" for $2M–$10M ARR companies. And the line that should govern any tooling conversation:

> **"The platform is 20% of ABM success. The other 80% is your target account list, your content, your sales-marketing alignment, and your execution consistency."**

https://growigami.com/blog/abm-tools-comparison `[FETCHED]`

### 2.3c Intent data, judged honestly

> "59% of B2B teams say they're only somewhat satisfied with intent solutions, and 61% report it takes six months or longer to see ROI."
>
> One RevOps professional spent **$60,000** on intent data and had **"4,000 surging accounts in a dashboard and exactly zero new meetings"** after six months.

Five ROI killers: treating all intent sources equivalently; using intent without technographics/firmographics; ignoring data decay; relying on vendors for compliance; misaligning sales and marketing on signal definitions.

**Realistic conversion benchmarks:** topic-level intent converts at **5–15%**; page-level intent at **15–30%**. "The most common waste in intent data is paying for signals that never reach your reps."

**The stack-cost argument:** **"The license fee is the smallest line item. The real cost is the stack you need around it."** A Bombora-based stack with enrichment, sequencing, dialer and CRM integration reaches **$73,600–$200,000+/year.**

**Compliance red flag:** "Bidstream data tends to be high volume and low accuracy" — and the **UK ICO** and **Belgian Data Protection Authority** have ruled that collecting bidstream data **violates GDPR**.

Bombora-specific practitioner criticism `[SNIPPET via Prospeo's Reddit sourcing]`: *"noise dressed up as signal"* (r/gtmengineering) · *"0 real success"* after two months (r/sales) · *"trash"* from a 15-year veteran after heavy 6sense/ZoomInfo/Bombora spend (r/LeadGeneration) · *"mostly generic signals"* with conversion on raw intent **"under 2%"** (r/b2bmarketing). Structural limit: **"Bombora tells you which account is surging, but not who to call."** Account-level only, no contact data, English-only.

https://prospeo.io/s/intent-data-provider `[FETCHED]`; https://prospeo.io/s/bombora-pricing-reviews-pros-and-cons `[FETCHED]`; https://salesmotion.io/blog/intent-data-providers `[FETCHED]`

**The counter-view on community signals**, from a competing platform CEO:
> **"I've never seen a Discord thread predict a seven-figure purchase. Earnings language, leadership changes, and strategic initiatives do, repeatedly."**

https://salesmotion.io/blog/common-room-pricing `[FETCHED]`

### 2.3d Deliverability is now an existential variable

Sculpted, a Clay agency, publicly pivoted away from outbound. July 2024:

> **"thousands of emails sent. Zero opens. Zero replies."**
> "While outbound still works, it's becoming increasingly challenging to maintain reliable results."
> "when emails did get through, conversion rates were declining too."
> "most CRMs are filled with outdated, duplicate, or incomplete records."
> "messy CRM data isn't just annoying, it impacts your entire GTM engine."
> "What would you do if your entire business stopped working overnight?"

Multiple clients dropped simultaneously. Root causes named: Google/Microsoft filter strengthening; conversion decay independent of deliverability; underlying data quality. Corroborating `[SNIPPET]`: "Deliverability is now the single biggest variable in campaign performance, ahead of subject lines or copy quality."
https://www.clay.com/blog/sculpted-agency-pivot `[FETCHED]`

**The enterprise data reality — the strongest argument for a claim-store product:**
- **60% lack a single source of truth for data**
- **47% say data governance could be improved**
- Only **16% rely on predictive scoring**
- 70% use AI for content creation; 63% plan AI-powered journey orchestration; 52% plan AI content platforms; **22% have active interest in agentic AI**

https://inflexiongroup.com/resources/new-inflexion-group-research-reveals-how-account-based-thinking-is-shaping-b2b-marketing-transformation/ `[FETCHED]`

### 2.4 The plays

**A. The account-based podcast.** Currently the highest-signal low-cost play in the corpus.

Mechanics (five steps): (1) start with ICP + named target account list + relevant buying-committee roles; (2) invite leaders from target accounts, potential partners, decision influencers as guests; (3) have genuine conversations focused on the guest's world, not a pitch; (4) use the episode as a relationship accelerator — follow up, share with their team, stay engaged; (5) align sales and marketing so sales continues the conversation with existing goodwill.

> "the relationships are just as important as the episodes themselves."
> "It's targeted, not random. It's relationship-first. And it's designed to support revenue."

Three podcast archetypes, only one of which is ABM: **Content Engine** (awareness/consistency; "It's often hard (and not that helpful) to trace one specific episode to one specific opportunity"); **Public Figure** (personal brand; doesn't scale without the host); **Account-Based** (relationships and revenue; guest list = target accounts).

Result: **Kyler Nixon, Forward Studios (Darn Good Distributors Podcast)** — "After 3 months of outbound with no success, we launched our account-based podcast through Scrappy ABM and have generated **$60k ARR and $90k in pipeline across less than 10 podcast guests**." Also **29 guests booked in 4 weeks**. And **Jay Schwedelson, Guru Events**: "$1.5M in Revenue in Year 1 on our Podcast."

https://scrappyabm.com/blog/what-is-an-account-based-podcast/ `[FETCHED]`; https://scrappyabm.com/blog/3-podcast-approaches/ `[FETCHED]`; https://scrappyabm.com/ `[FETCHED]`

**B. Closed-lost re-engagement.** Universally recommended as the *first* play, not a late-stage one.

> "Some of your best pipeline opportunities are already sitting in your CRM."
> Principle: **"Go Back Before You Go Broad"**
> "roughly 60 to 80% of closed-lost reasons are temporary"

Three playbook variants: **Vertical-Specific** (same industry, market conditions shifted — regulations, economic shifts, budget freezes); **Objection-Based** (grouped by close reason: pricing, missing features, status quo, bandwidth); **Persona-Based** (return to single-threaded deals, engage the missing committee members).

Five steps: pull closed-lost from the **past 6–18 months** filtered by ICP fit → identify patterns in close reasons → pick ONE playbook and execute it thoroughly → secure sales alignment before launch → center messaging on **"why is now different from the last time we talked?"**

Run it for **90 days**. Avoid generic outreach: "Here's what's changed in your industry, and here's how we're helping companies like yours right now."
https://scrappyabm.com/blog/where-to-start-with-abm/ `[FETCHED]`

**C. Webinars/events as ABM triggers** (not as lead-gen).

TestRail (Joao Crisostomo, ABM lead): **"Our list decreased from 1000+ accounts to 72."** Q1 result: "4 enterprise sales opportunities (1 closed won)" plus "22 Sales-Accepted Leads" within 90 days. Webinar drew **70+ tier-1 target accounts** and generated **22 enterprise deals**.

> "B2B buyers come for practical learnings, connections and entertainment"
> "We didn't run a product-pitching event, but invited our solution architect to host an education webinar on solving the most painful challenge."
> Post-event chain: "Educate -> Engage -> Create demand -> Research and understand the buyer journey stage and current needs -> Create 'bridge' activities."

Certn's webinar: **53-minute average view time**, **84 engaged accounts** added to pipeline.
https://fullfunnel.substack.com/p/abm-events-case-study-and-playbook `[FETCHED]`; https://fullfunnel.io/four-abm-programs/ `[FETCHED]`

**Bridge activities** — the long-cycle alternative to "book a demo": offer 1:1 sessions with experts instead of an immediate demo. This is a named, reusable mechanism.

**D. Executive dinners and field ABM.**

> **Emily Kramer:** "Dinners are the new trade shows" — on the shift from large conferences to intimate executive dinners.
https://www.growthunhinged.com/p/b2b-gtm-playbook-for-2026 `[FETCHED]`

Andela's event-based field motion: guest lists aligned to ICP, coordinated sales+marketing invites and follow-ups, pre- and post-event sequences defined, events positioned as entry points to broader conversations. Result: **74 non-Andela attendees — 35 customers, 39 prospects.** https://scrappyabm.com/blog/abm-campaign-examples/ `[FETCHED]`

**E. Executive engagement programmes** — the enterprise version. Bev Burgess's seven steps: (1) set objectives (reputation with the organisation / with customers and influencers / revenue); (2) select executives (tiered like frequent-flyer benefits); (3) understand their motivations (including competing programmes competitors run); (4) decide content and themes — "what executives need to hear rather than organizational messaging"; (5) design activities and channels — peer networks (communities, conferences), small-group (advisory boards, workshops), individual (governance meetings, personalized briefings); (6) select, brief and train the team — **avoid sales pitches within the programme**; (7) create success metrics and a dashboard.
https://inflexiongroup.com/resources/seven-steps-to-setting-up-an-executive-engagement-programme/ `[FETCHED]`

**F. Engagement-based LinkedIn outreach.** Fullfunnel's six-step Account-Based Engagement Playbook: Thought Leadership → Thoughtful Commenting → Ecosystem Engagement ("Regularly appearing in the newsfeeds of the target accounts") → Personalized Connection Requests → Non-Sales Touches → Engagement-Based Outreach.

Weekly cadence: post content regularly; **5+ thoughtful comments weekly**; connect to **10 ICP buyers weekly**; engage with the ecosystem daily.

Reported rates: **up to 80% connection acceptance** and **40%+ response rates** with personalization; up to **60% response** to messages referencing a specific engagement signal (e.g. "saw your reaction on [Influencer]'s post about [topic]").

Ad targeting — five audiences, all of which amplify rather than convert: (1) ICP buyers; (2) Engagers (industry participants connected to buyers); (3) Industry influencers; (4) Partner brands (non-competitive, same ICP); (5) Niche media (podcast hosts, event organizers, community leaders). Paid spend goes to **guaranteed distribution of thought leadership**, not gated-content conversion.

> "LinkedIn is not an intent channel. People come to LinkedIn to connect, learn, or simply to distract themselves."
> "Five+ figure buyers don't download an e-book, and get 'nurtured' into an opportunity with a 5-email sequence."
> "People buy from people they know, like and trust."
> Result: **41 engaged, researched accounts** generated from vendor-unaware prospects, after zero replies from prior cold outreach.

https://fullfunnel.io/linkedin-marketing/ `[FETCHED]`; https://fullfunnel.substack.com/p/account-based-engagement-playbook `[FETCHED]`

**LinkedIn ads without clicks.** Adam Holmgren (Fibbler), via Scrappy ABM: measure influence via CRM connection, not clicks — **average CTR 0.4%**. Target specific titles; exclude broad "super titles." https://scrappyabm.com/blog/abm-lessons-from-practitioners/ `[FETCHED]`

**Organic social as an ABM play.** Greg Rokisky (Calendly): engage authentically when target accounts have viral moments, then hand off to sales; tag content by persona and brand; let performance shape the content calendar. Same source `[FETCHED]`

**G. Sales-rep-as-publisher.** CrossKnowledge had dedicated sales reps posting **five pieces weekly**; marketing-sourced pipeline went **30–40% → 60% in six months**.
> **Ellen Kaross, Certn:** "Our best-performing content wasn't from the corporate page—it was from sales reps sharing insights that spoke directly to target accounts."
> **Divash Basnet, Cardata:** "When sales reps act as thought leaders, they get better engagement than a corporate LinkedIn page ever could."
Certn's named artifact: **"Account Love Letters"** — sales-shared LinkedIn posts addressing industry-specific challenges with no product pitch.

**H. Product-as-content / proprietary research.** Austin Fuller (Exiger): use your own product like a customer, turn findings into reports, distribute across customers, prospects, analysts, media, sales and success. Result: **4–10x engagement vs other content types, millions in qualified pipeline, CEO testified before Congress.** https://exitfive.com/articles/8-marketers-share-top-plays-of-2026-so-far/ `[FETCHED]`

**I. The book-as-ABM-play.** Aditya Vempaty (Coram AI): design a book around what authors and readers care about; instant digital + print; distribution via 14 partner authors; launch event with signings and videos. Result: **4,000 downloads, 270 target accounts engaged, $10.8M revenue attributed = 65× return.** Same source `[FETCHED]`

**J. Customer-celebration campaigns.** Jessica Rosenberg (AirOps): celebrate customer wins instead of the product — SF billboards featuring customer champions, LinkedIn selfies with paid boost, a personalized marketing-archetype quiz. High viral engagement across customer networks. Same source `[FETCHED]`

**K. Direct mail and gifting.** Treated in the corpus as a *supporting* channel, not a standalone play:
> **Alex Olley (Reachdesk):** "You can weave direct mail and gifting to support your other channel tactics."
Fullfunnel lists "Direct Mail Outreach — personalized gifts with relevant case studies" as one of five warm-up tactics. https://insights.strategicabm.com/account-based-marketing-playbook `[FETCHED]`; https://fullfunnel.io/abm-strategy/ `[FETCHED]`

**L. Retention / churn-prevention ABM.**
> "Retention is just ABM applied to the accounts you've won."
> "Keeping a great-fit customer is almost always more efficient than replacing them."
> "Catching a churn signal early means you have options. You can address specific concerns before they become objections."
Mechanics: catch competitor research via third-party intent *before* renewal conversations; coordinate CS + sales + marketing on one account; replace generic check-ins with targeted interventions shaped by the discovered research pattern.
https://scrappyabm.com/blog/prevent-abm-churn/ `[FETCHED]`

### 2.4a Play mechanics with hard numbers

**Direct mail and dimensional mailers.** `[SNIPPET, aggregated]` Dimensional mailers post the highest response rate of any format at **12.19%**; ABM-coordinated direct mail reports **5–15%** on dimensional pieces. Cost per piece **$5.00–$25.00** (printing + postage, excluding design and list). Meeting generation **1–3 per 100 pieces** → implied **cost per meeting ≈ $500–$1,500**. Other KPIs: delivery rate 95%+ · account penetration 2–4 contacts per account · pipeline influence 10–20% of total · PURL engagement 8–20% · ROI target **5:1 to 15:1** for mature campaigns.

The only hard *gifting* performance number found: best-performing programs achieve **"15 to 25 percent meeting-acceptance lift on stalled outbound accounts"** — with the caveat that "generic, unfocused campaigns typically see no measurable lift." Cost structure is three separate line items: platform fee + gift catalog markup (**20–30% above direct brand purchases**) + shipping. https://theabmpulse.com/tools/sendoso-review/ `[FETCHED]`

Practitioner criticism of the gifting platforms, verbatim: *"They have platform fee, user license fee, inventory charges, shipping inventory from vendor to their warehouse, shipping from warehouse to customer, packaging."* · *"The cost is outrageous for the very low utility of the product."* · *"Slow shipping, inconsistent and unreliable."* Reachdesk uses **pay-on-redemption**, which "can reduce effective cost-per-acceptance by half" where redemption is low; Sendoso charges on send but wins on integrations (**90+ vs ~19**). Postal.io and Giftnote offer pay-per-send with no platform fee. https://www.docket.io/resources/research/sendoso-review `[FETCHED]`

**Executive dinners and roundtables — the best per-unit economics in the corpus.**

*Sizing and fill rate:* target **8–15** senior attendees (director+); **invite ~3× target headcount**; acceptance **25–40%** with strong personal outreach; keep a standby list of **2–3 vetted alternates per seat**; expect **15–25% of confirmed guests to drop in the final week**.

*Table design:* cap at **8–14** to hold a single conversation — larger groups splinter. Composition roughly **50/50 customers to prospects** for peer credibility. One sharp topic, one opening question, minimal host talking, **ban slides entirely**.

*The invite copy is the lever:*
> "An invitation that says 'Join [Your Company] for a product showcase' converts poorly; one that says 'I'm hosting a small dinner for a handful of [ICP] leaders to compare notes on [problem]'" performs well.

*Cost per head:* Lean (borrowed boardroom) **$300–$500** · Standard (private dining room) **$400–$800** · Premium **$800–$1,500+**. A 12-person standard dinner = **$5,000–$10,000 all-in**.

*Follow-up:* 24-hour debrief logged to CRM → one-week personal thank-you referencing the actual conversation, account owner initiates 1:1s → 30-day pipeline check. **Target: 4+ qualified meetings within 30 days for a 12-person event.** "Single influenced six-figure opportunity covers $8,000 dinner cost."
https://attendir.com/blog/executive-roundtable-vip-dinner-playbook `[FETCHED]`

*Field-marketing budget bands* (Vendelux): per-event spend in a Tier-1 city **$8,000–$25,000 all-in**. Annual supplementary program (4–8 events) **$80,000–$300,000**; primary channel with dedicated team **$500,000–$2,000,000+**; first-year startup budget **$80,000–$150,000**. Justification threshold **4–8 opportunities per dinner**. Worked example: **20 dinners annually → $3.2M event-sourced pipeline on ~$280k spend (≈11×)**.

*Planning cadence:* T-8 to T-12 weeks pull attendee data and identify target accounts → T-6 to T-8 begin personal invitation outreach → T-3 to T-4 confirm venue and brief executives → T+3 days personal follow-up from executives → T+30 days pipeline rollup.
> "Don't measure field marketing on 30-day pipeline only; the lag is real" — **60–90 day lag** from dinner to opportunity stage.

Formats and sizes: Regional Dinners **8–25** (the workhorse) · Executive Briefings 4–12 · Breakfast/Coffee 10–20 · Roundtables & Panels 15–40 · Conference Side Events 15–30.
https://vendelux.com/event-marketing/field-marketing `[FETCHED]`

`[SNIPPET, corroborating but vendor-sourced — treat as directional]`: attendee-to-meeting conversion for well-executed dinners **35–60%**; **5×–10×** pipeline-to-cost is the 2026 benchmark; a 12-seat dinner converts senior buyers at **25–45% vs 4–8% at large summits**; "a ten-person dinner outperform[s] a 500-person summit on every metric that matters at the enterprise tier."

**Job-change and champion-tracking plays.** The best dataset here is UserGems' Buying Signals Benchmark: **350+ companies, 2.3M opportunities, 67M contacts, 4.2M target accounts.**

*People signals ranked by opportunity-creation lift:* **Champion contacts +58%** · Closed-Won contacts **+50%** · New Hires **+45%** · Promotions **+39%**

*Company signals — % of companies seeing lift:* Funding 71% · Layoffs 69% · Hiring 68% · IPO 67% · Expansion 65% · Product Announcement 65% · Acquisition-as-acquirer 64% · Awards 64% · Partnership 63% · Legal Issues 63% · Management changes 63% · Acquisition-as-acquired 57%

*Champion account impact:* win rates **114% higher** · deal cycles **12% shorter** · deal sizes **54% larger**. **Customer Competitors** convert **2.5×** higher than cold ICP accounts; emails mentioning competitors carry **+40%** opportunity-creation lift. **New executives convert 2.5× higher in their first 3 months** than after one year.

*The market-decay numbers that justify the whole category:*
> Activities needed per meeting **5 years ago: 300. Today: 1,300 (4× increase).**
> Opportunity creation takes **3× longer than 2020**; deal cycles **66% longer**; **1.5× more contacts** needed.

https://www.usergems.com/power-up-your-pipeline `[FETCHED]`

*Play mechanics:* new leaders evaluate vendors most openly in their **first 90 days**; reach out within **30 days** of the move — "moves caught in week one land inside the high-conversion window; quarterly CRM audits burn 6+ weeks." **New executives spend roughly 70% of their budget within the first 100 days.**

*Portfolio math per 1,000 tracked contacts annually:* ~200 job changes (20%) → 80–100 ICP-fit signals (40–50% land at target companies) → 12–38 qualified conversations (15–25% response on warm outreach) → **~$90,000–$100,000 closed revenue at $50K ACV**.

*Win rates:* "opportunities involving contacts with prior experience of the product won at **37%, versus 19%** without" (Champify 2025). Former advocates convert **6.3× more efficiently** first-touch-to-close; alumni buyers **3× more likely** to purchase.

*Message structure:* lead with congratulations, not a pitch. Cadence **3–5 touches** — email → LinkedIn message → email with relevant content → call, each adding new value. Channel contribution: **10–20% of total pipeline** in systematic programs, at 2–3× cold conversion.

*Who to track — five tiers:* (1) Tier 1 customer accounts (primary contacts, decision-makers, champions, influencers) · (2) product users (admins, power users, high-NPS regulars) · (3) open-opportunity decision-makers and influencers · (4) closed-lost contacts · (5) churned accounts (approach carefully, with solutions to past objections). Baseline: **20%+ of contacts change jobs annually; 2–4% per month.** Data-quality standard: **<5% bounce rate**, monthly refresh.
https://salesmotion.io/blog/job-change-signals-pipeline `[FETCHED]`; https://www.usergems.com/blog/track-job-changes `[FETCHED]`

**Cold calling after content engagement — the intent-triggered call.**

The segmented benchmark that matters `[SNIPPET, Precision Outbound]`:
> "Cold list should be benchmarked against **1.5–2% dial-to-meeting**. Marketing-qualified leads against **4–6%**. **Intent-triggered or warm contacts against 5–25%.**"

Belkins' full funnel `[FETCHED]` https://belkins.io/blog/cold-calling-benchmarks:
- **Per-dial connect 9.9%** · per-prospect connect 24.5% across attempts · connect-to-conversation 58% · conversation-to-meeting 4.6% → **~370 dials per booked meeting**
- **Call duration as a quality signal:** meeting-booking calls average **3.7 minutes**; "not interested" calls **~0.9 minutes** — meeting calls are **4× longer**
- Best days **Wednesday (0.95% positive), Monday (0.77%)**; worst **Friday (0.51%)**. Best hours **3–4 PM (1.05–1.22%)**, secondary peak 6 PM (1.47%)
- Seasonality: strongest **February 8.9%, May 8.5%, November 6.5%**; weakest **July 2.7%, August 3.0%, September 3.2%**. "Summer kills meeting rates, not connect rates"
- By seniority: C-level 0.95% positive (follow-ups only, no live bookings) · **Directors book the most actual meetings** · **VPs 7.3% live rate (most gatekeeper-protected)**
- Geography: US 9.0% live / 0.55% positive vs **UK 14.7% live / 2.84% positive**
- Of non-conversions: hard rejections 31%, follow-up requested 19%, **data-quality issues (wrong person/number) 13.5%**

`[SNIPPET]` r/SalesOperations: *"6% honestly sounds about right for 2025. Those 15-20% numbers from a few years ago feel like ancient history at this point — everyone's screening unknown numbers now."*

**The full outbound benchmark set** — 12 benchmarks across 100+ SaaS companies, the densest numbers table found. https://www.autobound.ai/blog/10-outbound-sales-benchmarks-crushing-it-for-100-saas-companies-and-how-to-steal-their-playbook `[FETCHED]`

| Benchmark | Figures |
|---|---|
| Cold email reply | Average **3.43%**, top quartile 5.5%, elite 10.7%+. **First emails generate 58% of replies; follow-ups 42%** |
| Open rate | Well-targeted 40–60%; generic 5–10%. Caveat: Apple Mail Privacy Protection **inflates opens by ~18 points**. Subject lines referencing company/pain: **+22–30%** |
| Meeting book rate | **1–4% of sequences started.** Enterprise/C-suite 1–2%; mid-market Director/VP 3–5%. Reply→meeting 15–30%; meeting→qualified opp 25–40%. **Generic problem hooks 0.69% vs timeline-based hooks 2.34%.** "Email-only sequences underperform email + LinkedIn + phone by 2-3x" |
| MQL→SQL | Industry average **13%**; behavioral scoring **39–40%**. SEO 51% · email 46% · webinars 30% · PPC 26% · **purchased lists <1%**. Speed: **53% within 1 hour vs 17% at 24 hours** |
| Deal size | Median SaaS ACV **$26,265**. SMB $4.8–15K · mid-market $15–50K · enterprise $50–250K+ · public-company median $220K |
| Sales cycle | Median **84 days**. SMB 30–90 · mid-market 60–120 · enterprise 180+. **Average stakeholders 6.8, up from 5.4 in 2020**; $250K+ deals **19+ stakeholders**. **Deals with 3+ contacts close at 2.4×** |
| CAC | Median payback 6.8 months (B2B SaaS 8.6). LTV:CAC median 3.8×, top 5–7:1. **CAC rose 40–60% 2023–2025**; current private SaaS CAC payback **23 months** |
| Lead response | **Within 5 min = 21× more likely to qualify** vs 30 min. **First-vendor advantage 35–50% of sales.** Industry average response **42 hours**; **55% of companies take 5+ days** |
| Win rate | SMB (<$10K) median **31%** · mid-market ($10–50K) 24% · upper mid ($50–100K) 18% · enterprise (>$100K) **15%**. Executive sponsorship (VP+) **2–3× higher** |
| Pipeline coverage | 3–5× quota. **3.2×+ coverage → 89% quota attainment; below 2.8× → 52%.** Weekly-tracking orgs grow **34% annually** vs 11% |
| SDR productivity | Top 25%: **12–15 qualified meetings/month**; median 8–10; elite 10%: 18+. By channel: multi-touch 4.0–7.0% · LinkedIn DM 2.0–4.5% · cold call 2.0–3.5% · **cold email alone 0.8–2.0%** |
| Quota attainment | **27% of B2B reps hit quota (2024)**; average SDR attainment 53.2% |

> "These 12 benchmarks form a diagnostic funnel, not a report card."

**Personalized microsites / 1:1 ABM pages.** Page anatomy per Mutiny's blueprint: personalized header with **paired logos** · initiative-mapped headline **in the prospect's language** · industry-specific social proof · feature spotlight tied to their use case · **2–3 curated resources** for their industry and maturity · **a single CTA aligned to buying stage**. Microsite view-rate benchmark `[SNIPPET]`: **7–12% of targeted accounts**. https://www.mutinyhq.com/blueprints/1-1-abm `[FETCHED]`

The BDR-drives-traffic mechanic matters more than the page: BDRs call prospects *before* sending the microsite link, reference the content during the call, then follow up days later.
> **Meg Noonan, Senior Marketing Manager, Veracode:** "Another area that we are bringing them in from is through our BDR outreach"
> **Grace Kleaveland Kupczak, Senior Digital Marketing Manager, 6sense:** "Things I've run in Mutiny that I thought were gonna do well didn't, and things that I might not have thought would have gone well did"
https://www.mutinyhq.com/blog/abm-tactics `[FETCHED]`

**The reverse demo.** The prospect shares *their* screen and solves a real problem live, guided by the rep. Steps: email beforehand asking them to prepare a specific problem → if unprepared, spend the first 5 minutes co-developing a personalized use case → prospect shares screen and signs up → rep uses **Zoom annotations** to guide exact click locations → **solve their stated problem within 30 minutes** → invite everyone to a shared Slack community before the call ends. Rationale: early Clay demos left prospects "unable to reproduce what they'd witnessed, causing churn." Results: 100+ sessions; a-ha moment reduced from multiple calls to **5–20 minutes**.
> "Solve the customer's stated problem within the 30 minutes, and try to blow their minds in the process."
https://www.clay.com/blog/reverse-demo `[FETCHED]`

**Paid ads as an ABM channel.** Clay's own numbers: **$1.3M pipeline from a few thousand ad dollars (~23×)**, campaigns ranging **30×–90×**; LinkedIn CPL **$250 → $25**; Google CPL down 30–50%. Three workflows: **dynamic exclusion lists** (customers, open opps, recent inbound, partners — refreshed daily), **first-party retargeting** (product usage, lead scores, inbound history), **enriched lookalikes** (adding personal emails/phones raised Meta match from **~30% to 70%+**, taking Meta from "unusable" to **$10 CPL within 24 hours**). Match rates: **LinkedIn up to 95%, Meta up to 70%.**
> "The moment you export it, the data starts falling behind immediately."
> **Talia Schliefer, demand gen lead at Clay**, on exclusion lists: "they become stale so fast" — automation prevents wasting "50% of your budget on accounts that are going to generate zero percent of your pipeline"
> "If you convert 20 customers, they should stop seeing ads within days, not at the next calendar reminder."
https://www.clay.com/blog/paid-ads-playbooks `[FETCHED]`; https://www.clay.com/blog/how-clay-uses-clay-ads `[FETCHED]`

**LinkedIn ads — the ABM-relevant benchmark set.**

*ZenABM, 2026 report — 161,256 ads from 211 companies across 29 countries, CRM-connected* `[FETCHED]` https://zenabm.com/blog/linkedin-abm-benchmarks:
- Median: **CTR 0.69% · CPC $11.04 · CPM $78.30 · pipeline per $1 = 5.21 · ROAS 1.62**
- **Thought Leader Ads: CTR 2.68%, CPC $2.29–$3.06** vs Single Image 0.42%/$13.23 · Carousel 0.49%/$11.28 · Video 0.24%/$15.61 · Text 0.02%. TLAs are roughly **6× more efficient** than single-image
- **Top-quartile performers by pipeline/$: $6,576 monthly spend, pipeline per $1 = 15.20 (3× median), ROAS 2.79 — at a LOWER CTR of 0.21% and a higher $21.91 CPC**
- Median monthly spend **$2,693**; median 312 ads across 16 groups; **median 6,423 target accounts/month**; median deal open rate 0.58%
- **"Impressions drive pipeline" (ρ = 0.445); CTR shows a negative relationship to pipeline**
- CPL by region: North America $200–250 · Europe $120–150 · APAC $80–120 · LATAM $60–90. Conversion by offer: demo/high-commitment 2–5%; content/low-friction 10–15%. Lead Gen Forms ~10% and **reduce CPL 20–30%**

*Six practitioner rules from the same dataset:* (1) never use blended benchmarks — compare within ad formats only; (2) higher CTR doesn't guarantee pipeline quality; (3) Lead Gen Forms work best **paired with landing pages** for retargeting and account-level tracking; (4) **"Top performers optimize for accounts, not leads"**; (5) "Engagement ≠ business impact"; (6) **"Attribution is the biggest gap — LinkedIn influence [is] undercounted without account-level CRM tracking."**

*HockeyStack Labs, 2025 — 70+ B2B SaaS companies, $28M in LinkedIn spend, 3 years* `[FETCHED]` https://www.hockeystack.com/lab-blog-posts/linkedin-ads-benchmarks:
- CTR Q1 0.82% → Q3 0.96% → September peak 1.05%; CPC Q1 $10.48 → Q3 $15.72
- Spend seasonality: Q1 27.5% · Q2 18% · Q4 31%; peak month February
- **Efficiency (spend share → MQL share): Q1 27→27 · Q2 18→30 (best quarter) · Q3 22→22 · Q4 31→20 (worst)**
- **MQL→SQO cycle lengthens through the year: Q1 24 days · Q2 45 · Q3 62 · Q4 68**
- Pipeline ROI: Q1 2.44× · Q2 2.53× · **Q3 6.01×** · Q4 2.46×

*ABM targeting mechanics* `[SNIPPET]`: matched audiences + persona filters convert **2.7× higher** than broad targeting; **optimal audience size 50–500 companies**; ABM campaigns produce **38% lower CPLs** once the audience reaches statistical maturity. B2B CPL typically $150–$450, rising to **$400–$800** for enterprise ICPs.

**M. The four starting places** (Cosby) — ranked by leverage, not by ambition:
1. **Website traffic** — "accounts actively poking around, and in some cases, evaluating solutions like yours"
2. **Closed-lost** — "These are accounts that know you, and at some point said, 'This could work.'"
3. **Sales pipeline** — "They've been qualified, and conversations have started. They're just moving slower than you'd like." (acceleration, not creation)
4. **Current customers** — "They already know and trust you. And chances are, they have problems you can help with that they don't even realize you solve."
> **"Start where you have the most leverage."**
https://scrappyabm.com/blog/4-places-to-start-with-abm/ `[FETCHED]`

### 2.5 Timelines to results

| Milestone | Timeframe | Source |
|---|---|---|
| Brand recall / awareness metrics become meaningful | **3–6 months** | Cosby `[FETCHED]` |
| Early signals visible | "within the first few months" | Scrappy ABM `[FETCHED]` |
| Setup → education → sales cycle → revenue | ~**12 months** | Cosby, Exit Five `[FETCHED]` |
| Pilot program duration | **6 weeks** (Fullfunnel 1-1-1-…-10) to **6 months** (CrossKnowledge) | `[FETCHED]` |
| Closed-lost playbook test window | **90 days** | Cosby `[FETCHED]` |
| 1:1 strategic account relationship cycle | **12–18 months**; planning horizon **3 years** | Fullfunnel / Burgess `[FETCHED]` |
| Opportunities from a narrowed list | "6–9 months post-outreach" | Fullfunnel case 3 `[FETCHED]` |
| Client graduation from an ABM agency program | "about 18 months" | Scrappy ABM `[FETCHED]` |
| Enterprise buying cycle | **10.1 months** (2025), down from 11.3 (2024) | 6sense `[FETCHED]` |

---

## 3. Measurement Practitioners Respect

### 3.1 The 3Rs — the framework everything else hangs off

ITSMA coined **Reputation, Relationships, Revenue** in 2004; it remains "the core framework for measurement" in the 2026 Inflexion benchmark. Revenue and relationship metrics predominate; **reputation impact proves challenging to measure**.

**Reputation** — surveys, interviews, advocacy programs, NPS; social engagement rates, follower growth, content shares, referral traffic; campaign engagement; landing-page and hero-asset traffic.
> **Declan Mulkeen:** "ABM (and ABMers') job is to focus on the named Account list and build 'Reputation-building' programs."

**Relationships** — number of contacts within target accounts; quality of contacts (identifying Champions and Blockers); sales conversations generated; event/workshop attendance; content engagement and sharing.
> **Declan Mulkeen:** "When you are selling high-value products and services (that have a long and complex sales cycle), the relationships you form...will often make or break these deals."

**Revenue** — meetings booked; win rate (Strategic ABM reports 25%); % of pipeline from named accounts over time; deal velocity (28% faster with ABM per Gartner); ACV; CAC.
> **Alex Olley, Reachdesk:** "The real ROI of ABM is revenue, right? Close won revenue on the board. That's what we all want at the end of the day"

Implementation warning: "Try not to build a comprehensive reporting dashboard on day one. Focus on what is achievable in terms of measuring and build out your full dashboard over time."

https://insights.strategicabm.com/account-based-marketing-metrics `[FETCHED]`; https://insights.strategicabm.com/account-based-marketing-roi `[FETCHED]`; https://inflexiongroup.com/resources/2026-abm-benchmarking-study-research-summary-a-look-at-programme-objectives-metrics-and-governance/ `[FETCHED]`

**Why the 3R structure matters politically** (Inflexion): "marketing's influence over revenue growth is less direct" — the three-category structure protects marketing from being "reduced to a single, often lagging, revenue figure."

**Important correction to the common belief:** there is **no ITSMA "activity / output / outcome" three-tier hierarchy.** ITSMA's canonical framework is the Three Rs. The activity/output/outcome shape exists, but under other names — see §3.1a. Bev Burgess's own statement of the framework:

> **"The best ABM-ers identify their impact on the levers that drive long term growth in accounts: building stronger reputations, broadening and deepening relationships with buyers and influencers, and supporting opportunities to increase revenue."** — Bev Burgess, SVP ITSMA Europe & ABM Practice Leader
https://www.agent3.com/blog/agent3-itsma-make-measuring-abm-easier `[FETCHED]`

### 3.1a The documented extensions of the 3Rs

**Agent3 — the "4Rs":** Revenue, Reputation, Relationships, **Readiness**, applied across program maturity. Maturity progression: **Launch** = on-time/on-budget asset delivery → **Early** = reputation metrics (opens, clicks, web visits) → **Mid** = relationship indicators (key buyer engagement, early opportunities) → **Mature** = revenue (pipeline, influenced revenue, deal velocity). Three measurement roles named: "Generating Insights," "Reporting on performance," "Analyzing program impact."
https://www.agent3.com/blog/precision-abm-measuring-what-matters `[FETCHED]`

**Harte Hanks — the "5 R's":** **Readiness, Reach**, Reputation, Relationships, Revenue.
- **Readiness** — "your ability to enable and scale ABM initiatives, considering the capabilities and resources that contribute: budget, capacity, data, headcount, leadership and alignment."
- **Reach** — capacity to connect: identified decision-makers, opt-in rate, contact addresses per account, known external influencers, contact data volume.
No formulas published. https://www.hartehanks.com/blog/measuring-success-the-5-rs-of-account-based-marketing-metrics/ `[FETCHED]`

**INFUSE — three layers: Activity / Progression / Revenue.** This is the closest published analogue to an activity/output/outcome hierarchy.
- **Activity layer:** engagement velocity; contact engagement signals. These "confirm that marketing reached an audience" but say nothing about whether purchase-influencing stakeholders are engaged.
- **Progression layer:** buying-group coverage %; time-to-opportunity; stakeholder progression.
- **Revenue layer:** pipeline sourced from target accounts; deal velocity by segment; ARR ÷ program cost (including expansion and retention); forecasted contribution via "stage-weighted conversion rates."
https://infuse.com/insight/abm-measurement-framework-engagement-to-revenue/ `[FETCHED]`

**Starr Conspiracy — six named frameworks:** ICP-Fit Account Selection Model · Tiered ABM Coverage Framework (**1:1 = 5–25 accounts, 1:Few = 50–200, 1:Many = programmatic rest**) · Account Orchestration Sequence · Intent-Signal Activation Framework (signal taxonomy, source weighting by provider confidence, threshold logic, play assignment, **decay rules**) · **TEAM** (Targeting, Engagement, Activation, Measurement) alignment framework · Pipeline-Weighted ABM Measurement Model. https://www.thestarrconspiracy.com/insights/frameworks/account-based-marketing-frameworks `[FETCHED]`

### 3.1b Formulas and thresholds

The corpus rarely publishes formulas. These are the ones that do exist.

| Metric | Formula | Threshold / benchmark |
|---|---|---|
| **Account coverage** | `accounts engaged ÷ Target Account List × 100` | **"Aim to touch 60 to 80 percent of your target list each quarter"** |
| **Buying-group coverage** | `(engaged stakeholders ÷ total buying-group members) × 100`; or `roles engaged ÷ roles in persona model` | **"Coverage above 60% correlates with higher pipeline progression rates for Tier 1 accounts"**; lower acceptable for Tier 3 |
| **Multi-threading depth** | `avg contacts per account` | **≥4 mid-market, ≥6 enterprise**; GTMonly: "Push for **three or more** engaged contacts per account" |
| **Account penetration** | `engaged or won accounts ÷ total list × 100` | "For an enterprise program, landing **20 to 30 percent** is genuinely strong" |
| **Account engagement score** | `Σ (touchpoint × recency)`, weighted **ad = 1, content = 5, demo = 10** | "Hot Account Count" = accounts ≥ **50 pts/quarter**; touchpoint volume, mature: **50+/quarter** |
| **Engagement velocity** | acceleration/deceleration over defined periods | **"Velocity increases of 25% or more week-over-week typically precede stage progression within two to four weeks"** |
| **Time-to-opportunity** | qualification → opportunity creation | **"Under 60 days indicates efficient execution; above 120 days signals operational bottlenecks"** |
| **Deal velocity lift** | `(ABM − non-ABM) ÷ non-ABM` | Programs should "shave that cycle by **20 to 40 percent** versus your non-ABM deals" |
| **ACV lift** | `(ABM avg − non-ABM avg) ÷ non-ABM` | Benchmark cited: "ABM-sourced deals close **33% larger**" |
| **Account-to-opportunity rate** | `opps from targets ÷ targets × 100` | Fullfunnel's field version: **account-to-pipeline ratio** |
| **Program ROI** | `(revenue − cost) ÷ cost` | "average ROI is **137%**"; measure over a **12–18 month window** "because anything shorter lies to you" |

Sources: https://www.motionabx.com/abm-kpi-framework `[FETCHED]` · https://gtmonly.com/abm-metrics/ `[FETCHED]` · https://infuse.com/insight/abm-measurement-framework-engagement-to-revenue/ `[FETCHED]` · https://thesmarketers.com/blogs/abm-measurement-framework/ `[FETCHED]`

**Refine Labs' HIRO — a qualification threshold, not a count.** HIRO = **High Intent Revenue Opportunity**, defined by an outcome bar: **"a 25% or higher win rate"** — at least 1 in 4 closes. Their published comparison: **Pipe™ (declared intent) $3.4M sales velocity, 25% HIRO win rate, 8% lead-to-win** vs **Cold Outbound $1.1M, 15% SQO win rate, 5% lead-to-win**. https://www.refinelabs.com/blog/pipeline-qualification `[FETCHED]`

### 3.1c The metric practitioners trust most: conversion lift vs a held-back control group

This is the methodological answer to the whole attribution debate, and it comes with a real published number.

> **Brian Kotlyar, Hightouch:** "The accounts that are in the treatment group… they'll convert from unengaged to a stage one opportunity with us at about **thirty two percent higher rate** than the general population." Also reported: **38% more conversion from stage one to stage two** among ABM accounts.

The method, stated plainly:
> **"Stop asking 'which touch gets the credit.' Start asking 'what would have happened without us.' The way you answer it is uncomfortable but simple: hold back a control group."** … **"The win rate, deal size, and velocity gap between the treated accounts and the held-back ones is your real contribution. Not the total. The difference."**

Snowflake runs the same logic without the word "control": rather than crediting teams, they measure **"lift"** by comparing engagement between target and non-target accounts.
https://exitfive.com/podcast/abm-what-ramp-snowflake-and-hightouch-are-doing-in-2026/ `[FETCHED]`; https://gtmonly.com/abm-metrics/ `[FETCHED]`

### 3.2 Coverage

Coverage is measured two ways in practice:
1. **Account coverage** — what proportion of the target list has been researched, has a plan, and has an owner. Fullfunnel tracks **"Fully researched accounts"** and **"Buying committee members enrolled"** as explicit leading indicators for the Future Pipeline list.
2. **Buying-group coverage** — how many distinct committee members inside an account have been engaged. This is the metric the 2026 benchmark says is displacing lead counts: measurement is driven by **"buying group engagement and pipeline impact."**

Cunningham's replacement metric set makes this explicit: measure **"Buying group engagement"** rather than "Lead volume [which] counts individual identities captured."

Coverage discipline in Fullfunnel's model runs the other way too — the number that matters most is how aggressively you *cut*: TestRail "1000+ accounts to 72"; one case "Initial list 200 accounts narrowed to 13"; BenchPrep "62 strategic accounts."

### 3.3 Engagement — and the "progression not activity" rule

**The distinction that separates good ABM measurement from bad,** Cosby, verbatim:

> **ABM metrics (activity):** impressions, clicks, account visits, email opens, engagement data — "Numbers reflecting what happened"
> **Business outcomes (impact):** pipeline created, deals moving faster, customer expansion — "Numbers revealing what it meant"
> "both matter, but most teams spend too much time on the first category and not enough connecting it to the second."
> **"Movement > engagement."**
> "a dashboard full of data and one full of answers are two different things."
> "If you stopped sending your current reports tomorrow, would sales or leadership feel a serious loss of insight?"
> "When the information marketing tracks starts changing what sales does next, that's when you know the ABM strategy is working."

https://scrappyabm.com/blog/activity-isnt-impact-fixing-abm-measurement/ `[FETCHED]`

**The four leading indicators to report before pipeline exists:**
1. **Account engagement depth** — multiple people from the account repeatedly engaging with *evaluative* content (case studies, pricing, product pages)
2. **Persona spread** — engagement expanding beyond a single champion to multiple committee roles
3. **Stage velocity** — speed of progression between stages; shorter gaps = strategy working
4. **Sales behavior change** — reps gravitating toward target accounts and reporting prospect brand familiarity

Cadence: leading indicators **weekly or bi-weekly**; lagging indicators **monthly or quarterly**.
> Signals must be "account-level and show movement" to be useful — general traffic spikes lack the specificity needed.
https://scrappyabm.com/blog/abm-signals-before-pipeline/ `[FETCHED]`

**The four questions every ABM report should answer** (Cosby):
1. Are we measuring each stage on the right timeline? ("Brand recall takes three to six months, so awareness metrics need a monthly or quarterly view to mean anything.")
2. Are we tracking the signals that matter? ("The signals worth watching are the ones that consistently show up right before an account is ready for sales.")
3. Why aren't engaged accounts advancing? ("Usually it's not a lack of interest but a broken next step.")
4. Are we doing more of what works before starting something new? ("Most of the growth available in an ABM campaign comes from the first two rather than the third.")
https://scrappyabm.com/blog/four-questions-every-abm-report-should-answer/ `[FETCHED]`

### 3.4 Metrics by program type — the single most-violated rule

> **"The worst thing you can do is measure different ABM campaigns the same way."** — Fullfunnel

| Program type | Metrics |
|---|---|
| **Net New Revenue** | # engaged accounts · # discovery calls booked · # sales opportunities · ACV · sales cycle length · won deals · new revenue ROI |
| **Deal Acceleration** | # interviews with Champion · # workshops booked · won deals · "Activation cycle (from interview to invoice)" |
| **Expansion** | case studies created · workshops arranged · new licenses sold · LTV growth · total expanded revenue |
| **Contract Renewal / Churn Prevention** | presentations booked · resigned contracts · renewed revenue |

https://fullfunnel.substack.com/p/how-to-measure-abm-w-report-templates `[FETCHED]`

**KPIs by list** (Fullfunnel):
- **Cluster ICP** (unaware) → goal: awareness. Leading indicators: "Personalized connection requests", "Thoughtful comments"
- **Future Pipeline** (aware, need unknown) → goal: engaged buying committee. Track "Fully researched accounts", "Buying committee members enrolled"
- **Active Focus** (aware, need known) → goal: discovery calls. Monitor "Fully personalized solution offerings", "Booked bridge activities"

**Six essential reports:** total revenue by program/tier; pipeline progress with deal status; program performance; sales engagement (personalized outreach); account engagement; account development progress.
> "Show the impact on revenue and pipeline, and show your progress."
https://fullfunnel.substack.com/p/abm-kpis-and-reports `[FETCHED]`

**Program-level unit economics worth committing to memory** (Fullfunnel's own quarter): **46 accounts engaged · 43% engagement rate · 8.7% account-to-pipeline ratio · 3 sales opportunities · 1 closed-won** ("the biggest project ever"). https://fullfunnel.substack.com/p/our-abm-program-breakdown-case-study `[FETCHED]`

### 3.5 What practitioners mock

**MQLs.** Cunningham's **"MQL-Industrial Complex."** Miller's **"gumball machine"** — "in goes budget, out comes leads." Fullfunnel's podcast summary lists **"MQLs are fictional lifecycle stages."** Fullfunnel: "LEADS are a lagging indicator of your marketing & sales efficiency."

**Dashboards as theatre.** Cosby: "You spend twenty minutes making sure the formatting is perfect before the leadership meeting (s/o color gradients)."

**Attribution software.** Chris Walker (Refine Labs) — the most quotable critique in the corpus:

> **"The attribution Mirage is where companies are following attribution software, thinking that they're super data-driven. And they're actually being led astray."**
>
> "I believe that most companies make the wrong decisions because they rely too much on attribution software and not enough on common sense."
>
> "It's not that attribution software is wrong. It's that attribution software is favoring lower funnel channels that people pass through when they're ready to buy..."
>
> **"Attribution software based attribution fails to measure social media accurately. It fails to measure communities at all. It fails to measure word of mouth at all. It fails to measure podcasts at all."**
>
> "Social media for us is under-reported by about 70%. And then what the attribution software says is that 85% of our leads and our opportunities come from organic search or direct traffic."
>
> "There has been opened up word-of-mouth channels between B2B professionals… none of it gets tracked by attribution software and none of it creates intent data."
>
> "Use capture demand attribution with multi-touch attribution software. But you need an additional layer of what's creating demand in channels that aren't typically attributable"

https://martechpod.com/episode/measuring-marketing-without-vanity-metrics-chris-walker-refine-labs/what-is-dark-funnel-chris-walker-refine-labs/ `[FETCHED]`

Additional Refine Labs figure `[SNIPPET]`: a **90-percentage-point gap** between software-reported and customer-self-reported attribution against web search, across a 12-month, 620-conversion, $21.5M ARR study.

**On "influenced pipeline" as a fudge** — the cleanest dismissal, and it comes from the man who built Marketo and Engagio:

> **Jon Miller:** "marketing sourced and or marketing influenced pipeline… **I think that's actually a terrible idea**"

And the selection-bias argument, stated as bluntly as anyone states it:
> **"When those accounts close, claiming ABM caused it is a sleight of hand. They were your strongest bets before a single ad ran."** — GTMonly

Miller's team-scoreboard alternative: what matters is "is there enough pipeline to make our goals. And everybody, marketing, sales and the AE should be measured against that total." … "nobody's measuring on the scoreboard… the wide receiver scored versus the running backs. What's on the scoreboard is did we get enough points to beat the other team?"
https://www.modop.com/podcasts/the-death-of-mqls-how-to-measure-marketing-performance/ `[FETCHED]`

**On engagement scores as black boxes:**
> **"Engagement scores are seductive liars. An account bingeing your whitepapers feels like a hot lead, but reading is not buying."** — GTMonly
> "Platform-driven metric optimization" — chasing "engagement scores, intent tiers" **designed by vendors rather than correlating to revenue**; and "Engagement without progression" — high activity masking "stalled pipelines behind positive-looking interaction data." — INFUSE
> "Engagement metrics are improving but meeting volume is not" — listed as a **warning sign of structural failure**. — DemandScience

**On lead volume as the comparison basis:**
> Comparing "300 leads" from inbound to "30" from ABM, where "those 30 accounts are worth ten million in pipeline" while "the 300 leads are mostly students and competitors," is **"judg[ing] a sniper by how many bullets they fire."** — GTMonly

**On impressions, clicks, form fills, emails sent:**
> **"Activity metrics will kill an ABM program faster than a bad target list."** — Starr Conspiracy
> "Emails sent, ads served, and impressions delivered demonstrate operational output without conversion context" — INFUSE
> "Clicks and opens describe the campaign. Stage progression describes the account. Report the second, not the first." — Motion ABX
> "The B2B buyer journey is not linear. Clicks and downloads ≠ buying intent." — Fullfunnel

**On form fills specifically** — 6sense indicting the form-fill model it once profited from:
> "**Fewer than 30% of eventual buyers ever fill out a form** on the winning vendor's website." Teams measure only "the fraction of the buying group willing to trade an email address for content." Myth #1: "A person who fills out a form is likely to buy." Myth #2: "Form-fill leads are the gold standard for predicting pipeline."
https://6sense.com/blog/the-broken-assumptions-that-limit-b2b-revenue-growth/ `[FETCHED]`

**On MQLs, the best horror story with a number:**
> **Ken Roden:** "We had a month where we generated **3,500 MQLs**… very few resulted in actual opportunities. Sales teams didn't trust the leads." … "Marketing and sales were not speaking the same language. Sales didn't trust MQLs."
> **Refine Labs:** "Measuring on MQLs incentivizes teams to get the most volume of MQLs for the lowest cost (low intent conversions), which creates a gap in alignment with sales productivity and sales goals." … "Most companies don't analyze their marketing performance with revenue in mind."
> **The Smarketers:** "Lead metrics would score eleven stakeholders from one target account as **eleven unrelated records**"
> **Inverta:** "volume-based goals meant that marketers were incentivized to qualify more and more MQLs, leading to lower and lower lead quality for sales" … "Sales got overloaded with junk leads—most of which they had to say no to"
> **Forrester (Simon Daniels, principal analyst): "Fewer than 1% of leads ever convert to a closed deal"**

Also: Forrester 2013 measured **"just 0.75% of MQLs converted to revenue."** And the 2026 shift `[SNIPPET]`: **61% of CMOs report being measured primarily on pipeline contribution in 2025 vs 38% in 2022.**
https://fullfunnel.io/abm-pilot-program/ `[FETCHED]`; https://www.refinelabs.com/blog/split-the-funnel `[FETCHED]`; https://www.revsure.ai/blog/mql-is-dead-what-replaces-it-in-2026 `[FETCHED]`

**On the whole genre:**
> "marketing's legacy is of years spent trying to fill the timeline gap with unwieldy slide decks, full of so-called 'vanity metrics'" — the result "often dismissed as meaningless." And: "wildly unrealistic calculations of ABM ROI… erode trust in the value that the activity provides." — Agent3

**The "just stop" position** — the most quotable line in the measurement literature:
> **Brian Kotlyar, Hightouch: "Fighting over attribution is the biggest waste of time in a B2B company. Just don't do it."**
> **Drew Pinta, Ramp:** "You shouldn't really measure these the same way as traditional marketing campaigns… On an MTA basis they're gonna look like they a terrible ROI."

Hightouch's working alternative — **narrative attribution generated per deal**, not a model:
> **Brian Kotlyar:** "We actually run a lot of LLM based manual attribution stuff… actually writes a little deal story for us of what caused what."

**Sourced-vs-influenced as a category.** Jon Miller: "rigid attribution models dividing opportunities sourced by marketing vs. sales are archaic."

**Meetings booked, cold dials, cold emails.** Explicitly rejected as ABM SDR KPIs by Fullfunnel.

**Vendor ROI stats.** Worth flagging as the *marketing* side of the ledger, and treating with suspicion when repeated: "87% of B2B marketers report ABM outperforms other investments on ROI"; "91% see average deal size increases; 25% increase >50%"; "86% report improved win rates"; "70% increase in opportunities created"; "92% of companies say ABM delivers higher ROI than any other marketing approach." Sources: https://insights.strategicabm.com/account-based-marketing-metrics `[FETCHED]`, https://6sense.com/resources/research-reports/ `[FETCHED]`. These circulate without primary methodology and should be treated as vendor claims.

### 3.6 The dark funnel and self-reported attribution

> **Dark Funnel, per 6sense:** "It's a ghostly data-realm packed with buyer intent information that revenue teams historically haven't been able to access."
> **Alice de Courcy, CMO Cognism:** "It's a term that means the places that buyers are engaging and making decisions that no attribution software or tracking can account for."
> **Mark Schaefer:** "Today, customers educate themselves in countless ways and your website may not even be in the mix."
> "Dark Social is a term coined in 2012 by Alexis Madrigal...we are only measuring the tip of the iceberg."

Stats: **1 in 6** website visitors arrive through private messaging apps; around **80% of shortlists are finalized before** a demo request or sales outreach. Buyers use ChatGPT, Claude, Gemini, Copilot to "sense-check ideas, understand unfamiliar concepts, compare approaches, and reduce perceived risk in private, untracked conversations."
https://insights.strategicabm.com/dark-funnel-vs-dark-social-how-to-track-hidden-traffic-in-2026 `[FETCHED]`

Poyar's 2026 conclusion: "most B2B purchase intent lives" in private communities, peer conversations, and AI search before prospects reach company websites — requiring **"how did you hear about us?"** fields to capture LLM-driven discovery. https://www.growthunhinged.com/p/b2b-gtm-playbook-for-2026 `[FETCHED]`

**The Attribution Mirage — Refine Labs' published gap numbers.** https://www.refinelabs.com/blog/attribution-mirage `[FETCHED]`
- Definition: "An attribution mirage is a phenomenon that occurs when a person, organization, or system attributes a success or failure to the wrong cause."
- "Software-based attribution reports that **78%** of conversions were sourced from web searches (direct and organic), whereas customers report web searches only **12%** of the time."
- "Self-reported attribution from customers records **85%** of conversions were sourced from Dark Social (social media, podcast, word of mouth, and community)."
- "…for **98%** of our closed won revenue" the source was Dark Social by self-report.
- Core provocation: **"What if you're not measuring something at all?"**

Their **Hybrid Attribution Framework** study — **12 months, 620 declared-intent conversions, $21.5MM closed-won ARR**; headline **"90% measurement gap"**; **podcasts attributed 53% of revenue ($11.4MM) by self-report vs 0% by software.** https://www.refinelabs.com/article/hybrid-attribution-framework `[FETCHED]`

**The counter-case against self-reported attribution.** This is the part most ABM content omits, and an agent should hold both.

> **"Self-reported attribution is about as useful as a screen door on a submarine if it's taken alone."** — Powered by Search
> "The Recency Bias will likely cause your brain to believe that the place you heard about [a brand] was whichever one of these ads you last remember seeing – even if you've been seeing [their] content for months or even years."
> "It assumes that leads are better at remembering your marketing than they may be in reality."
> "leads were more often than not incorrectly reporting their 'first-touch'" *(citing Dreamdata research)*
> "If you remove content and SEO investments based on your understanding that most leads see an ad on Twitter and then convert (because they tell you directly) then you will find that your acquisition costs rise significantly."
> On vendor bias: "Each platform has an inherent bias towards attributing conversions to whichever product they're selling alongside analytics."
https://www.poweredbysearch.com/blog/self-reported-attribution/ `[FETCHED]`

The marketing-mix-modeling camp's rebuttal (Recast):
> "People often struggle to accurately recall how they initially heard about a business, and their responses may be influenced by recency bias"
> Self-reported data favors "more emotional or memorable channels like TV" over channels that actually drove conversion across multiple touches.
> Relying solely on surveys is **"as damaging as focusing just on software-reported last-touch attribution."**
> Dropdown formats introduce **"order bias"** where "people are more likely to select the first visible option," or give false answers when their channel isn't listed.
https://getrecast.com/hdyhau/ `[FETCHED]`

**Multi-touch attribution's named biases** (HockeyStack): last-touch **"undervalues awareness channels"** (top-of-funnel influence "completely invisible") and **"misrepresents complex buyer journeys"** (the final touch is "a tiny fraction of the actual journey" across 5–11 stakeholders). Per-model primary bias risk: **Linear** — "treats all touches as equally important"; **Time-Decay** — "under-credits early-stage engagement"; **Position-Based** — "under-credits mid-funnel nurturing." And: "Even the most capable attribution model is only as good as its underlying data architecture."
https://www.hockeystack.com/blog-posts/the-complete-guide-to-fixing-attribution-bias-in-marketing `[FETCHED]`

**Practical implementation of self-reported attribution** (Oktopost): add "How did you hear about us?" to forms · add social referral options to demo requests · train sales to ask about content exposure during discovery · add a CRM field. Recommended answer options designed to *catch* dark social: "Recommended by colleague," "Email from colleague," "Slack/Teams message," "Text message," "Phone conversation," "LinkedIn direct message," "WhatsApp." Supporting numbers: average B2B buyer journey **272 days across 88 touchpoints**; **only 52% of senior marketing leaders say they can prove marketing's value**.
> **"Self-reported attribution ('How did you hear about us?') is one of the highest-leverage tactics available, because it surfaces signals that no software-based model can detect."**
https://www.oktopost.com/blog/dark-social-in-b2b-marketing/ `[FETCHED]`

**In-market base rates — note the internal contradiction.** 6sense publishes **"roughly 7-8% of your TAM is close enough to a purchase decision to be worth a rep's time"** on one page and **"roughly 60% of target accounts aren't in-market at any given time"** on another. Both are from the same vendor. Flag this if either is cited. The Ehrenberg-Bass base rate (3–5%) and Clay's "only about 5% of your market is ready to buy" are the more conservative and more widely corroborated figures.

Also from 6sense, and consistent with §1.10: **"A rep working 20 accounts deeply will always outpace a rep working 150 accounts shallowly."** And: by the time sellers engage, **"the job isn't to guide. It's to confirm."**

### 3.7 What practitioners report to leadership

Inflexion 2026: measurement is driven by **buying-group engagement and pipeline impact, supplemented by programme-level metrics and anecdotal evidence.** Many organizations treat ABM as "business as usual" rather than requiring separate governance.

Practitioner-stated priorities (strategicabm 2026 research): **90%** want active engagement with target accounts · **84%** want pipeline growth · **77%** want revenue growth.
> "Boards don't buy theory—they buy outcomes."
https://insights.strategicabm.com/what-makes-a-great-abm-agency-in-2026 `[FETCHED]`

**The reporting discipline that keeps programs alive** (Cosby): anchor every metric to a decision; translate metrics into next steps; emphasise movement over volume; close every report with three questions — what's working, what needs adjustment, what changes next month based on this data.

> "A shorter report that drives even just one or two decisions beats a longer one that drives none, every time."
> A client nearly dismantled their program after three months of "flat" results; asked when their last report actually changed team behavior, "nobody could answer it."
https://scrappyabm.com/blog/stop-spinning-up-new-abm-programs/ `[FETCHED]`

---

## 4. Named Case Studies With Numbers

Ordered roughly by how usable the numbers are. Vendor-published vs independent is flagged on each.

**1. CrossKnowledge — ABM pilot, 130 accounts, 6 months.**
Marketing-sourced enterprise pipeline **30–40% → 60%**. **35 of 130 accounts engaged (26%)**. Team: ABM Lead, SDR/Inside Sales, Content Marketer, later an Expansion Marketer; supported by AEs, SME, RevOps.
> **Magali Finet-Perdu (enterprise sales):** "Over six months, we engaged 35 accounts with multiple meetings and project discussions. We receive more strategic, early off-the-record information and speak directly to top executives."
> **Ken Roden (former head of marketing):** "The most rewarding part was seeing my team take pride in their work. We were business drivers, not just lead generators."
> **Magali:** "Budgets are decided far in advance. A company may make a purchase decision once every three years."
*Consultancy-published (Fullfunnel).* https://fullfunnel.io/abm-pilot-program/ `[FETCHED]`

**2. Charlesgate — real estate services, 2–3 year sales cycles.**
**$3.5M+ ABM-sourced revenue** — company-record quarter. Improved win rate. Signal source: city planning and land filings, not any commercial database.
> **Amy Loesch, Fractional CMO:** "Developers don't announce their projects on LinkedIn—we had to find them through public filings and industry data."
> "Instead of selling our services, we showed how we helped a similar developer increase their leasing speed by 40%."
> "In an industry with long cycles, the key is to be present—not just when they're ready to buy, but long before that."
*Consultancy-published.* https://fullfunnel.io/four-abm-programs/ `[FETCHED]`

**3. TestRail — technical buyers, community-first ABM.**
Target list cut **1000+ → 72 accounts**. **22 enterprise deals created, 2 closed.** Q1: 4 enterprise opportunities (1 closed-won) + 22 Sales-Accepted Leads within 90 days. Single webinar drew **70+ tier-1 target accounts**.
> **João Crisóstomo, Enterprise PMM:** "We found QA teams in places where they actually engage—Slack, Reddit, and industry newsletters."
> "Engineers don't respond to sales pitches, but they will engage with technical content that helps them improve their processes."
> "Engineers respect knowledge, not marketing fluff. We built authority by sharing technical insights, not sales pitches."
> "This was a marketing-led ABM program. We built trust first—sales only stepped in when the time was right."
*Consultancy-published.* https://fullfunnel.io/four-abm-programs/ `[FETCHED]`; https://fullfunnel.substack.com/p/abm-events-case-study-and-playbook `[FETCHED]`

**4. Certn — background screening, US market entry.**
**84 engaged target accounts**, 3 enterprise deals in pipeline, record webinar engagement (**53-minute average view time**).
> **Ellen Kaross, Global Marketing Communications Manager:** "We weren't just selling background checks. We were selling a better candidate experience—something HR teams actually care about."
> "Our best-performing LinkedIn posts weren't about our product. They were about hiring trends and regulatory risks."
> "Webinars only work if they provide real value—not if they're just thinly veiled sales pitches."
> "Salespeople don't need marketing brochures—they need real insights that help them start conversations."
*Consultancy-published.* https://fullfunnel.io/four-abm-programs/ `[FETCHED]`

**5. Cardata — vehicle reimbursement SaaS.**
New pipeline generated; ABM team expanded; two additional cycles approved.
> **Lee Adam, PMM:** "Finance teams don't care about software—they care about saving money. That's how we positioned our message."
> **Divash Basnet, VP Marketing:** "Instead of spamming every HR leader, we focused on companies showing engagement signals—reducing wasted effort."
> "We removed the short-term pressure by guaranteeing commissions. That allowed sales to actually focus on the right accounts."
> **Lee Adam:** "This isn't a one-off experiment. We've already got two more ABM cycles planned, with more resources allocated. We're all in on this."
*Consultancy-published.* https://fullfunnel.io/four-abm-programs/ `[FETCHED]`
*(Programs 2–5 combined: **$7M in sales-qualified pipeline**.)*

**6. Postindustria — 11 accounts.**
**100+ target buyers engaged → 9 qualified opportunities (81% of accounts) → 3 closed high-six-figure deals.**
*Consultancy-published.* https://fullfunnel.io/linkedin-marketing/ `[FETCHED]`

**7. Fullfunnel.io's own program — one quarter.**
**46 accounts engaged · 43% engagement rate · 8.7% account-to-pipeline ratio · 3 sales opportunities · 1 closed-won** ("the biggest project ever"). Three people. Stack **under $1,000/month**.
Separately: **76% response from 21 accounts; 46% agreed to interviews**; "2 clients and 6 sales opportunities in 3 months." ICP: Belgium B2B scale-ups, $5M–$10M ARR, ACV >$50k.
*Self-published.* https://fullfunnel.substack.com/p/our-abm-program-breakdown-case-study `[FETCHED]`; https://fullfunnel.substack.com/p/abm-case-studies `[FETCHED]`

**8. Unnamed video streaming company.**
**$375k pipeline in 3 months**, 5 new sales opportunities + 1 re-engaged. Team = head of product marketing + 1 AE. ACV $80k, 6-month sales cycle.
*Consultancy-published.* https://fullfunnel.substack.com/p/abm-case-studies `[FETCHED]`

**9. Unnamed — the list-narrowing case.**
**Initial list 200 accounts narrowed to 13**; **54% of accounts (7 of 13)** generated opportunities. Opportunities appeared **6–9 months post-outreach**.
*Consultancy-published.* https://fullfunnel.substack.com/p/abm-case-studies `[FETCHED]`

**10. Electric Era — webinar-based pipeline engine.**
**$2M net-new pipeline · $10M accelerated opportunities.** Enterprise engagement from Target and Walmart.
> **Marina Resto Black, VP of Marketing:** "We now have a repeatable program that's a staple of our revenue generation."
*Agency-published (Scrappy ABM).* https://scrappyabm.com/blog/abm-campaign-examples/ `[FETCHED]`

**11. ArborXR — existing-demand activation.**
**20+ target accounts entered pipeline · 6 deals closed in first 3 months · 28 accounts closed within 12 months · 89% higher average contract value.**
*Agency-published.* https://scrappyabm.com/blog/abm-campaign-examples/ `[FETCHED]`

**12. Andela — event-based field motion.**
**74 non-Andela attendees at the featured event — 35 customers, 39 prospects.**
*Agency-published.* https://scrappyabm.com/blog/abm-campaign-examples/ `[FETCHED]`

**13. Forward Studios / Darn Good Distributors Podcast — account-based podcast.**
> **Kyler Nixon:** "After 3 months of outbound with no success, we launched our account-based podcast through Scrappy ABM and have generated **$60k ARR and $90k in pipeline across less than 10 podcast guests**."
Also **29 guests booked in 4 weeks**.
*Agency-published, named client attribution.* https://scrappyabm.com/blog/what-is-an-account-based-podcast/ `[FETCHED]`

**14. Parsable.**
> **Steph Byce:** "Over $3M in Qualified Pipeline in Just 6 Months"
*Agency-published testimonial.* https://scrappyabm.com/ `[FETCHED]`

**15. Guru Events.**
> **Jay Schwedelson:** "$1.5M in Revenue in Year 1 on our Podcast"
*Agency-published testimonial.* https://scrappyabm.com/ `[FETCHED]`

**16. Coram AI — the book play.**
**4,000 downloads · 270 target accounts engaged · $10.8M revenue attributed · 65× return.** Mechanics: book designed around what authors and readers care about, instant digital + print, 14 partner authors for distribution, launch event with signings and videos.
*Practitioner-reported at Exit Five Live (Aditya Vempaty).* https://exitfive.com/articles/8-marketers-share-top-plays-of-2026-so-far/ `[FETCHED]`

**17. Exiger — product-as-content.**
**4–10× engagement vs other content types · millions in qualified pipeline · CEO testified before Congress.**
*Practitioner-reported (Austin Fuller), Exit Five Live.* Same URL `[FETCHED]`

**18. Verbatim (agency) — LinkedIn creator program.**
**$10K/month pilot, 4 creators, 3 posts each monthly → 500K–1M impressions/month at 40% lower cost per conversion than paid social; top-3 channel for trial signups.**
*Practitioner-reported (Brianna Doe).* Same URL `[FETCHED]`

**19. Customer.io — AI-search content optimization.**
One page reached **100th percentile citations (11,000 in 5 months)**; active users **+104%**; visibility **+30%**; now the #1 recommended brand for alternatives.
*Practitioner-reported (Molly Evola).* Same URL `[FETCHED]`

**20. Acxiom (via strategicabm).**
**86 accounts engaged · 15+ meetings booked · 6 sales opportunities.**
*Agency-published.* https://insights.strategicabm.com/what-makes-a-great-abm-agency-in-2026 `[FETCHED]`

**21. GlobalSign — one-to-many ABM, financial services.**
~**100 select accounts** in Financial Services around Digital Signatures Solutions. Reported outcomes are reputation/relationship-stage (early program): amplified brand awareness, engagement from leading finance brands, sustained social selling traction.
> **Ofer Yatziv-Green, Marketing Manager:** "We attracted big accounts, bigger than we ever had before... Sales team sees value."
> "It makes sense... It is data-based and logical."
*Agency-published.* https://insights.strategicabm.com/globalsigns-abm-growth-journey `[FETCHED]`

**22. BenchPrep.**
Narrowed to **62 strategic accounts** on four criteria (revenue potential, relationship level, awareness, product-need evidence). Pilot team of three.
*Consultancy-published.* https://fullfunnel.substack.com/p/who-owns-abm `[FETCHED]`

**23. Dapper.**
Grew **7 → 65 people**, **80% inbound from LinkedIn**; 7 infographics → **285k impressions in one month**.
*Consultancy-published.* https://fullfunnel.substack.com/p/the-2026-b2b-content-playbook `[FETCHED]`

**24. Wings4U.**
6-month program → became a recognized brand in customer advocacy, landed **5 US deals**.
*Consultancy-published.* https://fullfunnel.io/linkedin-marketing/ `[FETCHED]`

**25. Workflows.io (Dan Rosenthal + Fivos Aresti).**
Bootstrapped to **$2.5M ARR in 10 months** running the AI-native ABM engine described in §2.3.
*Self-reported via Growth Unhinged.* https://www.growthunhinged.com/p/how-to-build-a-modern-abm-engine `[FETCHED]`

**26. Scrappy ABM aggregate (house numbers).**
**$300M+ pipeline sourced · $100M+ sourced revenue · 200+ playbooks launched · 1,000+ marketers trained · 35+ teams graduated.** Mason Cosby personally: **"$25M+ in revenue, 16x ROI."**
*Self-published.* https://scrappyabm.com/ `[FETCHED]`

### 4.0a Agency-published, deep detail (strategicabm — the most detailed public programs)

**27. AVEVA → GSK | 1:1 ABM on a single enterprise account.**
**£7m / $9m active pipeline from ONE account · 2,000 personalized microsite visits · 46 new stakeholder relationships · GSK expanded from 1 → 3 AVEVA platforms.** Phased awareness → influence → commitment, culminating in a face-to-face executive meeting. **Won Forrester B2B Program of the Year 2025.**
https://insights.strategicabm.com/abm-case-study-elevating-relationships-through-abm `[FETCHED]`

**28. BlueBotics | Two-tier: 400-account 1:many + 12-account 1:few — the best-documented tiering case.**
1:many (400 accounts): 21,000 ad impressions, ~160 new relationships, **6 clients won.** 1:few (12 accounts): **100% account engagement**, 15 sales conversations, **2 clients won.** Total **£4m+ / $5m+ opportunities; £750k+ / $1m+ closed revenue.** Logos won: Michelin, Toyota Forklift, ABB, Creform, Yaskawa Electric. **Run by a one-person marketing team.**
https://insights.strategicabm.com/the-transforming-power-of-abm `[FETCHED]`

**29. Acxiom | Blended 1:many + 1:few, automotive vertical.** **£1.5m pipeline in 120 days**; 6–8 week campaign execution inside a 3–4 month program. Named accounts touched: AA, McLaren, Nissan, PSA Groupe.
> **Jo Robson, Marketing Director International, Acxiom:** "Insights and research form the foundation of ABM. Without them, you're in the dark about market dynamics and challenges."
https://insights.strategicabm.com/how-acxiom-created-a-1.5m-pipeline-in-120-days `[FETCHED]`

**30. GoodShape | 1:many across 6 sectors, 337 accounts.** **80%+ engagement across 337 target accounts · 500,000 impressions · 2,000+ campaign views · £1m+ pipeline.** Relationships built at DWP, Transport for London, Legal & General, EY, PwC, Tesco, Burberry, Capgemini. Multi-stakeholder: CHRO, CEO, CFO, COO, wellbeing leads.
> **Terry Osborne, Director of Marketing:** "Our content was used to educate the C-Suite that wellbeing is not just a tick-box exercise."
https://insights.strategicabm.com/how-goodshape-shaped-up-workplace-wellbeing `[FETCHED]`

**31. Kineo | 1:many across Financial Services / Pharma / Tech.** 74 MQAs · 66 new relationships · 7 meetings booked · 4 accounts in active sales nurture · **$300,000 confirmed revenue (one deal).** LinkedIn: 476,030 impressions, 2,732 clicks, 210,724 video views.
> **Alex Treasure, Global Marketing Manager:** "ABM wasn't a quick win, so you need to work collaboratively across teams."
https://insights.strategicabm.com/forging-new-relationships-kineos-abm-quest `[FETCHED]`

**32. Rakuten Advertising | Workshop-led ABM across 5 territories.** **66% workshop-to-pipeline conversion rate across 5 territories.** https://www.strategicabm.com/abm-services `[FETCHED, aggregate only]`

### 4.0b More Fullfunnel programs

**33. Postindustria (expanded) | LinkedIn "allbound" ABM — 200 accounts narrowed to 15.** 15 accounts × 7–10 buying-committee members = 100 LinkedIn profiles targeted; ~30-person internal engagement pod. **9 enterprise qualified opportunities · 3 won contracts · 10× increase in ACV · $5M pipeline.** Budget **<$10,000 over 6 months** → est. **50,000%+ ROI.**
https://fullfunnel.io/demand-generation-strategy/ `[FETCHED]`

**34. Iridium Mobile | Virtual summit as the ABM engine — best "event-as-ABM" case.** 2,320 sign-ups · **900 new accounts (39% of attendees)** · **34 sales-qualified opportunities · 5 new customers.** **$3,000 budget, 3-person team**, 50 speaker companies, 5-day event / 35 hours live-stream. 9–12 month sales cycle; customer LTV >$100k.
> "People buy from people they know, like, and trust. That's why warming up your accounts is crucial for ABM success."
https://fullfunnel.io/abm-tactics/ `[FETCHED]`

**35. Unnamed custom software dev firm | 3-tier ABM with direct mail — the cleanest tier-by-tier numbers.** Tier 3 (41 accounts): 7-step personalized cold email → 3 opportunities. Tier 2 (30 accounts): role-personalized proposals + physical gifts + phone follow-up + LinkedIn/Twitter → **37% reply rate (12 of 30), 20% success rate.** **$300,000 revenue on a $5,000 budget = 6,000% ROI**, 4 months total (2 strategy + 2 execution). IP-based banner ads ($150) discontinued as ineffective.
https://fullfunnel.io/abm-campaign/ `[FETCHED]`

### 4.0c Intent-triggered ABM (6sense-published — vendor, but the densest numbers set found)

**36. Socure | "Treasure Ops" — replaced MQLs with Engaged Qualified Accounts.** **$52M sourced pipeline year one → $98M in H1 2025** · **153 opportunities via EQAs in year one** · **3.5× higher reply rates** on signal-stacked sequences · **60% faster time-to-engage** on surging accounts · **2.1× meetings booked** · $315M ARR by end 2025.
> **Amber Romo, Head of Market Development:** **"Don't roll it out—earn it in. Transformation doesn't happen because you flip a switch. It happens because people feel the impact."** · **"Start where you are. We didn't wait for the perfect team structure. Our intern kicked this off."**
https://6sense.com/customer-stories/how-socures-treasure-ops-unlocked-transformational-pipeline-results/ `[FETCHED]`

**37. Asana | 90 licensed users globally — best win-rate delta in the set.** 2,500+ net-new accounts added · **2.5× larger deal size** · **70% win rate vs 39%** · 32-point lift in ARR win rate · 25% faster close.

**38. Check Point Software | 84 SDRs, 100% adoption.** **$150.7M pipeline from 6QA opportunities** · **120% opportunity-value lift · 63% deal-size increase** · 60% YoY SDR pipeline growth.

**39. RepTrak | MQL → intent-driven paid media — best sales-cycle + ACV case.** **96% decrease in ad costs · 46% increase in ad engagement · sales cycle 112 → 90 days · 64% increase in average contract value · 3× LinkedIn pipeline · 93% of opportunities from strong-fit accounts.** Counter-example inside the same case: the legacy campaign delivered **+245% leads but −30% pipeline**, with 80% of leads stuck in awareness.
> **Ali Jawin, former VP Global Marketing:** **"We tried to move the market to us instead of meeting the market where it is, and that never works."**
https://6sense.com/customer-stories/reptrak-increases-contract-value-and-cuts-average-sales-cycle-with-6sense/ `[FETCHED]`

**40. Mission Cloud (a CDW company) | Timing-based migration campaign — best "timing beats intent" case.** Renewal dates + technographics + keyword intent → **524 MQAs · $17M new-business pipeline · $8.2M launched ARR within six months.**
> From the case: **"high intent didn't reliably indicate readiness to buy — because many accounts were locked into long legacy contracts."**
https://6sense.com/customer-stories/how-mission-cloud-a-cdw-company-turned-intent-signals-into-pipeline-wins-with-a-timing-based-migration-campaign/ `[FETCHED]`

**41. Hexagon (ESPRIT division) | Stage-specific ABM workflows, email-first.** **459% increase in known account engagement (175 → 978 accounts)** in **3 months** · 1,379 accounts surfaced with active intent (previously zero) · **62% reduction in disengaged accounts** · 1,600+ accounts out of dormancy.
> **Sarah Kumlin, Global Director of Marketing Operations:** "We believe the key to success isn't more campaigns, but smarter campaigns."

**42. Portnox | Three-workflow full-funnel orchestration by buying stage.** **423% increase in engaged accounts · 55% more new opportunities · 180% more closed/won · 70% higher ASP** from named accounts.

**43. Swimlane | 7-person team, segment-specific intent.** **90% higher engagement vs non-intent accounts · $3.35M pipeline · 190% 6QA increase · 27% ARR increase despite 50% fewer BDRs · 31% shorter deal cycles.**

**44. SPINS | 8-person team, six campaigns/month.** **Sales cycle 69 → 33 days** · 200% campaign productivity · 13× reach.

**45. Syniti.** 5× campaigns · 14× engaged accounts · 5× 6QAs · **~69% sales-cycle reduction · 229% increase in net-new opportunities.**

**46. Rithum | 90-day relaunch of a dormant ABM instance.** **58% of Q2 opportunities from 6QA accounts vs 37% non-6QA · 37% higher average opportunity value · 22% larger won deals** · 3× sales adoption.

**47. Service Express | 6sense hardwired into SDR comp + coaching.** Purchase-stage opportunities **3× higher deal sizes** · **65% of rolling 12-month pipeline** from decision/purchase stage · **sales velocity 12 → 9 months.**

**48. Experian | Customized BDR dashboards.** Attainment **60% → 100% in 6 months** · **75% YoY opportunity-volume lift · 106% ACV increase.**

**49. Blue Yonder | 60 Intelligent Workflows unified with LinkedIn targeting.** **12× ROI** · 170+ new logos engaged · consolidated 200 workflows → 60.

**50. FireMon | Scaled ABM from 10 → 100+ accounts.** 80% increase in accounts engaged · 3× faster campaign launches · **54% faster close time** · competitive-displacement campaign live in **10 days.**

**51. Marathon Health** `[SNIPPET]` — **$66M net-new pipeline; 211% growth in in-market buying.**

All 6sense cases above `[FETCHED]` via https://6sense.com/blog/meet-and-learn-from-the-2025-breakthrough-award-finalists/ and https://6sense.com/blog/breakthrough-2025-awards/ unless a dedicated URL is given. *Vendor-published.*

### 4.0d Demandbase-published

**52. SAP Concur | Intent-prioritized cohorts + personalized display — the cleanest "advertise consistently for 3–4 months" causal story.** **52% increase in closed-won revenue · 57% improvement in deal size · 59% increase in pipeline** · 60% lift in website visits from advertised accounts · **~500 dormant accounts re-engaged.** Timeframe explicitly stated: **3–4 months of consistent advertising.**
https://www.demandbase.com/resources/case-study/sap-concur-elevates-every-metric/ `[FETCHED]`

**53. CyberArk | Engagement × propensity "top quadrant" scoring — best account-concentration stat found.** **4× higher close rates** on high-propensity accounts. **3% of targeted accounts generated over one-third of total pipeline.**
> **Renske Galema, AVP Northern Europe:** "Demandbase has made it so clear which accounts to prioritize and when to engage—and that has had a direct impact on our win rates."
https://www.demandbase.com/resources/case-study/cyberark-abx-success/ `[FETCHED]`

**54. PageUp | 6-week implementation.** **30% account-list lift · 15 net-new opportunities influenced · 11%+ of yearly pipeline · 5 six-figure closed-won deals within 6 months · 161% QoQ increase in sales/SDR engagement.**

**55. Denodo | Lead-based → ABX transformation.** **2.42× ROI · 80% increase in funnel velocity · up to 60% improvement in journey-stage conversion.**
**56. GoCardless.** **11× pipeline ROI.** **57. Unanet.** 66% reduction in ad campaigns (12 → 4); 50% less campaign-management time in one quarter. **58. Zoom** `[SNIPPET]` — sales converted **36% more engaged accounts**; 300%+ MRR boost. **59. Tricentis** `[SNIPPET]` — 31% YoY increase in BDR pipeline.

### 4.0e Gifting and direct mail

**60. Verkada | Gifting as the *primary cold outbound channel* in EMEA — the most interesting motion in the set.** Branded building-block sets (miniature monitoring stations) as the cold-open gift. **40% ROI increase from switching gifts · 10×+ growth in annual sends · 99% redemption rate · 95% delivery accuracy (up from 60–70%) · +2–3% warm conversion lift · +4–5% cold conversion lift.** Seven-figure annual gifting budget. **Gifting displaced email as the #1 cold outbound channel in EMEA.**
> **Bayo Bankole, Senior Growth Manager:** "Email was effective, but it was a one-trick pony. Once you email somebody, you can't do anything other than email them some more." · **"Gifting has become our primary cold outbound program. It's displaced email as the primary motion."**
https://www.reachdesk.com/customers/verkada `[FETCHED]`

**61. Invoca | Holiday direct mail with a strict 2-day SDR call-back rule — best "the follow-up is the play" case.** **50% redemption-to-meeting rate · 80% of those meetings converted to opportunities · 7× ROI · +23% YoY influenced opportunities.** Marketing-branded email to non-pipeline contacts; rep-personalized sends for pipeline accounts.
> **Suzzette Giron, ABM Sr. Manager:** "We're not selling to a company. We're selling to a human being. And we're not selling to robots … yet."
https://www.sendoso.com/success-stories/invoca `[FETCHED]`

**62. Outreach | 1:few Tier-A gifting + 1:many seasonal + 1:1 international.** **$8M influenced pipeline · ~$1M influenced ARR · 2× ROI on marketing spend.** Best play: Sales Lunch & Learn virtual event + lunch eGift = **10.34× new-logo ROI.**

**63. Blend | Closed-lost win-back via branded Oreo cookies.** **62% conversion rate from cold leads to opportunities · 40× ROI on pipeline value.** #1 of all mailers ever sent.
> **Matthew Dilworth, Demand Generation:** "If you're not doing direct mail, then you're not doing demand generation… If you're doing high-touch account-based marketing, direct mail has to be a part of it."

**64. Cornerstone OnDemand.** **$4,000 influenced pipeline per $1 spent · $7M total influenced pipeline · 30% lead-to-opportunity conversion.**
> **Sara Schonfeld, Senior Marketing Strategist:** **"I think the most important part of our strategy is the real partnership between sales and marketing. It's not about a truffle, no matter how delicious."**

**65. LiveRamp | Direct mail layered onto cold calls/emails.** **33% increase in meetings booked from Sendoso-influenced cold calls · 8–12% direct-mail response rate.**
> **Ben Coffee, Head of Marketing Operations:** "Conversion over 10% for a cold list [is] phenomenal, let alone 33%."

**66. Salesloft | Stage-gated gifting** (coffee at SDR stage, lunch pre/post demo, personal 1:1 gift late stage). **60× ROI program-wide; 203× potential ROI**; one AE attributed **$250K closed-won = 100× ROI.**
**67. Employment Hero.** **$1.6M revenue influenced globally in year one · 200× ROI**; 98% redemption on partnership gifting; **~2 SAOs per rep per month** (APAC outbound).
> **Maisie Goss, VP of Marketing UK:** "Once reps saw the impact on sit rates and engagement, adoption became self-reinforcing. The right gift, at the right funnel stage, with the right approval process. That is what drives the result."

**68. Samsara.** **250%+ QoQ increase in pipeline sourced** from door-opener direct mail. **69. Terminus (using Sendoso).** $5.5M influenced pipeline; $659K influenced revenue. **70. HighRadius.** **366% increase in conference meeting bookings**; 50+ meetings unlocked in year one; 100% SDR adoption. **71. InterVision.** $377 influenced closed-won revenue per $1 spent. **72. Lacework.** **25% of pipeline influenced by gifting**; one deal closed in **38 days** off a single webinar. **73. Planet DDS.** 7× pipeline return; 20 opportunities in first six months; 93% claim rate. **74. Chili Piper.** 74% claim rate; **4× monthly send growth (43 → 182)**; 241% growth 2024. **75. Iterable** `[SNIPPET]` — **350 opportunities over 4 years; 91 closed-won deals influenced in 2024.**

**76. Snapdocs.** Physical guidebooks to C-suite during a virtual book launch → **84% response rate.** **77. Lessonly.** Coffee eGift 1 day before a CEO virtual coffee → **60% attendance rate.** **78. PubNub.** Charity donations instead of gifts → **+32% webinar registrations; +14% response rates.** **79. Unnamed cybersecurity co.** 1:1 food-delivery eGifts across the lifecycle → **53 opportunities, $1.2M ARR.**

⚠️ **80. Unnamed enterprise software co.** 345 holiday bundles sent Dec 2019 → "$100M pipeline, $30M recognized revenue." **Treat with suspicion** — 345 bundles → $100M is an outlier ratio and the account is anonymized.

All gifting cases *vendor-published* (Sendoso / Reachdesk), `[FETCHED]` from https://www.sendoso.com/success-stories and https://www.reachdesk.com/customers.

### 4.0f Job-change and champion plays (UserGems-published)

**81. UserTesting | Job-change trigger → direct-mail congratulation → SDR sequence — the canonical job-change case.** **~1,300 job-changer leads in the first week · $8M+ pipeline · $1M+ closed-won in under one year · 18× ROI.**
> **Steve Jones, VP Demand Generation:** **"Your alumni customers are your lowest hanging fruit."**
https://www.usergems.com/customers/usertesting `[FETCHED]`

**82. Mimecast | "New Leadership Hire" play — VPs/CISOs in their first 90 days at in-market accounts + M&A signals.** **$20M+ new pipeline over 2 years · $18M in the first year · $1M+ in 7 months from AI automation.** Described internally as "one of our highest-generating pipeline campaigns to date."

**83. Docebo | "GTM brain" — CRM + first-party + third-party into one scoring engine, AI-drafted emails pre-loaded as Outreach tasks. The most sophisticated 2025-era orchestration case.** **54 enterprise opportunities in the first full quarter · 16% average reply rate (up from 11%) · 70% of pipeline funneled through the signal layer · BDR ramp cut from 4–6 months to pipeline in month one · first deals created in 4–6 working days · 20% reply on English sequences, 43% on German.**
> **Mark Kosoglow, CRO:** "We have enough logic, enough data, and with AI now… you can actually now create all of the stuff that you need so that the reps don't have to make those kind of decisions anymore."
> **Simona Gatta, BDR Leader:** **"I don't want to show BDRs all the work they could do. I just want to show them what they should do."**
https://www.usergems.com/customers/docebo-2025 `[FETCHED]`

**84. Cobalt | "Former Champion" playbook.** 91 opportunities · $1.79M new-business pipeline · **18× ROI** · 8% of new-logo pipeline revenue.
**85. CaptivateIQ | New Hires + Past Champions + Closed-Lost + expansion.** **$1.3M pipeline · 2× reply rates · 15 opportunities in 10 weeks.**
> **Kristen Wisdorf, Sr. Director of BD:** "When implementing AI, BDRs can feel like you're taking away their voice… when prospects started replying saying, 'this message is so good,' the proof was real."
**86. Diligent.** **30× ROI in pipeline · 40–50% response rates · 3× higher return than other outbound tools.**
> **Rob Kiser, Director of Product:** "We saw thousands of job changes from our ideal persona that we had missed out on by tracking it manually."
**87. Others** `[SNIPPET]` — Quickbase (5× leads, 3× pipeline, 2× closed-won) · NetSPI ($610K pipeline in 5 months) · Planful ($1M+ pipeline) · Sendoso (44 expansion opportunities in 40 days) · Accord (50–60% of outbound meetings) · Greenhouse ($1.6M revenue closed) · Metadata (**81% shorter sales cycle, 17% bigger contract sizes**).

### 4.0g Personalized-web and misc.

**88. LaunchDarkly | AI-generated 1:1 microsites for 100+ target enterprise accounts.** **45 sales-accepted leads against a 30 target (150% of goal) · 18 opportunities · 4 closed-won — in under 60 days.** Run by **1 sole ABM practitioner for 2 years** before expanding. Mechanics: AI-generated microsites → LinkedIn ads + inbound sidepop → **sales enablement via a Google Sheet of account links + email templates** → web extension for contact-level alerts → **bi-weekly marketing/sales syncs** → dedicated Salesforce campaign + Looker dashboard → weekly CMO updates.
> **Colleen Pierre (ABM lead):** "It got to the point where I felt like I couldn't maintain this anymore." · "your success is my success" · **"I try to let BDRs and SDRs lead those conversations…Empowering them works best."**
> **Axel Lloyd (BDR):** "I was 'calling at just the right time' as the team had finally decided they needed vendors."
https://www.mutinyhq.com/case-studies/launchdarkly `[FETCHED]`

**89. Unnamed large cloud services provider (manufacturing) | 50 enterprise accounts, personalized content hubs.** 50 researched → **35 engaged (70%)** → 6 accounts generated pipeline. **$1.3M pipeline · 18 actionable opportunities in one month · 190% increase in successful contacts · 10× ROI.**
> **Brian Schmid, Senior Consultant, Inverta:** "The buyer is in control. Research continues to indicate that the buyer will reach out to sales when they're ready (not when your outreach sequence tells them to), and they'll likely buy from the first business they reach out to."
https://www.inverta.com/resources/the-power-of-precision---building-effective-abm-campaigns-a-case-study `[FETCHED]`

**90. Clay's own ABM campaign.** Filtered "hundreds of thousands of accounts down to **300**" on three criteria: account fit "Good"/"Best" · engagement above "Passive"/"No Signal" · **potential contract value over $50K.** Sequence: personalized physical mailer with a **unique QR code** → personalized landing page (logo, tech stack, sales motion tokens) → **LinkedIn + Meta ads during the two-to-three-week window between shipment and delivery** → 4-step SDR follow-up triggered by *delivery confirmation* (soft opener email → call task with a detailed script → LinkedIn → final check-in). Pre-flight validation of email deliverability, phone accuracy, and office-location confidence. Built "almost entirely by one growth lead"; after the first run "the Clay portion of running a subsequent campaign takes about 20 minutes."
https://www.clay.com/blog/how-clay-runs-abm-campaigns `[FETCHED]`

**91. Clay's paid ads.** **$1.3M pipeline from a few thousand ad dollars (~23×)**; LinkedIn CPL **$250 → $25**; Meta match rate 30% → 70%+ → **$10 CPL within 24 hours**; one test yielded **486 leads at $15.93 each** from 1% lookalikes.

**92. Content Allies — "Leaders of B2B" podcast.** **94 C-level executives booked as guests → 43 new sales opportunities (45.7% guest-to-opportunity) → $100,500 attributable revenue in 4 months.**
**93. "Disruptive Innovators" podcast.** **5,300 targeted recipients → 311 engaged → 63 booked calls → 31 new CRM leads.** 5,281 downloads / 53 episodes.
https://contentallies.com/learn/abm-podcast-strategy `[FETCHED]`

**94. Cognism (own GTM) | Three-layer 1:many / 1:few (~50-account cohorts) / 1:1 (5–10 accounts per rep) — the best published scoring rubric.** **$700K pipeline in 2025 YTD.**
*Fit signals (max 10 pts):* ICP segment 3 · key region 2 · SDR-RevOps headcount >20 = 3 · CRM + sales-engagement tool user 2
*Trigger signals (max 9 pts):* high intent 3 · SDR-RevOps hiring 3 · recent revenue-leadership change 3 · closed-lost in 12 months 1
> **Tim Hughes, Demand Generation Lead:** "ABM is just good marketing. It's targeted demand gen."
https://www.cognism.com/gtm-plays/abm-at-scale `[FETCHED]`

**95. Cognism customers** `[SNIPPET]` — an EdTech client: **£5.8M pipeline generated in a single call-out day, 30 meetings booked, 33% with C-suite** · Localz: outreach +180%, opportunity generation +500% · Druva: 22% quarterly pipeline growth.

**96. Vercel | AI agent replacing inbound SDR workflow.** **10 SDRs → 1 QAing the agent, in six weeks**, with lead-to-opportunity conversion held flat and touches-to-convert reduced. Built by **a single GTM engineer at ~25–30% of his time.** https://tomtunguz.com/vercel-ai-sales-agents-jeanne-grosser/ `[FETCHED]`

**97. Malbek | AI-first account-based campaigns.** **145+ campaigns vs 12 previously · 14× BDR capacity · ~22× ROI on conversational email**; speed-to-lead 5+ days → 48 hours max.
**98. F12.net | Solo marketer, intent-triggered segments.** 3× weekly engagement from in-market accounts; campaigns launched in 48 hours; **annual target hit 5 months early.**
**99. 2X (agency) → JAGGAER.** **$13.5M pipeline at 76% lower cost.**
**100. Everbridge.** Renewal ABM across **930+ accounts annually** via a single workflow; windows at **180/90/30 days pre-renewal.**

### 4.0h Awards-circuit programs — name-drops only, no public metrics

⚠️ **Momentum ITSMA does NOT publish results numbers in its award announcements.** The metrics live in paid submission write-ups. Use these as credibility name-drops, never as evidence.

**2025 winners:** Unisys (ABM Program of the Year) · Hope Price / Autodesk (Account-Based Marketer of the Year) · Virtusa (Client-Centric Strategy of the Year, second year running) · Thoughtworks (Customer Insights Program of the Year).
**2024 Diamond winners:** PwC, Kyndryl, IBM, ServiceNow, Checkout.com.
**2024 finalists:** EY, NTT Data, Red Hat, Virtusa, Palo Alto Networks, Fortinet, Infosys, Cisco, Hexagon, VMware by Broadcom. Individual finalists: Rhiannon Blackwell (PwC), Bonnie Sparkman (Fortinet), Priyanka Dasgupta (Kyndryl), Sudhanshu Gupta (Virtusa), Britney Bartlett (Cisco), Lisa Sim (Palo Alto Networks).
**2023 Diamond/Gold:** PwC, Microsoft, TCS, Autodesk, Salesforce, IBM, Google Cloud, ServiceNow.
**B2B Marketing Awards 2024, "Best use of ABM"** `[SNIPPET]` — **Gold:** "Time is of the essence: bringing a data breach to life" — Kyndryl, by HH Global. **Silver:** "How to Win Funds and Influence Pipeline" — NTT Ltd, by Agent3.
https://www.prnewswire.com/apac/news-releases/momentum-itsma-announces-2024-global-marketing-excellence-awards-finalists-celebrating-innovation-and-impact-302246523.html `[FETCHED]`

### 4.1 Benchmark statistics (separate from case studies)

| Statistic | Source | Marker |
|---|---|---|
| Enterprise deals >$100k require **417 touchpoints** to close; analysis of **1.5M contacts from 50+ B2B SaaS companies over 13 months** (Jan 2023–Jan 2024) | HockeyStack industry report, cited by Fullfunnel | `[FETCHED via Fullfunnel]` |
| Typical ABM playbooks contain **7–10 touchpoints** | Fullfunnel | `[FETCHED]` |
| Point of first contact: **61% of journey** (2025), down from 69% (2024) — 6–7 weeks earlier | 6sense 2025 Buyer Experience Report | `[FETCHED]` |
| Buying cycle: **10.1 months** (2025) vs 11.3 (2024) | 6sense | `[FETCHED]` |
| Buying group: **10+ members** | 6sense | `[FETCHED]` |
| Vendors evaluated: **5.1** (2025) vs 4.5 prior | 6sense | `[FETCHED]` |
| Day One shortlist: **3.6–4 vendors**; win rate from Day One list **95%** (up from 85%) | 6sense | `[FETCHED]` |
| First vendor contacted wins **77–81%** of deals | 6sense | `[FETCHED]` |
| **97%** of buyers had prior experience with ≥1 shortlist vendor; **85%** with the winning vendor | 6sense | `[FETCHED]` |
| **79%** of engagements are buyer-initiated (2025) vs 82% prior | 6sense | `[FETCHED]` |
| **94%** of buyers picked a favorite before the Validation Phase | Cunningham / 6sense | `[FETCHED]` |
| **40%** of buying journeys collapse from inability to reach consensus | Cunningham / 6sense | `[FETCHED]` |
| **60%** of target accounts not in-market at any time | Cunningham / 6sense | `[FETCHED]` |
| Fewer than **30%** of eventual buyers fill out forms on the winning vendor's site; vendors see only **10–15%** of research activity | Cunningham / 6sense | `[FETCHED]` |
| **3–5%** of a market is in-market at any time (95-5 rule) | Ehrenberg-Bass, via Harrison/Miller | `[SNIPPET]` |
| ABM = **17–20%** of marketing budget; **14%** of headcount | Inflexion 2026 (n=40) | `[FETCHED]` |
| **60%** lack a single source of truth for data; **47%** say governance needs improvement; **16%** use predictive scoring | Inflexion 2026 | `[FETCHED]` |
| **98.5%** of B2B marketers not satisfied with ABM performance; **49%** frustrated (poll of 300+, elsewhere 450+); alternate wording "only 9% reported great results" | Fullfunnel | `[FETCHED]` |
| **"roughly 78% of ABM programs have failed"** since 2020 | Scrappy ABM — **no source attribution given** | `[FETCHED]` |
| **66%** of ABM programs underperform | ITSMA + TechTarget, cited by Kristina Jaramillo | `[SNIPPET]` |
| **81%** of marketers report higher ROI from ABM than other initiatives; **76%** of *mature* programs | Momentum ITSMA 2024 Global ABM Benchmark | `[SNIPPET — site 504]` |
| **208%** increase in marketing-sourced revenue from ABM-engaged accounts vs inbound-only | Momentum ITSMA Marketing Performance Management Study 2024 | `[SNIPPET — site 504]` |
| Mature ABM programs: **171%** qualified-pipeline lift over matched non-ABM controls within 12 months | Momentum ITSMA | `[SNIPPET — site 504]` |
| Deal velocity **28% faster** with ABM | Gartner, via strategicabm | `[SNIPPET]` |
| Only **17%** report complete sales-marketing alignment; **10%** revenue slippage from misalignment; **40%** of sales time wasted on unproductive prospecting | strategicabm | `[FETCHED]` |
| **84%** of buyers now use AI for vendor discovery, up from 24% last year | Gaetano DiNardi, cited by Fullfunnel | `[FETCHED]` |
| LinkedIn organic reach **down 65% from peak** (Q3 2025); company page visibility **7% → 2%** | Fullfunnel | `[FETCHED]` |
| **1 in 6** website visitors arrive via private messaging apps | strategicabm | `[FETCHED]` |
| AI search ≈ **one-third of all searches** | Growth Unhinged | `[FETCHED]` |
| Cold outbound produces **<1%** discovery-to-closed-won | Fullfunnel | `[FETCHED]` |
| Without a dedicated sales rep: **1.77%** meeting rate, **70.51%** no-response, **0** accounts to pipeline | Fullfunnel | `[FETCHED]` |

### 4.1a Demandbase Labs, *State of ABM 2026* — the largest-N dataset available

Not a survey: observational platform data across **1,452 tenants · 429,634 ad campaigns · 38 million marketing activities · 9.7 million sales interactions.** *(Vendor-published, but the methodology is measurement rather than self-report, which makes it more defensible than most.)*

- Buying groups achieve **up to 2–3× higher win rates** vs lead-centric models
- **58.7% win rate** for companies running four advertising tiers vs **34.3%** with none = **71% relative lift**
- Mature ABM programs: **22.33% median MQA conversion** vs **14.19%** for less-mature
- Companies tracking **3–4 buying groups** achieve **48.5% higher win rates**; sweet spot is **2–3 buying groups per product**
- Typical buying group composition: **13–17 stakeholders**
- **Buying groups reaching 180–190 engagement touches → 94% conversion rate**
- TOFU→MOFU conversion rises **1.78% → 7.55%** as ad engagement rises

**Integrations study** (579 tenants: 231 mature, 301 non-mature): integrated stack (CRM + MAP + predictive + ads) **3.62% MQA conversion** vs **2.37%** limited = **+53%**. **Time in MQA stage: 49.8 days integrated vs 68.9 days limited = 28% faster.**

Also: **ChatGPT referrals to B2B websites rose 303% YoY.**
https://www.demandbase.com/resources/labs/state-of-abm-2026-benchmark-report/ `[FETCHED]` · https://www.demandbase.com/resources/labs/integrations-increase-conversions/ `[FETCHED]` · https://www.demandbase.com/resources/report/b2b-ai-gtm-benchmarks-report/ `[FETCHED]`

### 4.1b Momentum ITSMA / ABM Leadership Alliance benchmark (6th annual, the last freely readable edition)

Sample: **279 ABM heads and practitioners globally.**
- **28% of the 2022 marketing budget dedicated to ABM**
- **71% planned to increase ABM budgets** the following year (a **13.1% YoY increase**); 50% planned to add staff
- **90% report improved engagement** with selected accounts · **84% pipeline growth · 77% revenue growth · 66% improved sales–marketing alignment**
- **72% say ABM delivers higher ROI** than other marketing types (elsewhere reported as 81%, and as 87% by ITSMA)
- **Only 17% of programs are fully "Embedded"** as a foundational GTM component. Maturity stages: **Exploring → Experimenting → Expanding → Embedding.**

> **This last figure is the closest thing to a defensible "% of ABM programs that fail" statistic in the entire corpus: 83% never reach full embedding.** It is far better sourced than the "78% have failed" and "98.5% dissatisfied" house numbers.

Organizations seeing most success are **2× more likely to have mature programs.**
https://www.prnewswire.com/in/news-releases/momentum-itsmas-annual-abm-benchmarking-study-shows-no-signs-of-slow-down-for-account-based-marketing-301760212.html `[FETCHED]` · https://www.demandbase.com/press-release/the-abm-leadership-alliance-and-momentum-itsma-release-sixth-annual-abm-benchmark-report/ `[FETCHED]`

### 4.1c Vendor aggregate claims — label clearly as marketing

`[SNIPPET]` **RollWorks:** customers average **+18% win rates, +16% opportunities created, +20% opportunity-converting form-fills within 6 months of go-live.** · **Terminus (Forrester TEI):** **313% ROI over 3 years, $1.6M NPV.** · **6sense:** **4× win-rate increases, 2× ACV, 20–40% reduction in time to close.** · **Sendoso:** **3× meeting rates, 2× win rates, close 29% faster**; publicly guarantees "5x ROI on pipeline generated in the first year or your money back." · **PFL direct-mail survey:** **83% report good/very good ROI when direct mail is fully integrated into a multichannel mix vs 51% without**; **63% response-rate increase** when digital + direct mail are combined.

### 4.1d ⚠️ Low-confidence — do not cite without verification

`https://www.thestarrconspiracy.com/insights/benchmarks/account-based-marketing-benchmarks-2025` returns a very tidy set: 70% ABM adoption (up from 49% in 2020); 23% mature; **18-month median time to mature performance**; 91% larger average deal size; 36% higher win rate; median closed-won ACV **$148,000 ABM vs $76,000 non-ABM**; 63% of named accounts engaged within 6 months; **4.2 stakeholders per ABM account vs 1.6**; 30% faster pipeline velocity; median annual ABM tech spend $350,000; **cost per SQO $4,800 mature-ABM vs $7,200 non-ABM**; 21.3% MQA→SQO within 90 days. It attributes these to "ITSMA, Forrester, Demandbase, Momentum ITSMA, Demand Metric (2023–2024)" **but gives no per-figure citation, and the precision pattern is characteristic of synthesized content.** `[FETCHED, treated as unverified]`

**Provenance warning to carry into the agent's reasoning.** The headline failure statistics are soft. Fullfunnel's "98.5% dissatisfied" appears with a 300+ sample in one place and 450+ in another and coexists with a "9% report great results" variant — different question wordings from one survey family. Scrappy ABM's "78% have failed" carries no attribution on their own page. The Inflexion 2026 study is **n=40 companies**. The figures with genuine research weight are the 6sense Buyer Experience Report numbers, the HockeyStack touchpoint study, and the Ehrenberg-Bass in-market base rate.

---

## 5. Failure Modes — Why Most ABM Programs Fail

### 5.1 The two canonical failure lists

**Fullfunnel's "11 Guaranteed Ways to KILL an ABM Program"** — verbatim:

1. **Run a program to 1000s of accounts.** "How many of these 1000s accounts are vendor aware? How many demonstrate buying signals?" → **"It's not ABM, it's spray and pray."**
2. **Buying an expensive ABM stack for the pilot.** **"Software ≠ ABM. No expensive stack will help to fix a broken playbook."**
3. **Targeting a wish list.** "if these companies are not in market and don't prioritize the challenge your product solves, you program will fail."
4. **Lack of sales buy-in.** "ABM success heavily depends on coordinated actions of marketing and sales. If there is no buy-in and support from sales, you're likely to do 'air cover' that won't convert into revenue."
5. **Lack of account qualification criteria.** "Not all accounts that fit your firmographics are a good fit. You need to define patterns between lost deals."
6. **Trying to generate opportunities with cold accounts.** "Accounts that are not aware of you are very likely to ignore you. Instead of targeting cold accounts, identify accounts that are already 'aware' of you and demonstrate product-need / buying signals."
7. **Lack of account research.**
8. **Targeting decision-makers only.** "Your message is likely to be bulk deleted and call blocked by a gatekeeper."
9. **Lack of human interactions with the buying committee.** **"Programmatic display ads and automated outbound is not a warm-up and activation."**
10. **Lack of leading indicators.** "ABM is not a silver bullet that can drastically decrease sales cycle. Make sure you have leading indicators to track program performance to avoid killing program too early that shows traction but doesn't generate revenue."
11. **Focusing on new pipeline for a pilot.** "Generate new logos without proven playbooks is hard. To create a proof of concept you'll have higher chances for success if you run pipeline acceleration and expansion programs with accounts that are already aware of you."

> **"ABM ≠ lead generation. Don't be fooled that you can buy an ABM platform, prospect thousands of accounts with programmatic ads and automated outbound cadence."**
> **"It requires a lot of manual work. But this is the only way to generate enterprise, 6-7 figure deals."**

https://fullfunnel.substack.com/p/killing-abm `[FETCHED]`

**Scrappy ABM's 9 mistakes** — verbatim headers:
1. "Trying ABM When Your Business Isn't Built for It"
2. "Starting With Tactics Instead of Targeting"
3. "Treating ABM Like a One-Off Campaign"
4. "Only Engaging One Person in the Account"
5. "Personalizing Without Permission"
6. "Running ABM in Marketing Alone"
7. "Not Having a Dedicated Owner"
8. "Measuring the Wrong Things"
9. "Overcomplicating ABM With Too Much Tech"

> "ABM isn't automatically a successful marketing tactic. It's a specific go-to-market motion designed for complex B2B sales."
https://scrappyabm.com/blog/abm-mistakes-to-avoid/ `[FETCHED]`

### 5.2 The "Core 4" structural causes

Cosby's diagnosis is that the failure is almost always *pre-launch*:

> "The problem is almost always something that was off before the first email went out or the first ad went live."

**1. The business isn't built for ABM.** ABM is "an amplifier" requiring: B2B model, sales-led motion, longer cycles, higher ACVs, clear PMF, sufficient customer data. Without it, "targeting turns into opinions and whoever shouted loudest in the last meeting."
> "If the answer to 'who's your ideal customer?' is 'honestly, we could sell to pretty much anyone,' ABM isn't the right move yet."

**2. Sales and marketing misalignment.** "Marketing says 'MQL.' Sales hears 'demo booked.'" → "dashboards light up while the sales calendar stays empty."
> "True alignment isn't a kickoff meeting and shared Slack channel."

**3. No dedicated ownership.** **"ABM dies slowly when everyone owns it. Which really means no one owns it."**
> "A well-run ABM campaign requires eight core roles to function." — and those roles get assigned to already-stretched teams with no dedicated capacity.

**4. Measurement complexity.** "Everything looks fine on the surface, but nobody can tell if the right accounts are moving." Root cause: "CRMs configured for contacts/deals rather than account-level tracking."

https://scrappyabm.com/blog/why-abm-programs-fail/ `[FETCHED]`; https://scrappyabm.com/blog/abm-falling-flat/ `[FETCHED]`

### 5.3 The six root causes of the category-level failure

Fullfunnel's section headers, verbatim:
1. "ABM IS OFTEN MISINTERPRETED AS A LEAD GEN IN A NEW WRAPPING"
2. "TECHNOLOGY-FIRST + BIG BUDGETS"
3. "GENERIC CONTENT FROM ABM VENDORS AND AGENCIES"
4. "MOST B2B COMPANIES FAIL OR ARE DISSATISFIED WITH ABM RESULTS"
5. "OBSOLETE ABM THEORY"
6. "ABM IS SILOED FROM AWARENESS AND DEMAND GENERATION PROGRAMS"

The lead-gen-in-wrapping loop they describe: upload account wish lists to LinkedIn or an ABM platform → run programmatic display → track engagement → set up outreach cadences → repeat. Verdict: **"No surprise these programs fail."**

On consultants: ABM consultants "mystify it and positioning themselves as 'people with the secret sauce'."

On the tier model being obsolete: they name the traditional Tier 3/2/1 segmentation and reject it — **"Modern reality is far from the ABM theory"** — on three grounds: insufficient resources for 1:1 outside large enterprises; poor marketing–sales alignment; static lists that should be dynamic based on engagement and intent.

On the ABM-vs-demand-gen framing: **"You don't compare tires to motors as you need both to drive a vehicle."**

The failure response loop (2025 reality check): teams "double down on volume: More accounts in the target list. More AI-generated content. More automated touchpoints. More ad spend."
> "It's not different from the lead generation playbook companies have been running for years"
> "The success of ABM lies not in your stack or budget, but in making necessary changes"
https://fullfunnel.substack.com/p/killing-abm `[FETCHED]`; https://fullfunnel.substack.com/p/2025-abm-reality-check `[FETCHED]`

### 5.3a "That's not ABM, that's targeted demand gen" — the field's consensus insult

This exact phrase recurs independently across Snowflake, Ramp, Hightouch, and Fullfunnel. It is the single most reliable diagnostic in the corpus.

> **Casey Patterson, Snowflake:** "One person cannot know two hundred accounts intimately. **That's not ABM anymore that's kind of targeted demand gen.**"
> **Drew Pinta, Ramp:** "We're stopping paid social ads for, like, ABM brand awareness… when you're doing ABM very top of funnel like this, **it can quickly just morph into, like, targeted demand gen**."
> **Andrei Zinkevich:** "If your list includes hundreds or thousands of accounts, you can't do real ABM." … **"It's just cold outbound with display ads."**
> **Brian Kotlyar, Hightouch:** "One of my stops is you don't do this for people you don't know. Everyone just wants, like, magically conjure up pipeline, but this won't work if they're not somewhat engaged."

https://exitfive.com/podcast/abm-what-ramp-snowflake-and-hightouch-are-doing-in-2026/ `[FETCHED]`; https://revopsfm.substack.com/p/episode-55-why-abm-doesnt-work-and `[FETCHED]`

**And on qualifying accounts *out*:**
> **Drew Pinta, Ramp:** "This account has a three-year contract with a competitor. **Take them off the list and put them back in three years.**"
> **Inverta:** "Within your total addressable market, there are potential customers that you don't want to sell to."
> **DemandScience** lists as warning signs of structural failure: **"No one can articulate why a specific account is on the tier-one list"** and **"The account list is growing rather than being refined."**

### 5.3b The category critique — "ABM was a software marketing campaign"

The sharpest verbatim material in the corpus, and it comes from outside the ABM industry.

> **Connor Skelly:** "ABM has been co-opted by sales leaders and uninformed CMOs. They've turned a legitimate program b2b marketers can implement into **'let's have marketing do outbound sales.'**"
> "Let's have marketing be responsible for researching, identifying, contacting, and nurturing cold prospects that fit specific criteria." … **"That is literally the job description of a sales development rep."**
>
> **Gaetano DiNardi**, quoted in the same piece: **"ABM is a code for marketers doing sales + a lot of ads. The concept of narrowly targeting a focused set of accounts has been around forever, but vendors needed a clever way to brand their software."** … "They influenced the industry to buy their expensive tools — and the official category of ABM was born to fuel this purpose."

https://connorskelly.substack.com/p/account-based-marketing `[FETCHED]`

### 5.3c Inverta's "Who Killed ABM" — the practitioner mea culpa

A multi-part post-mortem series written as a murder mystery, and the most honest self-criticism in the corpus. Named author: **Kathy Macchi**, Inverta.

> **"If we're being really honest with ourselves, when it came to ABM, marketing undersold, underdelivered, and didn't truly understand what was involved."**
>
> "we slapped the veneer of ABM on our programs while still running the demand waterfall"
> "we bought the idea that software _equals_ ABM, hoarded too many tools, and let them languish in disuse"
> "we believed the comforting lie that ABM would be easy and didn't invest in meaningful change management"
> "we overpromised on what ABM could do and didn't own up to our mistakes when it failed to deliver"
> "we resisted changing our sales processes (or failed to meaningfully empathize and collaborate with sales)"
> "we made the B2B buying journey too hard. Instead of having the basic dignity to empathify with our customers—really understanding what they needed"
> "we've created target account lists with too-broad parameters"
> "we failed to meaningfully map our buyer's journey"

On the ICP failure: **"'all companies over 5000 employees.' Ms. List, this isn't an ICP, it's your total addressable market!"** And the stat behind it: **"42 percent of marketers did not talk to customers when building out their customer profiles."** Also: "54 percent of companies did not recognize customer behavior in their marketing planning efforts."

On sales resistance: "sales was particularly unwilling to let go of their entrenched processes (especially when it meant putting their commission checks on the line)." … **"We always say, compensation plans drive behavior."**

On the technology trap: "The technology was driving the strategy—and it was. Marketers planned campaigns based on the constraints of their software rather than what buyers actually needed." … "Marketo, Engagio, Demandbase, 6Sense, and Terminus all had significantly overlapping features." … "Perhaps some marketers also purchased software to avoid having difficult internal conversations."

On the buyer's experience: "Prospects grew more likely to receive a poorly targeted email because business development reps had all become their own mini email marketing teams." … "By 2016, 77% of buyers agreed: Buying had grown even more difficult."

On the shallow funnel work — directly relevant to a research product: **"Many teams, unequipped to do real research on their buyer's journey, simply applied the theory of the funnel by labeling the 'top,' 'middle,' and 'bottom,' of their buyer's journey and calling it a day."** … **"Every call-to-action (CTA) became 'book a meeting,' regardless of whether the customer was ready for that step or not."**

On change management: "ABM often takes multiple attempts to stick because change is hard and humans are resistant to it." … "no one starts from an ideal place—every ABM program starts within a company that has its own culture and inertia."

On the current state: "ABM's heyday seems to have been from 2015 to 2021—since then, it's been on a slow but perceptible decline" … **"ABM swept marketing in the mid-2010s but little actually changed. It was everywhere. Now it's nowhere."** … "Teams are reverting back to using marketing qualified leads (MQLs) as their main success metric rather than pipeline."

Series hub: https://www.inverta.com/who-killed-abm `[FETCHED]`, with parts at `/in-cold-blood`, `/murder-on-the-icp-express`, `/the-missing-link`, `/marketing-most-foul`, `/his-dark-technologies`, `/death-of-a-sales-funnel`, `/the-hound-of-the-buyers-journey`, `/a-study-in-strategy`, `/trouble-in-paradise` — all `[FETCHED]`.

### 5.3d Intent data noise and false positives

> **Casey Patterson, Snowflake — the strongest practitioner rebuke of intent data found:**
> **"There's no amount of intent data that outweighs the fact that a sales rep knows that account intimately."**

> **Adam Turinas** names as separate failures: "Poor intent data" (#9) and "Not having the right topics available in third-party intent data" (#10). https://www.linkedin.com/pulse/22-reasons-why-abm-goes-wrong-adam-turinas `[FETCHED]`

And the vendor conceding it (6sense, quoted in full in §2.3a): *"When signals pile up without context, they stop being signals and start being noise."* … *"Any one of them alone produces a hunch."*

### 5.3e The "specifically wrong" trap — why bad data is worse than no personalization

This is the most important quote in the corpus for anyone building an AI research layer.

> **Mason Cosby:** "when you do ABM well, it resonates better than generalized ICP messaging because it's specific and correct. **The challenge is if your data source is incorrect, you are specifically incorrect.**"
https://www.pathfactory.com/blog/successful-abm-tips/ `[FETCHED]`

Related:
> **Andrei Zinkevich:** **"It's not enough to just run accounts through some AI automation to pull together easily accessible data."**
> **Fullfunnel:** "Sending a templatized email follow-up is not an activation playbook." · "Sales sends automated emails with nothing beyond title and industry personalization."
> **Fullfunnel:** **"Nobody cares about your unique value proposition… The buying committee members care about their own performance and KPI."**
> **UnboundB2B:** "Personalization that can't scale — Teams over-customize early and burn out fast."

A measured personalization ladder `[FETCHED, but self-published and unaudited]`: Generic **18%** engagement → Industry-specific **27%** → Company-specific **42%** → Individual + company-specific **63%**. Same dataset: **"The average closed-won deal had 6.2 stakeholders involved. Yet most ABM campaigns only target 1-2 personas per account."** and **"Deal velocity increased by 34% when we expanded our stakeholder targeting from 2 to 6+ people per account."** Plus: **"3+ touches within 48 hours of showing buying intent converted 4x better"** than the same content a week later; when sales response slipped to 72+ hours, **conversion dropped 48%**. https://demandloops.substack.com/p/what-12-months-of-abm-data-reveals `[FETCHED]`

### 5.3f ABM dies quietly, not loudly

> **UnboundB2B:** **"Most ABM campaigns don't fail dramatically. They stall quietly."**
> **Mason Cosby:** ABM programs "quietly stall out" and the program "turns into a side project instead of a growth engine."
> **Inverta:** "I noticed ABM getting quieter and quieter in meetings. She'd stay camera-off on Zoom and when we finally returned to office, she seemed a shell of herself"

The excuses given, which Cosby classifies as **symptoms, not root causes**: *"We didn't have the right tools yet." / "Sales just wasn't bought in." / "Leadership changed priorities." / "We couldn't prove ROI."*

**On ABM as a marketing initiative rather than a revenue system:**
> **UnboundB2B:** "ABM breaks when organizations treat it as a marketing initiative instead of a revenue system." … **"ABM is often over-engineered at the top with heavy planning, ICP workshops, and segmentation and under-designed in the middle, where buying decisions actually happen."**
> **DemandScience:** "Treating ABM as a campaign type rather than a go-to-market model" · "Most ABM program marketing failures are not tool problems. They are structural decisions made before any tool was selected." · **"The most consistent predictor of ABM failure is the state of the relationship between marketing and sales before the program launches."** · "If the two teams do not share an account list, the program is already split at launch."
> **Jon Miller:** "ABM was, frankly, just about marketing… anybody who's practiced ABM knows it's not just about marketing."
> **Chris Rack, CEO PharosIQ:** **"Vendors sell ABM like it's a button you press, but it's not. ABM is a strategy, not software."**
> **John Short, CEO Compound Growth Marketing:** "ABM can't work if sales is sitting there asking, 'What is this campaign supposed to do?' Alignment isn't just a kickoff meeting; it's an ongoing conversation."
> **Trinity Nguyen, CMO UserGems:** **"A quarter after launching the program, we realized that the sales team only worked on half of the target accounts."** … "Starting aligned is easy. Staying aligned is harder, especially when teams have conflicting priorities."

Additional failure statistics: **"42% of ABM campaigns struggle to show ROI"** (Forrester, via Exit Five) · ~**36%** of marketers struggle with measuring ABM ROI (Gartner) · **"56% of opportunities handed off to sales fail to close successfully"** (Forrester, *Demand, ABM, And Customer Marketing Survey, 2024*, via Kelvin Gee).

### 5.4 Why viral plays fail in enterprise

The most important 2026 addition to the failure canon: plays that work at $10–30k ACV break at enterprise scale.

> **"ABM stands for account-based marketing, not account-based lead generation."**
> **"if your playbook doesn't account for 417 touchpoints across 18 months, you don't have a playbook."**
> **Ernesto Ortega Alvarez (Malt):** "In Enterprise, the biggest mistake is trying to scale a playbook that assumes all accounts behave the same."
> **Astrid van Dam (Customs4trade):** "The whole enrich-and-blast approach just doesn't land. It's built for volume and speed, and enterprise buying is neither."
> **Sam Jacobs (Pavilion CEO):** "Buyers don't buy because you caught them at the right moment. They buy because what you're saying maps to a real, enduring problem."

**The "drama" failure mode** — the most underrated one, and the one most relevant to a research-and-resonance product:
> **Nate Nasralla:** "If you're moving upmarket, the biggest difference you'll see is that, now, you've got a second type of problem to solve in every deal: → 1st problem: Math → 2nd problem: 'Drama'"

Their worked example: a VP of Support whose ego blocked adoption of a solution to an obvious problem. Job-change and funding triggers don't scale to enterprise because "buy-in requires procurement, IT, compliance, legal, finance involvement." Personalized outreach alone cannot overcome internal politics.

On AI specifically: automating unrefined processes merely scales dysfunction. Also cited — **Sam Jacobs's framework**: without explicit strategy, organizations fill the void with disconnected "plays," producing fragmentation — different messages, value propositions and narratives competing inside one organization.

https://fullfunnel.substack.com/p/why-viral-abm-plays-fail-in-enterprise `[FETCHED]`

### 5.5 A real first-program post-mortem

Mason Cosby's own failed first ABM program — the most useful single failure narrative in the corpus because every detail is specific:

**The program:** 700 CEOs from Inc. 5000-winning companies. Message: "Don't be a one-hit wonder." One automated outbound email sequence. A cloned landing page with rewritten headlines. Zero personalization except company-name insertion. One channel. No sales involvement. One metric: immediate meetings booked.

**Result: zero meetings booked.**

**What went wrong, verbatim:**
- **Data quality** — many Inc. 5000 winners had won multiple times, so the "one-hit wonder" premise insulted them. "Data quality is non-negotiable"
- **Wrong channel** — "Cold outbound email to 700 CEOs who had never heard of us, at companies we had no relationship with, was never going to work."
- **Tone** — internally clever, externally condescending
- **No personalization** — "Seven hundred people all received the exact same experience, which is the opposite of what an ABM program is supposed to deliver."
- **No budget** — zero ABM budget eliminated channel diversity and testing. Lesson: scope down rather than launch oversized.

https://scrappyabm.com/blog/what-my-first-abm-program-taught-me/ `[FETCHED]`

### 5.6 Death by measurement and by impatience

**Quitting at month 3.** The most common cause of death, and it is a measurement failure rather than a program failure. Cosby's client nearly dismantled a program after three months of "flat" results; asked when their last report actually changed team behavior, "nobody could answer it." Brand recall takes 3–6 months. Fullfunnel failure mode #10 is explicitly "Lack of leading indicators... to avoid killing program too early that shows traction but doesn't generate revenue."

**Rebuilding instead of fixing.** "if nobody's using the data to change anything, a brand-new ABM program will hit the same wall."
https://scrappyabm.com/blog/stop-spinning-up-new-abm-programs/ `[FETCHED]`

**The messaging failure that is invisible until it kills you.** Teams agree on goals and target accounts but never agree on *which buyer problem* the message addresses. Marketing and sales then emphasize different pains; campaigns underperform for unclear reasons; "safe" broad messaging reduces relevance.
> "A message trying to speak to everyone tends to resonate with no one, because nothing about it is specific enough to be about the reader's situation."
> "A sharp B2B marketing plan picks the problem that matters most right now and says it clearly, trusting that clarity will do more work than breadth ever could."
The fix: lock two decisions — the primary problem being solved this quarter, and the buyer stage being targeted.
https://scrappyabm.com/blog/messaging-problem-that-kills-abm-programs/ `[FETCHED]`

**Operational failure — no documentation.**
> "The real truth why most B2B companies can't make ABM work and later scale it is lack of strong documentation and orchestration."
The master document has four sections: Program Overview (goals, reports, weekly backlog); Account Qualification (signals, criteria, CRM processes); Account Research & Development (cadences, scripts, SDR KPIs); Account-Based Content (workflow, quality benchmarks). CRM elements named: "Account card structure to store all the information", "Buying committee mapping in Sales Navigator", "Tracking frequency and ownership (who tracks what and when)."
https://fullfunnel.substack.com/p/operationalizing-abm `[FETCHED]`

**Common bottlenecks observed across four client programs** (Fullfunnel): lack of dedicated content resources; sales KPIs misaligned or insufficient ABM focus time; leadership distraction with unplanned activities.

**The organizational-change failure.**
> **Mason Cosby:** "In theory, it's not really that difficult. In practice, it's organizational change."
> **Mason Cosby:** "The worst thing that happens is a CMO hears about ABM...throw it at a marketing manager."
> **Mason Cosby:** "Sales is really protective of their accounts...if one seller owns entire relationship, what happens if that seller leaves?"
https://exitfive.com/podcast/how-to-simplify-abm-with-mason-cosby-founder-of-scrappy-abm/ `[FETCHED]`

### 5.7 Jon Miller's structural critique of ABM itself

The "spear fishing" critique `[SNIPPET — quotes live in an embedded video; treat as second-hand]`: there is a fatal flaw in traditional ABM, which Miller likens to fishing with spears — "You go identify those big fish you want to go after, and then you go after them, regardless of whether they're interested in talking to you or not." His proposed successor is **Buying Group Marketing (BGM)**. https://trendemon.com/blog/b2b-marketing-playbook/ `[BLOCKED — paraphrase page]`

His diagnosis of the broader playbook:
> "we are still relying on those same tactics, even though they are becoming less and less effective."
> "Years of eBook promotions, nurturing emails, social posts, and SDR outreach have numbed buyers to the traditional tactics"
> On intent data, the honest defense: "If even 10% of accounts exhibiting intent are genuinely in-market, the data is incredibly valuable."
https://www.jonmiller.com/blog/2024/1/20/the-marketing-playbook-i-helped-create-doesnt-work-anymore-heres-the-new-b2b-marketing-playbook `[FETCHED]`

### 5.8 The personal-vs-personalized failure

Kristina Jaramillo (Personal ABM) `[SNIPPET — personalabm.com returns an empty body to fetchers]`: her signature distinction is **"personalized" vs "personal"** ABM. A *personal* approach is what shifts the hearts, minds and wallets of the ~60% of markets that are disengaged and stuck in the status quo, in ways a *personalized* approach will not. Her stated position: ABM "starts with the foundational research and messaging to resonate with target companies and move them to take action," not with intent data. She and Eric Gruber cite ITSMA and TechTarget reporting **66% of ABM programs underperform**. Podcast: *ABM Done Right — A Personal ABM Podcast*.

---

## 6. How a Great Head of ABM Thinks

### 6.1 The qualification gate — the questions asked before anything else

A great Head of ABM's first job is deciding whether to run ABM at all. The convergent gate across independent sources:

**Fullfunnel's ABM-Fit Checklist (5 parameters):**
- Sales cycle **> 180 days**
- **ACV > $30,000**
- Hybrid sales model (product + consulting + training)
- **TAM < 1,000 companies**
- Multiple buyers in vendor evaluation

https://fullfunnel.io/abm-strategy/ `[FETCHED]`

**Scrappy ABM's ICP for its own clients:** B2B only · dedicated sales team · long sales cycles · **high ACV, ideally $50,000+** · mid-market SaaS · existing tech stack compatibility.
> **Mason Cosby:** "B2B dedicated sales team...average contract value of at least $50,000 or greater."
> **Mason Cosby:** "If you're super vertical specific, I think you should pretty much only be running ABM."
https://scrappyabm.com/ `[FETCHED]`; https://exitfive.com/podcast/how-to-simplify-abm-with-mason-cosby-founder-of-scrappy-abm/ `[FETCHED]`

**Growth Unhinged / Dan Rosenthal:** ACV **$50k+** and TAM **<20,000 qualified companies**. Below that, "traditional approaches like automated outbound have conversion rates too low to rely on independently" — i.e. above a certain TAM, outbound math works and ABM overhead isn't justified. https://www.growthunhinged.com/p/how-to-build-a-modern-abm-engine `[FETCHED]`

**Fullfunnel's five readiness questions:**
1. Do you have a clear ICP and qualification criteria?
2. Do you have a tailored value proposition per vertical and role?
3. Do you have a clear awareness / demand-gen / activation playbook?
4. Do you have a **dedicated ABM team with 70% time commitment**?
5. Are marketing, sales and executives aligned on measurement?

**Bev Burgess's first question, verbatim:**
> **Andrew Fitzgerald, VP Global ABM, Kyndryl:** "The most important thing is to understand what your business is trying to do and ABM's role in that."
> "Start with your business objectives first, then build your ABM strategy around them — not the other way around!"
https://inflexiongroup.com/resources/designing-the-right-abm-strategy-for-your-business/ `[FETCHED]`

### 6.2 When a great Head of ABM refuses

Refuse — or defer — when any of the following is true:

- **The ICP is "anyone."** "If the answer to 'who's your ideal customer?' is 'honestly, we could sell to pretty much anyone,' ABM isn't the right move yet."
- **ACV can't carry a 12-month payback.** Cosby's math: 3–4 months setup + 3–6 months education + 90–120 day sales cycle ≈ 12 months to revenue.
- **There is no dedicated sales counterpart.** The comparison numbers are brutal: 1.77% meeting rate, 70.51% no-response, **zero** accounts to pipeline without one.
- **No one owns it.** "ABM dies slowly when everyone owns it. Which really means no one owns it."
- **Leadership hasn't agreed what success is, who owns it, and how it's measured** — the three pre-kickoff agreements. "Leadership buy-in is the foundation on which everything else in ABM is built."
- **The team wants to buy a platform first.** "Software ≠ ABM." "Audit before you spend."
- **The company wants ABM everywhere at once.** Roll out to a pilot group of motivated sellers, never org-wide.
- **The seller culture is lone-wolf.** Sales culture must support collaboration with marketing; otherwise "air cover" that never converts.
- **The company is pre-PMF.** ABM is "an amplifier" — it amplifies a working motion, it does not create one.
- **A CoE is proposed before the pilot has worked.** "If your ABM is still experimental...an ABM Center of Excellence is premature."

Sources: https://scrappyabm.com/blog/abm-falling-flat/ · https://scrappyabm.com/blog/before-you-launch-abm/ · https://scrappyabm.com/blog/why-abm-programs-fail/ · https://fullfunnel.substack.com/p/who-owns-abm · https://insights.strategicabm.com/what-is-an-abm-center-of-excellence-in-2026 — all `[FETCHED]`

**And the substitution to offer instead of refusing outright:**
> **Mason Cosby:** "I would actually, before you go build an ABM program, start a website re-engagement playbook or close loss program first."

### 6.3 The planning questions asked of a client, in order

Synthesised from the corpus. These are the questions a Head of ABM asks before proposing anything:

**Business context**
1. What is the business trying to do, and what is ABM's role in that? (Fitzgerald)
2. Which of the four ABM goals is this — net new revenue, pipeline acceleration, expansion, or renewal/churn prevention? (Fullfunnel) Or, in Mulkeen's framing: account penetration, a major pursuit, a new logo, or a perception shift?
3. What should be different by the end of the quarter? ("'More pipeline' isn't a goal. Really, it's a direction.")
4. What is intentionally out of scope?

**Qualification**
5. What's your ACV, sales cycle length, and TAM size?
6. How many people are typically involved in an evaluation?
7. Do you have a dedicated sales team, and will a named rep commit to this?

**Evidence**
8. Show me your closed-won and closed-lost from the last 6–18 months. What patterns are in the close reasons?
9. If you filter your CRM by your stated ICP, do real customers show up? ("If the filter comes back empty, that's worth sitting with.")
10. Which accounts already know you exist? Which show product-need evidence? Who do we already have a relationship with?
11. What signals precede a real buying conversation in your business — and are any of them vertical-specific and not in a commercial database?

**Alignment**
12. Sort the target list into must-win / nice-to-win / not-a-focus-this-quarter — separately, sales and marketing. Where do you disagree?
13. Which single buyer problem are we solving this quarter, and at which buyer stage?
14. Who owns this, what triggers handoff, and what's the weekly cadence?
15. What would need to be true by week six to justify changing approach?

**Resources**
16. What content already exists? (Audit before you spend.)
17. What's in the stack today, and what does it actually do?
18. Who is the executive sponsor?

Sources: https://scrappyabm.com/blog/tasked-with-abm/ · https://scrappyabm.com/blog/abm-things-to-agree-on/ · https://scrappyabm.com/blog/three-tier-test-team-alignment/ · https://scrappyabm.com/blog/icp-bcp-targeting/ · https://fullfunnel.io/abm-strategy/ — all `[FETCHED]`

### 6.4 How they sequence from zero

**Cosby's seven-step sequence for a new ABM owner:**
1. Start with strategy
2. Get alignment before creating anything
3. Build a realistic target account list
4. Start small to get wins fast
5. Do your homework
6. Build your account progression model
7. Know what success looks like

> "Tactics without strategy are just expensive guesses."
> "The teams that skip these ABM steps end up rebuilding everything three months later."
> "Proof comes from doing something focused well rather than doing everything at once."
> "The teams that create something sustainable are the ones that took the time to get the foundation right first."
https://scrappyabm.com/blog/tasked-with-abm/ `[FETCHED]`

**The implementation sequence** (Scrappy ABM, deliberately timeline-free):
1. Define best-fit accounts (profitability, renewal rates, value realization, support ease)
2. Align sales and marketing (one shared list, ownership, success metrics, review rhythm)
3. **Start with activation** — launch one repeatable play off existing buying signals (no-shows, pricing page visits, stalled deals, usage spikes)
4. Build 2–3 simple plays with clear owners, triggers, messaging and next steps
5. Personalize only where it matters
6. Add budget and tools **only after** plays generate meetings and pipeline
> **Trevor Grimes, Scrappy ABM:** "ABM usually breaks when the plan looks great on paper but is too heavy to execute in real life."
https://scrappyabm.com/blog/how-to-implement-abm/ `[FETCHED]`

**Fullfunnel's three-stage arc:**
- **Pilot Campaign (6 weeks)** — the **1-1-1-1-1-1-1-10 framework**: 1 market, 1 vertical, 1 SDR, 1 marketer, 1 intent source, 1 warm-up tactic, 1 tier, 1 goal, **max 10 accounts**
- **ABM Operations** — document processes, create playbooks, install new intent sources
- **Scaling ABM** — build a dedicated team, onboard multiple SDRs/marketers, expand to new verticals
https://fullfunnel.io/abm-strategy/ `[FETCHED]`

**How small to actually start** (Cosby): **one sales rep**, not a team. **2–3 accounts** with shared characteristics from that rep's pipeline. **10 accounts per segment** is enough to launch. **5–10 accounts** lets you monitor progress without dashboards.
> "One rep and a handful of accounts is enough to start proving the model works."
> "When you're working with five or ten accounts, you can stay close enough to what's happening to know whether things are moving."
> "When the target account list covers too much ground, programs tend to get generic, and budget goes toward leads that don't match the ideal customer profile."
> On constraints: "Give them a genre, tempo, and specific direction, and suddenly they're off. The constraints look like limitations from the outside, but they're what makes the work happen."
https://scrappyabm.com/blog/start-small-abm-strategy/ `[FETCHED]`

### 6.5 How they decide tier splits

The decision is not "how much revenue" — it is **how much evidence exists that this account has the problem, plus how much awareness and relationship already exists.**

**The decision procedure, assembled from the corpus:**

1. **Cluster before you tier.** ABM 3.0's core shift: from "vertical and firmographic targeting to cluster-based targeting" — "Groups accounts that share the exact same strategic challenge and use case." Verticals are a proxy; the shared *strategic challenge* is the real segment. https://fullfunnel.substack.com/p/abm-strategy-30 `[FETCHED]`
2. **Score on the four pillars** — revenue potential, vendor awareness, relationship, product-need evidence.
3. **Sort into the three lists** by opportunity likelihood: Cluster ICP (<5%) → awareness only; Future Pipeline (<30%) → profiling and challenge validation; Active Focus → opportunity development.
4. **Cap Tier 1 hard.** 1–5 accounts (Mulkeen), 10 max for a pilot (Fullfunnel), 2–3 for a first rep (Cosby). Strategic ABM is "depth over breadth."
5. **Size 1:few by shared context, not by count.** 15–20 accounts sharing something in common (Mulkeen); ~30 per segment (Inflexion Segment ABM).
6. **Run the three-tier alignment test** with sales independently. Disagreement is the finding.
7. **Make the list dynamic.** Static lists are named as a reason the classic tier model is obsolete. Fullfunnel's weekly review explicitly includes "account list additions/removals."
8. **Bias the pilot toward warm.** Failure mode #11: don't chase new logos in a pilot. Run acceleration and expansion against accounts that already know you.

### 6.6 The operating rhythm

> **The weekly agenda, verbatim:** "what's working and why, what's not working and why, what bottlenecks do we have and how to unblock them"

- **Daily:** ecosystem engagement; act on high-intent signals within a day ("A quick, relevant follow-up within a day will outperform the perfectly crafted message two weeks later")
- **Weekly:** ABM↔rep sync per priority account; leading-indicator review; account list adds/removes; 5+ thoughtful comments; 10 ICP connections
- **Bi-weekly:** regional marketing overlap reviews
- **Monthly:** lagging indicators; check-ins with email/PMM/events teams; awareness metrics
- **Quarterly:** sales leadership review; program retro; objective reset
- **Annual/3-year:** account ambition, for strategic accounts

Fullfunnel's ABM Strategy 3.0 names this explicitly as pillar 8: **"Quarterly-weekly-daily coordination meetings."**

### 6.7 The intellectual posture

The lines that best encode how a great Head of ABM thinks:

> **"You can't personalise what you don't understand. You can't be relevant to someone you've never listened to."** — Declan Mulkeen
> **"They build value propositions from account intelligence, not assumptions."** — Declan Mulkeen
> **"Human-first. AI-fast. Strategy-led. That's the model that works."** — Declan Mulkeen
> **"The goal is not to map every capability onto every priority – it is to find the most credible and compelling intersections."** — Inflexion
> **"Ultimately, the judgment about where to focus, and why, needs to come from people who know the account."** — Inflexion
> **"Movement > engagement."** — Mason Cosby
> **"Prioritize progression, not just activity."** — Mason Cosby
> **"Remember, this is not about you... It's about your clients, your prospects, and what the problems that they're experiencing."** — Declan Mulkeen
> **"You must accept the fact that not everybody is going to buy your product."** — Fullfunnel
> **"The narrower your focus, the higher ROI you'll see."** — Fullfunnel
> **"Get into the consideration set of strategic accounts when they evaluate solutions."** — Fullfunnel's stated success metric for 2026
> **"Crawl, walk, run...an infant takes anywhere from seven to ten months...to learn to crawl."** — Mason Cosby

---

## 7. Maturity Model — Week 1 / Month 1 / Quarter 1 at a Series A–C B2B Company

Assembled from the sequencing guidance across Fullfunnel, Scrappy ABM, Inflexion and Growth Unhinged. Assumes a company that has passed the qualification gate in §6.1 and has one motivated sales rep.

### Week 1 — Qualify, align, and choose the warmest ground

**Do:**
- Run the qualification gate. ACV, cycle length, TAM, committee size, dedicated sales counterpart. If it fails, say so and propose a website re-engagement or closed-lost play instead.
- Get the three pre-kickoff agreements from leadership in writing: **what success looks like, who owns it, how it's measured.** "Leadership buy-in is the foundation on which everything else in ABM is built."
- Pull closed-won and closed-lost from the last **6–18 months**. Find the patterns in close reasons. Test the stated ICP by filtering the CRM against it — "If the filter comes back empty, that's worth sitting with."
- Pick **one** of the four starting places: website traffic, closed-lost, active pipeline, or current customers. Start where you have the most leverage. Do **not** start with net-new cold.
- Audit existing content before proposing any spend. "Some of the best ABM examples we've seen were built almost entirely on existing resources."
- Run the three-tier alignment test with sales independently.

**Do not:** buy a platform; write a target account list from a whiteboard; announce ABM company-wide; promise pipeline this quarter.

**The pitch to leadership, if you need budget** (Cosby's four-step, ~1 hour of prep): document current programs → assign a purpose to each → apply the 4D framework (Data / Distribution / Destination / Direction) → identify the gap and make one specific ask.
> **"Specific asks get fast yeses. General asks get added to next quarter's agenda."**
https://scrappyabm.com/blog/fastest-way-to-get-leadership-buy-in/ `[FETCHED]`

### Month 1 — Scope the pilot to something absurdly small, then research properly

**Do:**
- Lock the pilot scope. **Fullfunnel's 1-1-1-1-1-1-1-10:** one market, one vertical, one SDR, one marketer, one intent source, one warm-up tactic, one tier, one goal, **max 10 accounts.** Or Cosby's version: one rep, 2–3 accounts from that rep's pipeline, 10 per segment maximum.
- Cluster, don't verticalise. Group accounts by *shared strategic challenge and use case*, not by SIC code.
- Score the shortlist on the four pillars: revenue potential, vendor awareness, relationship, product-need evidence. Sort into Cluster ICP / Future Pipeline / Active Focus.
- **Do the research.** For each account: strategic priorities, challenges, stakeholder KPIs. Desk research plus 1-1 research. Structure each finding as *research question → what this insight tells you → how to use it.* Aim for 30+ data points per account if you have the tooling.
- Map the buying committee: **8–10 people** for amplification, **2–3 core decision makers**. Roles: champion, decision-maker, influencer, blocker — or economic buyer, technical evaluator, end user, influencer.
- Build the messaging spine: the one buyer problem for this quarter, the buyer stage, the messaging house (roof / pillars / foundation), and one account-specific value proposition per Tier 1 account.
- Write the rules of engagement: handoff trigger, who owns what pre- and post-handoff, weekly sync.
- Set up account-level tracking in the CRM. This is the #4 structural failure — "CRMs configured for contacts/deals rather than account-level tracking."
- Define the account progression model: Awareness → Initial Engagement → Meaningful Engagement → MQA → SQA → Opportunity → Re-Engagement. Define the signals that mark each transition.

**Minimum viable stack:** CRM + marketing automation + sales outreach. Add website visitor ID, Sales Navigator, and account enrichment if the budget exists. Nothing else.

**Do not:** personalize for its own sake; run programmatic display; target decision-makers only; measure meetings booked.

### Quarter 1 — Activate, report movement, and prove the model before scaling

**Weeks 5–8 — activation**
- Launch **one** repeatable play. The highest-yield candidates for a Series A–C company: closed-lost re-engagement (60–80% of close reasons are temporary), an account-based podcast (guests = target account execs), a genuinely educational webinar with a solution architect (not a product pitch), or engagement-based LinkedIn outreach.
- Warm-up before activation. Fullfunnel's five: content collaboration, virtual events, social engagement, awareness ads/retargeting, direct mail. Explicitly **not** programmatic display + an automated 21-touch cadence.
- Sales reps publish. CrossKnowledge's reps posted five pieces weekly. "Our best-performing content wasn't from the corporate page."
- Offer **bridge activities** — 1:1 expert sessions — instead of jumping to "book a demo."
- Act on high-intent signals within a day.

**Weeks 6 — the pre-agreed checkpoint**
- "What would need to be true by week six to justify a change in approach?" — decided *before* the quarter started, while everyone is calm.

**Weeks 9–13 — report movement, not activity**
- Report the four leading indicators weekly/bi-weekly: account engagement depth, persona spread, stage velocity, sales behavior change.
- Report lagging indicators monthly/quarterly. Do not expect revenue.
- Every report ends with: what's working, what needs adjustment, what changes next month.
- Track the unit economics that matter: engagement rate (Fullfunnel's own benchmark: 43%), account-to-pipeline ratio (theirs: 8.7%), account-to-conversation ratio, account penetration.

**Realistic Quarter 1 outcome, based on the case set:** roughly **26–43% of the target list engaged**; a handful of discovery calls; **0–4 sales opportunities**; possibly one closed-won if you ran acceleration or expansion rather than net-new. TestRail's Q1: 4 enterprise opportunities (1 closed-won) + 22 SALs within 90 days, from a list cut to 72. Fullfunnel's own quarter: 46 accounts, 3 opportunities, 1 closed-won.

**What NOT to do in Quarter 1:** expect revenue; add accounts; add channels; buy a platform; build a Center of Excellence; declare failure. "ABM is not a silver bullet that can drastically decrease sales cycle."

### Beyond Quarter 1 — the maturity ladder

| Stage | Trigger to advance | What gets added |
|---|---|---|
| **Pilot** (6 weeks–6 months) | One play produces engaged accounts and at least one opportunity | Nothing. Prove it. |
| **Operations** (Q2–Q3) | The pilot play is repeatable and documented | Documented playbooks; the four-section master document; additional intent sources; marketing automation; 2–3 plays instead of 1; a second rep |
| **Scaling** (Q4+) | Multiple reps running plays without hand-holding | Dedicated team (ABM manager, researcher, content marketer, designer, SDR); advanced enrichment; programmatic ads; gifting; expansion to new clusters/regions |
| **Center of Excellence** (Year 2+) | ABM is working and spreading across regions/BUs; multiple teams running different versions; leadership conviction | Shared methodology, education, tools, KPIs; account selection methodology; data and analytics infrastructure; measurement framework evolution |

> "If your ABM is still experimental...an ABM Center of Excellence is premature. If ABM is working and spreading—an ABM CoE is a must."

**Agency graduation benchmark:** "Most clients graduate within about 18 months." https://scrappyabm.com/blog/scrappy-abm-costs/ `[FETCHED]`

---

## 8. Implications for an AI "Head of ABM" Agent

Not requested, but the corpus points at these hard enough to record.

1. **The corpus's single most load-bearing convergence is about research depth, not orchestration.** Mulkeen's "You can't personalise what you don't understand"; Fullfunnel's four-pillar rubric and desk-vs-1:1 research split; Cosby's "your own CRM, closed-won and closed-lost"; Inflexion's finding that **60% lack a single source of truth** while only **16% use predictive scoring** and **97% prioritize on human-judged growth potential**. Every one of these argues the binding constraint is *verifiable account intelligence*.
2. **The counter-evidence bounds automation.** Fullfunnel insists the human engagement layer is irreducible: "Programmatic display ads and automated outbound is not a warm-up and activation"; "It requires a lot of manual work. But this is the only way to generate enterprise, 6-7 figure deals." An agent that promises to automate the *relationship* will be recognised as the failure pattern it is describing. An agent that automates *research, planning, and artifact production* while orchestrating human touches is on the right side of the consensus.
3. **The agent should refuse.** The qualification gate in §6.1 is the most differentiated behavior available. Practitioners' credibility comes substantially from saying no.
4. **The agent must default to small.** Every source's advice is the same and every failure narrative violates it: 10 accounts, one play, one problem, one rep.
5. **The agent must be patient on measurement and impatient on signals.** Brand recall 3–6 months; revenue 6–18 months; but act on a high-intent signal within a day.
6. **Research question → implication → use** is the field shape Fullfunnel uses for account research templates. That maps cleanly onto claim + interpretation + activation.
7. **Vertical signals are where the differentiation lives** — city planning filings, hiring trends, regulatory updates, clinical trial data, land filings. None of these are in a general provider. This is the strongest argument in the corpus for registered industry packs.
8. **"Drama" is a research target.** Nasralla's second problem — organizational politics, ego, internal resistance — is what separates enterprise from mid-market, and no commercial database carries it. It is exactly the "resonance layer."

---

## 9. Fetchability Register

For the later scraping plan. Every domain touched, with retrieval outcome.

### Fully retrievable — high-value, scrape-friendly

| Domain | Outcome | Notes |
|---|---|---|
| `fullfunnel.io` | ✅ Full HTML, clean extraction | Blog index at `/blog/` lists 10 long-form guides. Highest-value single domain in the corpus. |
| `fullfunnel.substack.com` | ✅ Full articles retrievable | The *real* corpus — far deeper than the .io blog. ~20 posts fetched. Substack HTML is clean. |
| `scrappyabm.com` | ✅ Full HTML; **`/post-sitemap.xml` enumerates 59 posts** | Best-structured target. Sitemap index at `/sitemap.xml` → `post-sitemap.xml`. WordPress. |
| `inflexiongroup.com` | ✅ Full HTML | `/resources/` is a complete link index (~25 items). 2026 Benchmarking Study split across 8 summary pages. Note: some findings live only in embedded infographics that do not extract as text. |
| `insights.strategicabm.com` | ✅ Full HTML | HubSpot-hosted. Index at root. Podcast transcripts are unusually quote-dense. |
| `jonmiller.com` | ✅ Full HTML | Squarespace. URL pattern `/blog/YYYY/M/D/slug`. |
| `6sense.com/science-of-b2b/` | ✅ Full HTML | Report landing pages carry the headline stats in text. |
| `exitfive.com` | ✅ Articles and podcast pages | `/articles` and `/podcast/*` both extract. Community threads not tested (likely auth-walled). |
| `growthunhinged.com` | ⚠️ Partial — paywall mid-article | Free portion is substantial (Steps 1–3 of 7 on the ABM engine piece). **Note:** `growth-unhinged.beehiiv.com/p/*` returns 404; the canonical host is `www.growthunhinged.com/p/*`. |
| `martechpod.com` | ✅ Full transcripts | Excellent verbatim source for Chris Walker. |
| `b2bmarketing.net` | ✅ Full HTML | Four-expert interview page was productive. |
| `humbleroots.agency` | ✅ HTML, but summary-only content | No verbatim quotes on the page; audio on YouTube. |
| `demandgenreport.com` | ✅ Full HTML | Source of the original FIRE model article (2018). |
| `revopsfm.substack.com` | ⚠️ Thin extraction | Page loaded but yielded fragments only. |
| `demandbase.com/resources/*` | ✅ HTML, low yield | Resource pages describe rather than state statistics. |
| `hockeystack.com/blog` | ✅ Index extracts; `/lab-blog-posts/*` are the data studies | `/blog-posts/b2b-benchmarks` 404s. The 417-touchpoint report was reached only via Fullfunnel's citation; the LinkedIn benchmark lives at `/lab-blog-posts/linkedin-ads-benchmarks`. |
| `clay.com/blog` + `university.clay.com` | ✅ Full HTML, ~144 posts, clean | The single richest source for play mechanics and signal taxonomy. Blog index enumerates. |
| `salesmotion.io/blog` | ✅ Full HTML | Best pricing/contract-terms source found; Vendr-derived medians throughout. |
| `prospeo.io/s/*` | ✅ Full HTML | Pricing + aggregated Reddit criticism. Note `/s/apollo-pricing-*` returns **410 Gone**. |
| `syncgtm.com/blog` | ✅ Full HTML | Balanced tool reviews with named weaknesses. |
| `inverta.com/who-killed-abm` | ✅ Full HTML, 9-part series | The best independent post-mortem in the corpus. All parts extract. |
| `exitfive.com/podcast` + `/newsletter` | ✅ Full transcripts | Where Snowflake/Ramp/Hightouch practitioners actually speak. High quote density. |
| `usergems.com/customers` + `/power-up-your-pipeline` | ✅ Full HTML | The benchmark report is the best job-change dataset. |
| `sendoso.com/success-stories` + `reachdesk.com/customers` | ✅ Full HTML | Vendor, but dense with named-practitioner quotes. |
| `6sense.com/customer-stories` + `/blog` | ✅ Full HTML | Largest single case-study bank found. |
| `demandbase.com/resources/labs/*` | ✅ Full HTML | Observational platform data (n=1,452 tenants) — better methodology than most vendor research. |
| `mutinyhq.com` (blog / case-studies / blueprints) | ✅ Full HTML | `/playbooks/*` sub-pages are nav hubs with no article body. |
| `autobound.ai/guides` + `/blog` | ✅ Full HTML | The 60-signal taxonomy and the 12-benchmark table. |
| `intel.42agency.com/abm-sentiment` | ✅ Full HTML | Highest-signal tooling source; aggregates otherwise-unreachable Reddit. |
| `growigami.com`, `userled.io`, `grouglobal.com`, `zenabm.com`, `attendir.com`, `vendelux.com`, `belkins.io`, `gtmonly.com`, `infuse.com`, `thesmarketers.com`, `motionabx.com`, `agent3.com`, `hartehanks.com`, `refinelabs.com`, `revsure.ai`, `oktopost.com`, `poweredbysearch.com`, `getrecast.com`, `demandscience.com`, `unboundb2b.com`, `connorskelly.substack.com`, `kylepoyar.substack.com`, `bloomberry.com`, `stevenmoody.com`, `tomtunguz.com`, `apollo.io/insights`, `amplemarket.com`, `unifygtm.com`, `cognism.com`, `contentallies.com`, `pathfactory.com`, `modop.com`, `xgrowth.com.au`, `docket.io`, `theabmpulse.com`, `coldiq.com`, `factors.ai`, `pipeline.zoominfo.com`, `warmly.ai`, `conversionwax.com`, `thestarrconspiracy.com`, `demandloops.substack.com` | ✅ All fetched successfully | Long tail, all clean. |

### Blocked, degraded, or unavailable

| Domain / target | Outcome | Workaround |
|---|---|---|
| `fullfunnel.co` | **404 — dead domain** | Use `fullfunnel.io`. |
| `momentumitsma.com` / `momentumabm.com` | **301 → then repeated HTTP 504 Gateway Timeout** on `/insights/`, `/account-based-marketing/`, `/use-cases/abm-leader`, `/global-account-based-marketing-benchmark` | All Momentum ITSMA benchmark figures in this brief are `[SNIPPET]` only and **unverified**. Retry later; the site appears down or aggressively rate-limiting. This is the largest verification debt in the brief. |
| `personalabm.com` | **Empty response body** (JS-rendered SPA) | Kristina Jaramillo material is snippet-only. Would need a headless browser. |
| `b2binstitute.org` | **DNS failure — `getaddrinfo ENOTFOUND`** | LinkedIn B2B Institute 95-5 material sourced indirectly via Miller and Harrison snippets. |
| `gtmpartners.com/move-framework` | **404** | Sangram Vajre's MOVE framework stage definitions never obtained. Gap. |
| `linkedin.com` (all) | **Not fetchable** | Dale Harrison's primary posts, and most creator content, are unreachable. Search-indexed copies were the only route and search budget ran out. |
| `trendemon.com/blog/b2b-marketing-playbook/` | ⚠️ Paraphrase page; quotes are in an embedded video | Miller's "spear fishing" quote is second-hand. |
| Inflexion — the five ABM type **definitions** | **Named on the site, defined nowhere public** | Gated behind Burgess's 2025 Kogan Page book (ISBN 9781398619135). Reconstructed operationally from the 2026 benchmark summaries. **This is the single most important unfilled gap.** |
| `growthunhinged.com` — Steps 4–7 of the ABM engine | **Paywalled** | Signal tracking, orchestration, and measurement steps not obtained. |
| `duckduckgo.com` / `html.duckduckgo.com` / `lite.duckduckgo.com` | **CAPTCHA challenge** | Not usable as a fallback search route. |
| `mojeek.com` | **403 Forbidden** | Not usable. |
| **Reddit — all of it** | **Hard-blocked at the tool level.** `www.reddit.com`, `old.reddit.com`, and the `r.jina.ai` proxy all returned *"You've been blocked by network security."* | **The single biggest content gap.** The rawest practitioner venting — r/sales, r/b2bmarketing, r/gtmengineering, r/SaaS, r/LeadGeneration, r/SalesOperations — is entirely absent except where aggregators (42 Agency, Prospeo) quote it with usernames and dates. Threads identified but unread: r/gtmengineering/1sjjqvf · r/b2bmarketing/yd6qfw · r/ABM/sbyj63 · r/ABM/1b27m2o · r/SalesOperations/1pr1ffg. **Needs an authenticated API path or a residential-proxy scrape.** |
| `peersignal.org/p/i-just-churned-6sense` | **SSL handshake failure ×2; `r.jina.ai` proxy returned 422** | Adam Schoenfeld's churn post is the catalytic artifact of the 2025–26 platform backlash. **Highest-value single un-retrieved source in this brief.** Worth a manual read. |
| `web.archive.org` | **Fetch refused** | ITSMA's original pre-acquisition pages unreachable. |
| `google.com`, `bing.com`, `brave` (rate-limited), `ecosia`, `yandex`, `startpage`, `searx.be` | **CAPTCHA / challenge / 403 / truncation** | Brave worked as a *throttled* proxy (HTTP 429 on more than one call per batch). Bing returned results but **truncated every query at the first word**. No reliable search fallback exists. |
| `marketingweek.com`, `cxl.com`, `marketingprofs.com`, `modernb2b.co` | 403 / empty body | Not retrievable. |
| `gtmpartners.com/move-framework`, `alyce.com` (DNS gone — folded into Sendoso), `rb2b.com/case-studies` (404), `warmly.ai/customers` (404), `on24.com` (403), `gartner.com` (403) | 404 / 403 / DNS | Sangram Vajre's MOVE stage definitions, RB2B and Warmly first-party cases, and Gartner ABM data all unobtained. |
| LinkedIn profile feeds / `recent-activity` | **HTTP 999** | Individual public *post* permalinks fetch fine; feeds do not. So Dale Harrison's and Chris Walker's LinkedIn critiques could not be swept. |
| WebSearch (the tool itself) | **Budget exhausted at 200 calls, session-wide** | This is the biggest structural constraint on this research run — it was consumed inside the first few minutes across four parallel agents. Discovery after exhaustion was limited to link-lists already harvested and sitemaps. Raise `CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION` before the next run, **or allocate an explicit per-agent search quota.** |

### Never reached (search budget, not blocking)

Peep Laja / Wynter · Adam Robinson (RB2B) founder commentary · Exit Five *community* threads (the podcast and newsletter were reached) · Sangram Vajre primary material and the MOVE stage definitions · Robert Norum beyond one interview · Pavilion · RevGenius · GTMfund/GTMnow · Sales Hacker · Bowery Capital · Hacker News · Kristina Jaramillo primary (site is a JS-rendered SPA) · Dale Harrison's actual intent-data and self-reported-attribution critiques (podcast timestamps obtained, transcripts not) · ITSMA/Momentum award-winner *metrics* (never published publicly) · B2B Marketing Awards 2024 winner detail (rolled off the live site) · HockeyStack's primary 417-touchpoint report (reached only via Fullfunnel's citation) · Attio, Folk, Default, Octave, Ocean.io, Lemlist, Instantly, Postal, Alyce standalone · "industry-report-as-bait" and community-led plays as named motions.

**Named companies from the original hunt list with no findable numbers:** Databricks · Zendesk · Thomson Reuters · Fujitsu · SAP (only SAP Concur) · Salesforce · Dun & Bradstreet · Iron Mountain · Cisco / Juniper / Xerox (award finalists only) · Gong · Klaviyo · Lattice · Drift · Vanta · Deel · Ramp (qualitative only, via Exit Five) · Lavender · Amplemarket (product content only).

### Scraping-plan recommendations

1. **Prioritise `scrappyabm.com` (sitemap-enumerable, 59 posts) and `fullfunnel.substack.com` (deepest, most quotable).** Between them they carry most of the practitioner voice in this brief.
2. **`inflexiongroup.com/resources/` is the enterprise-side spine** and is fully link-indexed — but budget for the fact that several 2026 benchmark findings are locked in infographics, so text extraction under-reports.
3. **Retry `momentumabm.com` on a schedule.** It holds the only large-n ABM benchmark series and was 100% unavailable during this run.
4. **Anything requiring LinkedIn needs a different acquisition path** — this is where a large share of 2024–26 practitioner discourse actually lives, and it is structurally unreachable by fetch.
5. **Budget WebSearch explicitly when fanning out to parallel agents.** Four concurrent research agents exhausted a 200-call session budget before any of them finished discovery. Everything after that was link-list traversal and sitemaps.
6. **`clay.com/blog` (~144 posts) and `6sense.com/customer-stories` are the two largest untapped structured banks** — play mechanics and case-study numbers respectively. Both extract cleanly and both have enumerable indexes.
7. **Reddit needs a separate acquisition path** (authenticated API or residential proxy). It is where the unvarnished tool criticism lives, and every fetcher tried was refused. `intel.42agency.com` and `prospeo.io` are the best available second-hand proxies for it today.
8. **Two named gaps worth a manual human read, not a scrape:** Adam Schoenfeld's "I just churned 6sense" (peersignal.org, SSL-blocked) and Bev Burgess's 2025 handbook, which is the only source for the five ABM type definitions.

### Provenance hygiene for whoever consumes this corpus

Three tiers of trust, in descending order:
1. **Measured, large-N, methodology stated** — 6sense 2025 Buyer Experience Report · HockeyStack's 1.5M-contact touchpoint study · Demandbase Labs (1,452 tenants, observational) · ZenABM (161,256 ads, CRM-connected) · UserGems (350+ companies) · Steven Moody's salary benchmark (491 hand-checked postings) · Ehrenberg-Bass in-market base rates.
2. **Small-N or self-reported but honestly labelled** — Inflexion 2026 (n=40) · Momentum ITSMA 6th annual (n=279) · Fullfunnel's own program economics · Belkins' cold-call funnel.
3. **House statistics with no attribution — quote only with the hedge** — "78% of ABM programs have failed" (Scrappy ABM, no source) · "98.5% not satisfied" (Fullfunnel, drifting denominator: 300+ in one place, 450+ in another, and a "9% report great results" variant) · every "87%/91%/92% of marketers say ABM outperforms…" figure · thestarrconspiracy.com's benchmark tables · all vendor ROI multiples.

Roughly **75 of the ~100 case studies in §4 are vendor-published.** The genuinely independent voices in this corpus are: Inverta's *Who Killed ABM* series (Kathy Macchi) · Fullfunnel (Zinkevich/Blagojevic) · Scrappy ABM (Mason Cosby) · Connor Skelly and Gaetano DiNardi · Jon Miller · Adam Turinas · Bev Burgess/Inflexion · Declan Mulkeen/strategicabm · Kyle Poyar · Steven Moody · and the Exit Five operators (Casey Patterson/Snowflake, Brian Kotlyar/Hightouch, Drew Pinta/Ramp).

**"Influenced pipeline" dominates the vendor tier and is nearly always unaudited.** The most defensible case studies are the ones with both a denominator and a clock: BlueBotics (12 accounts → 100% engaged → 15 conversations → 2 wins) · Fullfunnel's own quarter (46 accounts → 43% engaged → 3 opps → 1 win, 8.7% account-to-pipeline) · LaunchDarkly (45 SALs vs a 30 target in under 60 days) · the unnamed dev shop (30 accounts → 37% reply → 20% success) · SAP Concur (explicit 3–4 month advertising causality window) · Hightouch's control-group lift (+32%).

One attribution conflict to resolve before use: the **"$250K closed-won / 100× ROI"** quote appears attributed to a **Salesloft** AE on one fetched page and to a **Sprout Social** field marketer in a search summary. One of the two is a summarizer error.
