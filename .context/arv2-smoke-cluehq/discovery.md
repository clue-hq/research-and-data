# A4 — Discovery: the queries, what came back, and what I kept

**23 Exa calls total for A4** — 8 discovery searches, 10 gate-verification searches, 5 tie-break
probes. **$0.161 for A4** ($0.177 for the whole of Agent A). Every query string and every result
is reproduced verbatim in the appendices at the bottom of this file; the raw JSON is in `raw/`.

---

## 1. The angles, and which one earned its keep

I ran five distinct angles so the run could tell me *which kind of query finds ICP accounts*,
rather than just handing me a list.

| # | Angle | Queries | Usable ICP companies found | Verdict |
|---|---|---|---|---|
| 1 | **Semantic ICP** — describe the company shape in prose | `d1`, `d2` | `d1`: **0**. `d2`: **7** | Split decision — see below |
| 2 | **Signal-first (job reqs)** — describe the *job posting*, restricted to greenhouse/lever/ashby | `d3`, `d4` | **11** (7 of them ICP-shaped) | ⭐ **Best angle by a distance** |
| 3 | **Funding-signal** — describe the *funding announcement*, `startPublishedDate` filtered | `d5` | 7 (mostly needing extra gate work) | Good for H2, weak for H3 |
| 4 | **Founder-pain post** — describe the complaint | `d6` | **0** | ❌ Failed completely |
| 5 | **Vertical-specific** — fintech / agency | `d7`, `d8` | 3 + 0 | Mixed; agencies confirmed a prior |

### ⭐ The winner: signal-first job-req search with `includeDomains` on the ATS boards

`d3_jobs_abm` and `d4_jobs_demandgen` returned **20 results, of which 20 were actual job postings
at actual companies** — a 100% "is this a company?" hit rate — and **7 of them survived the H1/H2
gates**. Four of my final five came out of this angle. Two reasons it works:

1. **It returns companies, not content.** A job posting is a first-party artifact published by the
   company itself, so the result *is* the account. Every other angle returns articles *about* the
   space, from which a company must then be extracted.
2. **It returns the evidence and the account in the same object.** The req text *is* the Q1
   quantifiable-pain proof, already quoted, already sourced, already dated — no second call needed.
   `Harmonic Security` came back with a posting literally titled *"Account-Based Marketing Manager,
   Strategic Accounts"* with a salary band attached. That is a scored ICP claim in one $0.008 hit.

The `includeDomains` restriction to `boards.greenhouse.io` / `job-boards.greenhouse.io` /
`jobs.lever.co` / `jobs.ashbyhq.com` is what makes it work — without it, the neural search drifts
to job-description *templates* and recruiting blogs.

### ❌ The failure worth reporting: the founder-pain angle (`d6`)

The query — *"we spent weeks researching accounts to personalize outbound and only shipped a
handful of campaigns — B2B marketing leader writing about ABM being too much work"* — returned
**ten results, zero companies**. Every single one was a vendor's SEO content page about why ABM
programs fail: `sparkle.io`, `ciente.io`, `formanorden.com`, `demandscience.com`,
`thesmarketers.com`, `humanr.ai`, `usergems.com`, plus a LinkedIn Pulse post and two consultant
blogs. **The internet's supply of "ABM is hard" content is entirely vendor-manufactured**, and it
crowds out any genuine practitioner complaint. My ICP listed Q3 ("founder/leader public complaint")
as a 5-point Tier-1 signal; **discovery could not find a single instance of it**, and Q3 scored
zero for every one of the ten candidates I scored. That is a real finding: *Q3 should be demoted
or dropped from the rubric* — it is not discoverable by cheap search.

### The semantic angle split in a way I did not expect

`d1` (semantic, generic SaaS) returned **zero companies** — ten pieces of ABM content marketing,
including two from `abmatic.ai` and one from `factors.ai`, i.e. **competitors' blogs**. Describing
your ICP in prose returns *people writing about that ICP*, not members of it.

`d2` (semantic, **healthcare vertical**) returned **seven funded companies** — Sift Healthcare,
Translucent, Arintra, CertifyOS, Ascertain, Prosper AI, Anterior — because in a vertical, the
dominant document type is the funding press release, not the SEO blog. **Lesson: semantic
company-shaped search only works when the vertical is named.** Generic semantic ICP search is a
trap; it retrieves your competitors' marketing.

### One incidental yield worth naming

The `d1` search surfaced `growthspreeofficial.com/case-studies/case-study-uptiq-ai-…`, a
third-party agency case study titled **"Uptiq.ai ABM Case Study: $400K+ Pipeline"**. That single
result did two jobs at once: it *identified* an account (Uptiq) and it *proved* that account
already funds an ABM motion with an outside agency. **Third-party agency case studies are an
under-used discovery surface: they are a directory of companies that have already bought the
category.** Worth a dedicated angle in a future run.

---

## 2. Dedup, exclusions, and what survived

- **73 result rows** returned across the 8 discovery queries (8 × ~10, minus overlaps).
- **~38 distinct companies** extractable.
- **Exclusions applied** (per brief): `probook.ai`, `lassie.ai`, `avoca`, Insight Health, and Clue
  itself. None of the first three appeared in any result; **Clue's own site appeared only in the A1
  probe**, not in discovery.
- **Competitor removals (D6):** Demandbase (appeared as a *hiring company* in `d4` — it was
  recruiting a Director of Demand Generation), Sprouts.ai, Factors.ai, Abmatic, Octave, Clearcue,
  GR0, Amy, The Smarketers, UserGems.
- **10 companies scored** against the rubric; **21 dropped or deferred at a gate** with the reason
  recorded in `candidates.json`.

## 3. The scoreboard

