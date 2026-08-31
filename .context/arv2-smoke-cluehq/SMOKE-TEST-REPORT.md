# Clue smoke test — we pointed the platform at Clue's own customers

**Run date:** 2026-08-31 · **Client:** Clue (`cluehq.ai`) · **Two agents:** A (ICP + discovery), B (research + contacts + database)
**Total cost:** **$0.51 in cash + 32.5 AI Ark credits** · **10.4 minutes** of provider time · **203 database rows**
All artifacts in `.context/arv2-smoke-cluehq/`. Every number below came out of a real API response that is saved on disk.

---

## 0. What this test was, in one paragraph

We ran Clue's own pipeline on Clue. Agent A read cluehq.ai, worked out who Clue should sell to, searched the
web for candidates, and picked five companies — with a **prediction** of which one would be hottest. Agent B
then did the real work on those five: read their websites, ran one deep research pass per company, looked up
their people, bought verified email addresses, went hunting for bad news, and turned everything into a
structured database of sourced facts. The point was not to find leads. The point was to find out **whether the
machine tells the truth, how fast it is, and what it costs** — and to check Agent A's predictions against what
the research actually found. Two of the five predictions were wrong, and the reasons why are the most useful
part of this document.

**Headline:** the five accounts cost **10 cents each, end to end.** The single most valuable fact in the whole
run — "is that job advert still open?" — cost **nothing** and took **0.2 seconds**, and it overturned the
ranking that $0.18 of AI search had produced.

---

## 1. Can we trust Exa on a brand-new company? (Agent A's test, on cluehq.ai itself)

Agent A fetched Clue's own website two ways: directly, and through Exa's search index. Verdict:

- **Clue is in Exa's index and ranks #1** for a plain-English description of its business, ahead of Factors.ai,
  Abmatic, Clari and others. For a company this young that is better than expected.
- **The indexed copy was not stale — at all.** Agent A pulled the cached copy and a forced fresh crawl and the
  two were byte-for-byte identical (same 4,477 characters, same hash). That trick — cached vs live, compare
  hashes — is a **1-second, $0.002 freshness audit** you can run on any page that matters.
- **The index is only as deep as the site.** Exa holds exactly one page for cluehq.ai, because there *is* only
  one page. Every route a researcher would guess (`/product`, `/pricing`, `/about`) and both footer links
  (`/privacy`, `/terms`) return **404 on the live site**. Worth fixing — a buyer's lawyer will click those.
- **Exa's text extraction quietly drops interactive tab labels.** The strip naming Clue's five agents
  (Deep Research · Campaign Brief · Microsites · Paid Media · Direct Mail) vanished from Exa's copy. A human
  still gets the idea from the prose; an automated extractor looking for "the list of modules" gets nothing.

**The rule this gives us:** trust Exa for finding things and for reading the body of a page. Do **not** conclude
"this company doesn't have X" from Exa alone. A direct fetch costs $0, takes a third of a second, and returned
**6× more raw text**. Agent B's run confirmed this at scale — see §7.

---

## 2. The ICP, on one page

> **A US-headquartered, Series A–C B2B software company selling a high-ticket product to a small, named list of
> accounts, whose marketing team is 2–15 people, which has publicly committed to an account-based motion
> (it is hiring for it), and which has not already installed an enterprise ABM platform.**

Three rules are pass/fail, not scored:

| Gate | Test |
|---|---|
| **US** | Headquarters in the United States |
| **Series A or later** | A named priced round, with a date and at least one named investor |
| **Pain you can count** | At least one citable, dated piece of evidence that account-based work is a bottleneck, **with a number attached** |

The third rule does all the work. The strongest form of it is a **live job advert** for the exact seat Clue
replaces — because that advert names the job, carries a salary band (the price anchor), and its **age** is the
intent signal. A 105-day-old ABM req means they cannot hire it.

Everything else is a 100-point score: 35 points for countable pain, 25 for the sales motion, 20 for stage and
size, 15 for an open seat / timing, 5 for whether LinkedIn ads and physical mail would actually land.
Disqualifiers remove an account outright: consumer, self-serve-only, an ABM platform already installed,
below Series A, non-US, **or a direct competitor**. That last one fired in this run.

---

## 3. Every search we ran, and what it returned

### Agent A — discovery (25 searches, $0.175)

| # | Query (verbatim) | What came back | Kept / discarded |
|---|---|---|---|
| 1 | `Clue cluehq.ai agentic ABM platform AI agents for account-based marketing` | 10 results, cluehq.ai at #1 | Kept — proved Exa indexes Clue |
| 2 | `Clue agentic ABM platform` (restricted to cluehq.ai) | Exactly 1 result | Kept — proved the domain is 1 page deep |
| 3 | `US Series B B2B SaaS company selling to large enterprise named accounts with a small marketing team running account-based marketing campaigns` | 10 | Kept — sourced Cogent, Harmonic |
| 4 | `Series A or Series B US healthcare software company selling to hospitals, health systems and payers…` | 10 | Kept — sourced Arintra, Translucent, Prosper |
| 5 | `Account Based Marketing Manager job opening: build and maintain the target account list, research accounts, run 1:1 ABM campaigns for our top accounts` | 10 | **Best query of the run** — sourced Zafran + Harmonic reqs |
| 6 | `Demand Generation Manager job description: account research, target account lists, personalized outbound campaigns, direct mail and field marketing` | 10 | Kept — sourced Cogent's Head of Demand Gen |
| 7 | `raises Series B funding to expand its enterprise go-to-market and sales team, B2B software company, United States` | 10 | Kept — sourced Vendelux, Uptiq |
| 8 | `we spent weeks researching accounts to personalize outbound and only shipped a handful of campaigns — B2B marketing leader writing about ABM being too slow` | 10 | **Discarded — total failure.** Returned vendor blog posts, no founder complaints. See §8. |
| 9 | `venture-backed US fintech software company selling software to banks and credit unions…` | 10 | Kept — sourced Uptiq |
| 10 | `venture-backed US B2B marketing services company running account-based marketing programs…` | 10 | Mostly discarded — agencies rarely have a priced round |
| 11–20 | Ten verification searches, one per finalist (`<company> funding round investors headquarters`) | 5 each | Kept — confirmed US + Series A+ for all finalists |
| 21–25 | Five job-board checks (`<company> marketing demand generation growth job opening`) | 5 each | **Two gave false negatives** — see the Arintra finding in §8 |

