# Clue sample run — one full account-research pass, run live

**Date:** 2026-08-25 · **Total live spend: $0.22998** (ceiling $2.00) · **Apollo credits: 3** (ceiling 12) · **20 API calls**
**Account picked:** Lassie (lassie.ai) · **Primary contact:** Steijn Pelle, co-founder & CEO
**Deliverables:** this file · `claims.json` (52 rows) · `claims_summary.json` · `cost_ledger.json` · `raw/` (every response) · `step*.py`

This is a simulation of one pass of the future agent loop, run against live APIs on the founder's keys.
Everything below is grounded in a real response saved in `raw/`. Where something was not found, it says
so. No number in this document was estimated unless it is explicitly labelled an estimate.

---

## 0. The context the agent ingested

**The client is Clue itself.** Clue is an AI-native ABM orchestration platform: agents discover target
accounts, enrich account and contact data, run dossier-grade deep research on accounts and buying
committees, draft personalised campaign content (including direct mail), and scale artifacts across
contacts. **This run is finding buyers FOR Clue.**

**ICP (stated as a hypothesis, not a validated ICP):** US vertical B2B SaaS / AI startups, seed to
Series B, ~10–200 employees, selling a high-touch product into a **fragmented SMB / mid-market
vertical** (medical practices, dental, legal, logistics, construction back-office). Founder-led or
first-GTM-hire sales motion; outbound + direct mail; no enterprise ABM platform installed
(6sense/Demandbase absent = greenfield).

**Priority signals:** recent seed/A/B funding (budget + growth pressure) · hiring for founding AE, SDR,
growth, demand-gen or GTM roles · outbound tooling in the stack · founder/company content about
outbound, personalisation or ABM pain · a named fragmented target vertical · direct-mail or
field-marketing usage · small marketing team (0–3).

**Account priority order:** sells into a fragmented vertical (their need for account research at scale is
*structural*) > funded within ~18 months > actively hiring GTM > outbound stack present > founder-led
sales visible.

**Buying-committee personas for Clue:** CEO / co-founder = **economic buyer** · Head of Growth /
Marketing / founding GTM lead = **champion** · sales lead / first AE = **user / influencer** ·
technical co-founder or CTO = **technical evaluator / blocker** (data + integrations).

**Exclusions applied:** Insight Health and any Clue-affiliated entity; companies >1,000 employees; pure
consumer companies. *(Insight Health is the archetype the ICP was written from — it was excluded from
research, per the brief.)*

---

## 1. Discovery — candidates and why Lassie won

Three Exa searches (`type: auto`, 10 results each, $0.007 each) returned 30 candidate pages. The
shortlist below is every distinct company found, scored against the account-priority order above.

| # | Company | Vertical (fragmented?) | Funding | GTM hiring seen | Fit rationale | Verdict |
|---|---|---|---|---|---|---|
| 1 | **Lassie** (lassie.ai) | Dental / doctors' offices — **~160,000 US dental practices** | **$35M Series A, a16z, Jun-2026** ($47M total) | **4 GTM reqs** (AE, GTM Associate, Head of Marketing, Product Marketer) | Maximally fragmented vertical; funded 3 months ago; *sales headcount 0* with an AE + GTM Associate open; founder-led selling documented in detail; the GTM Associate req literally describes Clue's product as a human job | **PICKED** |
| 2 | Probook | Home services | $34M Series A (a16z) + $6M seed (Sequoia), Jun-2026 | 1 (Enterprise AE) | Very strong fragmented vertical and fresh capital, but only one GTM req surfaced and an *enterprise* motion (fewer, larger accounts) weakens the research-at-scale case | Runner-up |
| 3 | Datatruck | Long-haul trucking | $12M Series A, Jan-2026 | none surfaced | Good vertical + stage, no GTM hiring signal in the corpus | Hold |
| 4 | SwiftSku | Independent convenience stores (85% independently owned) | YC-backed, early | 2 (Founding Head of Growth, Founding Head of Marketing) | Excellent fragmentation and founding-GTM hiring, but earliest stage → smallest budget and thinnest web footprint | Hold |
| 5 | Twin A1 | Legal | $20M seed, Aug-2026 | none surfaced | Right vertical/stage, no GTM signal | Hold |
| 6 | Freight Hero | Freight brokerage | $5M seed, Jul-2026 | none surfaced | Small round; services-led model dilutes the software-ABM fit | Hold |
| 7 | Annie | Dental practices | $4M seed, Nov-2025 | none surfaced | Right vertical, small round, Utah, thin footprint | Hold |
| 8 | Hemut (YC X25) | Trucking back office | $1.8M seed, 2025 | none surfaced (team 4→20) | Too early; budget unlikely | Pass |
| 9 | PatientDesk AI (YC W26) | Dental front desks | $1M pre-seed, Feb-2026 | none surfaced | Too early | Pass |
| 10 | Linda AI | Dental practices | €2.6M, Feb-2026 | none surfaced | **EU-based** — ICP says US; also GDPR-heavier | Pass |
| 11 | Crosby / Hyperscale / Asendia / Handly / Flamio | mixed | unknown | founding AE/GTM reqs only | Surfaced via job boards only; no company-level evidence in corpus | Pass |

**Why Lassie, in the ICP's own priority order:**

1. **Fragmented vertical (structural need).** *"Across roughly 160,000 dental practices in the U.S., this work is increasingly hard to staff and expensive to get wrong."* — https://a16z.com/announcement/investing-in-lassie/ . 160k addressable accounts is a market you cannot sell into without account research at scale.
2. **Funded within 18 months.** $35M Series A announced **3 June 2026** — under three months before this run.
3. **Actively hiring GTM.** **16 open roles**, four of them go-to-market. Apollo's own departmental head count says **sales = 0**.
4. **Outbound stack present — but *greenfield for ABM*.** Salesforce, Hightouch, LinkedIn Ads, Zendesk and Snowflake are present; **no 6sense, no Demandbase, no Clay, no Outreach, no Apollo.io** in 60 detected technologies.
5. **Founder-led sales visible and documented.** *"Lassie has spread, one dentist Invisalign study group at a time, to work with more than 700 practices."* — https://www.upstartsmedia.com/p/toothy-ai-lassie-raises-35m

**Disqualifier check:** 41 employees (<1,000 ✓), B2B (✓), not Insight Health or Clue-affiliated (✓), US/San Francisco (✓).

**A name-collision trap this account carries (and why it matters):** "Lassie" is also a Swedish pet-insurance
company (lassie.co) and the fictional collie. The research charter excluded them explicitly, and the deep
report confirms it did: *"Excluded same-name entities: (1) Lassie pet-insurance companies at lassie.co/lassie.se … (2) Lassie the fictional collie…"*.
**Apollo did not exclude them** — see §3, where the pet-insurance company's staff appear inside Lassie's Apollo org record.

---

## 2. The account: Lassie — a human view over the claim rows

> Every fact below is a row in `claims.json` with its own `source_url` and, where quoted, its own
> `evidence_span`. This section is the readable rendering; the claim rows are the truth.

### 2.1 Identity, and the entity disambiguation

Lassie is a San Francisco AI company building autonomous administrative systems for independent
healthcare practices, starting with dental.

- **Legal/operating name in the funding release:** *"SAN FRANCISCO, Calif.--(BUSINESS WIRE)-- Lassie, the company building autonomous systems to run small businesses, announced it has raised $35 million in Series A financing, bringing its total capital raised to $47 million."* — https://www.businesswire.com/news/home/20260603909717/en/Lassie-Raises-%2435M-Led-by-Andreessen-Horowitz-to-Build-AI-for-Small-Businesses-to-Run-Themselves
- **Positioning:** *"Lassie — AI That Runs the Doctor's Office"* — https://www.lassie.ai/
- **Domain:** `lassie.ai` (Apollo `primary_domain`), marketing site also resolves at `getlassie.com`.
- **LinkedIn:** http://www.linkedin.com/company/lassie (Apollo, tier 1)
- **HQ:** San Francisco, California, United States (Apollo `raw_address`)
- **Company phone:** +1 650-405-0509 (Apollo, tier 1)
- **Founding year:** the deep report returned **NOT FOUND** from public pages. Apollo's `founded_year` is also `null`. Apollo's employment history for the CEO starts **March 2020**, which is a tenure date, not a confirmed incorporation date. *Left unresolved rather than guessed.*
- **Excluded entities:** Lassie pet insurance (lassie.co / lassie.se), the fictional collie, all veterinary/pet "Lassie" results.

### 2.2 Product and target vertical