| Rank | Company | Score | Band | Vertical | Why |
|---:|---|---:|---|---|---|
| 1 | **Zafran Security** | **81.0** | select | Cyber | Open ABM req + "no large team, no large budget" quote; Series C costs it 4 pts |
| 2 | **Cogent Security** | **80.0** | select | Cyber | $42M Series A (Feb 2026) + Head of Demand Gen req building the team now |
| 3 | **Harmonic Security** | **79.5** | select | Cyber | An open req *named* "ABM Manager, Strategic Accounts" at $93–108K |
| 4 | **Uptiq** | **67.5** | strong bench | Fintech | 150+ of ~9,000 US FIs; a published $400K-pipeline ABM case study |
| 5 | **Vendelux** | **66.5** | strong bench | Martech | $50M Series B (Jul 2026) + **four** concurrent GTM reqs |
| 6 | RevenueCat | 61.8 | strong bench | SaaS | Real ABM req, but PLG-hybrid and the weakest artifact fit |
| 7 | Arintra | 55.5 | watch | Healthcare | Freshest round in the set (5 days) but **zero** hiring signal |
| 8 | Translucent | 54.2 | watch | Healthcare | $27M GV Series A but hiring engineers, not marketers |
| 9 | Alloy | 52.5 | watch | Fintech | Vertical demand-gen req; under-verified, so deliberately under-scored |
| 10 | Glia | 44.0 | drop* | Fintech | *Score depressed by unverified gates, not by evidence of bad fit |

**Honesty note on the selection:** only **three** candidates cleared my own ≥75 "select" bar. Slots
4 and 5 are the top of the *strong bench* (67.5 and 66.5), and I am labelling them that way rather
than quietly moving the bar. If the founder wants five accounts that all clear 75, the answer is
that this discovery pass did not produce five — it produced three, plus a bench.

## 4. Three things discovery taught me about my own ICP

1. **My vertical ranking was wrong.** `icp.md` put healthcare-adjacent SaaS at **priority 2**.
   Discovery found plenty of well-funded US healthcare companies (Arintra, Translucent, Prosper,
   Anterior, CertifyOS, Sift) — and **not one of them showed a single GTM hiring signal.**
   Translucent has 18 open roles; the visible ones are Delivery, Design, Domain Intelligence,
   Product and Engineering. These companies are in *build* mode, not *distribute* mode. Healthcare
   should drop below cybersecurity and fintech until a company shows a marketing req.
2. **Cybersecurity Series A/B is the densest pocket of ABM demand in the US right now.** Three of
   my five selections are security companies and I did not aim for that — no query mentioned
   security. `d3_jobs_abm` returned Zafran, Harmonic and Filigran (all security) unprompted, and
   `d4` added Cogent. That concentration is a finding, not an accident: security sells to a finite
   named list of CISOs, has high ACV, and is currently well capitalised.
3. **Q1 (a job req) and Q4 (a fresh round) are not interchangeable, and Q1 is worth more.** The
   three companies with an open GTM req scored 79.5–81. The three with only a fresh round scored
   54–68. The rubric weights Q1 at 15 and Q4 at 5, and that 3:1 ratio is *why* the ranking came out
   this way — so the ranking is partly a restatement of my own weighting, which Agent B should
   treat as the hypothesis under test, not as a result.

---
## Appendix A — the 8 discovery queries, verbatim

### `d1_semantic_saas` — angle: *semantic_icp*

```
POST https://api.exa.ai/search
{
  "query": "US Series B B2B SaaS company selling to large enterprise named accounts with a small marketing team running account-based marketing campaigns",
  "type": "auto",
  "numResults": 10,
  "contents": {
    "text": {
      "maxCharacters": 1200
    }
  }
}
```

`HTTP 200` · **1.87s** · **$0.007** · 10 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://abmatic.ai/blog/account-based-marketing-playbook-for-series-b-saas` | Account-Based Marketing Playbook for Series B SaaS \| Abmatic AI | 2026-04-29T00:00:00.000Z |
| 2 | `https://demandcollective.substack.com/p/signal-based-demand-gen-done-right` | Signal-based demand gen done right: how Fingerprint 2x'd ACV while tripling ARR | 2026-08-11T00:00:00.000Z |
| 3 | `https://www.factors.ai/conversations/the-abm-playbook-behind-high-acv-deals` | The ABM Playbook Behind High-ACV Deals | 2026-08-06T00:00:00.000Z |
| 4 | `https://www.vector.co/blog/contact-level-abm-how-fingerprint-rebuilt-their-motion-and-opened-up-new-channels` | Contact-level ABM: how Fingerprint rebuilt their motion | — |
| 5 | `https://ziellab.com/post/account-based-marketing-b2b-small-teams-guide` | Account-based marketing for small B2B teams | 2026-06-07T00:00:00.000Z |
| 6 | `https://demandcollective.substack.com/p/how-aline-is-driving-80-100-demos` | How Aline is driving 80-100 demos per month (& growing 30% MoM) w. 1 marketer | 2026-06-02T00:00:00.000Z |
| 7 | `https://fullfunnel.substack.com/p/abm-case-study-how-backbase-built` | 🕵🏻‍♂️ [ABM Case Study] How Backbase built an AI-native ABM motion | 2026-06-12T00:00:00.000Z |
| 8 | `https://www.growthspreeofficial.com/case-studies/case-study-uptiq-ai-building-an-abm-engine-for-modern-financial-leaders` | Uptiq.ai ABM Case Study: $400K+ Pipeline \| GrowthSpree | 2026-05-28T00:00:00.000Z |
| 9 | `https://abmatic.ai/blog/abm-playbook-for-series-a-saas-startups-2026` | ABM Playbook for Series A SaaS Startups 2026 \| Abmatic AI | 2026-04-28T00:00:00.000Z |
| 10 | `https://salesrelief.com/how-openais-first-b2b-marketer-built-ai-powered-abm-7-intelligence-frameworks-converting-43-more-enterprise-accounts/` | How OpenAI’s First B2B Marketer Built AI-Powered ABM: 7 Intelligence Frameworks Converting 43% More Enterprise Accounts \| SalesRelief | 2026-03-21T00:00:00.000Z |

### `d2_semantic_health` — angle: *semantic_icp_vertical_health*

```
POST https://api.exa.ai/search
{
  "query": "Series A or Series B US healthcare software company selling to hospitals, health systems and payers with an enterprise sales team and a small marketing team",
  "type": "auto",
  "numResults": 10,
  "contents": {
    "text": {
      "maxCharacters": 1200
    }
  }
}
```

