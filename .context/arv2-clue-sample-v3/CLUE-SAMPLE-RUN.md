# Clue sample run v3 — correct committee, per-person depth, signal-ranked, two-layer representation

**Date:** 2026-08-26 · **Total live spend: $0.23394** (ceiling $2.50) · **Apollo credits: 6** (ceiling 12) · **34 API calls**
**Account picked:** Probook (probook.ai) — $34M Series A led by a16z, announced 2026-06-23
**Committee: 5 people, 5 of 5 confirmed on the open web *before* Apollo was called, 5 of 5 admitted by Apollo, 4 of 5 with verified emails**
**Deliverables:** this file · `claims.json` (106 rows) · `claims_summary.json` · `committee.json` · `cost_ledger.json` · `layer1_payloads.json` · `layer2_display.json` + `layer2_display_proposed.json` · `account_report.md` + 5 × `person_report_*.md` · `raw/` (every response) · `step*.py`

Everything below is grounded in a real response saved in `raw/`. Where something was not found it says
so. No number in this document is estimated unless it is explicitly labelled an estimate.

**What v3 was for.** v2 passed on account depth and cost and **failed on people** — it took Apollo's free
people-search as the committee source and shipped 6 unconfirmed members out of 10, including staff of a
same-name Swedish pet-insurance company. The founder's verdict was "not the correct people." v3 inverts the
order: **the open web builds the committee; Apollo only enriches it.** The result is in §3, and the
same-name trap it was designed to defeat showed up on schedule — the deep call on the CRO found and
discarded **nine** other Mark Hoffmans.

---

## 0. The context the agent ingested

**The client is Clue.** Clue is an AI-native ABM orchestration platform: agents discover target accounts,
enrich account and contact data, run dossier-grade research on accounts and buying committees, draft
personalised campaign content and scale artifacts across contacts. **This run finds buyers FOR Clue.**

**The ICP, as tightened by the founder for v3 (binding):**

| Criterion | v3 rule | Change from v2 |
|---|---|---|
| Stage | **Series A or A-extension ONLY**, raised within ~24 months. NOT seed. NOT Series B+. | v2 allowed seed→Series B |
| Geography / type | US, B2B, vertical SaaS or vertical AI | unchanged |
| Buyer base | sells into a **fragmented SMB vertical** | unchanged |
| Hiring | **actively hiring now**, GTM roles especially | promoted from "signal" to **filter** |
| Intent | **buying-intent signals required** — GTM reqs describing list-building/outbound, founder-led sales at its scaling point, outbound tooling present or conspicuously absent, no ABM platform | new hard criterion |
| Exclusions | Insight Health, any Clue-affiliated entity, >1,000 employees, pure consumer | unchanged |