- **What it does:** *"Then they spent years building the infrastructure and integrations required for agents to operate directly within a practice's workflow: reading insurance claims, reconciling payments, posting to the ledger, and flagging claims that need action. Lassie is not a copilot that creates more work for the practice to review. It does the work."* — https://a16z.com/announcement/investing-in-lassie/
- **Autonomy claim:** *"Lassie works autonomously, around the clock, reading insurance claims, reconciling payments, handling denials and appeals."* — https://www.lassie.ai/company
- **Beachhead vertical:** *"Lassie is building AI that runs small businesses, starting with dental practices."* — https://a16z.com/announcement/investing-in-lassie/
- **Integrations (the practice-management systems):** *"We automate EOB posting and payment matching across Dentrix, Eaglesoft, and Open Dental, without human intervention."* — https://www.lassie.ai/blog/ai-dental-admin-support
- **Pricing model:** *"Lassie sells into independent practices on a usage- and workflow-based pricing model rather than a per-seat subscription."* — https://sacra.com/c/lassie/ ; corroborated: *"The company is HIPAA-compliant and operates on a performance-based pricing model."* — https://inforcapital.com/companies/lassie/ . **Published price points: NOT FOUND.**
- **Onboarding friction (useful for messaging):** *"Offices already receiving EFTs can typically go live in one to two weeks, while practices still using paper checks may take up to eight weeks to reach full auto-posting."* — https://sacra.com/c/lassie/

### 2.3 Traction

- *"Lassie already works with more than 700 practices across 49 states, generates more than $10 million in annualized revenue, and provides practices with 250,000 hours of labor a year."* — https://a16z.com/announcement/investing-in-lassie/
- Updated figure, 24 Aug 2026: scaled to *"800+ small businesses across 49 states"* — https://a16zbuild.substack.com/p/how-steijn-pelle-built-lassie-to
- Per-customer value: *"For bigger ones like Kwon's, Lassie's autonomous system can save more than 100 hours per month in admin work; on average, Lassie saves them at least 30 hours, nearly the cost of a full-time staffer."* — https://www.upstartsmedia.com/p/toothy-ai-lassie-raises-35m
- **Named customers:** only "Dr. Kwon", and that is a founder-origin story rather than a case study. Logos, ACV, NRR, retention: **NOT FOUND**.
- **Honest caveat carried from the source:** *"No independent customer reviews or third-party validation found — reported metrics (700+ practices, >$10M ARR) are unverified in public sources."* — https://algoturk.com/brief/lassie-ai

### 2.4 Funding

| Round | Date | Amount | Lead | Participants | Source |
|---|---|---|---|---|---|
| Series A | **2026-06-01/03** | **$35,000,000** | Andreessen Horowitz | Night Capital, Rahul Vohra (Superhuman), Zach Perret (Plaid), Taavet Hinrikus (Wise), Gokul Rajaram, Brian Balfour (Reforge) | Apollo `funding_events[0]` + BusinessWire |
| Pre-Series-A (seed) | not stated | **$12,000,000 implied** ($47M total − $35M A) | not stated | SV Angel, Homebrew, Go Global Ventures | https://sacra.com/c/lassie/ |

- Verbatim: *"The round was led by Andreessen Horowitz (a16z) with support from Night Capital, Rahul Vohra, founder and former CEO of Superhuman; Zach Perret, co-founder and CEO of Plaid; Taavet Hinrikus, co-founder and former CEO of Wise; Gokul Rajaram; and Brian Balfour, co-founder and CEO of Reforge."* — BusinessWire (above)
- Verbatim: *"Before the Series A, Lassie raised earlier rounds backed by SV Angel, Homebrew, and Go Global Ventures, bringing total disclosed funding to $47 million."* — https://sacra.com/c/lassie/
- **The seed round's exact date, stage label and amount remain NOT FOUND.** The $12M is arithmetic from two published totals, and is recorded as such — not as a sourced round.

### 2.5 Team and GTM composition — *the core of the pitch*

Apollo (tier 1, `api`), org record `63174e0badba1b00014e22fa`:

| Metric | Value |
|---|---|
| `estimated_num_employees` | **41** |
| `departmental_head_count.engineering` | 12 |
| `departmental_head_count.marketing` | **1** |
| `departmental_head_count.sales` | **0** |
| `departmental_head_count.operations` | 2 |
| headcount growth, 6 / 12 / 24 months | +19.0% / +38.9% / **+525%** |

Corroborated from the open web: *"Conferences, practitioner dinners, and peer referrals remain key
acquisition channels, and the company reportedly reached hundreds of customers before making its first
dedicated sales hire."* — https://sacra.com/c/lassie/

And from the CEO himself: *"Common wisdom: find someone after 5-10 customers. It took us a lot longer to
see a scalable, repeatable motion. That was the trigger to aggressively expand GTM."* —
https://founderledsalesstories.substack.com/p/lassie-from-flying-to-100-dental

> **⚠ Two Apollo surfaces disagree with each other.** `departmental_head_count.sales = 0`, yet Apollo's own
> people index returns **five GTM people** at Lassie (Founding GTM ×2, Founding GTM/Ops, GTM, Performance
> Marketing Designer). The department roll-up is stale or mis-classified. Treated here as: *a GTM team of
> ~5 exists and is brand new; the roll-up has not caught up.* Neither Apollo figure was promoted to truth
> without the web corroboration above.

### 2.6 Go-to-market motion, and the tooling

**How they acquire customers today — referrals, events and founder-led selling:**

- *"Growth has come largely through referrals and inbound demand – a sign that customers are not just buying the product, but telling other practice owners about it."* — https://a16z.com/announcement/investing-in-lassie/
- *"Lassie has spread, one dentist Invisalign study group at a time, to work with more than 700 practices."* — https://www.upstartsmedia.com/p/toothy-ai-lassie-raises-35m
- *"Before writing a single line of code, they spent months talking to dentists, primary care doctors, and healthcare finance teams."* — https://a16z.com/announcement/investing-in-lassie/
- *"…they worked inside Dr. Kwon's office, processing payments by hand to understand the workflow from the inside."* — https://a16z.com/announcement/investing-in-lassie/

**What they are building next — outbound, and they are hiring for it right now:**

- *"As a GTM Associate at Lassie, you'll create the first spark of demand. You'll identify promising doctors' offices, run thoughtful outreach you'd want to receive yourself, schedule demos, and help us learn which messages actually land with small businesses."* — https://jobs.ashbyhq.com/lassie/d7f41c77-908c-4206-852b-a99a17f9a867
- *"Build lists of promising doctors' offices and run thoughtful outreach across email, phone, social, events, and more"* — same posting
- *"Experiment with messages, segments, and channels to learn where demand is strongest."* — same posting
- *"As Lassie's Head of Marketing, you'll be responsible for turning customer love into compounding demand… find the repeatable, scalable channels and messages that help Lassie reach far more doctors' offices efficiently."* — https://jobs.ashbyhq.com/lassie/297fd72f-fe6d-40f1-8931-89085e66fa2f

**Technographics (Apollo, tier 1 — 60 technologies detected).** GTM-relevant subset:

| Category | Detected | Clue read |
|---|---|---|
| CRM | **Salesforce** | a system of record exists to write back to |
| Data activation | **Hightouch** | reverse-ETL from Snowflake → they already think in "sync the warehouse into GTM tools" |
| Warehouse | **Snowflake** | account data lives somewhere queryable |
| Paid | **LinkedIn Ads**, Facebook Pixel, Google Tag Manager | already buying audience |
| Support | Zendesk | — |
| AI | **OpenAI, Anthropic Claude**, Cursor | AI-native buyer; will not need convincing that agents work |
| **Absent** | **no 6sense, no Demandbase, no Clay, no Outreach, no Apollo.io, no Instantly** | **greenfield: no ABM platform installed, no outbound tool installed** |

**Direct mail / field marketing:** conferences and *practitioner dinners* are confirmed acquisition
channels (Sacra, above). Explicit **direct mail: NOT FOUND**.

### 2.7 Hiring signals — 16 open roles, four of them GTM

Source: https://jobs.ashbyhq.com/lassie — *"# Open Positions (16)"*. All San Francisco, all full time.

| Dept | Roles |
|---|---|
| **Sales** | **Account Executive**, **GTM Associate** |
| **Marketing** | **Head of Marketing**, **Product Marketer** |
| Customer Success | Customer Success Manager |
| Operations | Business Operations, Customer Operations |
| Engineering | Applied AI, Growth, Platform, Product, Security (5) |
| Design | Design Engineer, Product Designer |
| Finance | Head of Finance |
| People | Founding Recruiter |

**Salary bands: NOT FOUND** — none of the five Ashby postings fetched publishes one. **Posting dates: NOT FOUND**
(Ashby does not render them in the fetched HTML), so "currently open" means "live as of 2026-08-26", not a
claimed posting date.

Two quotes that matter more than the list:

- Head of Finance req: *"Lead strategic finance work beyond the core: pricing structure, sales commission design, rev ops foundations, and more."* — https://jobs.ashbyhq.com/lassie/3b76ef54-2d0f-4c64-a16a-4d76c3899afd → **they are building sales comp and RevOps from zero right now.**
- Head of Marketing req: *"You'll partner directly with Lassie's CEO, who scaled Robinhood's referral program as its first growth lead."* — https://jobs.ashbyhq.com/lassie/297fd72f-fe6d-40f1-8931-89085e66fa2f → **the CEO is the growth owner until this role is filled.**

### 2.8 Operational pain and strategic moves

- **Market pain they sell against:** *"Across roughly 160,000 dental practices in the U.S., this work is increasingly hard to staff and expensive to get wrong."* — https://a16z.com/announcement/investing-in-lassie/
- **Their own pain (the one Clue sells against):** they must convert a referral/inbound motion into a repeatable outbound engine against a 160,000-account long tail, with a sales team they have not hired yet. Evidence is the four GTM reqs plus *"turning customer love into compounding demand"* and *"find the repeatable, scalable channels and messages that help Lassie reach far more doctors' offices efficiently"* (Head of Marketing req).
- **Strategic move — vertical expansion:** *"But the larger insight is not dental-specific. Every small business is still held together by human labor."* — https://a16z.com/announcement/investing-in-lassie/ ; and *"Eventually, the ambition is to move beyond dental practices to other doctor offices, Pelle says."* — https://www.upstartsmedia.com/p/toothy-ai-lassie-raises-35m
- **Publicly aired frustrations / negative sentiment / attrition signals: NOT FOUND** (no Glassdoor or employee-review content in the corpus).

### 2.9 Culture and resonance

- *"We are a team of ambitious builders and operators, united in our shared optimism about the future. We value craft, rigor of thought, and direct communication."* — https://www.lassie.ai/company
- *"We're pushing the boundary on autonomous systems, and believe small businesses will soon run themselves."* — https://www.lassie.ai/company
- Recurring in every job post: *"Our team is small, flat, and ambitious. We value craft, intellectual rigor, and direct communication."*
- Product philosophy, stated as a contrast: *"Lassie is not a copilot that creates more work for the practice to review. It does the work."* — https://a16z.com/announcement/investing-in-lassie/

**Resonance read for outreach:** direct, quantitative, craft-obsessed, allergic to fluff. A generic
personalised-at-scale email is exactly the thing this buyer will notice and dislike — which is itself the
argument for Clue's depth.

### 2.10 Timing signals (newest first)

| Date | Event | Source |
|---|---|---|
| 2026-08-24 | a16z Build profile; scaled to **800+ small businesses across 49 states** | https://a16zbuild.substack.com/p/how-steijn-pelle-built-lassie-to |
| 2026-08-26 | **16 open roles live**, incl. AE + GTM Associate + Head of Marketing + Product Marketer | https://jobs.ashbyhq.com/lassie |
| 2026-07-10 | Blog: *"We built Lassie for the practice that does not want to hire another biller or hand its revenue cycle to an agency."* | https://www.lassie.ai/blog/independent-dentist-insurance-ar-staffing |
| 2026-07-03 | Blog: dental payment-posting guide; Dentrix/Eaglesoft/Open Dental automation | https://www.lassie.ai/blog/dental-payment-posting-guide |
| **2026-06-03** | **$35M Series A led by a16z announced; $47M total** | BusinessWire + a16z |
| 2025-08-22 | Podcast: *"From Flying to 100 Dental Offices to $100M ARR Via Product Obsession"* | https://founderledsalesstories.substack.com/p/lassie-from-flying-to-100-dental |
| 2025-07-01 | CEO post: *"Opening up a new role soon: another go-to-market hire. You'll work closely with me and early GTM team to build a $100m ARR engine over the next 12 months."* | https://www.linkedin.com/posts/steijn_after-helping-robinhood-and-coinbase-grow-activity-7345814439805243392-wFvO |

### 2.11 Why this is a Clue account, in one paragraph