`HTTP 200` · **1.71s** · **$0.007** · 10 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://www.prnewswire.com/news-releases/sift-healthcare-raises-20m-series-b-funding-round-to-enhance-ai-powered-payment-solutions-302140400.html` | SIFT HEALTHCARE RAISES $20M SERIES B FUNDING ROUND TO ENHANCE AI-POWERED PAYMENT SOLUTIONS | 2024-05-09T00:00:00.000Z |
| 2 | `https://www.businesswire.com/news/home/20260311059455/en/Translucent-Announces-%2427M-Series-A-Led-by-GV-to-Tackle-Healthcares-Existential-Financial-Crisis` | Translucent Announces $27M Series A Led by GV to Tackle Healthcare's Existential Financial Crisis | 2026-03-11T00:00:00.000Z |
| 3 | `https://www.prnewswire.com/news-releases/arintra-raises-25m-to-pioneer-revenue-assurance-for-americas-health-systems-302860106.html` | Arintra Raises $25M to Pioneer Revenue Assurance for America's Health Systems | 2026-08-26T00:00:00.000Z |
| 4 | `https://www.prnewswire.com/news-releases/certifyos-closes-14-5-million-series-a-funding-round-led-by-general-catalyst-301618753.html` | CertifyOS Closes $14.5 Million Series A Funding Round Led by General Catalyst | 2022-09-07T00:00:00.000Z |
| 5 | `https://www.businessinsider.com/amazon-10-million-raise-hospital-ai-agents-pitch-deck-ascertain-2025-5` | Ex-Amazon Leader Got $10 Million for Hospital AI Agents With This Deck - Business Insider | 2025-05-02T00:00:00.000Z |
| 6 | `https://www.prnewswire.com/news-releases/sift-healthcare-closes-9-million-series-a-financing-301587131.html` | SIFT HEALTHCARE CLOSES $9 MILLION SERIES A FINANCING | 2022-07-15T00:00:00.000Z |
| 7 | `https://techfundingnews.com/ex-bain-operators-raise-17m-to-tackle-behavioural-healthcares-data-blind-spot-with-ai/` | Ex-Bain operators raise $17M to tackle behavioural healthcare’s data blind spot with AI — TFN | 2026-08-26T13:59:13.000Z |
| 8 | `https://www.citybiz.co/article/894833/arintra-raises-25-million-series-b-to-expand-healthcare-revenue-ai/` | Arintra Raises $25 Million Series B to Expand Healthcare Revenue AI | 2026-08-26T17:25:12.000Z |
| 9 | `https://hitconsultant.net/2026/06/23/prosper-ai-raises-30-million-series-a-a16z/` | Prosper AI Raises $30M to Scale Patient Access Automation - | 2026-06-23T00:00:00.000Z |
| 10 | `https://www.anterior.com/insights/anterior-secures-usd20-million-series-a-to-unlock-administrative-efficiencies-for-healthcare` | Anterior | — |

### `d3_jobs_abm` — angle: *signal_first_job_req_abm*

```
POST https://api.exa.ai/search
{
  "query": "Account Based Marketing Manager job opening: build and maintain the target account list, research accounts, run 1:1 ABM campaigns for our top accounts",
  "type": "auto",
  "numResults": 10,
  "includeDomains": [
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "ashbyhq.com"
  ],
  "contents": {
    "text": {
      "maxCharacters": 1200
    }
  }
}
```

`HTTP 200` · **1.17s** · **$0.007** · 10 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://jobs.ashbyhq.com/ideals/6fbda266-7e85-4472-bb40-f875de0b9fdb` | Account-Based Marketing Manager @ Ideals | — |
| 2 | `https://jobs.ashbyhq.com/xero/ac00326f-1442-4af8-87d0-51ef25859571` | Senior Manager, ABM at Xero | 2026-07-13T00:00:00.000Z |
| 3 | `https://jobs.ashbyhq.com/filigran/9329f223-5491-433f-914c-bcfe0b651659` | Senior Account-Based Marketing Manager @ Filigran | — |
| 4 | `https://jobs.lever.co/smarsh/89fcfe70-7765-4980-8bbe-0657133834fc` | Smarsh - Sr. Account-Based Marketing Manager | — |
| 5 | `https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf` | Senior Manager, ABM & Integrated Campaigns at Zafran-security | 2026-06-17T00:00:00.000Z |
| 6 | `https://jobs.ashbyhq.com/harmonic-security-inc/f568f331-f4ea-4328-a690-03772941f561` | Account-Based Marketing Manager, Strategic Accounts @ Harmonic Security, Inc | — |
| 7 | `https://jobs.lever.co/idealscorp/a7a3bdad-d5ae-41d1-b874-84f558632a32` | Ideals - Account Based Marketing Manager | — |
| 8 | `https://jobs.ashbyhq.com/revenuecat/12fc97f3-d173-4e3a-a652-9afff63a9b56` | Senior Account Based Marketing Manager @ RevenueCat | — |
| 9 | `https://jobs.ashbyhq.com/airwallex/be9acfec-6f06-46f2-885e-088d7fb19cd9` | Manager, Global Account Based Marketing at Airwallex | 2026-03-06T00:00:00.000Z |
| 10 | `https://jobs.ashbyhq.com/ncontracts/1614ba87-3dbf-43a7-a9fd-581ac3785f7d` | Account-Based Marketing Manager @ Ncontracts | — |

### `d4_jobs_demandgen` — angle: *signal_first_job_req_demandgen*

```
POST https://api.exa.ai/search
{
  "query": "Demand Generation Manager job description: account research, target account lists, personalized outbound campaigns, direct mail and field marketing",
  "type": "auto",
  "numResults": 10,
  "includeDomains": [
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "ashbyhq.com"
  ],
  "contents": {
    "text": {
      "maxCharacters": 1200
    }
  }
}
```

`HTTP 200` · **1.22s** · **$0.007** · 10 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://jobs.ashbyhq.com/cogent-security/8ed749ff-cf21-47ec-815d-36af19ab389d` | Head of Demand Generation at Cogent-security | 2026-08-14T00:00:00.000Z |
| 2 | `https://jobs.ashbyhq.com/oscilar/f66f24ff-495b-400a-af28-c902cd8a20a1` | Outbound Marketing Manager @ Oscilar | — |
| 3 | `https://job-boards.greenhouse.io/centralreach/jobs/4202872009` | Job Application for Demand Generation Manager at CentralReach | — |
| 4 | `https://jobs.lever.co/ciandt/0461a3a5-61d4-4daf-a1b0-7f51148ada44` | CI&T - [Job-28760] B2B Demand Generation Manager | — |
| 5 | `https://jobs.lever.co/seerinteractive/4d7a9ca8-e79b-4654-8a49-1b9976227bb7` | Seer Interactive - Demand Generation Manager | — |
| 6 | `https://job-boards.greenhouse.io/auctane/jobs/7776417003` | Job Application for Sr Demand Generation Manager at Auctane | — |
| 7 | `https://job-boards.greenhouse.io/connectwise/jobs/4724677005` | Demand Generation Manager at Connectwise | 2026-08-17T00:00:00.000Z |
| 8 | `https://jobs.lever.co/jobgether/80102cc5-67ff-4fd5-a1b9-4d2970173e4d` | Jobgether - Senior Manager, Demand Generation | — |
| 9 | `https://jobs.ashbyhq.com/demandbase/83aa00bc-c44d-4583-995b-51d5bc038488` | Director, Demand Generation at Demandbase | 2026-08-04T00:00:00.000Z |
| 10 | `https://jobs.ashbyhq.com/directive/e6fdeeee-e00d-4043-bd30-c8e467c91547` | Demand Generation Manager (Remote US) at Directive | 2026-08-18T00:00:00.000Z |