### Agent B — research (21 Exa calls, $0.271; plus 40 free fetches)

| Label | Query / call | What came back | Verdict |
|---|---|---|---|
| `b0_ashby_*` | Ashby public job-board API for 6 companies (**free**) | 4 live boards (25/29/5/29 jobs), 2× 404 | **The highest-value call in the run.** Answered "is the req still open" for four accounts in 1.3 seconds total. |
| `b1a_contents_*` | Exa page reads, 17 URLs across 5 accounts | 16 served, 1 genuine 404 | Kept — the same 17 URLs were also fetched free (§7) |
| `b1b_deep_*` | 5 × deep-reasoning dossiers | 15.2k–21.1k characters each, 26–52 "NOT FOUND" markers each | Kept — the backbone of the report |
| `b1d_g_zafran_mktg` | `Zafran Security marketing team Head of Growth Marketing Nick Fisher VP Marketing…` | **Named the whole 9-person marketing team** + the hiring manager | Best gap-fill of the run |
| `b1d_g_cogent_mktg` | `Cogent Security Cameron Coles VP of Marketing Alexander Semien Head of Growth…` | Found both leaders + 4 quotable posts | Kept |
| `b1d_g_harmonic_abm` | `Harmonic Security Ana Corio Director of Demand Generation ABM manager hired…` | Found the hiring manager and her ABM advert | Kept |
| `b1d_g_uptiq_agency` | `Uptiq GrowthSpree ABM agency engagement 2026 still working together…` | Found the case study the deep pass had missed | Kept |
| `b2_contact_*` | 3 × deep-reasoning person profiles | 13.2k–20.0k characters | Kept |
| `b3_n_zafran / n_cogent / n_harmonic` | Criticism-hunting searches | 1 serious finding, 2 clean | Kept — see §5 |
| `b3_t_arintra` | Agent A's falsification probe | **Overturned Agent A's "zero hiring signal"** | Kept — see §8 |

---

## 4. The five accounts

Scores are out of 100 against the ICP rubric. "Predicted" is Agent A's cheap-evidence guess; "researched" is
after Agent B's work.

---

### 4.1 Zafran Security — `zafran.io`
**Predicted fit 81.0 → researched fit 87.0.** Predicted intent rank **4** → researched intent rank **1**.
*Cybersecurity, threat exposure management. New York + Tel Aviv. ~141 people. $130M+ raised.*

**Agent A's headline question was: is that ABM job advert still open after 75 days? The answer is YES.**

We checked it directly against their applicant-tracking system, not by guessing:

> `title: "Senior Manager, ABM & Integrated Campaigns"`, `department: "Marketing"`, `location: "USA"`,
> `publishedAt: "2026-06-17"`, **`isListed: true`** — read live from Ashby's public API on 2026-08-31.

And it is worse than 75 days. The hiring manager advertised it on LinkedIn on **2026-05-18**:

> "Our marketing team at Zafran Security is expanding! 🚀 I'm hiring a Senior Manager, ABM & Integrated Campaigns."
> — Vari Kaur, Head of Growth Marketing

That is **105 days of trying to hire one person**, and they still have not. Per Agent A's own falsification
test, Zafran's intent should be revised **up**, materially — and it is the single strongest buy-versus-build
signal in the set.

**What the job advert asks the human to do — this is Clue's product description:**
> "Own ABM from the ground up: 1:1 programs… 1:few cluster plays… and scaled 1:many motions"
> "define which accounts matter most, how they're tiered, and what a coordinated go-after looks like"
> "Map buying groups"
> "If you need a large team and a large budget to do great work, this role is probably not for you."

**The marketing team, named** (a third-party directory, `rocketreach.co/zafran-security-marketing-department`):
> "Zafran Security's Marketing department is led by Nick Fisher (VP of Marketing) and has 9 employees."
> Kelly Whelan (Sr Manager, Marketing Ops) · Molly S (Director of Product Marketing) · Matheus Turle (Field
> Marketing Manager, Central) · Bridget Armbrust (Sr Field Marketing Manager, East) · Karlyanna Burton
> (Director, Events and Field Marketing) · Jules Gross (PMM intern) · Vari Kaur (Head of Growth Marketing)

Nine marketers, with field and events covered — and **no ABM person**, because that seat has been vacant for
three and a half months. They also have **two other open marketing reqs** (Director of Product Marketing;
Sr Technical Marketing Manager, both published 2026-06-17 and both still listed).

**Tooling — Agent A's second bet, now tested with a real source rather than inference.** A job listing for
Zafran's Head of Growth Marketing published its required tool list:
> "Chatgpt, Claude, CMS Platforms, Gemini, GEO, Google Analytics 4, Google Workspace, **Hubspot**, Hubspot AI,
> **Jasper**, Linkedin Ads, Linkedin Insights, **Make**, **N8N**, Perplexity, SEO, **Zapier**"

HubSpot plus a pile of automation glue. **No 6sense, Demandbase, Terminus, RollWorks, Mutiny, Folloze, Influ2
or Madison Logic anywhere.** The ABM req asks for "Proficiency in Salesforce, HubSpot and major ABM platforms"
— they *want* one, they haven't *got* one. **One important caveat:** Vari Kaur's personal profile lists
"Marketo, HubSpot, Salesforce, **6sense, Demandbase**, ZoomInfo" among her skills. That is *her* experience,
not Zafran's stack — but it means she already knows the category, and she may have a favourite.

**Money:** $60M Series C led by Menlo (2025-12-02), **plus two strategic investments Agent A missed** —
Amex Ventures (2026-02-24) and Cisco Investments (2026-07-22). Company line: "Zafran Triples ARR". The actual
ARR number is **NOT FOUND** — the only figure anywhere is a press estimate of "around $20M ARR", not confirmed.

**Committee**