**Persona map for Clue's committee:** CEO/founder = economic buyer · growth/marketing/GTM lead = champion ·
sales lead = user · technical co-founder/CTO = technical evaluator. *(The platform's `Persona` enum has no
`user` — see §7.4; this was already v2's finding and v3 re-hits it.)*

**Two further binding rulings:** deep research on **each** committee member with **per-person cost**
reported (§4, §8.4); and every claim carries a **signal priority** with the top signals leading every view
(§2, §6.2, §7.1).

---

## 1. Discovery — the candidates, and why Probook won

Three Exa searches (`type: auto`, 10 results, text bundled, $0.007 each) plus one domain-lock search.
Searches 2 and 3 (GTM-hiring language, founder-led-sales content) returned **job-board aggregators and
generic SaaS advice, not companies** — a real negative result: *company* discovery works, *behavioural*
discovery through content search does not. Every candidate below came from search 1.

| # | Company | Vertical (fragmented?) | Round + date | Hiring | Intent signal | Verdict |
|---|---|---|---|---|---|---|
| 1 | **Probook** (probook.ai) | US plumbing / HVAC / electrical contractors | **$34M Series A led by a16z, 2026-06-23** (+ $6M Sequoia seed; $40M total) | **13 open roles, 6 of them GTM**, all Manhattan on-site | The SDR req says *"We have a clearly defined target: the top home service operators in America. **The list exists.** … What we need now is someone to go get them"*; the CEO posted *"Being stuck in founder-led sales isn't a flex"*; Apollo detects **no CRM, no sales-engagement tool, no ABM platform** in 30 technologies | **PICKED** |
| 2 | Lassie (lassie.ai) | US dental practices (~160,000) | $35M Series A, a16z, 2026-06-03 | 16 roles, 4 GTM | Strong — but **fully researched in v2**; re-running it would re-buy known evidence and prove nothing about the committee protocol on fresh ground | Excluded by design |
| 3 | Pie | US "Main Street" SMBs | $19.5M Series A led by Lightspeed, 2026-06-30 ($23.7M total) | not surfaced | **Weakest intent**: it says it grew to ~2,000 customers *"largely through referrals and platform partnerships"* — a partner/PLG motion, not outbound. Also sells *growth/customer-acquisition* to SMBs, so it is adjacent to Clue's own category | Runner-up, lost on motion |
| 4 | Avoca AI | HVAC / plumbing / roofing voice agents | **$125M at a $1B valuation**, 2026-04 | — | **Disqualified on stage** — that is a growth round, not a Series A. The v3 stage filter is a hard gate and this is exactly what it is for | Excluded |
| 5 | Datatruck / SwiftSku / Twin A1 / Freight Hero / Annie / Hemut / PatientDesk / Linda AI | mixed | seed or pre-seed, or EU | — | Excluded on stage (seed) or geography (EU). Carried over from the v2 corpus, re-checked against the tightened rule | Excluded |

**Why Probook, in the ICP's own priority order:**

1. **Series A, 2 months old.** *"a16z is leading Probook's $34 million Series A, bringing the company's total funding to $40 million after a seed round led by Sequoia."* — https://a16z.com/announcement/investing-in-probook/ (2026-06-23).
2. **Actively hiring, GTM-heavy.** 13 live reqs on the company's own Ashby board, **6 in GTM**: SDR, Enterprise AE, Strategic AE, Solutions Consultant, Senior Product Marketing Manager, Events Marketing Specialist.
3. **Buying intent is explicit and quotable** — the reqs describe Clue's product as a human job (§2.1).
4. **Tooling gap is total.** Apollo's 30 detected technologies contain **no CRM, no sales-engagement platform, no data provider and no ABM/intent platform.** The SDR req's answer to "run a clean CRM" is *"Maintain clean, accurate records **in Ashby** for every prospect interaction"* — their **applicant-tracking system**.
5. **Fragmented vertical, structurally.** US plumbing, HVAC and electrical contractors — tens of thousands of independent shops plus PE roll-up platforms. Selling into it without account research at scale is not possible.

**Disqualifier check:** 52 employees (<1,000 ✓), B2B (✓), US / New York (✓), not Insight Health or
Clue-affiliated (✓), Series A within 24 months (✓ — 2 months).

**Same-name trap carried by this account:** *ProBook* is a long-running **HP laptop line**, and there are
unrelated Probook/ProBook bookkeeping and booking products. The research charter excluded them explicitly
and the deep report confirms it did: *"(a) HP ProBook, the unrelated HP laptop line—discarded because it is
computer hardware, not the New York home-services AI company; (b) unrelated 'Probook'/'ProBook' bookkeeping
and accounting tools…"*

---

## 2. The account — signal-ranked, P1 first

> Every fact below is a row in `claims.json` with its own `source_url` and, where quoted, its own
> `evidence_span`. This section is the readable rendering; the claim rows are the truth.
> **P1 = active buying intent · P2 = qualifying firmographics · P3 = context.**

### 2.1 P1 — the buying window (8 account-level P1 claims)

**A $34M Series A, 8 weeks old, with the use of proceeds stated.**
*"The investment comprises a $34 million Series A led by Andreessen Horowitz (a16z) and a $6 million Seed
round led by Sequoia Capital. Sequoia also participated in the Series A."*
— https://www.globenewswire.com/news-release/2026/06/23/3316215/0/en/Probook-Raises-40M-from-Andreessen-Horowitz-and-Sequoia-to-Scale-the-AI-Operating-System-for-Home-Services.html
Use of proceeds, verbatim: *"scale its go-to-market team against surging demand, and grow engineering and
customer success to deliver on it."*

**Six open GTM reqs that describe Clue's product as a human job.** All Manhattan, all on-site, fetched in
full from the company's own Ashby posting API (free):

| Req | Posted | The line that matters |
|---|---|---|
| **Sales Development Representative** | 2026-04-23 | *"We have a clearly defined target: the top home service operators in America. **The list exists.** The product is proven. What we need now is someone to go get them."* … *"**Account research**: Understand each target account before reaching out. Tailor your approach to their specific business size, software stack, and operational context."* … *"You report to the **Director of Growth**"* |
| **Enterprise Account Executive** | 2026-06-03 | *"**Account Planning**: Know your patch better than anyone at the company. **Map accounts that fit the ICP, identify key contacts, and develop and iterate your value hypothesis** throughout each evaluation."* |
| **Strategic Account Executive** | 2026-06-23 | same Account-Planning charter; *"You will have SDR support generating pipeline and marketing backing you in the field."* |
| **Solutions Consultant** | 2026-06-22 | *"Probook is at an **inflection point**. We have product-market fit, a clearly defined target market, and capital to scale."* |
| **Senior Product Marketing Manager** | 2026-07-16 | *"**Define ICPs, personas, and jobs-to-be-done** that are actionable for Sales and Marketing."* |
| **Events Marketing Specialist** | 2026-07-16 | works with *"the **Director of Growth** to plan the event calendar"* |

That SDR paragraph is the strongest single artefact in this run. A company that has just raised $34M is
hiring a human being to do target-account list work, account research and personalisation — by hand, at
60 dials a day.

**The GTM stack is empty.** Apollo's `current_technologies` returns 30 items: AI, AWS, CloudFront, Cursor,
Excel Impact, Frame, Gmail, Google Meet, Google Search Console ×2, Google Sheets, Google Tag Manager,
Google Workspace, HSTS, **LinkedIn Ads**, **LinkedIn Recruiter**, Microsoft 365 (×3), Microsoft Exchange
(×2), Mobile Friendly, Next.js, Outlook, Priority Hints, React, Vercel, Viewport Meta, YouTube, webpack.
**No Salesforce. No HubSpot. No Outreach. No Salesloft. No Apollo.io. No Clay. No 6sense. No Demandbase.**
Corroborated from the other side: the SDR req's CRM instruction is *"Maintain clean, accurate records in
**Ashby**"*. Seven salespeople and one marketer are running on an ATS and a spreadsheet.

**Founder-led sales has publicly hit its ceiling.** The CEO, on LinkedIn:
*"Until December, our 'sales team' was just me"* … *"I've personally met pretty much every Probook customer,
run every demo, and traveled across the US to visit almost every shop."* … ***"Being stuck in founder-led
sales isn't a flex. I wish I realized that sooner."***
— https://www.linkedin.com/posts/george-eliadis_until-december-our-sales-team-was-just-activity-7441840906384683008-3s7v
And on hiring the CRO: *"After **19 months of running literally every demo myself**, I couldn't be more
excited to welcome Mark Hoffman as Probook's CRO."*

**The GTM org is being built right now, and its leaders say so.** CRO Mark Hoffman: *"The GTM team is
inching up towards 20 now, with many more to go."* Director of Sales & Development Aaron Churba:
*"Currently leading a team of **5 sellers and counting**."*

**A seventh GTM req exists that is not on the company's own board.** LinkedIn Jobs carries
*"Probook hiring **Head of Sales** in Manhattan, NY"* (job 4431770595) — absent from both `probook.ai/careers`
and the Ashby board. A leadership seat being recruited off-board.

### 2.2 P2 — the qualifying firmographics

- **52 employees** (Apollo `estimated_num_employees`), New York, NY 10022, founded **2024**.
- **Department split** (Apollo): engineering 12 · **sales 7** · operations 4 · **marketing 1** · HR 3 ·
  entrepreneurship 3 · support 4 · consulting 2 · finance 1 · IT 1. A 7:1 sales-to-marketing ratio with
  a Director of Growth two months into the job is a marketing org about to be built from zero.
- **Product:** *"the AI Operating System for home services,"* *"built around dispatch."* It *"unifies
  intake, data cleaning, chat, outbound, and dispatch."* — https://www.probook.ai/
- **Integration:** ServiceTitan is the only named external system; Fox Business reports Probook is
  *"listed as a ServiceTitan partner."* Other integrations: **NOT FOUND**.
- **Traction, all company-reported and labelled as such:** *"hundreds of locations nationwide,"* from
  independent shops to PE-backed platforms. Named customers: TurnPoint Services, Master Trades Group,
  Del-Air, Peterman Brothers, Sila Services, Summers Plumbing Heating & Cooling, Anthony Plumbing Heating
  Cooling & Electric, TR Miller (first customer), Cardinal, Lion Home Service.
- **Per-customer outcomes:** Summers (14 locations, 260 techs) *"booked 2,873 jobs in their first month on
  Probook with zero human intervention"*; Del-Air went *"from 22 dispatchers to 10"* and had *"90% of its
  call assignment happen automatically"*, containing *"74%"* of 16,000 May calls without a human; Anthony
  *"ran 10% more revenue per job on a 40% leaner team in eight months"*; Peterman *"centralized dispatch
  across 11 markets and 200 technicians without adding overhead."*
- **ARR / revenue / pricing: NOT FOUND.** No public price, rate card or ARR figure exists. Left blank.

### 2.3 P3 — context and resonance

- **Culture:** *"Built by the Trades. For the Trades."* · *"Most AI vendors flocked to home services because
  it looked attractive on a spreadsheet. We came to it because we grew up in it."* · *"We deploy in person,
  configure alongside your team, and stay on the hook for the outcomes we sell."* · *"the most talent-dense
  team in New York"* · *"a small, cracked team."*
- **Buying culture** (registered field `account.resonance.buying_culture`): founder-led, operator-oriented,
  deployment-committed.
- **Employee sentiment / attrition / public frustrations: NOT FOUND.** A 52-person company founded in 2024
  has no Glassdoor footprint. Three registered `account.resonance.*` fields are correctly empty.

### 2.4 Timing events, newest first

| Date | Event | Priority |
|---|---|---|
| 2026-08-26 | 13 reqs live on the Ashby board; a Forward Deployed Engineer req published *that morning* | P1 |
| 2026-07-30 | **The Director of Growth publicly compares ABM list-building tools** (§4.3) | **P1** |
| 2026-07-16 | Senior PMM + Events Marketing Specialist reqs posted | P1 |
| 2026-06-23 | $40M announced ($34M Series A a16z + $6M seed Sequoia); a16z and Sequoia posts; Fortune exclusive | P1 |
| 2026-06-23 | Director of Growth announces she has joined *"to lead growth and build out the marketing organization"* | P1 |
| 2026-06-03 / 06-22 / 06-23 | Enterprise AE, Solutions Consultant, Strategic AE reqs posted | P1 |
| 2026-02 | CRO Mark Hoffman and Director of Sales & Development Aaron Churba both start | P1 |
| 2026-04-23 | SDR req posted | P1 |

---

## 3. The buying committee — built from the open web, enriched by Apollo

### 3.1 The protocol, and what each step actually returned

| Step | Source | Cost | What it produced |
|---|---|---|---|
| 1. Own team page | `/contents` on `probook.ai/company` | $0.001 | All three co-founders with exact titles |
| 2. Funding announcements | `/contents` on a16z + Sequoia + GlobeNewswire | $0.003 | Co-founders corroborated three more times; investor partners named |
| 3. Live hiring index | Ashby public posting API | **$0** | 13 reqs in full, incl. *"You report to the Director of Growth"* — proof a GTM leader exists before knowing who |
| 4. LinkedIn via Exa (2 searches, `includeDomains: linkedin.com`, `includeText: ["Probook"]`) | Exa search | $0.024 | **The entire GTM leadership layer**: CRO, Director of Growth, Director of Sales & Development — each with a profile URL *and* a corroborating first-party post |
| 5. Apollo `people/match` × 5 by `linkedin_url` + `domain` | Apollo | 5 credits | Verified emails + full employment history; **hard gate**: any record whose `organization.primary_domain ≠ probook.ai` is discarded |

**The account deep-research call, run separately and in parallel, reported: *"CRO and director-level
growth/sales leaders: NOT FOUND in the reviewed company pages, funding announcements, and indexed LinkedIn
results."*** The $0.015 account call found none of the three GTM leaders. The $0.024 of dedicated
committee search found all three. **Committee discovery is a separate retrieval problem from account
research, and cannot be a sub-goal of the account charter.** That is the central mechanical finding of v3.

### 3.2 The committee

| # | Name | Title | Clue persona | Identity confirmed by (non-Apollo) | Apollo admitted? | Email |
|---|---|---|---|---|---|---|
| 1 | **George Eliadis** | Co-Founder & CEO | **economic_buyer** | https://www.probook.ai/company (*"George Eliadis / Co-Founder & CEO"*) + a16z + Sequoia + GlobeNewswire + Fortune + LinkedIn | ✅ `probook.ai` | **george@probook.ai** `verified` |
| 2 | **Mark Hoffman** | Chief Revenue Officer | **economic_buyer** (owns the number and the GTM budget) | The company's own post: *"Ten years ago, our CRO, Mark Hoffman, hired Aaron Churba…"* + the CEO's welcome post | ✅ `probook.ai` | **mark@probook.ai** `verified` |
| 3 | **Kate Blumberg** | Director of Growth | **champion** | Her own post: *"I'm excited to share that I've joined Probook to lead growth and build out the marketing organization"* + the SDR req's reporting line | ✅ `probook.ai` | **not available** (`email_status: unavailable`) |
| 4 | **Aaron Churba** | Director of Sales & Development | **champion** (day-to-day *user*; see §7.4) | The company's own post: *"We're excited to welcome Aaron to Probook as our Director of Sales & Development"* + his own announcement | ✅ `probook.ai` | **aaron@probook.ai** `verified` |
| 5 | **Lewis Zhang** | Co-Founder & CTO | **technical_evaluator** | https://www.probook.ai/company (*"Lewis Zhang / Co-Founder & CTO"*) + a16z + Sequoia + LinkedIn | ✅ `probook.ai` | **lewis@probook.ai** `verified` |

**Vacancies recorded as signals, not people** (the protocol's rule 2):
**Head of Sales** (LinkedIn Jobs 4431770595, off-board) · **Sales Development Representative** ·
**Enterprise AE** · **Strategic AE** · **Solutions Consultant** · **Senior PMM** ·
**Events Marketing Specialist** · **Head of Talent**.

**Deliberately NOT on the committee:** **Ben Cervantez**, third co-founder — named by the company page,
a16z, Sequoia and the wire release, but with **no title beyond "Co-Founder"**, no LinkedIn profile in the
corpus and no Apollo record. Naming a persona for him would be a guess, so he is recorded as a known
gap rather than admitted at low confidence. Eight further Probook employees surfaced in the LinkedIn
search (Grant Miller, Caroline Simon, Jason Jimenez, Alex Kahn, Katy Junior, Bradley Levine, Ian
Makhambetov, Saunghee Ko, Christian Yongwhan Lim) and were **not** admitted — they are individual
contributors, not a buying committee. **Correct beats many: 5 people, 5 confirmations.**

### 3.3 Apollo corroborated the web, and contaminated nothing

| Person | Web-derived title | Apollo `person.title` | Match |
|---|---|---|---|
| George Eliadis | Co-Founder & CEO | `Co-Founder & CEO` | exact |
| Mark Hoffman | CRO | `Chief Revenue Officer` | exact |
| Kate Blumberg | Director of Growth | `Director of Growth` | exact |
| Aaron Churba | Director of Sales & Development | `Director of Sales & Development` | exact |
| Lewis Zhang | Co-Founder & CTO | `Co-Founder / CTO` | exact |

**5/5 admitted, 0 rejected, 0 same-name contamination, 5/5 titles agreeing with a primary source.** v2's
free people-search returned obfuscated surnames and two pet-insurance employees; v3 never asked Apollo
who is on the committee, so that failure mode is structurally unreachable. The cost of the fix is
**+3 Apollo credits** (5 matches instead of 2) and **+$0.024** of LinkedIn search.

**One email is genuinely unavailable.** Kate Blumberg — the *champion*, the single most valuable person on
this committee — returns `email: null, email_status: "unavailable"` from a paid `people/match`. Apollo
charged the credit and returned no address. The honest output is her LinkedIn URL, and a note that the
`@probook.ai` first-name pattern (`george@`, `mark@`, `aaron@`, `lewis@`) makes `kate@probook.ai` a
*plausible guess* — which this run does **not** promote to a claim, because a guessed address is exactly
the kind of fabrication the architecture exists to prevent.

---

## 4. Per-person deep research — five calls, $0.015 each

Five Exa `deep-reasoning` calls, one per confirmed member, each target-locked in the `systemPrompt` with
the exact person, the exact employer and their Apollo-verified prior employers, and each carrying the
special-category compliance exclusion. **$0.075 total, $0.015 per person, 33–44 s each.**

| Person | Report | NOT FOUND markers | Same-name people found and excluded | Cost |
|---|---|---|---|---|
| George Eliadis | 21,293 chars | 17 | — | $0.015 |
| Mark Hoffman | 13,492 chars | 20 | **9** (Fort Lauderdale medtech; Boston attorney; Florida logistics; Bismarck HVAC sales; Tennessee holdings owner; Indiana strategic accounts; a NY property manager; a Chicago packaging owner; a LifeYield exec) + a *Josh* Hoffman podcast guest also rejected | $0.015 |
| Kate Blumberg | 18,669 chars | 25 | **3** (a South Carolina farm hand / Rover pet-care professional; a San Francisco Sierra Club / ICCT director; an Atlanta technical program manager) | $0.015 |
| Aaron Churba | 13,648 chars | 18 | **2** Florida corporate-registry records | $0.015 |
| Lewis Zhang | 14,192 chars | 12 | — | $0.015 |

**What per-person depth bought that account-level research could not**, in one line each:

### 4.1 George Eliadis — Co-Founder & CEO — *economic buyer*
Penn M&T dual degree (BSE Systems Engineering + Wharton BS Economics, 2020–2024); **2020 U.S. Presidential
Scholar with a perfect ACT 36** (Newburgh Free Academy announcement); pressure-washed with his father for
six summers at A2Z Exterior Pressure Washing; ran **Eliadis Numismatics** (coins) 2015–2021; presented at
the **Shortlist NY Founder Showcase at betaworks**; guest on the **Reimagining Home Services** podcast.
The buying-relevant line: ***"Being stuck in founder-led sales isn't a flex. I wish I realized that
sooner."*** And on point solutions: *"One tool for voice. One for outbound. One for follow-up. Operators
ended up with five vendors and more overhead."* — he sells consolidation, so he will hear a consolidation
pitch.

### 4.2 Mark Hoffman — CRO — *economic buyer*
Joined Feb 2026 after **Tennr** (Chief Sales Officer, Dec 2024–Feb 2026 — another a16z-backed vertical-AI
company) and **eight years at VTS** (Director → VP → SVP of Sales, 2017–2024), before that **Zocdoc**
(2013–2016). Binghamton University. *"The GTM team is inching up towards 20 now, with many more to go."*
*"The first 4 months have been far less easy, which is exactly how it should be."* He has scaled a
vertical-SaaS revenue org twice; he is not learning on the job, he is executing a playbook.

### 4.3 Kate Blumberg — Director of Growth — *champion* — **the single best find in this run**
Career: **Branch — Global Events Manager → ABM Manager → Sales Development Team Lead** (2017–2018) →
**Survata** Head of Demand Gen → **SafeGraph** Demand Gen → Director of Demand Gen → **Middesk** Head of
Growth → **BuildOps** Director of Demand Generation (Jun 2024–Apr 2026) → **Probook** Director of Growth
(Jun 2026). BA, The College of Wooster.

Three things make her the champion:

1. **She has personally held the job title "ABM Manager."** She then *hired* an ABM Manager at BuildOps,
   describing the role as building *"high-touch, high-converting programs"* with sales.
2. **She came from BuildOps** — vertical software for commercial contractors. She already knows this
   buyer, this vertical and this motion. Her own summary: *"building a demand generation engine that
   delivered for sales… hiring and leading a team, scaling programs across inbound, **ABM**, events,
   lifecycle, and paid."*
3. **She is publicly evaluating this exact category, four weeks before this run.** On 2026-07-30 she
   posted: ***"The martech hype cycle is relentless and Clay is everywhere right now. Glad to see new
   tools like Riveter gaining traction and cutting through the noise"*** — resharing a description that
   praises Riveter as more accurate than Clay, *"useful for list building"*, and able to analyse CRM
   signals to identify non-obvious characteristics of best customers and ***recommend who to ABM next.***
   — https://www.linkedin.com/posts/kibrady12_the-martech-hype-cycle-is-relentless-and-activity-7488693969325846528-STdm

   That is a live, dated, first-party statement of purchase criteria for Clue's own product category, made
   by the person who owns the budget line, at a company that just raised $34M and has no ABM tool. It is
   the highest-value claim in the run — and §6.3 records that the cheap structuring model needed **three
   attempts** to extract it.

**Compliance catch:** her LinkedIn field-of-study renders as *"Religion/Religious Studies."* The deep
report surfaced it despite the charter's religion exclusion (an academic discipline is not a religious
belief, so the model let it through). It is **deliberately not written as a claim** — `contact.facet.alma_mater`
records the institution only. Flagged as a real edge in the exclusion rule, not hidden.

### 4.4 Aaron Churba — Director of Sales & Development — *champion / user*
Joined Feb 2026; **Mark Hoffman hired him into his first job out of college ten years earlier** and the
company published that fact. Prior: Bite (Director of Sales), Zip Security (Director of Sales), Electric
(Manager, Sales / Senior AE). Penn State, Telecommunications, 2012–2016. **President's Club FY2021
(inaugural year) and FY2022.** *"Currently leading a team of 5 sellers and counting."* *"The companies that
get most from their technology aren't spending more, they're planning with precision."* *"Prospects buy
from people they like, relate to, or aspire to emulate."* He is the person who will actually operate an
ABM tool daily, and the SDR req reports into his peer.

### 4.5 Lewis Zhang — Co-Founder & CTO — *technical evaluator*
Berkeley EECS **in two years with a 4.0**; perfect AMC 12; started coding at 7; Senior ML Engineer at
**Roblox** 2021–2024 (player-server matching); research internships at Berkeley AI Research (Scalabel.ai,
autonomous-driving annotation) and Stanford; interned at Confluent, Rubrik, Tesla, Intel; Bellarmine
College Preparatory. *"I'm certainly not the best writer (way better at math) but I am going to start to be
more active on LinkedIn and share the small wins."* **No buying evidence exists for him — the report says
so explicitly** (*"Direct evidence about Zhang's software-evaluation or purchasing process… NOT FOUND"*),
and he is the only member with **zero P1 claims**. That is a correct, useful answer: do not lead with the
CTO.

**What per-person research changed about the sale.** Before it, the committee was five titles. After it:
the economic buyer has publicly named founder-led sales as his mistake; the second economic buyer has run
this exact scaling motion twice; the champion has done ABM as a job title and is shopping the category
this quarter; the user is a President's Club seller with five reports and a stated preference for
precision over spend; and the technical evaluator should not be contacted first. **That is the difference
between a contact list and a buying committee.**


---

## 5. The two-layer representation — backend truth, then a cheap model to make it human

This is the section the founder asked for. For each major view: **Layer 1** is the account's claims
rendered as the **exact production payload**, and **Layer 2** is the same payload turned into display copy
by a cheap model. Nothing here is a mock-up — the shapes were read off the real contracts first.

**Contracts read before writing a single byte** (all in this worktree):

| File | What it fixed |
|---|---|
| `apps/frontend/src/features/accounts/model/account.ts` | the accounts-list row (`AccountSchema`) |
| `apps/frontend/src/features/accounts/model/account-detail.ts` | `NeutralFactSchema`, `RelativeFactSchema`, `AccountProjectSectionSchema`, `CommitteeMemberSchema`, `AccountCoverageSchema` |
| `apps/frontend/src/features/accounts/model/account-contact.ts` | `AccountContactSummarySchema`, `GovernedFactSchema`, `ContactEvidenceSchema`, `RoleOnCommitteeSchema`, `ContactSignalsSchema` |
| `apps/frontend/src/features/accounts/model/vocabulary.ts` | the closed `Persona` (4 values) and `Freshness` enums; the rule that absence is `null`, never floored |
| `apps/frontend/docs/api-contracts/accounts.md` §"As-built backend read API (FI-2 slice 1)" | envelopes: list is `{data, meta}`, detail and profile are the bare object |
| `platform/api/clue_api/frontend_read/accounts_list.py` | `WireModel` — frozen, `extra="forbid"`, **camelCase alias generator** |
| `platform/api/clue_api/frontend_read/account_detail.py` | the neutral/relative split, and the rule at lines 411–419 that `insights[]` means "a relative field that is neither a score nor the narrative — today only a pack field that declares itself relative" |
| `platform/api/clue_api/frontend_read/contacts.py` | `_professional_facts` (registered order), `_signal_type_count`, `_evidence` (one chip per provider, **no URLs — G4**) |
| `platform/api/clue_api/frontend_read/committee.py` | the fail-closed `committee_member_displayable` gate |
| `libs/clue-core/clue_core/contact_research.py` | `CONTACT_PROFESSIONAL_FIELD_KEYS` — the frozen six |

Full payloads: `layer1_payloads.json`. Full display output: `layer2_display.json`.

### 5.1 View 1 — the accounts-list row

**Layer 1 — `GET /frontend/v1/accounts`**

```json
{
  "data": [{
    "id": "cd5ba6dc-c3bc-5413-9245-df235886b370",
    "name": "Probook",
    "domain": "probook.ai",
    "employeeCount": 52,
    "revenueBand": null,
    "logoUrl": null,
    "projects": [{ "projectId": "prj_clue_seriesa_verticalai",
                   "name": "Series A vertical-AI — fragmented SMB",
                   "addedVia": "discovered", "addedAt": "2026-08-26T21:40:00Z" }],
    "primaryProjectId": "prj_clue_seriesa_verticalai",
    "scores": [],
    "researchStatus": [{ "projectId": "prj_clue_seriesa_verticalai", "status": "needs_review" }],
    "updatedAt": "2026-08-26T21:40:00Z"
  }],
  "meta": { "total": 1, "nextCursor": null }
}
```

**What is honest about this row and worth saying out loud:** `revenueBand` is `null` because no source
published revenue — the contract's own rule is that absence is a legitimate answer, never floored to a
band. `scores` is `[]` because scoring is a rubric pass over claims and **no `account.scoring.*` claim was
written**: there was no ICP-spec version to score against. `fit`/`intent` being independently nullable is
precisely what makes "we have not scored this yet" expressible instead of fabricated as `0`.

**Layer 2 (Luna) — the row as a human reads it.** The list row is the one view that needs almost no
display model: name, domain, headcount and status are already human. The only value Layer 2 adds here is
`researchStatus: "needs_review"` → **"Ready for your review"**, and the `null` revenue band → render
nothing, not "Unknown". *(Cost attribution: this view is folded into the single Layer-2 call below.)*

### 5.2 View 2 — the account detail

**Layer 1 — `GET /frontend/v1/accounts/{accountId}` (16 `neutralFacts`, abridged to 6 here)**

```json
{
  "id": "cd5ba6dc-c3bc-5413-9245-df235886b370",
  "name": "Probook", "domain": "probook.ai", "aliases": ["Probook AI"],
  "registryIds": {},
  "hqGeo": { "city": "New York", "region": "New York", "country": "US", "postalCode": "10022" },
  "redirectedFrom": null,
  "neutralFacts": [
    { "fieldKey": "account.recent_funding", "value": { "amount_usd": 34000000.0, "round": "Series A" },
      "freshness": "fresh", "observedAt": "2026-08-26T21:40:00Z", "provider": "apollo" },
    { "fieldKey": "account.strategic_moves",
      "value": "Scale go-to-market team against surging demand; grow engineering and customer success",
      "freshness": "fresh", "observedAt": "2026-08-26T21:40:00Z", "provider": "exa_research" },
    { "fieldKey": "account.operational_pain",
      "value": "Scaling delivery capacity is a bottleneck: need to grow engineering, customer success and GTM to meet surging demand.",
      "freshness": "fresh", "observedAt": "2026-08-26T21:40:00Z", "provider": "exa_research" },
    { "fieldKey": "core.employee_count", "value": 52, "freshness": "fresh",
      "observedAt": "2026-08-26T21:40:00Z", "provider": "apollo" },
    { "fieldKey": "core.primary_tech_stack",
      "value": ["AI","Amazon AWS","Amazon CloudFront","Cursor","…","LinkedIn Ads","LinkedIn Recruiter","…","webpack"],
      "freshness": "fresh", "observedAt": "2026-08-26T21:40:00Z", "provider": "apollo" },
    { "fieldKey": "account.resonance.buying_culture",
      "value": { "culture_label": "founder-led, operator-oriented, deployment-committed",
                 "summary": "Founder-led origin with hands-on customer discovery and in-person deployments; public commitment to scale GTM and deliver outcomes post-sale." },
      "freshness": "fresh", "observedAt": "2026-08-26T21:40:00Z", "provider": "exa_research" }
  ],
  "projectSections": [{
    "projectId": "prj_clue_seriesa_verticalai", "name": "Series A vertical-AI — fragmented SMB",
    "addedVia": "discovered", "addedAt": "2026-08-26T21:40:00Z",
    "scores": [], "narratives": [], "insights": []
  }],
  "committee": [
    { "contactId": "8de16b15-…", "name": "George Eliadis", "persona": "economic_buyer",
      "roleOnCommittee": "economic_buyer", "projectIds": ["prj_clue_seriesa_verticalai"] },
    { "contactId": "f31ccd75-…", "name": "Mark Hoffman",  "persona": "economic_buyer",
      "roleOnCommittee": "economic_buyer", "projectIds": ["prj_clue_seriesa_verticalai"] },
    { "contactId": "0c49f3eb-…", "name": "Kate Blumberg", "persona": "champion",
      "roleOnCommittee": "champion", "projectIds": ["prj_clue_seriesa_verticalai"] },
    { "contactId": "61006812-…", "name": "Aaron Churba",  "persona": "champion",
      "roleOnCommittee": "champion", "projectIds": ["prj_clue_seriesa_verticalai"] },
    { "contactId": "f4ec4553-…", "name": "Lewis Zhang",   "persona": "technical_evaluator",
      "roleOnCommittee": "technical_evaluator", "projectIds": ["prj_clue_seriesa_verticalai"] }
  ],
  "coverage": {
    "researchedFieldCount": 16,
    "unresolvedFieldKeys": ["account.resonance.attrition_signal","account.resonance.employee_sentiment",
      "account.resonance.eng_blog_tone","account.resonance.public_frustrations","core.annual_revenue",
      "core.company_email","core.company_phone","core.revenue_band"]
  }
}
```

**Three structural facts this payload exposes, none of them cosmetic:**

1. **`projectSections[0].insights` is `[]` — and that is correct as-built.** `account_detail.py` routes by
   the field's *registered species*, and every FI-1-era "insight" family (`account.recent_funding`,
   `operational_pain`, `strategic_moves`, `account.resonance.*`) is `project_neutral` under the ratified
   §5.2 table, so they all land in `neutralFacts`. `insights[]` today means *only* "a pack field that
   declares itself relative". **This run registered no pack, so every P1 buying-intent signal it found is
   either flattened into `neutralFacts` or has nowhere to go at all.**