### `d5_funding_gtm` — angle: *funding_signal_gtm_earmark*

```
POST https://api.exa.ai/search
{
  "query": "raises Series B funding to expand its enterprise go-to-market and sales team, B2B software company, United States",
  "type": "auto",
  "numResults": 10,
  "startPublishedDate": "2025-09-01T00:00:00.000Z",
  "contents": {
    "text": {
      "maxCharacters": 1200
    }
  }
}
```

`HTTP 200` · **1.56s** · **$0.007** · 10 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://www.globenewswire.com/news-release/2026/07/01/3320495/0/en/Aligned-Closes-60M-Series-B-to-Solidify-Leadership-Position-as-the-System-of-Action-for-B2B-Sales.html` | Aligned Closes $60M Series B to Solidify Leadership | 2026-07-01T00:00:00.000Z |
| 2 | `https://www.businesswire.com/news/home/20260428810008/en/Actively-Raises-%2445M-Series-B-to-Scale-Intelligence-Led-Revenue-Platform` | Actively Raises $45M Series B to Scale Intelligence-Led Revenue Platform | 2026-04-28T00:00:00.000Z |
| 3 | `https://www.prnewswire.com/news-releases/letter-ai-raises-40m-series-b-to-bring-deal-level-intelligence-to-revenue-enablement-302694721.html` | Letter AI Raises $40M Series B to Bring Deal-Level Intelligence to Revenue Enablement | 2026-02-24T00:00:00.000Z |
| 4 | `https://alignedup.com/blog/why-we-raised-60m-to-build-the-system-of-action-for-b2b-sales/` | Why We Raised $60M to Build the System of Action for B2B Sales | 2026-07-01T00:00:00.000Z |
| 5 | `https://www.peakspancapital.com/resources/news/why-we-raised-60m-to-build-the-system-of-action-for-b2b-sales` | Why We Raised $60M to Build the System of Action for B2B Sales \| PeakSpan News | 2026-07-01T00:00:00.000Z |
| 6 | `https://www.globenewswire.com/news-release/2026/05/18/3296726/0/en/Dust-raises-40M-to-make-AI-multiplayer-inside-the-enterprise.html` | Dust raises $40M to make AI multiplayer inside the | 2026-05-18T00:00:00.000Z |
| 7 | `https://pulse2.com/aligned-raises-60-million-to-advance-ai-deal-workspace-platform/amp/` | Aligned Raises $60 Million To Advance AI Deal Workspace Platform | 2026-07-01T00:00:00.000Z |
| 8 | `https://siliconangle.com/2026/07/14/instalily-developer-ai-teammates-can-automate-complex-business-specific-work-raises-60m/` | InstaLILY, a developer of AI teammates that can automate complex, business-specific work, raises $60M - SiliconANGLE | 2026-07-14T00:00:00.000Z |
| 9 | `https://startupfortune.com/vendelux-raises-50-million-dollars-to-prove-trade-shows-actually-work/` | Vendelux Raises 50 Million Dollars to Prove Trade Shows Actually Work - Startup Fortune | 2026-07-14T00:00:00.000Z |
| 10 | `https://hrtechcube.com/genspark-ai-extends-series-b-to-485m-appoints-cro/` | Genspark.ai Extends Series B to $485M, Appoints CRO | 2026-06-22T00:00:00.000Z |

### `d6_founder_pain` — angle: *founder_pain_post*

```
POST https://api.exa.ai/search
{
  "query": "we spent weeks researching accounts to personalize outbound and only shipped a handful of campaigns \u2014 B2B marketing leader writing about ABM being too much work",
  "type": "auto",
  "numResults": 10,
  "contents": {
    "text": {
      "maxCharacters": 1200
    }
  }
}
```

`HTTP 200` · **1.41s** · **$0.007** · 10 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://sparkle.io/blog/account-based-marketing/` | Account-Based Marketing: What It Is, What It Costs, and When to Skip It | 2026-07-31T00:00:00.000Z |
| 2 | `https://ciente.io/blogs/account-based-marketing-for-saas/` | Account-Based Marketing For SaaS: It Is (Not) Personalization - Ciente | 2026-03-12T00:00:00.000Z |
| 3 | `https://www.linkedin.com/pulse/ive-run-40-abm-programs-heres-why-most-them-fail-3-fixes-3euic` | I’ve Run 40+ ABM Programs. Here’s Why Most of Them Fail (And the 3 Fixes) | 2026-08-12T00:00:00.000Z |
| 4 | `https://formanorden.com/blog/why-abm-programs-fail/` | 7 Reasons ABM Programs Fail in B2B SaaS (and How to Fix Each One) | 2026-03-21T00:00:00.000Z |
| 5 | `https://erikrmiller.com/blog/why-most-abm-programs-fail/` | Why Most ABM Programs Fail \| Erik R. Miller | 2026-04-27T00:00:00.000Z |
| 6 | `https://demandscience.com/resources/blog/abm-why-programs-fail/` | Why ABM Program Marketing Fails: What Vendors Won’t Tell- DemandScience | 2026-06-11T00:00:00.000Z |
| 7 | `https://www.marketscale.com/industries/marketing-tech/why-most-b2b-abm-programs-fail-before-the-first-campaign-goes-live` | Why most B2B ABM programs fail before launch | 2026-07-17T00:00:00.000Z |
| 8 | `https://www.usergems.com/blog/outbound-abm` | The Complete Outbound ABM Guide for Modern Revenue Teams | 2025-07-17T00:00:00.000Z |
| 9 | `https://www.humanr.ai/intelligence/abm-implementation-failures-why-70-percent-miss-roi` | Why Most ABM Programs Miss ROI (And How to Fix It) | 2026-04-29T00:00:00.000Z |
| 10 | `https://thesmarketers.com/ebook/why-abm-programs-fail/` | Why ABM Programs Fail and How to Fix Yours | 2026-04-29T00:00:00.000Z |