Lassie has just raised $35M to sell into **160,000 fragmented dental practices**, has **zero
dedicated salespeople** on Apollo's department roll-up and a five-person GTM team that did not exist
two years ago, is hiring an **Account Executive, a GTM Associate, a Head of Marketing and a Product
Marketer simultaneously**, and has **no ABM or outbound platform installed**. Its GTM Associate job
description — *"Build lists of promising doctors' offices and run thoughtful outreach across email,
phone, social, events, and more"* — is a line-item description of the work Clue automates. Its CEO is a
career growth operator (Robinhood's first growth PM) who has publicly committed to building *"a $100m
ARR engine over the next 12 months."* The buying window is now, the budget exists, the incumbent is
nobody, and the champion seat is literally vacant and being recruited for.

---

## 3. The buying committee

Sources: Apollo `mixed_people/api_search` (0 credits, **degraded** — obfuscated last names, no LinkedIn
URLs; a shortlist, never claim-store truth) unioned across `organization_ids` **and** `q_organization_domains_list`,
plus the open-web deep report. "Confirmed" = identity tied to Lassie by a primary source or a paid
`people/match`.

| # | Name | Title | Clue persona | Source | Confirmed? | Email |
|---|---|---|---|---|---|---|
| 1 | **Steijn Pelle** | CEO and Co-Founder | **economic buyer** (and de-facto champion until the CMO is hired) | apollo + web | ✅ `people/match` (1 credit) + steijn.com + a16z + LinkedIn | **steijn@lassie.ai** (`verified`) |
| 2 | **Max Shore** | Founding GTM | **champion / user** | apollo + web | ✅ `people/match` (1 credit) | **max@golassie.com** (`verified`) |
| 3 | Sam Mi\*\*\*r | Founding GTM @ Lassie | user | apollo only | ❌ obfuscated surname; not matched | `has_email: True`, not revealed |
| 4 | Jamie Ai\*\*\*a | Founding GTM/Ops | user | apollo only | ❌ | `has_email: True`, not revealed |
| 5 | Connor Os\*\*\*n | GTM | user | apollo only | ❌ | `has_email: True`, not revealed |
| 6 | Kenley Ti\*\*\*r | Performance Marketing Designer | influencer (marketing) | apollo only | ❌ | `has_email: True`, not revealed |
| 7 | Seth Ha\*\*\*n | Founding Bizops | influencer (RevOps) | apollo only | ❌ | `has_email: True`, not revealed |
| 8 | Robert Lee | Founding Implementation and Customer Ops | influencer (CS) | apollo only | ❌ surname present but unverified | `has_email: True`, not revealed |
| 9 | **Frédéric Renken** | Co-founder (technical; ex-Superhuman, ex-Uber product) | **technical evaluator / blocker** | **web only** | ✅ by a16z: *"Co-founders Steijn Pelle and Frédéric Renken"* | **none — absent from Apollo entirely** |
| 10 | *(vacant)* | **Head of Marketing** | **the champion seat — being recruited now** | web (job req) | n/a | n/a |

**Persona mapping notes, and one schema problem:**

- Steijn Pelle is the **economic buyer** at a 41-person company, *and* currently the growth owner — the
  Head of Marketing req says the hire *"will partner directly with Lassie's CEO, who scaled Robinhood's
  referral program as its first growth lead."* Single-threaded deal, fast.
- The **champion seat is open**. That is unusual and valuable: Clue can be the thing the new Head of
  Marketing inherits, or the thing that helps them hit month-one numbers.
- ⚠ **The platform's `Persona` enum cannot express this committee.** `clue_core.enums.Persona` has exactly
  four values — `champion`, `economic_buyer`, `technical_evaluator`, `blocker`. There is **no `user` /
  `influencer` persona**, yet the brief's own Clue committee names "sales lead / first AE" as the *user*.
  Five of the ten members above (rows 3–8) have no correct enum value. See PROPOSED FIELDS §7.
- ⚠ **Apollo's org record is contaminated by the same-name company.** The people search returned
  **"Daisy We\*\*\*r — Hund Vårdare"** (Swedish: "dog carer") and **"Damstra Re\*\*\*e — Teamleider bij Lassie"**
  (Dutch) under the same `lassie.ai` query. These are the **Swedish pet-insurance Lassie's** staff. They
  were excluded by hand. An automated pipeline that trusted Apollo's org grouping would have put a
  Swedish dog-insurance employee in a dental-AI buying committee.
- ⚠ **The union mattered.** `organization_ids` search returned **2 people**; the domain search returned **22**.
  The Apollo contract's "search both, union" rule is load-bearing, exactly as documented.
- ⚠ **Apollo has no record of the technical co-founder.** Frédéric Renken — named by a16z as co-founder —
  is absent from all 22 Apollo people. The technical-evaluator persona is **web-only** for this account.

---

## 4. The enriched primary contact

**Steijn Pelle** — `POST /people/match` (1 credit), raw response `raw/apollo_match_primary.json`.

| Field | Value | Source |
|---|---|---|
| Name | Steijn Pelle | Apollo `person.name` |
| Title | CEO and Co-Founder | Apollo `person.title` |
| **Work email** | **steijn@lassie.ai** | Apollo `person.email` |
| **Email status** | **`verified`** | Apollo `person.email_status` |
| Seniority | `founder` | Apollo |
| Departments | `["c_suite"]` | Apollo |
| LinkedIn | http://www.linkedin.com/in/steijn | Apollo |
| Location | San Francisco, California, United States | Apollo |
| Direct phone | **not retrieved** — `reveal_phone_number` requires an HTTPS webhook we do not have (Apollo contract §3.4). 8 extra credits if a mobile returns. | — |
| Personal emails | not requested (`reveal_personal_emails: false`) | — |

**Secondary — Max Shore**, Founding GTM: **max@golassie.com** (`verified`), http://www.linkedin.com/in/max-shore,
Founding GTM since 2024-06; prior: Lydian, Fig, WithMe Health (×2), Deloitte Consulting (×2), IBM,
3 Day Startup, Harvard Business School.

> ⚠ **Two different corporate email domains.** The CEO is `@lassie.ai`; the Founding GTM is `@golassie.com`.
> Both are `verified`. A naive "firstname@primary_domain" pattern guess would have produced the wrong
> address for Max Shore. This is a concrete argument for paying for verified emails rather than
> pattern-guessing, and a concrete deliverability trap to record on the account.

---

## 5. Steijn Pelle — contact deep research

One Exa `deep-reasoning` call, $0.030, 22,680 characters. Compliance charter refused special-category
data by construction (health, religion, politics, sexual orientation, ethnicity, union membership,
family/bereavement, home address, personal phone/email) — the report's own words: *"I also excluded any
source material containing health/medical information about Pelle personally, religion, political views,
race or ethnicity, sexual orientation, family or children, bereavement/personal tragedy, home address,
personal phone, and personal/private email."*

### 5.1 Identity confirmation

- *"CEO & Co-Founder at Lassie. Building AI that runs small businesses."* — https://steijn.com/ [primary]
- *"CEO and Co-Founder - Lassie (Current)"* — https://www.linkedin.com/in/steijn [primary]
- *"Co-founders Steijn Pelle and Frédéric Renken…"* — https://a16z.com/announcement/investing-in-lassie/
- *"Today, we're introducing Lassie and $47M in funding led by a16z."* — https://www.linkedin.com/posts/steijn_today-were-introducing-lassie-and-47m-activity-7467951103591038976-gfAQ
- **Confidence: HIGH.** Six independent sources converge on name, role, geography, prior employers and founder history. `identity_binding: strong` on every facet claim.

### 5.2 Career

| Dates | Role | Company | Source |
|---|---|---|---|
| 2020-03 → present | CEO & Co-Founder | **Lassie** | Apollo + LinkedIn |
| 2018-12 → 2019-11 | Product Manager (growth) | **Robinhood** | Apollo + LinkedIn |
| 2018-01 → 2018-07 | Product Lead, Growth | **Coinbase** | Apollo + LinkedIn |
| 2016-02 → 2017-12 | Product Manager, Growth | **HealthTap** | Apollo + LinkedIn |
| 2014-04 → 2016-02 | COO & Co-Founder | **FITMO** | Apollo + LinkedIn + siliconcanals |
| 2011-06 → 2014-04 | CEO & Co-Founder | **Pelliano** | Apollo + LinkedIn |
| 2007-01 → 2011-05 | CEO & Co-Founder | **ELF Entertainment** | Apollo + LinkedIn |

The growth track record, in his own words:
- *"Hired as the first product manager focused on user growth. Helped to accelerate Robinhood's user base from 6 million to 10 million users."* — https://www.linkedin.com/in/steijn
- *"I've joined Coinbase as a product lead to scale the company's growth team!"* — https://medium.com/@steijnpelle/im-joining-coinbase-4c10b34bf161
- *"We shipped 70+ experiments (SEO, paid, NUX) that increased annual new user activations by 275%."* (HealthTap) — https://www.linkedin.com/in/steijn
- *"After helping Robinhood and Coinbase grow to their first hundreds of millions in annual revenue…"* — https://www.linkedin.com/posts/steijn_after-helping-robinhood-and-coinbase-grow-activity-7345814439805243392-wFvO

**This is a fourth-time founder who is a professional growth operator.** He will evaluate Clue as a
growth system, not as a tool.

### 5.3 Education

- **Rotterdam School of Management, Erasmus University** — BSc Business Administration, 2007–2011. https://www.linkedin.com/in/steijn
- **Reforge — Product Growth Program**, 2016. *(Note: Brian Balfour, Reforge's founder, is on Lassie's cap table.)*
- University of Cambridge / St. Petersburg State University appear on one aggregator but were **rejected as insufficiently sourced** — recorded NOT FOUND rather than promoted.

### 5.4 Public writing, talks and podcasts

| Date | Title | Venue | URL |
|---|---|---|---|
| 2026-08-24 | How Steijn Pelle built Lassie to help small businesses run themselves using AI | a16z Build | https://a16zbuild.substack.com/p/how-steijn-pelle-built-lassie-to |
| 2026-06-03 | Lassie + $47M announcement post | LinkedIn | https://www.linkedin.com/posts/steijn_today-were-introducing-lassie-and-47m-activity-7467951103591038976-gfAQ |
| 2026-02-20 | Steijn Pelle on Dental AI Automation (ep. 342) | MDIB Podcast | https://mommydibs.com/steijn-pelle-lassie-ai/ |
| 2025-08-22 | From Flying to 100 Dental Offices to $100M ARR Via Product Obsession | Founder-Led Sales Stories | https://founderledsalesstories.substack.com/p/lassie-from-flying-to-100-dental |
| 2025-08-19 | Getting Paid in the Age of AI: Back Office Automation from Silicon Valley Pt. 2 | Dentalpreneur Podcast | https://www.truedentalsuccess.com/the-dentalpreneur-podcast/2315-getting-paid-in-the-age-of-ai-back-office-automation-from-silicon-valley-pt-2/ |
| 2025-07-01 | GTM hiring post ("$100m ARR engine") | LinkedIn | https://www.linkedin.com/posts/steijn_after-helping-robinhood-and-coinbase-grow-activity-7345814439805243392-wFvO |
| 2022-05-19 | "Come work with me! You'll be teammate #6 and the founding business hire" | LinkedIn | https://www.linkedin.com/posts/steijn_founding-business-hire-activity-6932862496571617282-GskC |
| 2018-04-09 | I'm joining Coinbase | Medium | https://medium.com/@steijnpelle/im-joining-coinbase-4c10b34bf161 |

### 5.5 How he thinks and writes

- **Quantitative to a fault.** He writes in numbers: *"6 million to 10 million users"*, *"70+ experiments"*, *"275%"*, *"8 person growth team"*, *"$100m ARR engine"*.
- **Growth as a system, not a channel:** *"We created growth model that identifies northstar metric, acquisition loops and retention loops."* — https://www.linkedin.com/in/steijn
- **Evidence before scale:** *"It took us a lot longer to see a scalable, repeatable motion. That was the trigger to aggressively expand GTM."* — https://founderledsalesstories.substack.com/p/lassie-from-flying-to-100-dental
- **Direct, recruiting-forward prose:** *"Come work with me!"*, asking for *"a brilliant generalist"* with *"masterful analytical chops"*.
- Company values he repeats: *"We value craft, rigor of thought, and direct communication."*

### 5.6 Non-sensitive personal hooks

| Hook | Evidence | Source | Use class |
|---|---|---|---|
| Dutch origin | *"Originally from the Netherlands."* | https://mommydibs.com/steijn-pelle-lassie-ai/ | personal-public-non-sensitive |
| Rotterdam / Amsterdam early career | Pelliano in Rotterdam; FITMO in Amsterdam Area | https://www.linkedin.com/in/steijn | professional-public |
| **Former professional runner** | *"Awarded Young Entrepreneur of the Year. Former Professional Runner."* | https://www.f6s.com/company/fitmoteam?flow=seePage | personal-public-non-sensitive |
| Young Entrepreneur of the Year | same quote; **no awarding body or year found** — recorded with that caveat | https://www.f6s.com/company/fitmoteam?flow=seePage | professional-public |
| Alma mater: Erasmus/RSM | BSc Business Administration | https://www.linkedin.com/in/steijn | personal-public-non-sensitive |

**Explicitly NOT FOUND** (and not invented): languages, sports teams, hobbies beyond running, side
projects, non-political community involvement. **Explicitly excluded as special-category:** anything
family-related. A "various marathons in San Francisco" claim was found on one aggregator and
**rejected as unsourced**.

### 5.7 Suggested openers — each grounded in a specific hook

1. *"Your description of Lassie as 'AI that runs small businesses, starting with doctors' offices' stood out — especially connecting it to working inside Dr. Kwon's office and processing payments by hand."*
   → hooks: his 2026-06-03 LinkedIn post + a16z announcement.
2. *"I noticed your point that it took longer than the usual five-to-ten customers to find a scalable, repeatable motion before expanding GTM."*
   → hook: Founder-Led Sales Stories interview.
3. *"The through-line from Robinhood referrals and onboarding to Lassie's customer-led growth engine is a genuinely unusual founder profile."*
   → hooks: LinkedIn career description + the same interview.
4. *"Your July 2025 post framed the next GTM role around building a '$100m ARR engine' while giving someone room to grow into an operator."*
   → hook: 2025-07-01 LinkedIn post.
5. *"The specificity in your growth background — '70+ experiments' and a 275% lift in annual new-user activations at HealthTap — is the reason this note is about mechanics, not vision."*
   → hook: LinkedIn profile.

*Every opener names its hook and URL. None references anything not found above. No flattery is unbacked
by a quote.*

---

## 6. Claims summary

**52 claim rows** in `claims.json`. Full breakdown in `claims_summary.json`.

| Cut | Value |
|---|---|
| Total rows | **52** |
| By `source_key` | `apollo` **19** · `exa_research` **33** |
| By tier | tier 1 (`api`) **19** · tier 4 (`llm_synthesis`) **33** |
| By entity | `account:lassie` **27** · `contact:steijn-pelle` **21** · `contact:max-shore` **4** |
| Distinct `field_key`s used | **30** |
| **Rows using an already-registered field key** | **52 / 52 (100%)** |
| **Rows requiring a new field** | **0** (unmappable facts went to PROPOSED FIELDS instead) |
| **Schema validation failures** | **0 / 52** |
| Rows contributed by `openai/gpt-5-mini@minimal` | 16 |
| Rows contributed by `z-ai/glm-4.7` | 17 |
| Rows contributed by the deterministic Apollo adapter | 19 |

**Counts by field key** (existing registered fields, all of them):

| field_key | n | | field_key | n |
|---|---|---|---|---|
| `core.account_name` | 1 | | `contact.current_title` | 4 |
| `core.primary_domain` | 1 | | `contact.current_location` | 3 |
| `core.company_linkedin_url` | 2 | | `contact.job_level` | 1 |
| `core.industry` | 3 | | `contact.persona` | 2 |
| `core.company_about` | 3 | | `contact.role_on_committee` | 1 |
| `core.employee_count` | 1 | | `core.work_email` | 2 |
| `core.hq_location` | 3 | | `contact.facet.career_history` | 3 |
| `core.company_phone` | 1 | | `contact.facet.alma_mater` | 1 |
| `core.annual_revenue` | 1 | | `contact.facet.publications` | 2 |
| `core.primary_tech_stack` | 2 | | `contact.facet.public_appearances` | 2 |
| `account.recent_funding` | 2 | | `contact.facet.recent_post` | 1 |
| `account.total_funding` | 2 | | `contact.facet.communication_style` | 1 |
| `account.operational_pain` | 1 | | `contact.facet.hobby` | 1 |
| `account.strategic_moves` | 2 | | `contact.facet.recent_award` | 1 |
| `account.hiring_velocity_eng` | 1 | | | |
| `account.resonance.culture` | 1 | | | |

**Stamping applied** (per `ARV2-schema-impact-audit.md` §3, verbatim):

- Apollo rows → `source_key=apollo`, `tier=1`, `extraction_method=api`, born `UNVERIFIED`, `reuse_scope=tenant_private` + `workspace_id`. **Built deterministically in Python, never by a model** — the `claim_tier4_iff_synthesis` CHECK means anything a model authors is tier 4 by construction, so a model may not author a tier-1 claim.
- Exa rows → `source_key=exa_research` (**not** `exa_deep`, which would trip `claim_exa_deep_lineage_required`), `tier=4`, `extraction_method=llm_synthesis`, born `UNVERIFIED`, `tenant_private` + `workspace_id`.
- Every `contact.*` row carries `identity_binding=strong` (identity confirmed against primary sources in §5.1).
- Every `contact.facet.*` row carries a `use_class` (`professional-public` or `personal-public-non-sensitive`). **No `sensitive` row was written** — none was collected.
- Every row carries a `source_url`; quoted rows carry an `evidence_span`.

### 6.1 Defects the structuring lane produced (found, not hidden)

The schema validator passed 52/52. These are the errors a **value_schema cannot catch** — hand-audited:

| Row | Emitted | Problem | What would catch it in production |
|---|---|---|---|
| `core.company_linkedin_url` (gpt-5-mini@minimal) | `https://www.lassie.ai/company` | Not a LinkedIn URL. Valid as a *string*, wrong as a *value*. Apollo's tier-1 row has the correct one. | a tool-side URL/host format validator on url-shaped fields |
| `contact.persona = champion` for Steijn Pelle (gpt-5-mini@minimal) | `champion` | He is CEO/co-founder = `economic_buyer`. The cited `evidence_span` is an interview-process sentence from a job posting and entails no persona at all. **glm-4.7 got this right.** | the M9.3 faithfulness judge — the span does not entail the value |
| `core.employee_count = 23` (gpt-5-mini, *default* reasoning run) | `23` | The account report explicitly flagged 23 as an unreliable aggregator estimate; Apollo's tier-1 value is **41**. | merge tier precedence (tier-1 `apollo` beats tier-4 synthesis) — and it was **not** carried into the merged set |
| all 24 rows (glm-4.7) | key `value_` instead of `value_json`; `confidence: "high"` instead of a number | Systematic key drift on **every** row. | a strict tool JSON-schema + per-item refusal loop; mechanically repairable |
| 4 rows (glm-4.7) | `evidence_span` not a verbatim substring of the corpus | Paraphrased quotes. | the "evidence_span must be a substring" check the harness already runs |

**The important structural point:** three of five defect classes are caught by machinery the platform
**already specifies** (faithfulness judge, merge tier precedence, tool refusal loop). Only the
LinkedIn-URL type error needs something new (a format validator on url-shaped fields).

---

## 7. PROPOSED FIELDS

I checked the existing registry first. **These already exist and were used, so they are NOT proposed:**
`account.total_funding`, `account.recent_funding`, `account.hiring_velocity_eng`,
`core.primary_tech_stack`, `account.operational_pain`, `account.strategic_moves`,
`account.resonance.*`, `contact.facet.*`, `core.employee_count`, `core.annual_revenue`.

The Clue ICP nonetheless needs fields the healthcare pack has no analogue for. Each below carries a real
value found in this run, so none is speculative.

### 7.1 A new industry pack: `vertical_saas`

Modelled on `HEALTHCARE_PRACTICE` / `FRONTIER_AI` / `DATA_INFRA` in `icp/packs.py`. A `<pack>.*` field
**must** declare `reuse_scope` and `research_scope` (no safe default — enforced at registration).

| # | `field_key` | `value_type` | `value_schema` | `reuse_scope` / `research_scope` | Agent-facing description |
|---|---|---|---|---|---|
| 1 | `vertical_saas.target_vertical` | `object` | `{"type":"object","required":["vertical"],"properties":{"vertical":{"type":"string"},"fragmentation":{"type":"string","enum":["fragmented_smb","mid_market","enterprise","consumer"]},"addressable_accounts":{"type":"integer"},"basis":{"type":"string"}}}` | `public_footprint` / `project_neutral` | The industry this company SELLS INTO (not its own industry) and how fragmented that buyer base is. Fill from the company's own positioning or an investor announcement; `addressable_accounts` only when a source states a count. |
| 2 | `vertical_saas.gtm_motion` | `object` | `{"type":"object","required":["primary_motion"],"properties":{"primary_motion":{"type":"string","enum":["founder_led","inbound_referral","outbound","field_events","plg","channel_partner"]},"secondary_motions":{"type":"array","items":{"type":"string"}},"evidence":{"type":"string"}}}` | `tenant_private` / `project_neutral` | How this company acquires customers today. Fill only from explicit evidence (investor writeups, founder interviews, job descriptions) — never inferred from industry. |
| 3 | `vertical_saas.gtm_team_shape` | `object` | `{"type":"object","required":["as_of"],"properties":{"as_of":{"type":"string"},"sales_headcount":{"type":"integer"},"marketing_headcount":{"type":"integer"},"open_gtm_roles":{"type":"integer"},"first_sales_hire_made":{"type":"boolean"}}}` | `tenant_private` / `project_neutral` | Size and maturity of the revenue org: current sales/marketing headcount, open GTM reqs, and whether a first dedicated sales hire exists. This is the single strongest buying-window signal for an ABM product. |
| 4 | `vertical_saas.open_gtm_roles` | `list[object]` | `{"type":"array","items":{"type":"object","required":["title"],"properties":{"title":{"type":"string"},"department":{"type":"string"},"location":{"type":"string"},"url":{"type":"string"},"posted_at":{"type":"string"},"comp_band":{"type":"string"}}}}` | `public_footprint` / `project_neutral` | Every currently-open go-to-market role with its posting URL. Job posts are the highest-signal, most quotable, most perishable evidence of GTM intent. |
| 5 | `vertical_saas.gtm_stack` | `object` | `{"type":"object","required":["as_of"],"properties":{"as_of":{"type":"string"},"crm":{"type":"array","items":{"type":"string"}},"outbound":{"type":"array","items":{"type":"string"}},"abm":{"type":"array","items":{"type":"string"}},"paid":{"type":"array","items":{"type":"string"}},"absent":{"type":"array","items":{"type":"string"}}}}` | `tenant_private` / `project_neutral` | The GTM-relevant slice of the tech stack, **including an explicit `absent` list**. For an ABM seller the absence of 6sense/Demandbase/Clay/Outreach is the qualifying signal, and `core.primary_tech_stack` (a flat `list[str]`) cannot express absence. |
| 6 | `vertical_saas.funding_runway_signal` | `object` | `{"type":"object","required":["latest_round_date"],"properties":{"latest_round_date":{"type":"string"},"latest_round_stage":{"type":"string"},"months_since_round":{"type":"integer"},"stated_growth_target":{"type":"string"}}}` | `tenant_private` / `project_relative` | Recency of capital plus any publicly stated growth target. "Funded 3 months ago and publicly committed to a $100M ARR engine" is a different buyer from "funded 30 months ago". |

### 7.2 Canonical (`pack=None`) contributions

| # | `field_key` | `value_type` | `value_schema` | `reuse_scope` | Agent-facing description |
|---|---|---|---|---|---|
| 7 | `account.customer_count` | `object` | `{"type":"object","required":["count","as_of"],"properties":{"count":{"type":"integer"},"unit":{"type":"string"},"as_of":{"type":"string"},"claimed_by":{"type":"string","enum":["company","investor","third_party"]}}}` | `public_footprint` | Number of customers the company or its investors publicly claim, with an as-of date and **who claimed it**. Proposed by `openai/gpt-5-mini` as `account.practices_count`; generalised. Traction is quoted constantly in the dossier bar and has no home today. |
| 8 | `account.entity_disambiguation` | `object` | `{"type":"object","required":["excluded"],"properties":{"excluded":{"type":"array","items":{"type":"object","required":["name","reason"],"properties":{"name":{"type":"string"},"domain":{"type":"string"},"reason":{"type":"string"}}}},"confidence":{"type":"string","enum":["high","medium","low"]}}}` | `tenant_private` | The same-name entities this account was explicitly distinguished FROM, and why. Durable, auditable proof that target-lock happened. |
| 9 | `account.integration_ecosystem` | `list[str]` | `{"type":"array","items":{"type":"string"}}` | `public_footprint` | Third-party systems the account's own PRODUCT integrates with (Dentrix, Eaglesoft, Open Dental). Proposed by `z-ai/glm-4.7` as `account.ecosystem_integrations`. Distinct from `core.primary_tech_stack`, which is what they *run internally*; this is what they *connect to*, and it names their customer's stack. |

### 7.3 A schema change, not a new field: the `Persona` enum is too small

`clue_core.enums.Persona` has four members — `champion`, `economic_buyer`, `technical_evaluator`,
`blocker`. Clue's own stated committee has a fifth role: **the user / influencer** ("sales lead / first
AE"). In this run that left **five of ten** committee members (Founding GTM ×2, Founding GTM/Ops, GTM,
Performance Marketing Designer) with no correct value.