| Persona | Person | Title | Confirmed by | Email | Status |
|---|---|---|---|---|---|
| `economic_buyer` | **Nick Fisher** | VP of Marketing (since Apr 2024) | zafran.io/about + AI Ark (`totalElements: 1`) | `nick@zafran.io` | **VALID / SMTP — verified** |
| `champion` | **Vari Kaur** | Head of Growth Marketing (1yr 3mo) | Her own hiring post + AI Ark | `vari@zafran.io` | **VALID / SMTP — verified** |
| `user` | *(vacant)* | Senior Manager, ABM & Integrated Campaigns | Live on Ashby, 105 days | — | The seat Clue fills |
| context | Sanaz Yashar | Co-Founder & CEO | AI Ark + company announcements | not bought | — |
| context | Tom Anthony | SVP, Global Sales | zafran.io/about + AI Ark | not bought | — |

---

### 4.2 Cogent Security — `cogent.com`
**Predicted fit 80.0 → researched fit 92.5.** Predicted intent rank **1** → researched intent rank **2**.
*Cybersecurity, AI vulnerability management. San Francisco (GTM in New York). ~49–62 people. $53M raised.*

Agent A was right that this is the textbook shape. The research made it stronger, not weaker.

**They are not hiring one marketer. They are building an entire go-to-market org at once.** Ten live
GTM/marketing reqs on their board today, six of them posted in the last 17 days:

| Req | Published | Days open |
|---|---|---|
| Head of Demand Generation (New York) | 2026-08-14 | 17 |
| Sales Enablement Lead (New York) | 2026-08-14 | 17 |
| Sales Operations Analyst (New York) | 2026-08-21 | 10 |
| **Field Marketing Manager (New York)** | 2026-08-21 | 10 |
| Director of Product Marketing (Remote US) | 2026-02-18 | 194 |
| Sr. Manager, Content and Community | — | — |

**Agent A scored "public founder complaint about GTM cost" as zero for every account. It was wrong — this
account has one.** The Head of Growth posted publicly on 2026-08-14:
> "Black Hat made it very clear that Zach Van Keulen, Andrew Cuzzone, and I need more teammates."
> — Alexander Semien, Head of Growth

Three people ran Black Hat and came back saying they cannot cover the ground. That is the pain, self-declared,
dated, and quotable.

**The job advert describes Clue's job:**
> "Build ABM and whale-hunting plays for named accounts, including competitive replacement, category education,
> executive outreach, and sales follow-up."
> "Scale field and channel as a core pipeline engine: repeatable event formats, regional plans, account
> targeting, rep/partner workflows."

**And there is a warning in it too.** Their Growth Lead posting says they intend to build:
> "signals flowing in from every direction: intent data, competitive engagement, account intelligence, event
> interactions, and product usage" … the role builds "**the account intelligence layer, the intent layer, and
> the automation**."

That is a company that may decide to build what Clue sells. It is the single biggest risk on this account.

**Traction is real and public:** named customers **Alteryx, Valvoline Instant Oil Change, CSC Generation,
University of the Pacific, Upwind**; "already working with dozens of Fortune 1000 companies"; and outcome
claims of "**3x in vulnerability management team output**" and a "97% reduction in exposure window". The CEO
committed publicly: "We're going to triple the team over the course of this year."

**Committee**

| Persona | Person | Title | Confirmed by | Email | Status |
|---|---|---|---|---|---|
| `economic_buyer` | **Cameron Coles** | VP of Marketing (since Nov 2025) | AI Ark + his own post "I'm thrilled to announce that I'm joining Cogent Security as VP of Marketing!" | `cameron@cogent.com` | **VALID / SMTP — verified** |
| `champion` | **Alexander Semien** | Head of Growth (since Aug 2025) | AI Ark + LinkedIn posts | **not found** | AI Ark's search index has him; its **export endpoint 404s on the same URL** (see §8) |
| `user` | *(vacant)* | Head of Demand Generation | Live on Ashby, 17 days | — | The seat Clue fills |
| context | Vineet Edupuganti | Co-founder & CEO | cogent.com/company/about | not bought | — |
| context | Justin Jancaric | Founding GTM Sales Leader (Feb 2026) | AI Ark | not bought | — |
| **excluded** | ~~Sheryl A. Culliver-Turner~~ | Founder & CEO, **sigma-Cogent Solutions, LLC** | AI Ark roster | — | **Different company — rejected by the same-name rule** |

---

### 4.3 Harmonic Security — `harmonic.security`
**Predicted fit 79.5 → researched fit 77.0.** Predicted intent rank **2** → researched intent rank **3**.
*AI data security / AI governance. San Francisco + London. ~56–69 people. ~$26M raised.*

**Agent A's #2 pick is the one the research damaged most — and the reason is a fact only a live check could find.**

Agent A cited an open req, "Account-Based Marketing Manager, Strategic Accounts", $93K–$108K. We looked up that
exact requisition ID on Harmonic's live job board today. It returns:

> `<title>Business Development Representative - East @ Harmonic Security, Inc</title>`

**The ABM requisition has been converted into a sales-development role.** Harmonic has five open jobs in total
and not one of them is an ABM or marketing seat. The budget that was going to buy an account-based marketer is
now buying a cold-calling BDR.

**But it is fresher than it looks, and that cuts the other way.** The hiring manager was still advertising it
three weeks ago, on **2026-08-10**:

> "Hiring post! 📣 I'm hiring an ABM (account based marketing) manager for our most strategic accounts.
> There'll be the classic stuff: **account mapping, outreach, direct mail, events** + some weird creative stuff
> nobody's tried yet 🤓 Whatever gets Harmonic Security in front of the right folks."
> — Ana Corio, Director of Demand Generation

**"Account mapping, outreach, direct mail, events" is a four-item list of Clue's product.** This is the single
best sentence for Clue in the entire run. Whatever happened in the last three weeks — hired quietly, or gave up
— the budget conversation happened *this month*.

**Corrections to Agent A's facts.** The Series A was **$17.5M led by Next47, announced 2 October 2024** — not
April 2025, and "N47" was a misreading of "Next47". That makes the last round **23 months old**, outside the
ICP's 24-month freshness window, not 16 months. Also: the "$1M annual revenue" figure Agent A flagged is an
automated LinkedIn estimate and should never be repeated as fact. The real traction evidence is the company's
own "enterprise customers already in double figures" (Oct 2024) and one named logo, Advisor360.