### `d7_fintech_banks` — angle: *vertical_fintech_finite_market*

```
POST https://api.exa.ai/search
{
  "query": "venture-backed US fintech software company selling software to banks and credit unions, enterprise deals, named account sales",
  "type": "auto",
  "numResults": 10,
  "contents": {
    "text": {
      "maxCharacters": 1200
    }
  }
}
```

`HTTP 200` · **1.51s** · **$0.007** · 10 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://www.uptiq.ai/` | Uptiq - Financial AI Platform for Banks, Credit Unions & Wealth Firms | — |
| 2 | `https://linkedin.com/company/withglide` | glide | 2026-06-23T00:00:00.000Z |
| 3 | `https://linkedin.com/company/fusefinance` | fuse | 2026-06-26T00:00:00.000Z |
| 4 | `https://linkedin.com/company/vikartech` | vikar | 2026-06-26T00:00:00.000Z |
| 5 | `https://linkedin.com/company/spiral-gives` | spiral | 2026-06-28T00:00:00.000Z |
| 6 | `https://linkedin.com/company/akuvo` | akuvo | 2026-06-22T00:00:00.000Z |
| 7 | `https://linkedin.com/company/linkerfinance` | linker finance | 2026-06-23T00:00:00.000Z |
| 8 | `https://www.naehas.com/` | Accelerate Value in Banking with Naehas \| Personalized at Scale | — |
| 9 | `https://adapfin.com/` | AI-Native Core Banking Platform for Community Banks | — |
| 10 | `https://www.candescent.com/` | Candescent \| Intelligent Banking Platform | — |

### `d8_agency` — angle: *agency_second_order*

```
POST https://api.exa.ai/search
{
  "query": "venture-backed US B2B marketing services company running account-based marketing programs for enterprise software clients",
  "type": "auto",
  "numResults": 10,
  "contents": {
    "text": {
      "maxCharacters": 1200
    }
  }
}
```

`HTTP 200` · **1.08s** · **$0.007** · 10 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://trevon.network/` | Trevon \| B2B Pipeline Marketing at Scale | — |
| 2 | `https://www.ignitium.com/enterprise-abm-agency` | Enterprise ABM Agency for Marketing Leaders \| Ignitium | — |
| 3 | `https://www.revvgrowth.com/abm-agency` | The ABM Agency for SaaS \| ABM Services \| Revvgrowth | — |
| 4 | `https://forefrontabm.com/` | Forefront ABM \| B2B Account-Based Marketing Consulting | — |
| 5 | `https://linkedin.com/company/precision-point-abm` | precisionpoint | 2026-06-23T00:00:00.000Z |
| 6 | `https://linkedin.com/company/abm-demand` | abm demand | 2026-06-10T00:00:00.000Z |
| 7 | `https://www.prnewswire.com/news-releases/sproutsai-raises-9m-pre-series-a-led-by-true-global-ventures-and-accel-to-scale-revenue-agents-with-differentiated-data-for-b2b-enterprises-302772512.html` | Sprouts.ai Raises $9M Pre-Series A Led by True Global Ventures and Accel to Scale Revenue Agents with Differentiated Data for B2B Enterprises | 2026-05-15T00:00:00.000Z |
| 8 | `https://www.cbinsights.com/company/sproutsai` | Sprouts.ai - Products, Competitors, Financials, Employees, Headquarters Locations | 2026-05-15T00:00:00.000Z |
| 9 | `https://linkedin.com/company/khronos-agency` | khronos | 2026-03-19T00:00:00.000Z |
| 10 | `https://www.ignitium.com/home/account-based-marketing-agency` | Ignitium \| Account Based Marketing Agency for Scaling Enterprise-Wide | — |

## Appendix B — the 10 gate-verification queries (H1 US / H2 Series A+), verbatim

### `v_cogent_security`

```
POST https://api.exa.ai/search
{
  "query": "Cogent Security AI autonomous cyber defense funding round investors headquarters",
  "type": "auto",
  "numResults": 5,
  "contents": {
    "text": {
      "maxCharacters": 1500
    }
  }
}
```

`HTTP 200` · **1.18s** · **$0.007** · 5 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://linkedin.com/company/cogentsecurity` | cogent | 2026-06-16T00:00:00.000Z |
| 2 | `https://www.cogent.com/blog/cogent-security-raises-42m-series-a` |  | — |
| 3 | `https://www.prnewswire.com/news-releases/cogent-security-raises-42m-series-a-to-arm-security-teams-with-autonomous-ai-agents-302691566.html` | Cogent Security Raises $42M Series A to Arm Security Teams With ... | 2026-02-18T00:00:00.000Z |
| 4 | `https://www.securityweek.com/cogent-security-raises-42-million-for-ai-driven-vulnerability-management/` | Cogent Security Raises $42 Million for AI-Driven Vulnerability Management | 2026-02-18T00:00:00.000Z |
| 5 | `https://fortune.com/2026/02/18/exclusive-bain-and-greylock-bet-42-million-that-ai-agents-can-finally-fix-cybersecuritys-messiest-bottleneck/` | Exclusive: Bain and Greylock bet $42 million that AI agents can fix cybersecurity’s worst bottleneck \| Fortune | 2026-02-18T00:00:00.000Z |

### `v_oscilar`

```
POST https://api.exa.ai/search
{
  "query": "Oscilar AI Risk Decisioning Neha Narkhede funding round Series A investors headquarters",
  "type": "auto",
  "numResults": 5,
  "contents": {
    "text": {
      "maxCharacters": 1500
    }
  }
}
```