**Hypothesis.** Persona is the key for `(account, persona)` addressing — it decides who receives which
artifact. Forcing a day-to-day product user into `champion` corrupts that keying: the champion gets the
business-case mailer, the user gets the workflow mailer, and they are not the same person. At a
41-person company the user often *outnumbers* every other persona, and in a bottom-up AI-tooling sale
the user is frequently the entry point. Proposal: add `USER = "user"` (and consider
`INFLUENCER = "influencer"`) to `Persona`, with the matching DB enum value, the enum-parity test update,
and a migration. This is a **contract-delta on frozen `core`**, so it needs explicit ratification — it is
not something to slip in. Until then, `contact.class` (the free-string pack/workspace grouping field) is
the only honest home, and consumers are forbidden from guessing a class from title.

### 7.4 Two more the ICP will want (flagged, not fully specified)

- `account.direct_mail_feasibility` — the design/direct-mail subsystem will need a physical-address
  confidence + deliverability read per account. Melissa is deferred out of the ARV2 build, so this is
  named here only so it is not rediscovered later.
- `contact.facet.openers` — the deep call produced five grounded openers and there is **no registered
  field for them**; they currently live only in this document. If openers are a durable output (they are
  what the content plane consumes), they need a governed `contact.facet.*` row with `use_class`.