**The deep research pass said "marketing leader: NOT FOUND". The people lookup found her in one call** —
Ana Corio, Director of Demand Generation since Sep 2024, plus a six-person marketing team she names herself:
Michael Marriott, Mariana Padilla (Community Evangelist), Lexy Marchbank (Director of Events), Tyler Chonoles
(Growth & Demand Gen Marketing Manager), Maya Smith (Brand Director), Jackson Harrower (Product Marketing Manager).

**Committee**

| Persona | Person | Title | Confirmed by | Email | Status |
|---|---|---|---|---|---|
| `champion` | **Ana Corio** | Director of Demand Generation (since Sep 2024) | AI Ark + her own hiring posts | `ana@harmonic.security` | **VALID / SMTP — verified** |
| `technical_evaluator` / `user` | **Tyler Chonoles** | Growth and Demand Gen Marketing Manager | AI Ark + Ana Corio's post | `tyler@harmonic.security` | **VALID / SMTP — verified** |
| `economic_buyer` | Alastair Paterson | CEO & co-founder | Series A coverage | not bought | No VP Marketing or CMO exists — **NOT FOUND** after two passes |
| context | Jessica Couto | VP Channels & Alliances (Oct 2025) | AI Ark | not bought | — |

---

### 4.4 Vendelux — `vendelux.com` — **DISQUALIFIED (competitor)**
**Predicted fit 66.5 → researched fit: VOID.** Predicted intent rank **3**.
*B2B event marketing intelligence. New York. 60+ employees (company claim). $71M raised (company-reported).*

Agent A flagged this as the thing to check first, and said "check this first" for good reason. **The answer is
that Vendelux already sells AI go-to-market agents.** In their own words:

> "**Vendelux Meetings** extends our platform by turning insights into pipeline — **using AI to identify
> high-value attendees and proactively book 1:1 meetings** between our customers and their ideal prospects at
> events." — from their own live job advert, 2026-08-27

> The Series B announcement says Vendelux pairs "proprietary attendee intelligence with **agents that book
> qualified meetings** for teams"; their product guide says ChatVDX "**auto-generates three sub-campaigns**"
> with "multi-step email sequences", and their Meetings team runs a "28-day cadence".

Account intelligence, campaign generation, outbound sequencing, meeting-booking agents, CRM attribution. That
is the disqualifier in the ICP, word for word: *"sells ABM orchestration, AI SDR/GTM agents… they are a
competitor, not a customer."* They also have **HubSpot Ventures** on the cap table.

**This is painful, because on hiring signals they were the hottest account in the set:** a **Head of Growth
Marketing** req at $175K–$215K published **four days before this run**, a Revenue Operations Lead published the
same day, and an "Outreach Campaign Operations Manager" that has been open since 2026-04-21 — **132 days.**
29 open roles in total. If they were not a competitor they would rank second on intent.

**Other corrections:** the CEO is **Alex Reynolds**, not the name in our target lock — the research model
refused our supplied fact and cited their About page instead, which is exactly the behaviour we want. Total
funding is **$71M** (company-reported), not $66.4M. And the "Growth Marketing Lead" req Agent A found is gone
— it was replaced by the more senior Head of Growth Marketing four days ago.

**Recommendation: move Vendelux from the target list to a partner/competitor watch list.** Their Head of
Marketing is Tanya Peress (since Jul 2025); we have 12 of their people mapped if that changes.

---

### 4.5 Uptiq (UPTIQ, Inc.) — `uptiq.ai`
**Predicted fit 67.5 → researched fit 70.0.** Predicted intent rank **5** → researched intent rank **5**.
*AI agents for banks, credit unions and lenders. McKinney, Texas. ~151 people. $55M+ raised.*

Agent A said Uptiq had already solved ABM with an agency, and that this made it the slowest sale in the set.
**Confirmed, with the actual numbers.** We read the case study Agent A could only see the title of:

> "A 120-day, multi-layered ABM motion across four lending segments turned **$2,700 of ad spend into $400K+ in
> pipeline** — with CFO-level engagement across 150+ enterprise accounts."
> "**3,874 ABM connections at 12.9% acceptance, a 23% reply rate**, and 50 interested prospects."
> "Closed deals including **$50K from Nubank** and a confirmed $100K Equipment Finance opportunity."
> "Events were the top lever: 30–50% conversion per event, lifting replies 3–4× over cold outreach."
> "**80% of opportunities came via LinkedIn** — personalized messaging plus human follow-up beat email."
> — GrowthSpree case study, published 2026-05-28

That is a company that has *proved* account-based marketing works for it, on a $2,700 budget, and knows the
exact conversion numbers. It is also a company that outsourced it. Whether the agency engagement is still live:
**NOT FOUND.**

**Two findings that lower the score, both new:**
1. **Zero US go-to-market hiring.** Their careers page today lists three roles — Site Reliability Engineer,
   Technical Support Engineer, SBA Loan Specialist — **all in India**. No US marketing or sales req exists.
2. **The marketing buyer is not in America.** Their VP Marketing, **Mandar Marathe**, is based in **Pune**.
   The HQ passes the US gate; the person who would buy Clue does not sit there. Direct mail — Clue's most
   differentiated channel — lands in the wrong country.

**The pitch numbers are excellent though.** They publish "150+ Financial Institutions Trust Us", and the real
universe is countable: the FDIC reports **4,336** insured institutions and the NCUA **4,287** federally insured
credit unions. Roughly 98% of their market is unwon, and they have no US marketer to work it.

**Committee (thin, by design — accounts 4 and 5 got a reduced budget):** Snehal Fulzele (Founder & CEO),
Mandar Marathe (VP Marketing, Pune), Craig McKeon (VP GTM Strategy, since Apr 2026), Gagan Kanjlia (Chief
Banking Officer), Marc Billanti (SVP Sales, credit unions), Joe Rost (VP Wealth Solutions). **No emails bought.**

---

## 5. Top 3 by researched intent — scorecards and how to approach them