`HTTP 200` · **2.02s** · **$0.007** · 5 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://www.cbinsights.com/company/oscilar` | Oscilar - Products, Competitors, Financials, Employees, Headquarters Locations | 2023-04-10T00:00:00.000Z |
| 2 | `https://linkedin.com/company/oscilar-inc` | Oscilar | — |
| 3 | `https://techcrunch.com/2023/03/30/oscilar-emerges-from-stealth-to-fight-transactions-fraud-with-ai/` | Oscilar emerges from stealth to fight transactions fraud with AI | 2023-03-30T00:00:00.000Z |
| 4 | `https://oscilar.com/about-us` | About Oscilar | — |
| 5 | `https://www.prnewswire.com/news-releases/renowned-technologists-and-entrepreneurs-neha-narkhede-and-sachin-kulkarni-announce-launch-of-oscilar--the-first-company-that-uses-real-time-data-and-ai-to-protect-every-online-transaction-301785090.html` | Renowned technologists and entrepreneurs Neha Narkhede and Sachin Kulkarni announce launch of Oscilar - the first company that uses real-time data and AI to protect every online transaction | 2023-03-30T00:00:00.000Z |

### `v_harmonic_security`

```
POST https://api.exa.ai/search
{
  "query": "Harmonic Security AI governance funding Series A Series B investors headquarters",
  "type": "auto",
  "numResults": 5,
  "contents": {
    "text": {
      "maxCharacters": 1500
    }
  }
}
```

`HTTP 200` · **1.33s** · **$0.007** · 5 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://linkedin.com/company/harmonic-security` | harmonic security | 2026-06-26T00:00:00.000Z |
| 2 | `https://www.cbinsights.com/company/harmonic-security` | Harmonic Security - Products, Competitors, Financials, Employees, Headquarters Locations | 2024-10-02T00:00:00.000Z |
| 3 | `https://www.crunchbase.com/organization/harmonic-security` | Harmonic Security - Crunchbase Company Profile & Funding | — |
| 4 | `https://www.harmonic.security/resources/harmonic-security-raises-17-5-million-series-a-to-accelerate-zero-touch-data-protection-to-market` | Harmonic Security Raises $17.5 Million Series A to ... | 2025-04-16T00:00:00.000Z |
| 5 | `https://www.harmonic.security/about` | Harmonic Security \| About | — |

### `v_zafran_security`

```
POST https://api.exa.ai/search
{
  "query": "Zafran Security funding Series B investors headquarters location",
  "type": "auto",
  "numResults": 5,
  "contents": {
    "text": {
      "maxCharacters": 1500
    }
  }
}
```

`HTTP 200` · **1.12s** · **$0.007** · 5 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://pitchbook.com/profiles/company/532538-83` | Zafran 2026 Company Profile: Valuation, Funding & Investors | — |
| 2 | `https://linkedin.com/company/zafran-security` | Zafran Security | — |
| 3 | `https://www.zafran.io/resources/zafran-announces-strategic-investment-from-cisco-investments` | Zafran Announces Strategic Investment from Cisco Investments | 2026-07-22T00:00:00.000Z |
| 4 | `https://tracxn.com/d/companies/zafran/__WnETF18DrQMZWAzVpBz7ZMYUDkaMGQwiNkucwmFp6j8` | Zafran - 2026 Company Profile & Team | 2026-08-06T00:00:00.000Z |
| 5 | `https://www.zafran.io/resources/zafran-triples-arr-in-60m-round-to-reinvent-exposure-management-with-agentic-ai` | Zafran Triples ARR in $60M Round to Reinvent Exposure ... | 2025-12-02T00:00:00.000Z |

### `v_revenuecat`

```
POST https://api.exa.ai/search
{
  "query": "RevenueCat funding Series C investors headquarters San Francisco",
  "type": "auto",
  "numResults": 5,
  "contents": {
    "text": {
      "maxCharacters": 1500
    }
  }
}
```

`HTTP 200` · **1.23s** · **$0.007** · 5 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://www.businesswire.com/news/home/20250522835623/en/RevenueCat-Raises-%2450M-Series-C-to-Expand-Global-Infrastructure-for-Consumer-Software-Monetization` | RevenueCat Raises $50M Series C to Expand Global ... | 2025-05-22T00:00:00.000Z |
| 2 | `https://techcrunch.com/2025/05/22/revenuecat-raises-50m-as-it-expands-beyond-mobile-app-monetization/` | RevenueCat raises $50M as it expands beyond mobile ... | 2025-05-22T00:00:00.000Z |
| 3 | `https://www.reuters.com/technology/subscription-management-platform-revenuecat-raises-50-million-series-c-funding-2025-05-22/` | Subscription management platform RevenueCat raises ... | 2025-05-22T00:00:00.000Z |
| 4 | `https://www.thesaasnews.com/news/revenuecat-raises-50-million-in-series-c/` | RevenueCat Raises $50 Million in Series C | 2025-05-26T00:00:00.000Z |
| 5 | `https://www.vcbacked.co/company/revenuecat` | RevenueCat Funding & Investors - Series C - San Francisco | 2025-05-22T00:00:00.000Z |

### `v_arintra`

```
POST https://api.exa.ai/search
{
  "query": "Arintra autonomous medical coding Series B funding investors headquarters",
  "type": "auto",
  "numResults": 5,
  "contents": {
    "text": {
      "maxCharacters": 1500
    }
  }
}
```

`HTTP 200` · **1.09s** · **$0.007** · 5 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://www.arintra.com/resources/press-release/arintra-banks-25m-series-b-funding-round-for-ai-driven-revenue-assurance-platform` | Arintra Raises $25M Series B to Scale Revenue Assurance | 2026-08-26T13:02:58.000Z |
| 2 | `https://www.cbinsights.com/company/arintra` | Arintra - Products, Competitors, Financials, Employees, Headquarters Locations | 2025-08-12T00:00:00.000Z |
| 3 | `https://www.arintra.com/resources/press-release/arintra-raises-25m-to-pioneer-revenue-assurance-for-americas-health-systems` | Arintra Raises $25M to Pioneer Revenue Assurance | 2026-08-27T07:20:11.083Z |
| 4 | `https://dealroom.co/news/146173-arintra-lands-25m-series-b-for-autonomous-medical-coding/` | Arintra lands $25M Series B for autonomous medical coding | 2026-08-20T00:00:00.000Z |
| 5 | `https://www.fiercehealthcare.com/finance/arintra-banks-25m-series-b-funding-round-ai-driven-revenue-assurance-platform` | Arintra nabs $25M for AI-driven revenue assurance | 2026-08-26T13:00:00.000Z |

### `v_translucent_health`

```
POST https://api.exa.ai/search
{
  "query": "Translucent healthcare finance $27M Series A GV headquarters founders",
  "type": "auto",
  "numResults": 5,
  "contents": {
    "text": {
      "maxCharacters": 1500
    }
  }
}
```