2. **`neutralFacts[]` has no rank.** The eight P1 rows sit alphabetically interleaved with the fifteen
   P2/P3 rows. `account.hiring_velocity_eng` (P2) sorts *first*; `core.primary_tech_stack` (P1 — because
   of what is *absent* from it) sorts last. The "why now" story is invisible to any client that renders
   the array in order. → **`PROPOSED-SLOT: neutralFacts[].priority`**, §7.1.
3. **The evidence span is not on the wire at all.** Every claim in `claims.json` carries a verbatim
   `evidence_span` and a `source_url`; `NeutralFactSchema` carries neither. The quote that makes a signal
   persuasive cannot reach the screen. → **`PROPOSED-SLOT: account.topSignals[]`**, §7.1.

**Layer 2 (Luna) — the same payload, rendered.**

> **Account summary**
> Probook is an information technology and services company building an AI operating system for
> home-services contractors, including plumbing, HVAC, and electrical businesses. Its system is built
> around dispatch and unifies intake, data cleaning, chat, outbound, and dispatch. Probook is at the
> Series A stage with 52 employees, 14 open positions listed, and $40M in reported total funding. It is on
> this list because it was discovered for the Series A vertical-AI project and its research status is
> needs_review.

> **Why now — top signals** *(as-built payload)*
> * **A $34M Series A creates room to scale the operating plan** — *"a16z is leading Probook's $34 million Series A"* · a16z.com
> * **Probook is scaling GTM, engineering, and customer success against demand** — *"scale its go-to-market team against surging demand, and grow engineering and customer success to deliver on it."* · globenewswire.com
> * **Delivery capacity is an explicit bottleneck across three functions** · globenewswire.com
> * **Its current technology footprint is broad enough to anchor a stack conversation** — *"current_technologies (30 detected) = AI, Amazon AWS, …"* · linkedin.com