**How the top 3 were chosen.** By *composite* intent = how likely they are to engage **×** whether Clue should
want them. On raw buying intent alone Vendelux would be third (75) ahead of Harmonic (62) — but Vendelux is
disqualified as a competitor, and spending contact-research budget on a disqualified account is waste. That
decision was made before the contact work, and it is why Harmonic got the third slot.

### Agent A predicted vs what we found

| Account | A's predicted intent | Researched intent | Verdict on the prediction |
|---|---:|---:|---|
| **Zafran** | 65 (rank 4) | **90 (rank 1)** | **Wrong, and A predicted exactly how it would be wrong.** A wrote: "If the req is still open at 75 days, intent should be revised up." It is still open — at 105 days from the hiring manager's first post. |
| **Cogent** | 85 (rank 1) | **88 (rank 2)** | **Right.** A's falsification test was "check who holds the Head of Demand Gen title now" — nobody does, the req is still open, and five *more* GTM reqs appeared since. |
| **Harmonic** | 78 (rank 2) | **62 (rank 3)** | **Wrong.** A could not see that the ABM requisition had been converted into a BDR role. Its own falsification test ("check whether the req is stale") pointed at the right thing. |
| **Vendelux** | 72 (rank 3) | **75 buying / DISQUALIFIED** | **Right to worry.** A wrote "check this first" — and it was correct: they ship AI meeting-booking agents. |
| **Uptiq** | 55 (rank 5) | **33 (rank 5)** | **Right, and worse than predicted** — no US GTM hiring at all, and the marketing buyer is in India. |

**A's aggregate bet was that recency of the hiring signal beats size of the round. That bet held.** Every
ranking change above was caused by a hiring fact, not a funding fact.

---

### 🥇 Zafran Security

| Score | 0–100 | The evidence line |
|---|---:|---|
| **Buying intent** | **90** | An ABM requisition advertised by the hiring manager on 2026-05-18 and still listed on the ATS on 2026-08-31 — **105 days unfilled** — plus two more open marketing reqs and two strategic investments in the last 7 months. |
| **Fit intent** | **87** | 9-person marketing team with field and events staffed and **no ABM seat**; enterprise CISO motion; published martech stack with **no ABM platform in it**. Only Series C stage costs it points. |
| **ICP intent** | **82** | Perfect shape, one real reservation: Series C means more procurement, and the Head of Growth Marketing personally knows 6sense and Demandbase — she may prefer an incumbent. |

**How to approach them — plain words**

- **Who first:** **Vari Kaur, Head of Growth Marketing** (`vari@zafran.io`, verified). She owns the vacant seat.
  She is the champion and she is the buyer of the *first* conversation. Nick Fisher (VP Marketing,
  `nick@zafran.io`, verified) is the second call, not the first.
- **The opener:** her own advert. *"You've been trying to hire someone to own ABM from the ground up — 1:1,
  1:few and 1:many — since May. Here's that program running, on your top 50 accounts, this month."*
  Then hand her one finished account: research, brief, microsite, ad set, mailer.
- **Which channel:** LinkedIn message first — she posts constantly and replies in public. Email as the
  follow-up. A physical executive report to Nick Fisher's New York office is the second touch, not the first.
- **What NOT to say:** **never mention the Cisco acquisition rumour.** On 2026-07-20 Calcalist reported Cisco
  was in talks to buy Zafran "at a steep discount" (~$150M+), and **Zafran publicly refuted it.** Referencing
  it is an instant loss. Also do not use their PeerSpot product-criticism thread — punching at their product
  when you are selling to marketing is off-target.
- **The one risk to plan for:** an acquisition process can freeze new vendor spend. Evidence says they are not
  frozen — they published a new sales req on 2026-08-28 — but keep the first ask small and cheap.

---

### 🥈 Cogent Security

| Score | 0–100 | The evidence line |
|---|---:|---|
| **Buying intent** | **88** | Ten live GTM/marketing reqs, six posted in the last 17 days, and the Head of Growth publicly saying after Black Hat that he and two colleagues "need more teammates". CEO on record: "We're going to triple the team over the course of this year." |
| **Fit intent** | **92.5** | Highest researched score in the run. Series A, $42M six months ago, ~4-person marketing team, named Fortune-1000 logos, enterprise CISO motion, no ABM platform found. |
| **ICP intent** | **90** | Textbook. The only deduction is the build-versus-buy risk below. |

**How to approach them — plain words**

- **Who first:** **Alexander Semien, Head of Growth.** No email was recoverable (see §8), so this is a
  **LinkedIn-first** account — which suits him, because he posts several times a month and answers in the
  comments. **Cameron Coles, VP of Marketing** (`cameron@cogent.com`, verified) is the email route and the
  budget holder.
- **The opener:** mirror his own words back. He wrote: *"When I interviewed with Vineet Edupuganti, I told him
  I wanted to create a marketing team that B2B SaaS hadn't seen before. Especially in cyber. He said, go do
  it."* Open with that ambition and the Black Hat post: three people cannot cover dozens of Fortune 1000
  accounts, and hiring four more takes two quarters.
- **The mirror that closes it:** Cogent sells "**3x in vulnerability management team output**". Clue sells
  more output at the same headcount. Sell them their own pitch, applied to marketing.
- **Which channel:** LinkedIn to Semien, email to Coles, and a physical executive report is *especially* apt
  here — he explicitly values "premium experiences, branded moments, and TikTok-ad-level swag 💅".
- **What NOT to say:** he has stated pet peeves — *"not all vendors showed real depth beyond the buzzwords"*
  and *"Vendors are starting to sound the same."* No category language, no "AI-powered" adjectives. Lead with
  a finished artefact, not a description of one. **No negative press exists on this company** — we looked and
  found none, so there is nothing to avoid factually.
- **The one risk to plan for:** their Growth Lead req says they intend to build "the account intelligence
  layer, the intent layer, and the automation" in-house. Position Clue as the thing that makes that layer
  *useful this quarter*, not as a competitor to their roadmap.

---

### 🥉 Harmonic Security

| Score | 0–100 | The evidence line |
|---|---:|---|
| **Buying intent** | **62** | The ABM requisition was advertised on 2026-08-10 and had disappeared from the board by 2026-08-31, converted into a BDR role. Live budget conversation this month — but the direction of travel is *away* from account-based marketing. |
| **Fit intent** | **77** | 7-person marketing team, no CMO or VP Marketing at all, enterprise/government motion via In-Q-Tel, no ABM platform found. Held back by a 23-month-old last round. |
| **ICP intent** | **78** | Right shape and right size, but the smallest budget in the top three and the least fresh capital. |