`HTTP 200` · **0.99s** · **$0.007** · 5 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://linkedin.com/company/translucentai` | translucent ai | 2026-06-14T00:00:00.000Z |
| 2 | `https://fortune.com/2026/03/11/exclusive-translucent-ai-native-healthcare-finance-startup-raises-27-million-series-a/` | Exclusive: Translucent, an AI-native healthcare finance startup, raises ... | 2026-03-11T00:00:00.000Z |
| 3 | `https://www.translucent.ai/blog/translucent-ai-raises-27m-series-a-led-by-gv` | Translucent Announces $27M Series A Led by GV to Tackle Healthcare's Existential Financial Crisis \| Translucent AI | 2026-03-24T00:00:00.000Z |
| 4 | `https://www.businesswire.com/news/home/20260311059455/en/Translucent-Announces-%2427M-Series-A-Led-by-GV-to-Tackle-Healthcares-Existential-Financial-Crisis` | Translucent Announces $27M Series A Led by GV to Tackle Healthcare's Existential Financial Crisis | 2026-03-11T00:00:00.000Z |
| 5 | `https://www.gv.com/news/translucent-ai-healthcare` | Translucent AI: Healthcare’s Financial OS | 2026-03-11T00:00:00.000Z |

### `v_prosper_ai`

```
POST https://api.exa.ai/search
{
  "query": "Prosper AI patient access automation $30M Series A a16z headquarters",
  "type": "auto",
  "numResults": 5,
  "contents": {
    "text": {
      "maxCharacters": 1500
    }
  }
}
```

`HTTP 200` · **0.76s** · **$0.007** · 5 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://www.getprosper.ai/company` | About Prosper AI \| $30M Series A Led by a16z | — |
| 2 | `https://a16z.com/announcement/investing-in-prosper-ai/` | Investing in Prosper AI \| Andreessen Horowitz | 2026-06-22T00:00:00.000Z |
| 3 | `https://www.fiercehealthcare.com/ai-and-machine-learning/prosper-ai-lands-30m-backed-andreessen-horowitz-build-ai-workforce` | Andreessen Horowitz backs Prosper AI's $30M series A round | 2026-06-22T00:00:00.000Z |
| 4 | `https://www.globenewswire.com/news-release/2026/06/22/3315343/0/en/Prosper-AI-raises-30M-from-Andreessen-Horowitz-to-scale-the-first-AI-platform-to-run-the-entire-patient-journey.html` | Prosper AI raises $30M from Andreessen Horowitz to scale | 2026-06-22T00:00:00.000Z |
| 5 | `https://www.getprosper.ai/blog/prosper-ai-raises-30m-from-andreessen-horowitz-to-scale-the-first-ai-platform-to-run-the-entire-patient-journey` | Prosper AI Raises $30M Series A Led by a16z | 2026-08-05T00:00:00.000Z |

### `v_vendelux`

```
POST https://api.exa.ai/search
{
  "query": "Vendelux event intelligence $50M funding round investors headquarters New York",
  "type": "auto",
  "numResults": 5,
  "contents": {
    "text": {
      "maxCharacters": 1500
    }
  }
}
```

`HTTP 200` · **1.34s** · **$0.007** · 5 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://www.businessinsider.com/vendelux-just-raised-50-million-to-capitalize-live-b2b-events-2026-7` | Vendelux Just Raised $50 Million to Capitalize on Live B2B Events - Business Insider | 2026-07-08T00:00:00.000Z |
| 2 | `https://www.finsmes.com/2026/07/vendelux-raises-50m-in-series-b-funding.html` | Vendelux Raises $50M in Series B Funding | 2026-07-10T00:00:00.000Z |
| 3 | `https://vendelux.com/about` | About Us \| Vendelux | 2026-02-06T00:00:00.000Z |
| 4 | `https://firstmark.com/story/vendelux-raises-50m-series-b-to-bring-ai-led-intelligence-to-b2b-events/` | Vendelux Raises $50M Series B to Bring AI-led Intelligence to B2B Events - FirstMark | 2026-07-08T00:00:00.000Z |
| 5 | `https://www.cbinsights.com/company/vendelux` | Vendelux - Products, Competitors, Financials, Employees ... | 2026-07-08T14:07:29.000Z |

### `v_uptiq`

```
POST https://api.exa.ai/search
{
  "query": "Uptiq AI financial AI platform for banks credit unions funding round headquarters",
  "type": "auto",
  "numResults": 5,
  "contents": {
    "text": {
      "maxCharacters": 1500
    }
  }
}
```

`HTTP 200` · **1.72s** · **$0.007** · 5 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://www.businesswire.com/news/home/20260212072104/en/Uptiq-Raises-%2425-Million-Series-B-to-Scale-Industry-Ready-AI-Solutions-and-Launch-Qore-for-Builders` | Uptiq Raises $25 Million Series B to Scale Industry-Ready AI Solutions and Launch Qore for Builders | 2026-02-13T00:00:00.000Z |
| 2 | `https://www.uptiq.ai/` | Uptiq - Financial AI Platform for Banks, Credit Unions & Wealth ... | — |
| 3 | `https://pitchbook.com/profiles/company/489650-77` | UPTIQ 2026 Company Profile: Valuation, Funding & Investors | — |
| 4 | `https://www.uptiq.ai/press-releases/uptiq-raises-25m-to-add-ai-agents-to-bank-workflows` | Uptiq - Main | 2026-02-12T00:00:00.000Z |
| 5 | `https://www.uptiq.ai/about-us` | About Uptiq \| AI Agent Platform Built for Financial Services | — |

## Appendix C — the 5 tie-break queries, verbatim

### `t_oscilar_round`

```
POST https://api.exa.ai/search
{
  "query": "Oscilar raises funding round Series A Series B 2026 investors Neha Narkhede",
  "type": "auto",
  "numResults": 5,
  "startPublishedDate": "2024-01-01T00:00:00.000Z",
  "contents": {
    "text": {
      "maxCharacters": 1200
    }
  }
}
```