---

## 8. Cost analysis

### 8.1 Every call, actual (from `cost_ledger.json`)

| # | Provider | Call | Type | s | Cost | Credits |
|---|---|---|---|---|---|---|
| 1 | Exa | `d1_vertical_ai_practices` | search/auto | 1.7 | $0.00700 | — |
| 2 | Exa | `d2_vertical_ai_smb_services` | search/auto | 1.4 | $0.00700 | — |
| 3 | Exa | `d3_gtm_hiring_outbound` | search/auto | 1.7 | $0.00700 | — |
| 4 | Exa | `d4_domain_lock` | search/fast | 0.5 | $0.00700 | — |
| 5 | Apollo | `organizations/enrich` | api | 0.4 | $0 | **1** |
| 6 | Exa | `account_deep` (no outputSchema) | deep-reasoning | 47.3 | $0.02800 | — |
| 7 | Exa | `account_deep` retry (1-string schema) | deep-reasoning | 43.7 | **$0.02100** | — |
| 8 | Exa | `g1_seed_round` | search/auto | 1.5 | $0.00700 | — |
| 9 | Exa | `g2_ashby_postings` (6 pages) | contents | 0.1 | $0.00600 | — |
| 10 | Exa | `g3_customers_team` | search/auto | 2.1 | $0.00700 | — |
| 11 | Apollo | `mixed_people/api_search` by org | api | 0.3 | $0 | 0 |
| 12 | Apollo | `mixed_people/api_search` by domain | api | 0.3 | $0 | 0 |
| 13 | Apollo | `people/match` (Steijn Pelle) | api | 0.3 | $0 | **1** |
| 14 | Apollo | `people/match` (Max Shore) | api | 0.4 | $0 | **1** |
| 15 | Exa | `contact_deep_steijn` | deep-reasoning | 46.4 | **$0.03000** | — |
| 16 | OpenRouter | structuring — `z-ai/glm-4.7` | llm | 169.3 | $0.02547 | — |
| 17 | OpenRouter | structuring — `openai/gpt-5-mini` | llm | 54.2 | $0.01828 | — |
| 18 | OpenRouter | structuring — `gpt-5-mini` @ minimal reasoning | llm | 32.1 | **$0.01185** | — |
| 19 | OpenRouter | BYO-loop synthesis experiment | llm | 79.6 | $0.02439 | — |
| 20 | Exa | `deep` (non-reasoning) comparison | deep | 44.5 | $0.02300 | — |
| | | **TOTAL** | | **~9.9 min** | **$0.22998** | **3** |

*Note on the OpenRouter numbers: `openai/gpt-5-mini` runs are BYOK, so OpenRouter reports `usage.cost = 0`.
The real figure is `usage.cost_details.upstream_inference_cost`, which is what is used above. Reading
`usage.cost` alone would have under-reported this run's spend by $0.0545.*

### 8.2 Unit economics discovered

| Unit | Observed | List price (repo plan doc) |
|---|---|---|
| Exa neural search (10 results, text included) | **$0.00700** flat | $7/1k ✅ exact match |
| Exa `contents` | **$0.001/page** (6 pages = $0.006) | $1/1k pages ✅ exact match |
| Exa `deep-reasoning` | **$0.021–$0.030** (varies with pages retrieved: 16→$0.021, 23→$0.028, 25→$0.030) | $15/1k = $0.015 ⚠ **observed 1.4–2.0× list** — retrieval is billed on top |
| Exa `deep` | **$0.023** | $12/1k = $0.012 ⚠ same |
| Apollo org enrich | 1 credit | — |
| Apollo people search | **0 credits** | — |
| Apollo people match | 1 credit (+8 if a mobile returns) | — |
| gpt-5-mini | $0.25/M in, $2.00/M out (derived from actuals) | — |

### 8.3 The production configuration, and what it costs per account