**How to approach them — plain words**

- **Who first:** **Ana Corio, Director of Demand Generation** (`ana@harmonic.security`, verified). She is the
  hiring manager and, with no VP Marketing above her, effectively the decision-maker on marketing tooling.
  **Tyler Chonoles** (`tyler@harmonic.security`, verified) is the person who would actually use it.
- **The opener — the best one in the run:** quote her advert back to her. She wrote that the ABM role would do
  *"account mapping, outreach, direct mail, events + some weird creative stuff nobody's tried yet."* That is
  four of Clue's five agents plus an invitation. *"You listed account mapping, outreach, direct mail and events.
  Here's all four, running on your top 25 strategic accounts, without the headcount."*
- **The second hook:** competitors are buying "Harmonic Security alternatives" pages against them —
  wald.ai, deepinspect.ai and guardion.ai all publish one, two of them in the last 10 days. That is a
  named-account defence campaign waiting to be run.
- **Which channel:** LinkedIn first — she is highly active and informal. Email second. Direct mail is on-brand
  because she named it herself.
- **What NOT to say:** she is explicitly anti-hype. Her words: *"most of it is a vendor pitch in disguise"*,
  *"security teams don't need more noise"*, *"zero fluff"*, *"another boring nurture campaign."* Send the
  artefact, not the pitch. Do **not** say "AI-powered". Also: do **not** repeat the "$1M annual revenue"
  figure — it is a LinkedIn robot estimate and quoting it would be both wrong and insulting.
- **The one thing to find out first:** did they hire the ABM manager or kill the role? A single question in
  the first message ("did you fill the ABM seat?") converts the whole approach either way, and we could not
  answer it from public sources.

---

## 6. Time and money

### 6.1 Timing — every phase, in seconds

Timing was a first-class deliverable in this run. Two clocks matter and they are very different: **provider
time** (how long the APIs actually took) and **phase time** (which includes deliberate rate-limit sleeping).

| Phase | Seconds | What it covers |
|---|---:|---|
| **B0** Ashby job boards + 5 live site fetches | **4.69** | 6 boards + 5 homepages, **all free** |
| **B0b** Harmonic req page, ATS hunt, careers pages | **3.59** | 11 free fetches |
| **B1a** Own-site reads, 5 accounts (17 URLs × 2 methods) | **4.88** | Exa + direct fetch of the same pages |
| **B1b** Deep research × 5 accounts | **233.28** | The single biggest time cost (370.1 s of that clock is the 8 deep calls across B1b+B2) |
| **B1c** AI Ark title-filter probe | **1.69** | 1 credit spent to discover the filter does not work — see §8 |
| **B1c** AI Ark people rosters × 5 | **45.79** | Of which **42.1 s is deliberate pacing sleep**; real provider time was 3.7 s |
| **B1d** Gap-fill searches × 4 + 1 people lookup | **11.82** | |
| **B2** Contact deep research × 3 | **146.59** | |
| **B2b** Email exports × 6 | **64.07** | Of which **52.5 s is deliberate pacing sleep**; real provider time was 11.5 s |
| **B2c** Re-parse of email responses | **0.00** | Zero provider calls — fixed from saved raw data |
| **B2d** Email retry for Alexander Semien | **12.93** | Failed — see §8 |
| **B3** Negatives × 3 + Arintra probe | **10.25** | |
| **B4** Structuring, 5 accounts (gpt-5-mini) | **114.50** | |
| **B4b** Structuring, 3 contacts + merge | **58.28** | |
| **B4c** Committee patch for accounts 4–5 | **0.01** | Zero provider calls |
| **Agent B total (phase clock)** | **712.4 s ≈ 11.9 min** | Includes ~95 s of forced AI Ark rate-limit sleeping |
| **Agent B total (pure provider time)** | **584.9 s ≈ 9.7 min** | 84 calls |
| **Agent A total (provider time)** | **38.7 s** | 40 calls |
| **Combined A + B provider time** | **623.6 s ≈ 10.4 min** | 124 calls |

**Per account, end to end:**

| Account | Seconds | Depth |
|---|---:|---|
| Cogent | **189.8** | full (deep + roster + gap-fill + contact deep + 2 emails + negatives + structuring) |
| Harmonic | **189.8** | full |
| Zafran | **146.5** | full |
| Uptiq | **79.7** | reduced (accounts 4–5) |
| Vendelux | **72.3** | reduced (accounts 4–5) |

**Per-call latency, by provider — the number to plan around:**

| Provider | Calls | Total seconds | Average per call |
|---|---:|---:|---:|
| **Exa deep-reasoning** | 8 | 370.1 | **46.3 s** — the slow step, always |
| Exa cheap search / page reads | 13 | 13.7 | **1.05 s** |
| **OpenRouter (gpt-5-mini)** | 8 | 172.7 | **21.6 s** |
| **AI Ark** | 15 | 20.0 | **1.3 s** (but +10.5 s of forced waiting between calls) |
| Direct HTTP fetch | 26 | 5.8 | **0.22 s** |
| Ashby / ATS public APIs | 14 | 2.6 | **0.19 s** |

**The finding that matters:** a free public-API call (0.19 s) is **~240× faster** than a deep-research call
(46.3 s) and costs nothing — and in this run it was the free one that produced the most decision-changing
fact.

### 6.2 Money — per provider, per account, and what production would cost

| Provider | Calls | Cash | Credits | Notes |
|---|---:|---:|---:|---|
| **Exa** | 21 | **$0.271** | — | **$0.199** for 8 deep-reasoning calls ($0.018–$0.027 each) + **$0.072** for 13 cheap calls (8 searches at $0.007, 5 page-read batches at $0.003–$0.004) |
| **OpenRouter** (gpt-5-mini) | 8 | **$0.059** | — | $0.0074 average per structuring call |
| **AI Ark** | 15 | $0.00 | **32.5** | 6 rosters, 2 name lookups, 7 email exports |
| Direct HTTP | 26 | $0.00 | — | |
| Ashby / ATS public | 14 | $0.00 | — | |
| **Agent B total** | **84** | **$0.330** | **32.5** | **12.7% of the $2.60 cash ceiling; 65% of the 50-credit ceiling** |
| Agent A total | 40 | $0.177 | 0 | |
| **Run total** | **124** | **$0.507** | **32.5** | |