**Humanised insight labels** — one per `neutralFacts` entry, 16/16 covered, in payload order, zero
fabricated keys:

| Priority | Raw `fieldKey` + value | Luna's label |
|---|---|---|
| P1 | `account.recent_funding` = `{"amount_usd":34000000.0,"round":"Series A"}` | **Raised $34M Series A** |
| P1 | `account.total_funding` = `{"amount_usd":40000000.0,"estimate_kind":"reported"}` | **Reported total funding: $40M** |
| P1 | `account.strategic_moves` = *(string)* | **Strategic move: Scale go-to-market team against surging demand; grow engineering and customer success** |
| P1 | `core.primary_tech_stack` = *(30-item array)* | Primary tech stack: AI, Amazon AWS, … webpack |
| P2 | `core.employee_count` = `52` | **Employees: 52** |
| P2 | `core.hq_location` = *(object)* | **Headquarters: New York, New York, United States, 10022** |
| P2 | `account.operational_pain` = *(string)* | Operational pain: Scaling delivery capacity is a bottleneck… |
| P2 | `account.resonance.buying_culture` = *(object)* | Buying culture: founder-led, operator-oriented, deployment-committed |
| P3 | `account.resonance.culture` = *(string)* | Company culture: Built by people from the trades… |

**The split works — and it fails in exactly one, very informative, place.** Luna's fourth "why now" item is
*"Its current technology footprint is broad enough to anchor a stack conversation."* That is a display
model doing its best with a bad payload. The real signal is that the stack contains **no CRM, no sales
engagement, no data provider and no ABM platform** — and `core.primary_tech_stack` is a flat `list[str]`
that **cannot encode absence**. Luna could not say the true thing because the backend could not serve it.
This is the clearest possible argument for `vertical_saas.gtm_stack` with its explicit `absent[]` array
(§7.2, and already v2's proposal).

### 5.3 The A/B that prices the missing slots

The same model, the same system prompt, run twice — once over the as-built payload, once over a payload
with `neutralFacts[].priority`, `topSignals[]` and a `project_relative` `vertical_saas.*` pack filled in.
Every other byte identical.

| | Run A — as-built | Run B — with proposed slots |
|---|---|---|
| Model / prompt | `openai/gpt-5.6-luna`, identical | identical |
| Prompt tokens | 17,232 | 18,849 |
| Completion tokens | 4,299 | 3,810 |
| Latency | 32.1 s | 26.5 s |
| **Cost** | **$0.00947** | **$0.00928** |
| "Why now" item 3 | *"Delivery capacity is an explicit bottleneck across three functions"* (a restatement of item 2) | **"Six open GTM roles signal active customer acquisition investment"** — *"We have a clearly defined target: the top home service operators in America. **The list exists.** The product is proven. What we need now is someone to go get them."* · jobs.ashbyhq.com |
| "Why now" item 4 | *"Its current technology footprint is broad enough to anchor a stack conversation"* | **"The GTM stack lacks CRM, sales engagement, data, and ABM tools"** — *"no CRM, no sales-engagement tool, no data provider and no ABM/intent platform are present; LinkedIn Ads and LinkedIn Recruiter are the only GTM tools detected"* · apollo.io |
| Account summary | *"It is on this list because it was discovered for the Series A vertical-AI project and its research status is needs_review"* — describes the CRM, not the company | *"It sells to US home-services contractors in plumbing, HVAC, and electrical, serving a **fragmented SMB market** … It is on this list for review because its Series A funding and **expanding GTM hiring** align with the project"* |

**The proposed slots cost $0.00019 less per account and turn two filler lines into the two lines that
actually sell the account.** The display layer was never the bottleneck; the payload was.

### 5.4 View 3 — the contacts table

**Layer 1 — `GET /frontend/v1/accounts/{accountId}/contacts`** (5 rows; 2 shown)

```json
{
  "data": [
    { "id": "0c49f3eb-…", "name": "Kate Blumberg", "title": "Director of Growth",
      "titleRestricted": false, "persona": "champion",
      "roleOnCommittee": { "value": "champion", "confidence": 0.9 },
      "linkedinUrl": "https://www.linkedin.com/in/kibrady12",
      "projectIds": ["prj_clue_seriesa_verticalai"], "signals": { "typeCount": 1 } },
    { "id": "f4ec4553-…", "name": "Lewis Zhang", "title": "Co-Founder / CTO",
      "titleRestricted": false, "persona": "technical_evaluator",
      "roleOnCommittee": { "value": "technical_evaluator", "confidence": 0.9 },
      "linkedinUrl": "https://www.linkedin.com/in/lewisfzhang",
      "projectIds": ["prj_clue_seriesa_verticalai"], "signals": { "typeCount": 1 } }
  ],
  "meta": { "total": 5 }
}
```

`signals.typeCount` is bounded by a two-key whitelist (`contact.facet.recent_post`,
`contact.facet.public_appearances`), so **George Eliadis's four distinct public statements score
`typeCount: 2`, and Kate Blumberg's four score `typeCount: 1`.** The contract's own docstring is explicit
that this counts *signal types*, not items — it is correct, and it is also the only trace of the
per-person research that reaches this table.

### 5.5 View 4 — one contact profile (the champion)

**Layer 1 — `GET /frontend/v1/accounts/{accountId}/contacts/{contactId}` for Kate Blumberg**

```json
{
  "id": "0c49f3eb-9f51-579b-99f7-6acb965af754",
  "name": "Kate Blumberg", "title": "Director of Growth", "titleRestricted": false,
  "persona": "champion", "roleOnCommittee": { "value": "champion", "confidence": 0.9 },
  "linkedinUrl": "https://www.linkedin.com/in/kibrady12",
  "projectIds": ["prj_clue_seriesa_verticalai"], "signals": { "typeCount": 1 },
  "accountId": "cd5ba6dc-…", "accountName": "Probook",
  "professionalFacts": [
    { "fieldKey": "contact.current_title",    "value": "Director of Growth",
      "observedAt": "2026-08-26T21:40:00Z", "provider": "apollo", "restricted": false },
    { "fieldKey": "contact.job_function",     "value": "master_marketing",
      "observedAt": "2026-08-26T21:40:00Z", "provider": "apollo", "restricted": false },
    { "fieldKey": "contact.job_level",        "value": "director",
      "observedAt": "2026-08-26T21:40:00Z", "provider": "apollo", "restricted": false },
    { "fieldKey": "contact.current_location",
      "value": { "raw": "New York, New York, United States", "country": "United States" },
      "observedAt": "2026-08-26T21:40:00Z", "provider": "apollo", "restricted": false }
  ],
  "evidence": [
    { "provider": "apollo",       "observedAt": "2026-08-26T21:40:00Z" },
    { "provider": "exa_research", "observedAt": "2026-08-26T21:40:00Z" }
  ],
  "redirectedFrom": null
}
```

**This is the most important payload in the report, because of what is missing from it.** Kate Blumberg is
the champion. This run spent **1 Apollo credit + $0.015 of deep research + 3 structuring passes** on her.
Her production contact profile serves **four facts, all four of them Apollo firmographics**, and two
provider chips with no timestamps that differ and no URLs.

Everything the research actually found about her has **no slot on this wire**:

| Researched fact | Field | Where it can go today |
|---|---|---|
| Verified/unavailable work email | `core.work_email` | **nowhere** — `CONTACT_PROFESSIONAL_FIELD_KEYS` is exactly six keys and does not include it |
| Branch → Survata → SafeGraph → Middesk → BuildOps → Probook, with dates | `contact.facet.career_history` | **nowhere** — no `contact.facet.*` key is on the profile wire |
| *"The martech hype cycle is relentless and Clay is everywhere right now…"* (2026-07-30) | `contact.facet.recent_post` | **nowhere** — only `signals.typeCount: 1` hints it exists |
| *"…building a demand generation engine that delivered for sales… inbound, ABM, events, lifecycle, and paid"* | `contact.facet.recent_post` | nowhere |
| Communication style: energetic, specific, revenue-oriented | `contact.facet.communication_style` | nowhere |
| Stated interests: martech and ABM, demand generation | `contact.facet.stated_interests` | nowhere |
| 3 grounded openers with hook + URL | *no registered field at all* | nowhere — **v2 raised this and it is still true** |
| The `source_url` behind any of the above | — | nowhere — `ContactEvidenceSchema` is `{provider, observedAt}`, URLs deliberately off the wire (G4) |

**Ten researched facts for this one person have no production surface.** That is not a bug in the read
layer — every one of those decisions is defensible in isolation (G4 is a privacy posture; the frozen six
are C0's semantic freeze). It is a **contract gap between what research now produces and what the
frontend can serve**, and phase-1 integration is exactly where it has to be resolved. See §7.3.

**Layer 2 (Luna) — the same payload, rendered.**

> **Kate Blumberg** · *Champion — Director of Growth*
> Kate Blumberg is Probook's Director of Growth, responsible for leading growth and building the marketing
> organization. She joined after serving as Director of Demand Generation at BuildOps and holding growth
> and demand-generation roles at Middesk, SafeGraph, and Survata; a verified work email is available.
>
> **How to open**
> * *"You shared that you joined Probook 'to lead growth and build out the marketing organization.' What is the first system you are putting in place?"*
>   — hook: her 2026-06-23 announcement · linkedin.com/posts/kibrady12_im-excited-to-share-…
> * *"At BuildOps, you focused on a demand-generation engine that delivered for sales across inbound, ABM, events, lifecycle, and paid. Which part carries over to Probook first?"*
>   — hook: her BuildOps retrospective · linkedin.com/posts/kibrady12_after-…-years-at-buildops-…

**Two honest defects in Layer 2, both material:**

1. **Luna wrote "a verified work email is available" for Kate Blumberg. It is not** — Apollo returned
   `email_status: "unavailable"`. Luna inferred it from the *other* four contacts' blocks, because the
   email is not on the profile payload at all and therefore its absence is not expressible either. **A
   fact that has no slot cannot be *denied* either** — this is the sharpest possible demonstration of why
   §7.3 matters. It is a hallucination, and it is the payload's fault, not the model's.
2. **Luna re-typed a URL and broke it.** It emitted
   `…/kibrady12_after-two-years-at-buildops-i-activity-7459629371444703232-esk_`; the real slug is
   `after-two-**incredible**-years-at-buildops-i-…`. **1 of 12 URLs (8%) was silently corrupted.**
   Mechanical fix, and it should be a hard rule: **the display model must never emit a URL.** The payload
   should carry an opaque `evidenceId` and the client resolves it; Layer 2 gets the id, never the string.


---

## 6. Claims summary

`claims.json` — **106 rows, 106/106 schema-valid, 30 distinct registered field keys, 6 entities, zero
invented keys.**

### 6.1 Composition

| Cut | Counts |
|---|---|
| By entity | account:probook **24** · george-eliadis **20** · kate-blumberg **17** · aaron-churba **16** · mark-hoffman **15** · lewis-zhang **14** |
| By source tier | tier 1 (`apollo`, `api`) **49** · tier 4 (`exa_research`, `llm_synthesis`) **57** |
| By structuring pass | deterministic Apollo adapter **49** · pass 1 broad extraction **30** · pass 2 priority sweep **15** · pass 4 per-person intent extractor **12** *(7 further rows across all passes were exact duplicates and deduped)* |
| By `use_class` (facet claims) | `professional-public` **41** · `personal-public-non-sensitive` **2** · `sensitive` **0** |
| Validation | 106/106 valid against the registered `value_schema`; every tier-4 row is `llm_synthesis`; every `contact.*` row carries `identity_binding`; every `contact.facet.*` row carries `use_class` |

**Registered fields exercised (30):** 7 account/core firmographic, 7 `contact.*`, **7 `contact.facet.*`**
(`alma_mater`, `career_history`, `communication_style`, `public_appearances`, `recent_award`,
`recent_post`, `stated_interests`), plus `core.work_email`, `core.primary_tech_stack`,
`account.recent_funding`, `account.total_funding`, `account.operational_pain`,
`account.strategic_moves`, `account.resonance.culture`, `account.resonance.buying_culture`,
`account.hiring_velocity_eng`.

**Registered account fields correctly left EMPTY (8):** `core.annual_revenue`, `core.revenue_band`,
`core.company_email`, `core.company_phone`, `account.resonance.attrition_signal`,
`account.resonance.employee_sentiment`, `account.resonance.eng_blog_tone`,
`account.resonance.public_frustrations`. **An empty, flagged field is a correct output.** These are the
`coverage.unresolvedFieldKeys` the account-detail payload serves.

### 6.2 Priority histogram

| Priority | Count | Share |
|---|---|---|
| **P1** — active buying intent | **30** | 28% |
| P2 — qualifying firmographics | 48 | 45% |
| P3 — context / background | 28 | 26% |

Per entity: account **8 / 15 / 1** · Eliadis **5 / 7 / 8** · Hoffman **5 / 6 / 4** · Blumberg **6 / 7 / 4** ·
Churba **6 / 6 / 4** · **Zhang 0 / 7 / 7**. Zhang having *zero* P1 rows is the annotation doing its job:
the CTO is real, confirmed and enriched, and there is no evidence he is in a buying motion. A ranked view
puts him last automatically instead of a human having to notice.

### 6.3 Defects found — the structuring lane is the weak link, and it is measurable

**(a) The cheap model systematically under-harvests the highest-value, lowest-frequency signal class.**
The run's best claim — Kate Blumberg's 2026-07-30 Riveter/Clay post — took **three passes** to extract:

| Pass | Shape | Prompt | Cost | Result |
|---|---|---|---|---|
| 1 | broad extraction, 5 subjects batched | "emit claims for the catalog" | $0.0113 | 32 claims, **missed it** |
| 2 | priority sweep, 5 subjects batched | charter explicitly named *"a tool they publicly praised or criticised"* as the top target | $0.0128 | 17 claims, **missed it again**, and emitted two rule violations (`"NOT FOUND"` as a value; an empty array) |
| 3 | single-purpose intent extractor, 5 subjects batched | one job only: pull buying-intent quotes | $0.0061 | **4 rows — all four for the first subject**, then stopped at 604 completion tokens |
| **4** | **the same extractor, ONE SUBJECT PER CALL** | identical prompt | **$0.0094** | **16 rows across all five people, including the Riveter post, "5 sellers and counting" and "GTM team inching up towards 20"** |

**4× the recall for 1.5× the price, from fan-out alone.** The failure was never comprehension — pass 3's
prompt was correct and it read the right report. It was **batching**: given five subjects in one context
the model satisfices on the first. This is a direct, measured confirmation of the platform's own
architectural bet (*"orchestrator/worker per account… workers return references"*) applied one level down,
to **structuring**: **one extraction call per subject, always.**

**(b) A semantically wrong claim passes schema validation and propagates cleanly to the screen.**
Pass 1 wrote `core.employee_range = {"label": "14 open positions listed", "min": 14, "max": 14}` from the
span `"Open Positions (14)"`. The field means *headcount band*. The value validates perfectly — right
type, required `label` present — so the 106/106 validation gate cannot see it, and Layer 2 then rendered
it faithfully as *"Open positions: 14 open positions listed."* **Both layers were faithful and the output
was wrong.** v2 hit the same class with `employee_count: 23`. The guard has to be a **semantic** field
check at write time (does this value plausibly mean what the field means?), not a schema check and
certainly not a display check.

**(c) The same field was written with two different meanings by the two lanes.**
`account.hiring_velocity_eng` — the deterministic Apollo adapter wrote **3** (open Engineering reqs, the
field's actual definition); pass 1 wrote **14** (total open positions). The merge's tier ranking resolves
it correctly to the tier-1 value of 3, but the tier-4 row survives in the store as a contender. This is
exactly the `current_value.conflict` vs corroboration-`conflict_flag` divergence already logged in
`CLAUDE.md` [M9.2×M1.2].

**(d) Five non-verbatim `evidence_span` values (out of 57 tier-4 rows, 8.8%)** failed the corpus-substring
check — mostly stitched-together quotes from two adjacent report sentences. Flagged in
`claims_summary.structuring_defects.unquoted_evidence`, not silently kept.

**(e) One unregistered key correctly refused:** pass 1 emitted `account.primary_tech_stack` (the real key
is `core.primary_tech_stack`); the validator dropped the row rather than repairing it.

**(f) Prompt caching finally engaged, and it is worth real money.** An accidental re-run of the account
structuring call (recorded honestly in §8.1 as an operator error) hit **17,536 cached prompt tokens** and
cost **$0.00436 instead of $0.00870 — a 50% saving on an identical call.** v2 measured `cached_tokens: 0`
on every run and listed catalog caching as the largest available structuring saving; this run is the first
evidence of the size of it.


---

## 7. PROPOSED — fields, slots, and one enum change

Everything here carries a real value found in this run, so nothing is speculative. Items marked
**[v2, re-confirmed]** were already proposed in the v2 report and are re-hit here with independent
evidence from a different account — which is the strongest argument any of them will get.

### 7.1 The signal-priority annotation — and what already exists

**Checked first, as instructed. `FieldDef.signal_class` exists and does NOT cover this.**
`libs/clue-core/clue_core/field.py:167-171`:

> *"The two-tier signal model (Doc C §1): fields sharing a `signal_class` are the cheap `scoring` proxy and
> the `deep` narrative of one signal — the research-schema compiler (M3.2) links them."*

`signal_class` is a **theme name declared at the FIELD** (`"growth"`, `"intent"`, `"<pack>_vertical"`) whose
job is to pair a Pass-A proxy field with its Pass-B narrative field. It answers *"which signal family does
this field belong to?"* Its sibling `pass_kind` answers *"cheap or deep?"*. **Neither answers "how
important is this particular claim, right now, for this ICP"** — which is per-**claim**, per-**ICP** and
**time-decaying**, and therefore cannot live on the field definition at all. Two claims of the same field
legitimately differ: `contact.facet.recent_post` holding *"Clay is everywhere right now"* is P1;
`contact.facet.recent_post` holding *"way better at math"* is P3. Same field, same `signal_class`,
different priority. They are orthogonal and both are needed.

| # | Proposal | Shape | Hypothesis |
|---|---|---|---|
| 1 | **`claim.signal_priority`** (a claim column, not a field) | `smallint NOT NULL DEFAULT 3 CHECK (signal_priority BETWEEN 1 AND 3)` | Rank is a property of the *claim*, not the field. Writing it at claim-write time (by the same rubric the structuring prompt already carries) makes ordering **server-authored and identical on every surface** — the account detail, the contacts table, the campaign brief and the export all sort the same way, and no client re-derives it. Composite with the existing `signal_class` (family) and `pass_kind` (depth): family + depth + urgency. Also the natural input to a decay job — a P1 timing claim older than 6 months should demote itself. |
| 2 | **`neutralFacts[].priority`** / `insights[].priority` on the wire | `z.number().int().min(1).max(3).nullable()` | Pure pass-through of (1). Without it, `AccountDetailSchema` gives a client no way to order 16 facts except alphabetically by `fieldKey` — §5.2 shows what that produces. |
| 3 | **`account.topSignals[]`** on `AccountDetailSchema` | `[{fieldKey, quote, sourceDomain, evidenceId, observedAt, entityId?}]` | The "Why now" card. Two things make it a real slot rather than a client-side filter: (a) the **quote** (`claim.evidence_span`) is not on the wire *anywhere* today, and a signal without its quote does not persuade; (b) an account's best "why now" signal is frequently a **CONTACT** claim (here: the champion's martech post), and the account payload has no path to contact claims at all. §5.3 measures the difference this makes: two filler lines become the two lines that sell the account, at $0.0002 *less* display cost. |

### 7.2 The `vertical_saas` industry pack **[v2, re-confirmed on a second account]**

v2 proposed six `vertical_saas.*` fields off Lassie. Every one of them had a real, unhoused value on
Probook too. Two are load-bearing enough to re-state with this run's evidence:

| # | `field_key` | Why this run needed it |
|---|---|---|
| 4 | `vertical_saas.gtm_stack` (`{as_of, crm[], outbound[], abm[], paid[], **absent[]**}`, `tenant_private`/`project_relative`) | **`core.primary_tech_stack` is a flat `list[str]` and cannot encode absence.** The qualifying signal on this account is that 30 detected technologies contain *no* CRM, *no* sales-engagement tool, *no* data provider and *no* ABM platform. §5.2 shows the display model reaching for *"broad enough to anchor a stack conversation"* because the true statement was unrepresentable. This is the single highest-value proposed field in either report. |
| 5 | `vertical_saas.open_gtm_roles` (`list[object]` with `title/department/location/url/posted_at`, `public_footprint`/`project_relative`) | Six reqs with quotable descriptions and posting dates are the most perishable and most quotable evidence of GTM intent that exists. Today they compress into one integer (`account.hiring_velocity_eng`) that is defined for *engineering* only, and the two lanes promptly disagreed about what it means (§6.3c). |
| 6–9 | `vertical_saas.target_vertical`, `.gtm_motion`, `.gtm_team_shape`, `.funding_runway_signal` | All four re-confirmed with Probook values (fragmented_smb / founder_led→outbound / 7 sales : 1 marketing : 6 open / Series A + 2 months + *"scale its go-to-market team against surging demand"*). Full schemas in the v2 report §7.1 — unchanged. |

Declaring these `project_relative` is what makes `projectSections[].insights[]` non-empty (§5.2 finding 1);
`layer1_payloads.json` → `_PROPOSED_SLOTS` → `example_if_pack_registered` shows exactly what lands there.

### 7.3 Contact-side slots — the largest gap this run found

| # | Proposal | Hypothesis |
|---|---|---|
| 10 | **`contact.facet.tool_evaluation`** — new registered field. `{"tool": str, "vendor_category": str, "stance": "praised"\|"criticised"\|"compared"\|"evaluating", "quote": str, "observed_at": date}`, `use_class: professional-public` | The highest-value personal buying signal that exists has **no typed home**. Kate Blumberg publicly comparing Riveter and Clay for ABM list-building, four weeks before the run, currently degrades into a free-text `contact.facet.recent_post` — untypeable, unqueryable, and invisible to any "show me every committee member currently evaluating a competitor" query. A typed field makes that a first-class ICP signal and an intent-scoring input. |
| 11 | **Widen the contact-profile wire** — either extend `CONTACT_PROFESSIONAL_FIELD_KEYS` or add a parallel `researchFacts[]` array to `AccountContactDetailSchema` | §5.5 is the argument: **ten researched facts about the champion have no production surface**, including the verified work email the platform paid an Apollo credit for. The frozen six are C0's semantic freeze and should stay frozen; the fix is a *second* array carrying the governed `contact.facet.*` claims with their `use_class`, so the display gate stays the same `display_allowed` predicate and nothing about the privacy posture changes. **This is a phase-1 integration decision, not a nice-to-have** — without it, per-person deep research is money the product cannot show. |
| 12 | **`contact.facet.openers`** **[v2, re-confirmed]** — `list[{opener, hook, source_url}]`, `use_class: professional-public` | Fifteen grounded openers were produced this run (3 per person × 5). There is still no registered field. They exist only in five markdown files. This is the most immediately actionable output of the entire pipeline and it has nowhere to live — for the second run in a row. |
| 13 | **`evidenceId` on every wire fact, and an evidence-resolution endpoint** | Two problems, one fix. (a) `ContactEvidenceSchema` is `{provider, observedAt}` with URLs deliberately off the wire (G4), so a reviewer cannot open the source of anything. (b) §5.5 defect 2: when the display model has to *re-type* a URL it corrupts one in twelve. Give every fact an opaque `evidenceId`; the display model never sees or emits a URL; the client resolves the id through the presign path. **Note the ordering constraint already on the books:** `CLAUDE.md` [B2×presign/frontend] says presign must be scope-gated before any consumer ships. |

### 7.4 The `Persona` enum is still too small **[v2, re-confirmed]**

`clue_core.enums.Persona` has four members — `champion`, `economic_buyer`, `technical_evaluator`,
`blocker`. Clue's own stated committee names a fifth role, the **user**. On this account **Aaron Churba**
(Director of Sales & Development, five sellers reporting to him, the person who would operate the product
daily) has no correct value and is recorded as `champion` alongside Kate Blumberg, who is a genuinely
different persona with a genuinely different message. v2 hit this with five of ten members; v3 hits it
with one of five — a smaller committee did not make the problem go away, it concentrated it.

Persona is the key for `(account, persona)` artifact addressing. Collapsing the user into the champion
means the champion's business-case mailer and the user's workflow mailer go to the same key. **Proposal
unchanged from v2:** add `USER = "user"` to `Persona`, the DB enum, the enum-parity test and a migration.
This is a contract-delta on frozen `core` and needs explicit ratification.

### 7.5 Canonical contributions **[v2, re-confirmed]**

`account.customer_count` (Probook: *"hundreds of locations nationwide"*, ten named customers) ·
`account.entity_disambiguation` (the HP ProBook exclusion, and the nine discarded Mark Hoffmans, are
durable audit evidence that target-lock happened and currently live only in prose) ·
`account.integration_ecosystem` (ServiceTitan — what their *product* connects to, which names their
customer's stack; distinct from `core.primary_tech_stack`, which is what they run internally) ·
`core.founding_year` (2024 — proposed independently by `gpt-5-mini` this run).


---

## 8. Cost analysis

### 8.1 Every call, actual (from `cost_ledger.json`)

| # | Provider | Call | Type | s | Cost | Cr |
|---|---|---|---|---|---|---|
| 1–3 | Exa | `d1/d2/d3` discovery | search/auto, 10 res | 4.7 | $0.02100 | — |
| 4 | Exa | `q1_probook_domain_lock` | search/auto, 10 res | 1.5 | $0.00700 | — |
| 5 | Exa | `gt1_owned_and_announcements` (8 pages) | contents | 0.5 | $0.00800 | — |
| 6 | Ashby | job board (13 reqs, full descriptions) | public posting API | 0.3 | **$0** | — |
| 7 | Apollo | `organizations/enrich` | api | 0.6 | $0 | **1** |
| 8–9 | Exa | `ct1`/`ct2` LinkedIn committee search | search/auto, **15 res** | 3.6 | **$0.02400** | — |
| 10 | Exa | `account_deep` (1-string schema) | **deep-reasoning** | 37.8 | **$0.01500** | — |
| 11–15 | Apollo | `people/match` × 5 (confirmed people only) | api | 2.2 | $0 | **5** |
| 16–20 | Exa | `person_deep_*` × 5 | **deep-reasoning** | 185.2 | **$0.07500** | — |
| 21 | OpenRouter | structuring pass 1 — account | `gpt-5-mini@minimal` | 31.5 | $0.00870 | — |
| 22 | OpenRouter | structuring pass 1 — contacts | `gpt-5-mini@minimal` | 44.0 | $0.01132 | — |
| 23 | OpenRouter | structuring pass 2 — priority sweep | `gpt-5-mini@minimal` | 32.9 | $0.01282 | — |
| 24 | OpenRouter | structuring pass 3 — batched intent *(experiment)* | `gpt-5-mini@minimal` | 8.8 | $0.00613 | — |
| 25–29 | OpenRouter | structuring pass 4 — per-person × 5 | `gpt-5-mini@minimal` | 32.3 | **$0.00940** | — |
| 30–31 | OpenRouter | **accidental re-run of calls 21–22 (operator error)** | `gpt-5-mini@minimal` | 77.2 | **$0.01682** | — |
| 32 | OpenRouter | **Layer 2 run A — as-built payload** | **`openai/gpt-5.6-luna`** | 32.1 | **$0.00947** | — |
| 33 | OpenRouter | **Layer 2 run B — proposed-slot payload** | **`openai/gpt-5.6-luna`** | 26.5 | **$0.00928** | — |
| | | **TOTAL** | | **~9.1 min** | **$0.23394** | **6** |

**The operator error, recorded rather than quietly dropped.** `step10_merge_validate.py` imported
`step9_structure` to reuse its stamping helper; step9's module body is not guarded, so the import
**re-executed both structuring calls** — $0.01682 of unintended spend, 7% of the run. Fixed by putting
step9 in cache mode before the import, with the cause commented at the site. It did produce one useful
number: the re-run hit 17,536 cached prompt tokens and cost **half** the original (§6.3f).

*OpenRouter numbers are `usage.cost_details.upstream_inference_cost`, not `usage.cost` — every model here
is BYOK, so `usage.cost` reads `0`. v2's finding #9, re-confirmed and now baked into `clue_lib.openrouter`.*

### 8.2 Unit economics — three corrections to v2

| Unit | v2 recorded | **v3 measured** |
|---|---|---|
| Exa neural search | "**$0.00700 flat**" | **per RESULT, not flat**: 10 results → $0.007, **15 results → $0.012**. v2 only ever ran 10-result searches, so it read a per-result price as a flat one. Budget `numResults × $0.0007`. |
| Exa `deep-reasoning` | $0.021–$0.030 (16/23/25 pages) | **$0.015 at 10 pages, on all six calls, with zero variance.** Combined with v2: ≈ **$0.0012–0.0015 per page retrieved**. Budget per call by expected page count, never by the $15/1k list price. |
| Exa `output.grounding` | "**empty array on every call**" | **POPULATED.** The account call returned 16 document-level citations (`{url, title}`) for the `report` field — *more* URLs than the 10 in `results[]`, so it names pages the synthesis reached that the result list does not show. Still document-level, **not** span-level, so it does not replace `evidence_span`; but v2's "do not design a pipeline that depends on it" is now too pessimistic. |
| Exa `contents` | $0.001/page | **confirmed** — 8 pages → $0.008 |
| Apollo org enrich / people match | 1 credit each | **confirmed**. `people/match` by `linkedin_url`+`domain` works and returns full `employment_history`. |
| `gpt-5-mini@minimal` | $0.25/M in, $2.00/M out | **confirmed**; and **prompt caching now engages** (0 → 17,536 cached tokens; 50% cost cut on a repeat call) |
| **`openai/gpt-5.6-luna`** | not measured | **≈$0.30/M in, ≈$1.20/M out** (derived: 17,232 in + 4,299 out = $0.00947). **≈$0.0093 per account for the whole display layer.** |

### 8.3 The production configuration, and what it costs per account

Excluding discovery (amortised separately), the three experiment calls (pass 3 batched-intent, Layer 2 run
A, and the duplicate structuring pair), the **recommended production pass for one account with a
five-person committee** is:

| Stage | Calls | Cost | Credits |
|---|---|---|---|
| Domain lock | 1 search | $0.007 | — |
| **Ground truth — own site + announcements + hiring index** | 1 `contents` (8 pages) + 1 free Ashby API call | $0.008 | — |
| Apollo org enrich | 1 | — | 1 |
| **Account deep research** | 1 `deep-reasoning` | $0.015 | — |
| **Committee ground truth (the v3 fix)** | 2 LinkedIn searches @ 15 results | **$0.024** | — |
| Contact enrichment | 5 × `people/match`, email only, no phone | — | **5** |
| **Per-person deep research** | 5 × `deep-reasoning` | **$0.075** | — |
| Structuring — account | 1 × `gpt-5-mini@minimal` | $0.0087 | — |
| **Structuring — per person (one call each)** | 5 × `gpt-5-mini@minimal` | **$0.0094** | — |
| **Layer-2 display copy** | 1 × `gpt-5.6-luna` | **$0.0093** | — |
| **Per account, all-in** | **17 paid calls** | **$0.1564** | **6** |
| *— of which research only (no display layer)* | | *$0.1471* | |

Discovery amortises separately: **$0.021 for ~15 distinct candidate companies** = $0.0014/candidate.

**Per-person cost, isolated (the founder's explicit ask):**

| Component | Per person | × 5 |
|---|---|---|
| Exa `deep-reasoning` profile | **$0.01500** | $0.0750 |
| `gpt-5-mini@minimal` structuring (one call per subject) | **$0.00188** | $0.0094 |
| Apollo `people/match` | **1 credit** | 5 credits |
| **Total per committee member** | **$0.01688 + 1 credit** | **$0.0844 + 5 cr** |

**Committee depth is 54% of the account's cash cost and 83% of its Apollo credits.** A 3-person committee
costs $0.1057 + 4 credits; a 6-person committee costs $0.1733 + 7 credits. Each extra person is a flat
**$0.0169 + 1 credit** — the cheapest marginal depth in the pipeline, and after v3 the most valuable.

### 8.4 v2 → v3, like for like

| | v2 (Lassie) | v3 (Probook) | Δ |
|---|---|---|---|
| Committee size | 10 | **5** | correct beats many |
| **Confirmed by a non-Apollo primary source** | **2 of 10** | **5 of 5** | the fix |
| Same-name contamination admitted | 2 (Swedish pet-insurance staff) | **0** | |
| People deep-researched | 1 | **5** | founder ruling #2 |
| Verified emails | 2 | 4 (1 genuinely unavailable) | |
| Claims | 52 | **106** | |
| Claims schema-valid | 52/52 | **106/106** | |
| Apollo credits | 3 | **6** | +3 = the price of correctness |
| Research cash / account | $0.0899 | **$0.1471** | +$0.057 |
| … of which the committee fix | — | $0.024 search + $0.075 deep + $0.0094 struct | |
| Display layer | not built | **$0.0093** | new |

**Getting the people right cost $0.057 and 3 Apollo credits per account.** For a product whose entire
premise is reaching the right person with the right argument, that is not a close call.

### 8.5 Extrapolation

**Uniform deep research on every account** (the thing the architecture says never to do):

| Accounts | Research | + display | + discovery | **Total** | Apollo credits |
|---|---|---|---|---|---|
| 10 | $1.47 | $0.09 | $0.01 | **$1.58** | 60 |
| 100 | $14.71 | $0.93 | $0.14 | **$15.78** | 600 |
| 1,000 | $147.10 | $9.28 | $1.40 | **$157.78** | 6,000 |

**Two-pass tiering, as the architecture actually specifies** — cheap scoring on all, deep on the top ~20%.
Pass A per account ≈ Apollo org enrich (1 credit) + a $0.0014 discovery share + the $0.007 domain lock:

| Accounts | Pass A (all) | Pass B (top 20%, full) | **Total** | Apollo credits |
|---|---|---|---|---|
| 10 | $0.08 | 2 × $0.156 = $0.31 | **$0.40** | 10 + 12 = 22 |
| 100 | $0.84 | 20 × $0.156 = $3.13 | **$3.97** | 100 + 120 = 220 |
| 1,000 | $8.40 | 200 × $0.156 = $31.28 | **$39.68** | 1,000 + 1,200 = **2,200** |

**Two-pass tiering is 4.0× cheaper on cash and 2.7× cheaper on Apollo credits than uniform depth** — a
wider margin than v2 measured (3.6× / 2.1×), because the deep pass got more expensive while Pass A did not.

**The v1 qualifier-first option, still available and now cheaper to justify.** Before spending $0.147 on an
account, one $0.007 10-result search plus the free Ashby/Greenhouse board fetch answers the two hard v3
gates — *is there a Series A in the last 24 months?* and *are they hiring GTM right now?* — for **$0.007
and 0 credits**. On this run that probe alone would have disqualified Avoca (wrong stage) and flagged Pie
(no GTM board). At 1,000 accounts, a $7 qualifier pass that removes half the list saves ~$16 of Pass-A
Apollo work and ~$15 of Pass-B depth. **Recommendation: keep it, and put the stage + hiring gates in it.**

### 8.6 Where the money goes, and the two cheapest wins available

| Stage | Share of the $0.1564 |
|---|---|
| Per-person deep research (5×) | 48% |
| Committee LinkedIn ground truth | 15% |
| Account deep research | 10% |
| Structuring (6 calls) | 12% |
| Display layer (Luna) | 6% |
| Ground truth + domain lock | 10% |

1. **Prompt-cache the field catalog and system prompts across accounts.** Measured this run at a **50%
   cut** on a repeat structuring call (§6.3f). Structuring is 12% of the account cost and the catalog is
   the fixed majority of every one of its six prompts. **Largest available saving, now with a number.**
2. **Drop the domain-lock search when discovery already returned the official site.** It did here —
   `probook.ai` was reachable from the d1 corpus. Saves $0.007 (4.5%). *(v2 said the same; still true.)*
3. **Do not** fold the committee search into the account charter to save $0.024. §3.1 measured what that
   costs: the account deep call returned *"CRO and director-level growth/sales leaders: NOT FOUND"* while
   the dedicated search found all three. That $0.024 buys the entire GTM leadership layer.


---

## 9. Verdict against the dossier bar

Compared section-by-section against `digestive-healthcare-of-georgia-p-c.md` — a different *domain*; the
target is section depth. **The row that failed in v2 is the row that changed.**

| Dossier section | v2 | **v3** |
|---|---|---|
| Account summary (name, site, size, locations, stack, fit) | Met | **Met** |
| Why this account is a strong fit, in priority order | Met | **Exceeded** — the priority annotation makes the ordering *data*, not prose, so every downstream view inherits it |
| Signals and evidence, quote + meaning + link per item | Met | **Met** — 30 P1 claims, each with a verbatim span and URL |
| Ownership, structure, expansion path | Partial | **Partial** — investors and PE-platform customers named; no cap table. Founding year now resolved (2024, Apollo + third-party) where v2's was unresolved |
| How to position the outreach (ROI numbers) | Partial | **Partial** — the account's own economics are quoted (2,873 jobs first month, 22→10 dispatchers, 74% call containment, 10% more revenue per job on a 40% leaner team); no Clue-side ROI model, which is the value-narrative layer downstream of research |
| **The people: decision makers, each identity-confirmed** | **Partial — 2 of 10 confirmed, 6 Apollo-only, 2 same-name contaminants** | **MET. 5 of 5 confirmed by a named non-Apollo primary source before Apollo was called; 5 of 5 corroborated by Apollo with exact title agreement; 0 contaminants; 14 same-name people found and explicitly discarded** |
| Career history per person | Met for 1 person | **Met for 5** — Apollo `employment_history` + the deep report's dated narrative, cross-checked |
| Education and training | Met for 1 | **Met for 5** |
| Published work | Met for 1 | **Partial for 5** — LinkedIn posts and one podcast appearance; none of these five has a byline or conference talk. Correctly reported as NOT FOUND rather than padded |
| Professional memberships | Gap | **Gap** — no analogue found; not invented |
| Awards and recognition | Partial (1) | **Partial** — Eliadis: 2020 U.S. Presidential Scholar + ACT 36; Churba: President's Club FY21/FY22; Zhang: perfect AMC 12. Three of five |
| Personal background, every item publicly sourced | Partial (5 hooks, 1 person) | **Met** — hooks for 4 of 5, all quoted, special-category excluded by charter and one edge case caught and dropped (§4.3) |
| Suggested conversation openers | Met (5, 1 person) | **Met (15, 3 per person)**, each naming its hook and URL |
| Fabrication audit | Claim-time validation | **Same, plus** an explicit same-name exclusion list per person, and a display-layer fidelity check that caught 1 hallucination and 1 URL corruption (§5.5) |

**The one structural gap v2 named — "no registry-grade identity anchor for people" — is now closed by a
different mechanism than v2 expected.** v2 assumed the answer was more Apollo credits. It was not: it was
**a primary-source URL per person, found on the open web before Apollo was called.** The company's own
team page, the company's own LinkedIn announcements and the person's own joining post are a stronger
anchor than a provider record, because they are *the employer asserting the employment*. Apollo's role is
now corroboration and email — which is what it is actually good at.

---

## 10. Honest gaps

1. **Kate Blumberg has no email.** The champion. Apollo charged a credit and returned
   `email_status: "unavailable"`. The `first-name@probook.ai` pattern is visible across the other four,
   but a pattern-guessed address is a fabrication and is not written. LinkedIn is the only confirmed
   channel to the most important person on this committee.
2. **Ben Cervantez is a known unknown.** A named co-founder with no title, no profile in the corpus and no
   Apollo record. Recorded as a gap, not admitted at low confidence.
3. **The company's careers page and its Ashby board disagree.** The deep call read `probook.ai/careers` and
   found *"Founding Account Executive"* and *"Business Operations Lead"*; the Ashby API (the system of
   record) has neither, and has six GTM roles the careers page does not list. A seventh req (Head of Sales)
   exists only on LinkedIn Jobs. **Three sources, three different role lists** — the run uses the Ashby API
   as authoritative and says so, but a production pipeline needs an explicit precedence rule here.
4. **No fit/intent scores.** Deliberate, unchanged from v2: scoring is a rubric pass over claims, and no
   ICP-spec version existed to score against. `scores: []` is the honest wire value.
5. **No employee-sentiment, attrition or public-frustration data.** A 52-person 2024-founded company has no
   Glassdoor footprint. Four registered `account.resonance.*` fields are correctly empty and are named in
   `coverage.unresolvedFieldKeys`.
6. **No ARR, no pricing, no revenue band.** Nothing public exists. Left blank.
7. **Fortune's exclusive is paywalled.** `/contents` returned the headline and one sentence behind an
   ad-block wall. Recorded as a partial fetch, not treated as a source.
8. **The structuring lane needs three shapes to reach full recall**, and one semantically-wrong claim
   passed every gate (§6.3b). Schema validation is necessary and not sufficient.
9. **The display layer hallucinated one fact and corrupted one URL** in 12 (§5.5). Both are payload-shape
   problems with mechanical fixes, but they are real and they shipped in `layer2_display.json`.
10. **The compliance charter's religion exclusion has a soft edge** — a *field of study* named
    "Religion/Religious Studies" is not a religious belief, and the model surfaced it. Caught by hand here.
    A production gate needs the rule written at the field-of-study level, not the topic level.

---

## 11. Wire findings worth keeping (new in v3)

1. **`output.grounding` is now POPULATED on Exa `deep-reasoning`** — 16 document-level `{url, title}`
   citations for the `report` field, including pages not present in `results[]`. **This reverses v2's
   finding #3.** Still not span-level, so `evidence_span` extraction remains necessary.
2. **Exa neural search is billed PER RESULT, not flat.** 10 → $0.007, 15 → $0.012. v2's "flat $0.007" was
   an artefact of only ever asking for 10.
3. **Exa `deep-reasoning` was $0.015 on all six calls at 10 pages each** — zero variance. With v2's
   16/23/25-page data points: ≈$0.0012–0.0015 per retrieved page.
4. **Ashby's public job-board API is free, complete and authoritative** —
   `https://api.ashbyhq.com/posting-api/job-board/<slug>?includeCompensation=true` returns every req with
   `descriptionPlain`, `jobUrl` and `publishedAt`. **It 403s on urllib's default User-Agent** and needs a
   browser UA. Best evidence-per-dollar in the run at exactly $0. Greenhouse and Lever have equivalents;
   registering them as sources is a cheap, high-yield resolver.
5. **Apollo `people/match` accepts `linkedin_url` + `name` + `domain` together**, returns
   `organization.primary_domain`, and that field is a reliable same-name gate: 5/5 admitted here, and it is
   the check that would have rejected v2's pet-insurance contaminants.
6. **Exa search with `includeDomains: ["linkedin.com"]` + `includeText: ["<Company>"]` is the committee-
   discovery primitive.** It returns profiles *and* the person's own announcement post *and* the company's
   announcement post — three corroborating artefacts per person, in one $0.012 call. This is what v2 was
   missing.
7. **The account deep-research charter cannot find the GTM leadership layer**, even when the charter
   explicitly asks for "every named executive and GTM leader… including the CRO and any director-level
   growth/sales leaders". It returned NOT FOUND for all three people that the dedicated search found. Two
   different retrieval problems.
8. **Batching subjects into one structuring call destroys recall on rare, high-value signals.** Measured:
   4 rows batched vs 16 rows one-subject-per-call, same prompt, same model, 1.5× the price. **One
   extraction call per subject.**
9. **OpenRouter prompt caching now engages for `gpt-5-mini`** (17,536 cached tokens; 50% cost cut on a
   repeat call). v2 measured 0 on every run.
10. **`usage.cost` is still 0 under BYOK.** `usage.cost_details.upstream_inference_cost` is the real
    number, for Luna as well as for gpt-5-mini.
11. **A display model must never emit a URL.** Given URLs as strings it re-types them and corrupts ~8%.
    Pass an opaque id.

---

### Files

| File | Contents |
|---|---|
| `CLUE-SAMPLE-RUN.md` | this report |
| `claims.json` | 106 stamped claim rows, each with `priority` |
| `claims_summary.json` | counts, priority histogram, per-pass attribution, validation, defects, model-proposed fields |
| `committee.json` | the five confirmed members: persona, confirmation URL + quote, Apollo admission verdict, email status, employment history |
| `cost_ledger.json` | every call: provider, op, latency, cost, credits, token usage |
| **`layer1_payloads.json`** | **Layer 1** — all four production payloads + the `_PROPOSED_SLOTS` block |
| **`layer1_payloads_proposed.json`** | the same account with `priority`, `topSignals[]` and the `vertical_saas.*` pack filled |
| **`layer2_display.json`** / **`layer2_display_proposed.json`** | **Layer 2** — Luna's display copy for run A and run B, with token usage and cost |
| `account_report.md` | the Exa account deep-research report (15,781 chars, 23 NOT FOUND markers) |
| `person_report_{eliadis,hoffman,blumberg,churba,zhang}.md` | the five per-person deep-research reports (81,294 chars total) |
| `structuring_bundle_*.txt` | the exact prompts sent to each structuring pass |
| `raw/` | every API response, verbatim |
| `step1..step13*.py` | every step, re-runnable; `--from-cache` where a re-run would re-spend |