Excluding the four experiment calls (#6 failed-shape, #16, #17, #19, #20), the **production pass** is:

| Stage | Calls | Cost | Credits |
|---|---|---|---|
| Domain lock | 1 search | $0.007 | — |
| Apollo org enrich | 1 | — | 1 |
| **Account deep research** | 1 `deep-reasoning` | $0.021 | — |
| Gap-fills | 2 search + 1 contents | $0.020 | — |
| Committee shortlist | 2 people searches | — | 0 |
| Contact enrichment | 2 `people/match` | — | 2 |
| **Contact deep research** | 1 `deep-reasoning` | $0.030 | — |
| Structuring | 1 `gpt-5-mini@minimal` | $0.01185 | — |
| **Per account** | **9 paid calls** | **$0.08985** | **3** |

Discovery amortises separately: **$0.021 for 30 candidates** = $0.0007/candidate.

### 8.4 Extrapolation

**Uniform deep research on every account** (worst case — and the thing the architecture says never to do):

| Accounts | Research cost | + discovery | **Total** | Apollo credits |
|---|---|---|---|---|
| 10 | $0.90 | $0.01 | **$0.91** | 30 |
| 100 | $8.99 | $0.07 | **$9.06** | 300 |
| 1,000 | $89.85 | $0.70 | **$90.55** | 3,000 |

**Two-pass tiering as the architecture actually specifies** — cheap scoring on all, deep research only on
the top ~20%. Pass-A per account ≈ Apollo enrich (1 credit) + a $0.007 search share:

| Accounts | Pass A (all) | Pass B (top 20% deep) | **Total** | Apollo credits |
|---|---|---|---|---|
| 10 | $0.07 | 2 × $0.0899 = $0.18 | **$0.25** | 10 + 4 = 14 |
| 100 | $0.70 | 20 × $0.0899 = $1.80 | **$2.50** | 100 + 40 = 140 |
| 1,000 | $7.00 | 200 × $0.0899 = $17.97 | **$24.97** | 1,000 + 400 = 1,400 |

**Two-pass tiering is 3.6× cheaper than uniform deep research, and 2.1× cheaper on Apollo credits.**

### 8.5 Apollo credit math vs plan size

Credits per account, by committee depth:

| Committee depth | Credits/account | 100 accounts | 1,000 accounts |
|---|---|---|---|
| Org only (Pass A) | 1 | 100 | 1,000 |
| Org + 2 matched contacts (**this run**) | **3** | 300 | 3,000 |
| Org + full 4-persona committee | 5 | 500 | 5,000 |
| Org + 4 contacts + job postings page | 6 | 600 | 6,000 |
| Any of the above **with phone reveal** | +8 **per phone** | +3,200 (at 4 contacts) | +32,000 |

Two hard consequences:

1. **People search is free (0 credits) and people match is not.** The shortlist-then-match discipline in
   the Apollo contract is a real cost control, not a style preference: this run listed 22 people for 0
   credits and paid for 2.
2. **Phone reveal is 8× the cost of an email and needs an HTTPS webhook we do not have.** At a 4-person
   committee it is the single largest line in the credit budget. Recommendation: **stay email-only** until
   there is a proven direct-dial use case, and price it separately when there is.

*Plan sizing itself cannot be computed here — the Apollo contract doc does not record credit pricing per
plan tier, and I did not have a verified price list. The arithmetic above (credits/account × N) is what
that decision needs; the $/credit has to come from the founder's actual Apollo plan.*

### 8.6 Alternatives, measured

**(a) Structuring model — three real runs, same prompt, same corpus:**

| Model | Reasoning | s | **Cost** | Claims | Proposed fields | Defects |
|---|---|---|---|---|---|---|
| `z-ai/glm-4.7` | default (6,277 reasoning tokens) | 169.3 | $0.02547 | 24 | 1 | **24/24 wrong value key; 24/24 string confidence; 4 non-verbatim spans** |
| `openai/gpt-5-mini` | default (4,672 reasoning tokens) | 54.2 | $0.01828 | 12 | 3 | 0 schema — but emitted a **wrong `employee_count: 23`** |
| **`openai/gpt-5-mini`** | **minimal (0 reasoning tokens)** | **32.1** | **$0.01185** | **21** | 3 | 1 unregistered key (correctly refused) |

**The finding that matters: reasoning tokens made the structuring pass more expensive, slower, AND worse.**
Turning reasoning off made gpt-5-mini **35% cheaper, 1.7× faster, and produced 75% more claims**. Structuring
is an extraction task, not a reasoning task.

GLM-4.7 is **2.2× the price and 5.3× the latency** of the winner, and its output needed repair on every
row. It did show better *semantic* judgement (it assigned `economic_buyer` correctly where gpt-5-mini
said `champion`), which is why the merged set keeps rows from both — but it is not the production choice.

**(b) Exa `deep-reasoning` vs `deep` — same charter, same query, same schema:**

| | `deep-reasoning` | `deep` |
|---|---|---|
| Cost | **$0.021** | $0.023 |
| Latency | 43.7 s | 44.5 s |
| Report | 19,368 chars | 17,140 chars |
| **"NOT FOUND" markers** | **30** | 14 |
| Behaviour on the headcount trap | refused it: *"a search-result company entity record reports a workforce of 23, but that is an aggregator/entity estimate rather than a primary source and is not sufficient to state current headcount as fact"* | asserted it: *"Lassie employs 23 people"* |

`deep-reasoning` was **cheaper, longer, and refused to guess twice as often**. `deep` (the "lite" option)
asserted the exact stale figure the reasoning variant rejected. **There is no case for `deep` here** — the
cheaper-looking option is both more expensive in practice and less truthful.

**(c) Build-your-own loop (search + contents + own model) — measured, not estimated:**

The failed no-schema call handed back its full 23-page, 124,620-character research corpus. That is
exactly what a self-built loop assembles. Feeding it to the winning cheap model with the identical
charter:

| | Exa `deep-reasoning` | Build-your-own |
|---|---|---|
| Retrieval | included | 2 searches ($0.014) + 23 pages contents ($0.023) = **$0.037** |
| Synthesis | included | gpt-5-mini@minimal, 28,429 in / 8,639 out = **$0.02439** |
| **Total** | **$0.021** | **$0.06139** |
| Latency | 43.7 s | 79.6 s (synthesis alone) |
| Report | 19,368 chars | 35,308 chars (verbose: repeats each fact as "Fact:" then "Quote:") |
| Query planning | **Exa does it** | you must build and pay for it |

**Build-your-own costs 2.9× more and is slower**, before you write a line of query-planning code. The
longer report is padding, not depth. **Do not build the loop.**

**(d) Parallel Task API and Firecrawl — NOT measured.** No keys were authorised for this run and the repo
carries no verified price list for either, so any number I wrote would be invented. What is known:
`parallel_task` is already a registered tier-4 synthesis source in `tier_plan`s alongside `exa_deep`, and
`firecrawl` is registered for `contact.facet.recent_post`. Both are **resolver-absent in production today**
(the composition to-do list in CLAUDE.md confirms `register_synthesis_wiring` has no production callers).
Given that Exa deep-reasoning lands at $0.021–0.030 for a 19k-character cited dossier, the bar either
would have to clear is: **under ~$0.02 per subject including retrieval, with comparable refusal
discipline.** That should be a small measured bake-off, not a procurement decision.

**(e) Melissa** — deferred out of the ARV2 build; relevant only when the direct-mail path needs verified
postal addresses. Not exercised.

### 8.7 Recommended cheapest dossier-grade configuration

| Stage | Choice | Why | Cost |
|---|---|---|---|
| Discovery | Exa `search` type `auto`, 10 results, text bundled | $0.007 flat returns 10 pages *with text*; `contents` on top is redundant at this size | $0.007 / 10 candidates |
| Domain lock | 1 Exa `search` type `fast` before any spend | Cheapest insurance against researching the wrong entity. Would have cost $0.021+ to discover the "Lassie = pet insurance" collision downstream | $0.007 |
| Firmographics | Apollo `organizations/enrich` | tier-1 headcount, dept split, funding events, 60 technographics — none of which the deep call found | 1 credit |
| **Account depth** | **Exa `deep-reasoning`, ONE call, single free-form string outputSchema** | cheaper and more honest than `deep`; 2.9× cheaper than building it yourself | $0.021 |
| Gap-fill | ≤3 cheap calls, only for named criticals | returned the seed investors, the pricing model and the 16-role board — the best value per dollar in the run | $0.020 |
| Committee | Apollo people search ×2 (org + domain, **unioned**) | 0 credits for a 22-person shortlist | 0 credits |
| Contacts | Apollo `people/match`, email only, **no phone** | verified emails at 1 credit; phone is 8 credits and needs a webhook | 2 credits |
| **Contact depth** | **Exa `deep-reasoning`, ONE call** | produced career, education, 8 publications, hooks and grounded openers | $0.030 |
| **Structuring** | **`openai/gpt-5-mini` with `reasoning: {"effort":"minimal"}`** | cheapest, fastest, most claims. Reasoning actively hurt | $0.012 |
| Provenance | stamp tier/source/method **in code**, never by the model | the tier-4-iff-synthesis CHECK makes this non-negotiable | $0 |

**≈ $0.090 and 3 Apollo credits per fully-researched account.** With two-pass tiering at 20% deep:
**≈ $0.025 per account across the list.**

**Three changes that would cut it further:**
1. **Skip the domain-lock search** when discovery already returned the official site in its results — it did
   here (lassie.ai appeared in the d1 corpus). Saves $0.007 (8%).
2. **Fold the gap-fills into the deep call's charter.** Two of three gap-fills asked for things the deep
   call was already told to find. A tighter charter that demands the funding *history* and the *jobs index
   page* would likely absorb them. Potential saving $0.014–0.020 (16–22%).
3. **Prompt-cache the field catalog and system prompt** across accounts. The structuring prompt was 17,466
   tokens of which the catalog + instructions are fixed; `cached_tokens` was **0** on every run. At scale
   this is the largest single saving available in the structuring stage.

---

## 9. Verdict against the dossier bar

Compared section-by-section against `digestive-healthcare-of-georgia-p-c.md` — the depth bar (a
different *domain*; the target is section depth).

| Dossier section | This run's equivalent | Depth reached |
|---|---|---|
| Account Summary (operating name, website, tier, ownership, size, locations, EHR, fit scores) | §2.1–2.5: name, domain, HQ, phone, 41 employees + dept split, funding, pricing model, integrations | **Met.** Fit *scores* absent — this run wrote no `account.scoring.*` rows because scoring is a separate rubric-driven pass, not research output |
| Why This Account Is A Strong Fit, In Priority Order | §1 (priority-ordered rationale) + §2.11 | **Met/exceeded** — ordered against the ICP's own stated priority sequence |
| Signals And Evidence, Written Out In Full (quote + meaning + link per item) | §2.5–2.8, every item quote + URL + "what it means" | **Met** |
| Ownership, Structure, And Expansion Path | §2.1 (entity disambiguation) + §2.8 (vertical expansion beyond dental) | **Partial.** No cap-table/parent structure beyond investors; no PE/MSO analogue needed for a startup, but *founding year* is genuinely missing |
| How To Position The Outreach (ROI numbers) | §2.11 | **Partial.** The bar quantifies ROI ($4,760/mo, +$480K/yr); this run has the *account's* economics (30–100 hrs/month saved, $10M ARR) but no Clue-side ROI model — that is the value-narrative layer, downstream of research |
| The People: Decision Makers (6 named, each with identity confirmation + NPI) | §3: 10 committee members, 2 identity-confirmed + verified emails, 1 web-confirmed, 6 apollo-only | **Partial.** The bar had a *registry* identity anchor (NPI) per person. Startups have no NPI equivalent — LinkedIn URL is the closest, and Apollo's degraded search does not return it. **This is the biggest real gap.** |
| Career history (per person) | §5.2, 7 roles with dates from Apollo `employment_history` + LinkedIn | **Met/exceeded** — Apollo's employment history is more structured than the bar's |
| Education and training | §5.3, RSM/Erasmus BSc + Reforge, with two aggregator claims explicitly rejected | **Met** |
| Published work | §5.4, 8 items with venue/date/URL | **Met** |
| Professional memberships and roles | not found | **Gap** — no analogue found; not invented |
| Awards and recognition | §5.6, one award with an explicit "no awarding body or year found" caveat | **Partial** (bar had 4 sourced awards) |
| Personal background and interests, every item publicly sourced | §5.6, 5 hooks, each quoted, special-category excluded by charter | **Partial.** The bar had 5 hooks/person including hometown; this run found country-of-origin and "former professional runner" but no hometown. Startup founders have thinner public personal footprints than physicians with practice bios |
| Suggested conversation openers | §5.7, 5 openers each naming its hook + URL | **Met** |
| Fabrication audit (links opened, items flagged) | §6.1 defect audit + 52/52 schema validation + the corpus-substring check on evidence spans | **Different, arguably better** — the bar audits links *after*; this audits claims *at write time* |

**Honest gaps, stated plainly:**

1. **No registry-grade identity anchor for people.** The bar's NPI is a deterministic tier-1 confirmation. For startup employees there is no equivalent, and Apollo's *free* people search deliberately withholds LinkedIn URLs and surnames. Confirming committee members 3–8 costs 1 credit each — that is the honest price of the bar.
2. **Founding year unresolved.** Both the deep report and Apollo returned nothing; a fourth gap-fill would probably have closed it. I stopped at three by the brief's budget rather than pad.
3. **No employee-sentiment / attrition / public-frustration data.** A 41-person 2020-founded company has no Glassdoor footprint. Three registered `account.resonance.*` fields are therefore empty. **This is a correct empty, not a failure** — but it means resonance-driven personalisation is weaker for startup targets than for established practices.
4. **No fit/intent scores.** Deliberate: scoring is a rubric pass over claims, not a research output, and no ICP spec version existed to score against.
5. **The seed round is arithmetic, not a source.** $47M − $35M = $12M is recorded as an implication, with the investors (SV Angel, Homebrew, Go Global) sourced separately. It was not promoted to a funding claim.
6. **`contact.facet.openers` has no registered field**, so the five openers exist only in this document — the single most immediately actionable output has nowhere to live in the claim store today.

**Verdict: the pipeline reaches the dossier bar on structure, evidence discipline and depth, at
$0.090 and 3 Apollo credits per account.** It falls short of the bar in exactly one structural place —
per-person deterministic identity anchoring — and that gap is a *credit budget* decision, not a
capability gap.

---

## 10. Wire findings worth keeping (things that cost time to learn)

1. **Exa `/search` with `type: deep-reasoning` and NO `outputSchema` returns no `output` key at all.** It returns `results[]` (23 pages, 124,620 chars) and bills $0.028, but the synthesis stage never runs. **The free-form report the brief specified is not achievable by omitting the schema.** The working pattern is a **single string property** — which keeps the report free-form and dodges the 10-property/depth-2 schema budget entirely. *(This invalidates the run's original premise in the best possible way: you can have one free-form cited report per call.)*
2. **`type: deep` and `type: deep-reasoning` return different output shapes.** `deep-reasoning` → `output.content.report` is a **string**. `deep` → `output.content.report` is an **object `{"value": "..."}"`**. Any adapter must handle both.
3. **`output.grounding` exists on both but was an empty array on every call.** The "field-level citations and confidence" the plan doc attributes to Exa did **not** materialise in this shape. Do not design a claim pipeline that depends on it without re-verifying.
4. **Exa deep-reasoning cost scales with pages retrieved**, not with the $15/1k list price: 16 pages → $0.021, 23 → $0.028, 25 → $0.030. Budget per call, not per list price.
5. **Apollo's `organization_ids` and domain people searches disagree badly** (2 vs 22 results). The contract's "union both" rule is essential.
6. **Apollo org records can be contaminated by same-name companies** — Swedish and Dutch pet-insurance staff appeared inside `lassie.ai`'s people list. Provider org grouping is not identity resolution.
7. **Apollo's `departmental_head_count` can contradict Apollo's own people index** (sales = 0 vs five GTM people).
8. **Corporate email domains are not always the primary domain** — `steijn@lassie.ai` vs `max@golassie.com`, both `verified`.
9. **OpenRouter BYOK models report `usage.cost = 0`.** The real cost is `usage.cost_details.upstream_inference_cost`. Reading the wrong field under-reported this run by $0.0545 (24% of total spend).
10. **`reasoning` tokens are a cost and quality *regression* for extraction tasks** — see §8.6(a).

---

### Files

| File | Contents |
|---|---|
| `CLUE-SAMPLE-RUN.md` | this report |
| `claims.json` | 52 stamped claim rows |
| `claims_summary.json` | counts, validation results, defect audit, model-proposed fields |
| `cost_ledger.json` | every call: provider, op, latency, cost, credits, rate headers |
| `account_report.md` | the Exa account deep-research report (19,368 chars) |
| `contact_report.md` | the Exa contact deep-research report (22,680 chars) |
| `account_report_byo.md` | the build-your-own comparison report (35,308 chars) |
| `account_report_deeplite.md` | the `type: deep` comparison report (17,140 chars) |
| `structuring_bundle.txt` | the exact structuring prompt |
| `field_catalog.py` | the real registered field keys + value_schemas used |
| `raw/*.json` | every raw API response |
| `step1..step11*.py`, `clue_lib.py` | the scripts, runnable end to end |