**Credits were the binding constraint, not cash.** We used an eighth of the money and two-thirds of the
credits. Any production budget should be sized in credits first.

**Per account (Agent B only):**

| Account | Cash | Credits | Credits as cash (Premium $0.0098/cr) | All-in |
|---|---:|---:|---:|---:|
| Zafran | $0.0796 | 9.5 | $0.093 | **$0.173** |
| Cogent | $0.0777 | 7.5 | $0.074 | **$0.151** |
| Harmonic | $0.0823 | 6.0 | $0.059 | **$0.141** |
| Vendelux | $0.0374 | 6.0 | $0.059 | **$0.096** |
| Uptiq | $0.0462 | 3.0 | $0.029 | **$0.076** |
| *shared / unattributed* | $0.007 | 0.5 | $0.005 | $0.012 |

**Extrapolated production cost per account**

| Depth | Cost per account (AI Ark Premium) | Cost per account (AI Ark at volume, $0.002–0.004/cr) |
|---|---:|---:|
| **Full depth** (deep dossier + roster + gap-fills + contact deep research + 2 verified emails + negatives + structuring) | **$0.155** | **$0.10** |
| **Reduced** (dossier + roster + structuring, no contact work) | **$0.086** | **$0.06** |
| **Cheap pass only** (discovery + scoring, Agent A style) | **$0.015** | $0.015 |

So a realistic two-pass campaign — score 200 accounts cheaply, research the top 40 at full depth — comes to
roughly **$3.00 + $6.20 = about $9.20 in provider cost**, plus the human review time. A single ABM manager
costs $93K–$230K a year at the salary bands these same companies published.

---

## 7. Scraping verdict — did we need Scrapling today?

We deliberately fetched the same 17 URLs **twice**: once through Exa's paid page reader and once with a plain
Python HTTP request carrying a normal browser user-agent. Then we counted.

| Result | Count |
|---|---:|
| URLs attempted (both methods) | **17** |
| **Exa served the page** | **16 / 17 (94%)** |
| **Plain direct fetch returned 200** | **16 / 17 (94%)** |
| Both worked | **16** |
| Only Exa worked | **0** |
| Only the direct fetch worked | **0** |
| Neither worked | **1** — `zafran.io/about-us`, a **genuine 404**; the real page is `/about` |
| **Pages blocked (403 / 429 / bot wall)** | **0** |

Widening to **every free fetch in the run** — 40 calls in total, which include the 17 above plus company
homepages, careers pages, a live job-posting page, six public job-board APIs and eight ATS-slug guesses, and
which cover Cloudflare-fronted marketing sites, `businessinsider.com` and `prnewswire.com`:

| Result | Count | Detail |
|---|---:|---|
| Free fetches attempted | **40** | 26 direct HTTP + 14 public-API calls |
| HTTP 200 | **29** | 25 of 26 direct fetches, 4 of 6 job boards |
| HTTP 404 | **11** | All genuine: 8 were us guessing ATS slugs that don't exist, 2 were companies with no Ashby board, 1 was a wrong URL guess (`zafran.io/about-us`) |
| **Blocked (403 / 429 / bot wall)** | **0** | |

**Verdict: Scrapling was not needed once. Zero pages, out of 40 free fetch attempts, were blocked.** A plain
HTTP GET with a browser user-agent got a 200 from every site we pointed it at, in an average of **0.22
seconds**, at zero cost — including sites behind Cloudflare.

**The recommended structure — the fetch ladder, in five lines:**

1. **Rung 1 — plain HTTP GET with a browser user-agent.** Free, ~0.2s, worked 100% of the time here. Always try this first.
2. **Rung 2 — the structured public API, if one exists** (Ashby, Greenhouse, Lever job boards). Free, ~0.19s, and returns *typed* data with dates and an is-still-open flag that no scraper can infer. **This rung produced the run's best fact and is currently missing from our pipeline.**
3. **Rung 3 — Exa `/contents`** ($0.001/page). Use for clean markdown extraction and for pages the crawler already has cached. Same hit rate as rung 1 here, but it returns tidy text instead of HTML soup.
4. **Rung 4 — Exa `deep-reasoning`** ($0.018–$0.027, ~46s). Only for synthesis across many sources, never for fetching one known page.
5. **Rung 5 — a stealth browser (Scrapling/headless).** Keep it built and keep it unused. Today it would have cost time and money to add nothing. Trigger it on an actual 403/429/JS-wall, not on principle.

One caveat that keeps rung 5 alive: Exa's extraction **silently drops interactive tab and accordion labels**
(§1). If a fact lives behind a tab, no amount of index quality will surface it — that is a rendering problem,
and rendering is what a real browser is for.

---

## 8. Honest gaps, mistakes, and what surprised us

### The biggest surprise
**The free calls beat the expensive ones on the facts that changed decisions.** The single most valuable action
in the run was reading four public job-board APIs — **1.3 seconds, $0.00** — and it did three things $0.18 of
AI search could not: it proved Zafran's ABM req was still open (moving it from 4th to 1st), it proved
Harmonic's ABM req had been converted into a sales role (moving it from 2nd to 3rd), and it revealed Cogent's
six brand-new marketing reqs and Vendelux's four-day-old Head of Growth Marketing req. **We should add public
ATS APIs to the pipeline as a first-class source before we spend another dollar on inference.**

### Where Agent A was wrong, and why
1. **Zafran's intent (65 → 90).** Not A's fault — A explicitly said "if the req is still open, revise up" and
   had no way to check. The tool was missing, not the judgement.
2. **Harmonic's intent (78 → 62).** Same root cause, opposite direction. A job advert's *published date* tells
   you nothing about whether it is still live.