`HTTP 200` · **1.98s** · **$0.007** · 5 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://aventure.vc/companies/oscilar-palo-alto-ca-us` | Oscilar - aVenture Company Research | 2024-02-15T00:00:00.000Z |
| 2 | `https://36kr.com/p/2219260858544771` | 海外New Things \|利用AI保障在线交易安全，「Oscilar」自筹2000万美元-36氪 | 2026-07-07T00:00:00.000Z |
| 3 | `https://oscilar.com/about-us` | About Oscilar | 2024-09-06T00:00:00.000Z |
| 4 | `https://www.linkedin.com/posts/oscilar-inc_yesterday-in-london-team-oscilar-picked-activity-7476322545324105728-IuPI` | Yesterday in London, Team Oscilar picked up two new awards at the FinTech Futures PayTech Awards. \| Oscilar | 2026-06-26T00:00:00.000Z |
| 5 | `https://rivalsense.co/intel/oscilar/` | Oscilar \| Competitive Intelligence Profile | 2026-02-16T00:00:00.000Z |

### `t_jobs_arintra`

```
POST https://api.exa.ai/search
{
  "query": "Arintra marketing demand generation growth job opening",
  "type": "auto",
  "numResults": 5,
  "includeDomains": [
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "ashbyhq.com",
    "careers.smartrecruiters.com",
    "wellfound.com"
  ],
  "contents": {
    "text": {
      "maxCharacters": 1200
    }
  }
}
```

`HTTP 200` · **1.24s** · **$0.007** · 5 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://jobs.ashbyhq.com/zania/70a3e7ce-37f6-432e-95a2-ce0194494c1a` | Growth & Demand Generation at Zania | 2026-08-03T00:00:00.000Z |
| 2 | `https://wellfound.com/jobs/4544847-senior-growth-demand-gen` | Senior Growth Demand Gen at Softr • New York City • San Francisco • London • Remote (Work from Home) \| Wellfound | — |
| 3 | `https://job-boards.greenhouse.io/aperaaiinc/jobs/5086182007` | Job Application for Marketing Demand Generation & Campaign Manager  at Apera AI Inc | — |
| 4 | `https://jobs.ashbyhq.com/builder-prime/50dd8569-5eaf-46a2-bdc7-c1508ed0c1ab` | Senior Demand Generation & Growth Marketing Manager at Builder-prime | 2026-08-05T00:00:00.000Z |
| 5 | `https://jobs.ashbyhq.com/optro/b9d8f372-741f-47a9-9af7-e793ee86fbff` | Senior Demand Generation Manager at Optro | 2026-07-31T00:00:00.000Z |

### `t_jobs_uptiq`

```
POST https://api.exa.ai/search
{
  "query": "Uptiq marketing demand generation growth job opening banks credit unions",
  "type": "auto",
  "numResults": 5,
  "includeDomains": [
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "ashbyhq.com",
    "careers.smartrecruiters.com",
    "wellfound.com"
  ],
  "contents": {
    "text": {
      "maxCharacters": 1200
    }
  }
}
```

`HTTP 200` · **1.72s** · **$0.007** · 5 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://jobs.ashbyhq.com/glia/4cdacf7f-a3c1-45fc-8997-eb180c4de7b1` | Growth Marketing Manager @ Glia | — |
| 2 | `https://job-boards.greenhouse.io/mxtechnologiesinc/jobs/4246603009` | Job Application for Demand Generation Manager at MX Technologies, Inc. | — |
| 3 | `https://wellfound.com/jobs/4480918-demand-generation-manager-mid-market-banking` | Demand Generation Manager - Mid-Market Banking at Alloy • New York City \| Wellfound | — |
| 4 | `https://jobs.ashbyhq.com/relayfi/8c97e561-ee64-427e-a7b5-16fc35c59791` | Senior Demand Generation Specialist @ Relay | — |
| 5 | `https://wellfound.com/jobs/4475795-demand-generation-manager-mid-market-banking` | Demand Generation Manager - Mid-Market Banking at Alloy • New York City \| Wellfound | — |

### `t_jobs_vendelux`

```
POST https://api.exa.ai/search
{
  "query": "Vendelux marketing demand generation growth job opening events intelligence",
  "type": "auto",
  "numResults": 5,
  "includeDomains": [
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "ashbyhq.com",
    "careers.smartrecruiters.com",
    "wellfound.com"
  ],
  "contents": {
    "text": {
      "maxCharacters": 1200
    }
  }
}
```

`HTTP 200` · **1.39s** · **$0.007** · 5 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://jobs.ashbyhq.com/vendelux/ad171a33-af7d-42b3-86fb-4e3dbb30116a` | Growth Marketing Lead at Vendelux | 2026-04-16T00:00:00.000Z |
| 2 | `https://jobs.ashbyhq.com/vendelux/634ef70b-e32c-409c-bcb1-f8ac69e8d18c` | Product Marketing Lead @ Vendelux | — |
| 3 | `https://jobs.ashbyhq.com/Vendelux/ad171a33-af7d-42b3-86fb-4e3dbb30116a` | Growth Marketing Lead @ Vendelux | — |
| 4 | `https://jobs.ashbyhq.com/vendelux/b5ea116c-95dc-47ad-adb0-3cdfa97a7620` | Revenue Operations Lead at Vendelux | 2026-06-02T00:00:00.000Z |
| 5 | `https://jobs.ashbyhq.com/vendelux/7dfeabd3-7595-490b-af19-dff052216d67` | Outreach Campaign Operations Manager @ Vendelux | — |

### `t_jobs_translucent`

```
POST https://api.exa.ai/search
{
  "query": "Translucent AI healthcare finance marketing growth job opening New York",
  "type": "auto",
  "numResults": 5,
  "includeDomains": [
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "ashbyhq.com",
    "careers.smartrecruiters.com",
    "wellfound.com"
  ],
  "contents": {
    "text": {
      "maxCharacters": 1200
    }
  }
}
```

`HTTP 200` · **1.09s** · **$0.007** · 5 results returned

| # | URL (verbatim) | Title (verbatim) | publishedDate |
|---|---|---|---|
| 1 | `https://job-boards.greenhouse.io/translucent/jobs/4038826009` | Job Application for Software Engineer at Translucent | — |
| 2 | `https://job-boards.greenhouse.io/translucent/jobs/4368978009` | Job Application for Product Manager / Sr. Product Manager at Translucent | — |
| 3 | `https://job-boards.greenhouse.io/translucent/jobs/4369098009` | Job Application for Product Lead at Translucent | — |
| 4 | `https://job-boards.greenhouse.io/translucent/jobs/4338339009` | Forward Deployed Insights Engineer (Applied AI) | — |
| 5 | `https://job-boards.greenhouse.io/translucent/jobs/4331918009` | Job Application for AI Engineer at Translucent | — |