3. **Harmonic's funding date.** A recorded "Series A, $17.5M, Apr 2025, investors N47, Ten Eleven, In-Q-Tel."
   It was **October 2024, led by Next47** — "N47" was a misparse. That is a 6-month error on a freshness gate.
4. **Zafran's funding history.** A missed the **Amex Ventures** strategic investment (Feb 2026) entirely.
5. **"No public founder complaints anywhere" (Agent A's failed search angle).** There was one, on the account
   A ranked first — Cogent's Head of Growth publicly saying his three-person team needs more people. A's
   natural-language query for founder pain returned vendor blog posts. **A signal that lives in a person's
   LinkedIn feed is not findable by describing the feeling; it is findable by looking up the person.**
6. **Arintra "zero hiring signal" — wrong.** A's job search found no Arintra postings. A single free fetch of
   `arintra.com/careers` found **five open US go-to-market roles**, two of them marketing (Events Manager;
   Product Marketing Manager), plus a Director of Demand Generation Marketing (Terri Logan) promoted in March.
   Their careers page is a Webflow page with no ATS behind it, so job-board search is blind to it.
   **The correct lesson is not that A's rubric weighting was wrong — hiring signals did drive every ranking
   change, so A's core bet held. The lesson is that A's hiring-signal *detector* has a blind spot**, and the
   blind spot is companies without a standard ATS.

### Where the tools failed
- **AI Ark's title filter does not work.** We paid 1 credit to find out: a search for Zafran people with
  "marketing" in the title returned `totalElements: 163` (more than the company's headcount) with a regional
  sales manager in the top two. The filter is ignored. **Consequence:** a 12-person sample of Zafran's 163
  records came back **100% sales, zero marketing** — the VP of Marketing was not in it. We recovered him with
  a name-scoped lookup for 0.5 credits, but only because the web had already told us his name. **Roster
  sampling without a working filter is a lottery; name-scoped lookups are 12× cheaper and exact.**
- **AI Ark's search index and its export endpoint disagree.** Alexander Semien is in the people search — right
  name, right title, right LinkedIn URL, `totalElements: 1` — and the export endpoint returns **404 for that
  same URL**, twice. We could not buy his email. That is a provider defect, not a data gap.
- **Our own parser was wrong for six calls.** The email address lives at `email.output[].address`, and we
  looked for `email.output[].email`. Six exports were briefly recorded as "not found" when all six had
  returned data. **It cost nothing to fix, because every raw response is written to disk before parsing** —
  that discipline paid for itself in this run.
- **The deep research pass missed a page the cheap page-read had already retrieved.** Asked to read the
  GrowthSpree case study on Uptiq, it went to `growthspree.com` (a different company) and reported NOT FOUND —
  while our $0.004 page read had the real case study at `growthspreeofficial.com` sitting in the corpus.
  **A known URL should always be fetched, never searched for.**
- **Eight ATS slug guesses returned 404** (`greenhouse.io/uptiq`, `lever.co/arintra`, etc.). Guessing board
  names does not work; the careers page has to be read.

### Where the model behaved *better* than expected
- **It refused a fact we gave it.** We told the research model Vendelux's CEO was "Kyle Fitzgerald". It came
  back: *"The supplied 'Kyle Fitzgerald' identification is not supported by the sources found: Vendelux's own
  About page names 'Alex Reynolds' as Co-Founder, CEO"* — and cited the page. It overruled its operator with
  evidence. That is exactly the behaviour the whole architecture is for.
- **It refused to launder estimates as facts.** Every report separated company-reported numbers from
  LinkedIn/CB-Insights robot estimates, unprompted, and marked the estimates as estimates.
- **"NOT FOUND" was used heavily and correctly** — 180 times across the five account dossiers. The Zafran
  dossier alone said NOT FOUND 52 times rather than guess.

### The database we built
**203 claims across 5 accounts and 53 people.** Every row carries a value, a verbatim quote, a source URL, a
trust tier and a priority (1 = active buying intent, 2 = qualifying, 3 = context).

| Account | Claims | Tier 1 (API) | Tier 2 (official) | Tier 4 (AI) | P1 | P2 | P3 | People |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Cogent | 48 | 23 | 1 | 24 | 5 | 28 | 15 | 12 |
| Zafran | 47 | 26 | 1 | 20 | 6 | 26 | 15 | 14 |
| Harmonic | 40 | 18 | 1 | 21 | 6 | 23 | 11 | 9 |
| Vendelux | 38 | 24 | 1 | 13 | 2 | 21 | 15 | 12 |
| Uptiq | 30 | 12 | 0 | 18 | 3 | 17 | 10 | 6 |

**Quality check:** 0 unregistered field keys, 0 missing source URLs, 0 missing priorities, 0 rows dropped.
**13 of 203 rows (6%) had an evidence quote that was a paraphrase rather than a word-for-word copy** — these
are flagged in `claims_summary.json`, not hidden. That is the honest defect rate of the structuring step.

**The schema is missing the field that matters most.** There is no registered field for go-to-market hiring.
`account.hiring_velocity_eng` counts *engineering* roles only. Every P1 signal in this run — a live ABM req, its
age, its salary band, its still-open flag — had to be squeezed into free-text prose. We have proposed
**`account.hiring.gtm_open_roles`** (title, department, published date, days open, salary band, still-listed
flag, URL) with a worked example. **This should be added before the next run.**

### What we still do not know
- **Whether Harmonic hired the ABM manager or killed the role.** Unresolvable from public sources; it is the
  first question of the first conversation.
- **Real revenue for any of the five.** Every ARR figure found was either a robot estimate or unconfirmed press.
- **Alexander Semien's email** — provider defect, above.
- **Whether Uptiq's agency engagement is still live** — decisive for that account's intent, and not public.
- **Whether Zafran is actually being acquired.** Reported by Calcalist, publicly refuted by Zafran. We treat
  it as unresolved and unusable in outreach.
- **The actual ABM tooling in any of the five.** We found HubSpot at Zafran, HubSpot/Salesforce at Vendelux,
  and Gong at Cogent. No ABM platform was found anywhere — but "not found" is not "not installed". Agent A's
  second bet (that no-ABM-tooling is real absence) is **supported but not proven**; the only citable proof we
  got was Zafran's published required-tools list, and that is one account out of five.
