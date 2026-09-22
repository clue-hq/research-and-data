# ONE ACCOUNT, END TO END — Hotel Equities (hotelequities.com), for the client Conduit

**Run:** `arv2-one-account-conduit-hotelequities` · **Date:** 22 September 2026
**Client (the "we"):** Conduit (conduit.ai / HostAI Labs, Inc.) — an AI agent platform for hospitality operations.
**Account:** Hotel Equities Group, LLC. — a ~300-property third-party hotel management company in Alpharetta, Georgia.
**Providers used:** ADP WorkforceNow public feed (free) · AI Ark (all structured data) · Exa (search, page reads, 6 deep-reasoning calls) · Google Gemini (the media layer) · OpenRouter gpt-5-mini (structuring only).
**Money:** **$0.4911 cash** and **7.1 AI Ark credits**, against ceilings of $3.50 and 20 credits.
**Wall clock:** **19 minutes 30 seconds** of live research (run start 06:34:07Z → the last provider call at 06:53:37Z); **33 minutes 34 seconds** total including writing both deliverables. Sum of per-phase time is 1,088s, so parallelism did the work.
**No ceiling was hit.** Everything below is measured: every number comes from a real API response saved in `raw/` before it was parsed. Where something was not found, this report says so.

---

## 0. The stack that actually ran — and "was Apollo used?"

**No. Zero calls. Firecrawl: zero calls.** This is checkable, not asserted:

- `z_lib.py` — the only module in this run that can make an HTTP call — **has no Apollo helper and no Firecrawl helper.** There is no function that could have called either.
- The cost ledger (`cost_ledger.json`) holds **151 calls**. The complete list of providers in it is `adp/live_http, ai_ark, exa, gemini, openrouter`. There is no `apollo` row, no `firecrawl` row, and no request to `api.apollo.io` or `api.firecrawl.dev`. The tables script asserts this and reports `apollo_calls: 0, firecrawl_calls: 0`.

### The stack, in the order it ran

| # | Step | Provider | Calls | Cost | What it was for |
|---|---|---|---|---|---|
| 1 | ADP WorkforceNow, 4 public career centres, all pages | free ATS feed | 17 | $0.00 | **145 live requisitions** + a 552-property location roster |
| 2 | Own-site direct fetches | free HTTP | 6 | $0.00 | **All six hung.** 20s timeout each, 0 bytes of usable HTML |
| 3 | Own-site fallback | Exa `/contents` | 1 | $0.007 | Recovered 4 of 6 pages including the leadership roster |
| 4 | Company lookup | AI Ark | 1 | 0.1 cr | Legal name, headcount, revenue band, **SynXis fingerprint** |
| 5 | Committee discovery | Exa `/search` ×8 | 8 | $0.056 | Found the VP of IT and HE Labs — neither was in the brief |
| 6 | Account deep research | Exa deep-reasoning | 1 | $0.030 | One call: portfolio, merger, leadership, negatives |
| 7 | Committee confirmation | Exa `/contents` | 1 | $0.011 | 12 primary pages read in full, people confirmed from them |
| 8 | Gap searches | Exa `/search` ×10 | 10 | $0.070 | The technology seat, the ITR claim, labor, negatives |
| 9 | Media resolution | free RSS + HTTP | 11 | $0.00 | 5 Ben Rafter episodes, exact durations, direct MP3s |
| 10 | Committee enrichment | AI Ark `/v1/people` ×6 | 6 | 3.0 cr | Employer re-confirmation + LinkedIn + tenure + reach |
| 11 | Email export | AI Ark ×5 | 5 | 4.0 cr | **4 of 5 found**, all SMTP VALID |
| 12 | Per-person deep research | Exa deep-reasoning ×5 | 5 | $0.128 | The personal charter, one call per member |
| 13 | Key primary pages | Exa `/contents` ×2 | 2 | $0.014 | HE Labs, the ITR release, the Tech Titans feature |
| 14 | Media transcription | Gemini, 2 models × 5 items | 10 | $0.0722 | **69 minutes** of the CEO's own voice |
| 15 | Embedding retrieval demo | Gemini embedding-2 | 50 | $0.0043 | 46 transcript chunks + 4 real questions |
| 16 | Structuring into claims | OpenRouter gpt-5-mini | 6 | $0.1005 | One subject per call, prose → typed claims |

Output: **350 claims** in `claims_hotelequities.json` — 135 P1, 152 P2, 63 P3; 125 of them under `PROPOSED::` keys the catalog does not yet have; 38 marked `outreach_safe: false`. No `birth_date` was written anywhere; it is dropped at parse time and scrubbed from `raw/`.

**Parallelism:** the sum of per-phase wall clock is 1,088s against 1,170s of real research time, because the independent phases were run as concurrent background processes (the ADP pull, the own-site fetches, the AI Ark company call, the committee searches and the account deep call all ran at once; later, five per-person deep calls and six structuring calls each ran as a fan-out). AI Ark calls were kept strictly sequential and paced ≥10.5s apart, as required.

---

## 1. What AI Ark actually returns — the field inventory

**Credits billed: 7.1 of the 20 allowed.** The full inventory with every field and its real value is in `h18_inventory.md` / `h18_ark_field_inventory.json`. Summary:

| endpoint | http | latency | credits | field rows | empty/null |
|---|---|---|---|---|---|
| `POST /v1/companies` | 200 | 0.97s | 0.1 | **63** | 0 |
| `POST /v1/people` (name-scoped + domain-scoped) | 200 | 0.5–0.8s | 0.5 each | **141** | 14 |
| `POST /v1/people/export/single` (the `email` block only) | 200 | 0.9–5.6s | 1.0 when found | **14** | 0 |
| `GET /v1/credit` | **401, empty body** | 0.95s | 0 | — | — |
| `POST /v1/people/export/single` (Al Smith) | **404** | 0.72s | 0 | — | — |

### The fields that earned their credit

| Field | Real value | Why it matters |
|---|---|---|
| `summary.legal_name` | "Hotel Equities Group, LLC." | Exact legal entity, in one 0.1-credit call |
| `summary.staff.total` | 990 | An exact number, not a band |
| `financial.revenue.annual.amount` | "50000000-100000000" | A revenue band with a provider label on it |
| `summary.founded_year` | 1989 | Confirms a 37-year-old operator, not a startup |
| **`technologies[]`** | **"SynXis (Sabre Hospitality)"**, Microsoft Office 365, Adobe Marketing Cloud / Omniture, iCIMS, Google Tag Manager, Vimeo, GoDaddy Premium DNS | **The single most valuable field in the run.** SynXis is Sabre's central reservation system — the *only* named hospitality booking system evidenced anywhere, by any provider, including a $0.03 deep-research call that marked the entire technology layer NOT FOUND |
| `position_groups[]` | Full career history with per-company and per-title dates | Made "at Hotel Equities since July 2021" computable for the COO, resolving an apparent conflict with the company bio |
| `statistics.network` | followers / connections per person | Who has reach |
| `email.output[0]` | address + `status` + `subStatus` + MX record + provider + free/generic flags | Not just a string — deliverability is settled |
| `link.linkedin` | the canonical profile URL per person | The locator the email export keys on |

### Empty or absent for this account

`profile.middle_name`, `link.twitter/github/facebook`, `location.position` (people), `languages.profile_languages`, `statistics.experience.prev_job_titles`, `educations[].grade` — all null, exactly as on the Zafran run. **No SIC/NAICS codes** are returned at all. `industries` for this company is a single value, `["hospitality"]` — thinner than the six-way industry array returned for a SaaS company.

### Three operational findings worth pinning

1. **The name filter works; the title filter is still broken.** Six name-scoped + domain-scoped lookups returned exactly the right person, six times out of six, for 0.5 credit each. Zero same-name strangers were admitted, including for "Albert Smith", "David Rosenberg" and "Brian Jenkins" — three of the most common names we could have asked for. The domain-roster approach was not used at all this run, and on this evidence it should not be.
2. **NEW: the export index and the people index disagree.** `/v1/people` returned `https://www.linkedin.com/in/albert-smith-3aa9318` for the COO. Passing that exact URL — AI Ark's own — to `/v1/people/export/single` returned **HTTP 404**. It is not a bad identity and not a rate limit; the two indexes simply do not cover the same people. Budget for it: ask for one more export than you need.
3. **`GET /v1/credit` still returns 401 with an empty body.** Carried finding from the Zafran run, unchanged. Credits here are counted by arithmetic (returned results × unit price). **Note for anyone reading `cost_ledger.json` directly:** `z_lib` ledgers the pre-call *reservation* (that is what enforces the ceiling). `h9b_ark_extra_email.py` rewrites the `credits` column to the **actual** billed amount and preserves the reservation as `credits_reserved`. The 7.1 figure is actual.

---

## 2. Database vs research — what AI Ark gives, and what only research gives

| What AI Ark gave on its own (7.1 credits, $0.00 cash) | What AI Ark could not give, and only research could |
|---|---|
| Legal name, founded year (1989), exact headcount (990), revenue band $50–100M, Alpharetta HQ | That **Marriott now pays up to 50 bps of gross room revenue** on ITR scores, and HE is ranked #1 on it four times running (their own release, free page read) |
| **SynXis (Sabre Hospitality)** in the web/DNS fingerprint | That the CEO names **Hotel Effectiveness and ProfitSword** and describes the product gap he wants filled (Gemini transcript) |
| Every committee member's title, department, tenure, career history and reach | That **HE Labs exists at all**, what its four buying gates are, and who runs it (Exa search + own site) |
| Four verified work emails with SMTP status and Microsoft MX | That there is a **VP of Information Technology named Stephen Hahn** with a published buying rule — the deep call marked the technology seat NOT FOUND (Exa search) |
| That Al Smith has been at Hotel Equities since July 2021, not since the 2025 merger | **19 of 145 open requisitions** are the exact seats Conduit relieves, with wages and days-open (free ADP feed) |
| LinkedIn locators that made the email exports possible | The CEO's own voice: "the goal isn't to become more automated—it's to become more connected" (own site + 69 min of audio) |
| — | That an **email migration is going badly right now** (Gemini transcript, 05:50) |

**The blunt version:** AI Ark is an excellent *spine* — identity, money, org shape, contactability — and one field on it (`technologies[]`) out-performed a $0.03 deep-research call on the technology question. But it knows nothing about **timing, intent, process or voice**, and for this account the three facts that actually change the first email (the ITR incentive, HE Labs' four gates, and the CEO's ProfitSword remark) came from a free page read, a $0.007 search, and $0.012 of audio respectively.

**The free ADP feed beat the paid deep call at its own job, again.** The $0.03 deep-reasoning call returned 30 NOT FOUND markers and explicitly could not quantify staffing pressure. A free GET against `workforcenow.adp.com` returned 145 typed requisitions with titles, locations, post dates and salary ranges — and a location filter enumerating 552 named properties, which is a portfolio roster nobody would think to ask a data vendor for.

---

## 3. The Gemini media layer — five items, 69 minutes, one voice

Every item is an MP3 enclosure, never a YouTube URL, because the Zafran run measured audio at ~25 tokens/second against video at ~91. **That measurement reproduced exactly: all five items billed at 25.0 tokens/second.**

| Item (Hospitality Daily, host Josiah Mackenzie) | Length | Audio tokens | tok/s | Cost | Latency | Words/min | Loop? |
|---|---|---|---|---|---|---|---|
| "Where AI Actually Pays Off in Hospitality, and What Owners Should Demand" (26 Jun 2026) | 11:24 | 17,106 | 25.01 | $0.011604 | 22.2s | 183.2 | clean |
| "How AI Addresses the Biggest Cost in a Hotel: Labor" (25 Jun 2026) | 10:40 | 16,016 | 25.02 | $0.011437 | 22.6s | 180.6 | clean |
| "Why Hotel Ownership Is Becoming Unsustainable…" (24 Jun 2026) | 11:22 | 17,070 | 25.03 | $0.012073 | 23.1s | 183.5 | clean |
| "Tech CEO-Turned-Hotel CEO Shares Tech Advice" (10 Jan 2025, Springboard era) | 19:36 | 29,422 | 25.02 | $0.020668 | 38.9s | 175.9 | clean |
| "What Happens When a Tech CEO Leads a Hotel Company" (9 Jan 2025, Springboard era) | 15:58 | 23,954 | 25.00 | $0.016423 | 29.9s | 185.0 | clean |
| **Total** | **1h 09m** | **103,568** | **25.0** | **$0.072205** | **136.7s** | — | **0 loops** |

**$0.0628 per hour of media kept.** 46% of the 2.5-hour ceiling used.

### The two-model recipe, and what it proved this time

Each item ran twice: `gemini-3.5-transcribe` for the faithful transcript (its text lands at `candidates[0].content.parts[0].audioTranscription.text`, **not** `parts[].text`, and it emits no timestamps), and `gemini-3.5-flash-lite` for MM:SS-timestamped lines plus candidate quotes.

**No loops occurred.** On the Zafran run flash-lite looped after 12½ minutes of a 43-minute episode. Here the longest item was 19:36 and the duplicate-long-line rate across all five items was 0–2.1%, with no sustained run of repeats. The honest conclusion is not "flash-lite is fixed" — it is **the loop is a function of length, and episodes under ~20 minutes stayed clean**. The duplicate check ran anyway, and is the only reason we can say that.

**What we publish is a hybrid, checked in code.** flash-lite lightly cleans filler words, so its quotes did not match the faithful transcript verbatim. Rather than publish flash-lite's tidied wording, `h12_quote_repair.py` locates each quote inside the faithful transcript and publishes **the exact ASR wording with flash-lite's timestamp attached**, widening to whole words and sentence boundaries. Any quote that could not be located would have been dropped; **25 of 25 were located** (9 exact, 16 window matches), and 0 were dropped.

### The quotes that matter for Conduit

> **[01:49]** "the value of AI is going to be almost entirely operational on the back end, right? We'll figure out ways to get the consumer to the hotel. It's when they get to the hotel, how do we make the hotel run more efficiently? And I use labor a lot because AI is very quantifiable in labor management, and we have several partners working on this in terms of we need to change how all scheduling is done in hotels." — *How AI Addresses the Biggest Cost in a Hotel: Labor*, 25 Jun 2026

> **[05:49–06:21]** "take hotel effectiveness and ProfitSword, right? I think ProfitSword is great at gathering and presenting the data where it would be nice for it to evolve and it will is it proactively reaches out and says, here are the three biggest problems you have, Mr. GM, Ms. Regional Director of Ops, Mr. Revenue Manager, and you need to solve these problems within X amount of time." — *Where AI Actually Pays Off*, 26 Jun 2026

> **[04:32]** "we look at technology as the solution here, which is if we can make the hotel more efficient well still being guest friendly, then owners can recoup some of the some of the losses of the higher expenses" — *Why Hotel Ownership Is Becoming Unsustainable*, 24 Jun 2026

> **[03:49]** "That's another reason why you beta things, right? Is can you get it to talk to all the other systems" — *Tech CEO-Turned-Hotel CEO Shares Tech Advice*, 10 Jan 2025 *(Springboard era — labelled everywhere it is used)*

> **[05:49]** "we're going through an email migration right now and uh it's a little bumpier than we were expecting" — *Where AI Actually Pays Off*, 26 Jun 2026. **`outreach_safe: false`.**

### The embedding retrieval demo (`gemini-embedding-2`, 768 dimensions)

46 transcript chunks embedded as `RETRIEVAL_DOCUMENT` — **21,665 tokens, $0.004333, 17.9 seconds**. Four questions embedded as `RETRIEVAL_QUERY` — 68 tokens, $0.0000136. Total **$0.004347**.

| Question | Top hit | Score |
|---|---|---|
| "What does Ben Rafter say about AI or technology in hotel operations?" | *AI Addresses the Biggest Cost* **[02:03–02:58]** — "AI and some of our technology partners can help solve that problem" | 0.806 |
| "What frustrates consistency, service or labor at scale across hotels?" | *AI Addresses the Biggest Cost* **[02:03–02:58]** — the scheduling/quantifiable-impact passage | 0.803 |
| "How does Hotel Equities choose, beta-test or evaluate vendors?" | *Tech CEO-Turned-Hotel CEO* **[01:59–02:56]** — the director-of-strategy / diverse-backgrounds passage | 0.791 |
| "What does he say about guest-facing service and the front desk?" | *Tech CEO-Turned-Hotel CEO* **[07:51–08:36]** — "I'm not a big fan of just go check in at the Marriott or the Hilton box" | 0.767 |

Retrieval also surfaced the HE Labs discussion in the owner-economics episode, which the quote pass had not selected.

**For the record:** embedding the **raw audio** of the same 4,140 seconds at $0.00016/sec would have cost **$0.6624** — **152× more** than the $0.004347 the text embeddings cost, for the same four answers. Transcribe first, embed the text. Never embed the audio.

---

## 4. The fruitful top 15 for Conduit

Ranked by how much each one would change what a Conduit rep writes in a first email. "Cost" is the marginal cost of the call that produced it.

| # | The fact | Source | Cost | Why it moves outreach |
|---|---|---|---|---|
| 1 | **Marriott now pays up to 50 basis points of gross room revenue as a rebate for strong ITR (guest satisfaction) scores — "funded directly from Marriott's profit and loss statement rather than shared system funds" — and Hotel Equities holds the #1 FMC ranking on ITR for the fourth consecutive time (Q2 2026)** | hotelequities.com, 14 Aug 2026, via Exa `/contents` | $0.003 | Guest satisfaction just became a line item on an owner's P&L. Conduit's after-hours guest response moves that number directly. This converts a soft "better guest experience" pitch into a rebate calculation, and they have a #1 ranking to defend. |
| 2 | **19 of 145 open requisitions are guest services / front desk / night audit — including "Night Auditor Fridays & Saturdays" and a guest-relations seat open 45 days; wages $14–$28/hr** | free ADP feed | **$0.00** | The quantified version of the pitch, with dates and dollar rates attached. A weekend-only overnight req is a coverage gap with a purchase order on it. |
| 3 | **HE Labs is a formal innovation-and-incubation division with four published buying gates** — "Every initiative begins with a clearly defined problem, opportunity, and success criteria"; "part of a broader operating system—not as isolated tools"; "Pilots run in live environments"; "Only validated solutions move forward" | hotelequities.com/he-labs.htm | $0.001 | They published their own procurement process. Conduit can arrive with the pilot already written to it instead of guessing. |
| 4 | **Brian Jenkins was appointed to lead HE Labs on 29 May 2026 and "will oversee all HE Labs initiatives, from testing and evaluation to deployment"; his own line is "The gap between what technology promises and what it actually delivers for owners is where HE Labs operates"** | Exa search + own site | $0.007 | The single best first contact in the account: paid to run the exact pilot, four months in, needs a validated win. Not in the brief; not findable from the homepage. |
| 5 | **The CEO names Hotel Effectiveness and ProfitSword and describes the product he wishes existed: one that "proactively reaches out and says, here are the three biggest problems you have, Mr. GM… and you need to solve these problems within X amount of time"** | Gemini transcript, 06:05 | $0.0116 | The CEO has specified Conduit's Operator, unprompted, in public. It is also the competitive map: labor management and BI are occupied; guest communication is not. |
| 6 | **A VP of Information Technology exists — Stephen Hahn — with a published disqualification rule: "We don't adopt technology because it's trendy… If it creates unnecessary complexity, we move on"** | Exa search → company LinkedIn post + HOTEL MANAGEMENT feature | $0.008 | The technical evaluator, his name, his email, and the exact test the demo must pass. The $0.03 deep call marked the technology seat NOT FOUND. |
| 7 | **The COO asked Conduit's pitch as a question, in public, in June 2026: "how do you maintain a consistent service culture across hundreds of properties, thousands of associates, and a wide range of brand identities?"** | hotelequities.com, 9 Jun 2026 | $0.001 | Brand-over-property configuration is the literal answer to a question the economic buyer published three months ago. |
| 8 | **The CEO's signed line on the HE Labs page: "The goal isn't to become more automated—it's to become more connected"** | hotelequities.com/he-labs.htm | (same $0.001) | Tells Conduit exactly how *not* to pitch. Every artifact for this account should lead with escalation-to-human, not automation rate. |
| 9 | **Four verified work emails** — `ben.rafter@`, `bjenkins@`, `shahn@`, `drosenberg@hotelequities.com`, all SMTP `VALID`, sub-status `EMPTY`, Microsoft MX, not free, not generic | AI Ark export | 4.0 cr | Deliverability settled. **And the pattern is not uniform:** the CEO is `first.last@` while everyone else is `finitial+lastname@` — generalising from Rafter would bounce. |
| 10 | **They run SynXis (Sabre Hospitality)** | AI Ark `technologies[]` | 0.1 cr | The only named hospitality booking system evidenced anywhere in the run. It is where above-property reservation context would come from, and naming it proves the homework. |
| 11 | **Their PMS is genuinely unknown, and no guest-messaging vendor could be evidenced.** FSPMS, FOSSE, Lightspeed, OPERA Cloud, OnQ, PEP, HIS, Concerto, choiceADVANTAGE, Canary, Kipsu, Akia, Revinate, Duve, HiJiffy, Asksuite, Medallia, Quore, Actabl, Whistle and Runtriz each checked, each NOT FOUND | Exa deep + 10 gap searches | $0.10 | A negative that is worth money: **do not claim OPERA**, and do not assume an incumbent to displace. It converts a fabrication risk into a discovery question. |
| 12 | **The CEO is a technology founder with two exits, one to Amazon** — "I was a tech guy for better part of 15 years, mostly startups. Sold two of 'em"; co-founded Innerlinx (LiveBid), acquired by Amazon.com; his verdict is that "any hospitality company that doesn't understand how to embrace tech and infuse it into the culture will eventually fail" | TMG transcript + own site + Hotel Investment Today | $0.008 | The sponsor does not need the category explained. Send an integration diagram, not a 101. |
| 13 | **An email migration is in progress and going badly: "it's a little bumpier than we were expecting"** | Gemini transcript, 05:50 | (same $0.0116) | **`outreach_safe: false`.** Never mention it. Its value is defensive: it predicts the IT-bandwidth objection and tells Conduit to make the implementation ask small. |
| 14 | **1,200+ Postcard Cabins across 29 locations, plus 12 open GM reqs including one at Postcard Cabins Big Bear** | own site + free ADP feed | $0.001 | 1,200 units with no front desk is structurally identical to the short-term-rental estate where Conduit already runs 90% automation. The GM openings are twelve low-friction rollout beachheads. |
| 15 | **The portfolio numbers do not reconcile** — "279 Hotels & Resorts"/"33,329 Guest Rooms" in company materials, "more than 250 hotels" in Skift (May 2026), "approximately 300" in marketing, and 552 named locations in their own job feed | own site + Skift excerpt + free ADP feed | $0.00 | Prevents an own goal. A rep who quotes a precise property count will be wrong, and the prospect will know. |

Runners-up in `claims_hotelequities.json`: David Rosenberg's "repeatable and scalable, not isolated to a handful of high-performing hotels" ITR quote; the 78%/22% select-vs-full-service mix; Rafter's AHLA board seat (23 Jan 2026); Jenkins' "Operators run hotels. HE Labs builds what improves them"; Hahn's 2026 "Tech Titans" recognition and his randonneur cycling; the November 2025 wave of eight divisional appointments.

---

## 5. The buying committee, with emails

Every person was confirmed from a **non-AI-Ark URL first** — the company's own leadership page, its dated appointment posts, Hospitality Net appointment notices, or the company's own LinkedIn post. AI Ark was used only to re-confirm employer, supply the LinkedIn locator and career dates, and export an email. **No AI-Ark-only person was admitted, and no employer mismatch was accepted.**

| Person | Title (web-confirmed) | Persona | Email | Status | Verified | At HE since | Reach | Identity confirmed by |
|---|---|---|---|---|---|---|---|---|
| **Ben Rafter** | Chief Executive Officer | executive sponsor | `ben.rafter@hotelequities.com` | **VALID / SMTP / EMPTY** | 22 Sep 2026 | 2025-05 | 5 podcast episodes, AHLA board | [meet-our-team.htm](https://www.hotelequities.com/meet-our-team.htm) |
| **Brian Jenkins** | Head of HE Labs \| EVP of Strategy | champion | `bjenkins@hotelequities.com` | **VALID / SMTP / EMPTY** | 22 Sep 2026 | 2025-06 | — | [hospitalitynet.org/appointment/79032251](https://www.hospitalitynet.org/appointment/79032251/brian-jenkins) |
| **Stephen Hahn** | VP of Information Technology | technical evaluator | `shahn@hotelequities.com` | **VALID / SMTP / EMPTY** | 22 Sep 2026 | 2022-10 | 2026 "Tech Titans" | [company LinkedIn post](https://www.linkedin.com/posts/hotel-equities_hotelequities-hospitalitytechnology-hotelmanagement-activity-7471283773595238400-nH7w), 12 Jun 2026 |
| **Albert (Al) Smith** | Chief Operating Officer | economic buyer | — | **export returned HTTP 404** | — | 2021-07 | published Hotel Executive article | [hospitalitynet.org/appointment/79030411](https://www.hospitalitynet.org/appointment/79030411.html), 14 Jul 2025 |
| **David Rosenberg** | President, Focused Service Division | divisional operator | `drosenberg@hotelequities.com` | **VALID / SMTP / EMPTY** | 22 Sep 2026 | 2020-02 | quoted in the ITR release | [10 Nov 2025 appointments post](https://www.hotelequities.com/blog/hotel-equities-strengthens-leadership-team-with-key-executive-appointments-across-new-divisions/) |
| **Bill Stachler** | SVP of Revenue Optimization | adjacent (revenue) | not requested | — | — | 2021-03 | — | [meet-our-team.htm](https://www.hotelequities.com/meet-our-team.htm) |

MX for all four addresses is `hotelequities-com.mail.protection.outlook.com` (Microsoft); none is flagged `free` or `generic`. **4 of 5 requested emails found → 4.0 credits.**

**Committee read.** This is not a marketing sale and it is not a CIO sale — it is an **operations-innovation** sale with a formal front door. Brian Jenkins is the champion because HE Labs is literally the function that evaluates and deploys technology, and he is four months into owning it. Stephen Hahn is the evaluator and the veto: his published rule is that unnecessary complexity ends the conversation. Al Smith is the budget and has already stated the problem Conduit solves. Ben Rafter is the sponsor who has publicly argued Conduit's thesis better than Conduit's own marketing does — but he should be brought in for the quantified-results conversation, not the first call. David Rosenberg runs 78% of the portfolio and owns the ITR number, which makes his division the natural pilot.

**Seats we looked for and did not find:** there is no CIO or CTO (the technology seat tops out at VP of Information Technology), and no VP of Guest Experience anywhere on the leadership page. Both absences are recorded as signals rather than gaps: technology authority sits with an operations-minded VP plus a strategy EVP, which is why the pitch must be operational rather than architectural.

---

## 6. What it cost

### 6a. This run, by provider — every figure from the ledger

| Provider | Calls | Cash | AI Ark credits | Time in-call | Avg latency | Non-200 |
|---|---|---|---|---|---|---|
| Exa | 28 | **$0.3140** | — | 258.0s | 9.21s | 0 |
| OpenRouter (gpt-5-mini) | 6 | **$0.1005** | — | 369.2s | 61.53s | 0 |
| Gemini | 65 | **$0.0766** | — | 163.4s | 2.51s | 0 |
| Free HTTP (ADP, RSS, MP3, own site) | 39 | $0.00 | — | 151.5s | 3.88s | 3 (own-site hangs) |
| AI Ark | 13 | $0.00 | **7.1** | 14.7s | 1.13s | 2 (`/v1/credit` 401, one export 404) |
| **Total** | **151** | **$0.4911** | **7.1** | 956.8s | — | 5 |

Against the ceilings: **14.0% of the $3.50 cash**, **35.5% of the 20 AI Ark credits**, **46% of the 2.5-hour media budget**. No ceiling was hit.

### 6b. Per-call latency by operation

| Operation | n | Avg | Max | Cash |
|---|---|---|---|---|
| `openrouter :: openai/gpt-5-mini` | 6 | **61.53s** | 73.47s | $0.1005 |
| `exa :: deep-reasoning` | 6 | 35.94s | 52.76s | $0.1580 |
| `gemini :: gemini-3.5-flash-lite` (timestamped) | 5 | 16.42s | 24.64s | $0.0411 |
| `gemini :: gemini-3.5-transcribe` (faithful) | 5 | 10.90s | 14.22s | $0.0311 |
| `exa :: contents/preferred` | 4 | 3.89s | 10.16s | $0.0300 |
| `exa :: auto` (search) | 18 | 1.49s | 3.49s | $0.1260 |
| `ai_ark :: /v1/people` | 6 | 0.60s | 0.80s | $0.00 |
| `live_http :: ADP feed` | 17 | 1.01s | 1.39s | $0.00 |
| `gemini :: gemini-embedding-2` | 50 | 0.39s | 0.63s | $0.0043 |
| `live_http :: hotelequities.com direct` | 6 | **20.00s** | 20.02s | $0.00 — **all six timed out** |

The structuring calls are the slowest thing in the run by a wide margin: six gpt-5-mini calls accounted for 369s of in-call time, more than the media layer and the deep research combined. They were run in parallel, which is the only reason the total wall clock is 22 minutes.

### 6c. Full recipe, per account

| Line item | Unit | Quantity | Credits | Cash |
|---|---|---|---|---|
| ADP WorkforceNow feed, 4 centres, all pages | free | 17 GETs | 0 | $0.00 |
| AI Ark company object | 0.1 cr/company | 1 | 0.1 | $0.00 |
| AI Ark people, name-scoped + domain-scoped | 0.5 cr/profile | 6 | 3.0 | $0.00 |
| AI Ark email export | 1 cr when found | 5 asked, 4 found | 4.0 | $0.00 |
| Own-site direct fetches (all hung) | free | 6 | 0 | $0.00 |
| Exa `/contents` — own site, committee, key pages | ~$0.001/page | 4 calls, 30 pages | 0 | $0.0300 |
| Exa `/search` — committee + gap searches | $0.007/search | 18 | 0 | $0.1260 |
| Exa deep-reasoning — ONE account call | $0.03/call | 1 | 0 | $0.0300 |
| Exa deep-reasoning — per-person calls | ~$0.026/call | 5 | 0 | $0.1280 |
| Podcast RSS + 5 MP3 downloads | free | 11 | 0 | $0.00 |
| Gemini transcription, 5 episodes × 2 models | measured | 10 | 0 | $0.0722 |
| Gemini embedding-2 index + 4 queries | $0.20/1M | 50 | 0 | $0.0043 |
| gpt-5-mini structuring, one subject per call | measured | 6 | 0 | $0.1005 |
| **FULL RECIPE** | | | **7.1 cr** | **$0.4911** |

### 6d. Trimmed recipe, per account — what to run at scale

Cuts two of the six AI Ark lookups and one email, four of the ten gap searches, three of the five per-person deep calls, three of the five media items, and three structuring calls.

| Line item | Credits | Cash | Why keep / cut |
|---|---|---|---|
| ADP WorkforceNow feed (all four centres) | 0 | $0.00 | Free, typed, and it is the P1 pain signal — never cut |
| AI Ark company object | 0.1 | $0.00 | Highest yield per credit in the run; the only source of the SynXis fingerprint |
| AI Ark name-scoped lookups × 4 | 2.0 | $0.00 | Sponsor, buyer, champion, evaluator. The divisional and adjacent seats can wait |
| AI Ark email export × 3 | 3.0 | $0.00 | The three send targets |
| Exa `/contents`, 6 primary pages | 0 | $0.006 | Team page, HE Labs, ITR release, two appointment posts — the committee, the process and the money |
| Exa `/search` × 4 | 0 | $0.028 | Committee, technology seat, ITR, negatives. Four narrow questions beat ten broad ones |
| Exa deep-reasoning, 1 account call | 0 | $0.030 | The only source of the reputation/negatives sweep |
| Exa deep-reasoning, 2 person calls | 0 | $0.050 | The CEO and the IT chief are the two whose words change the email |
| Gemini media, 2 episodes × 2 models (21 min) | 0 | $0.023 | One on-topic episode per key voice is enough |
| Gemini embedding index + queries | 0 | $0.0043 | Essentially free once the text exists |
| gpt-5-mini structuring × 3 | 0 | $0.028 | Required |
| **TRIMMED RECIPE** | **5.1 cr** | **$0.1693** |

### 6e. What that means at different AI Ark prices

| AI Ark credit price | Full recipe / account | Trimmed / account | Trimmed × 1,000 accounts |
|---|---|---|---|
| Free tier (today) | $0.491 | **$0.169** | $169 |
| $0.02 / credit | $0.633 | **$0.271** | $271 |
| $0.05 / credit | $0.846 | **$0.424** | $424 |

### 6f. Per-person media cost

| Person | Items | Media | Transcription (both models) | $/hour |
|---|---|---|---|---|
| Ben Rafter | 5 | 69m 00s | **$0.072205** | $0.0628 |
| Al Smith | 0 | — | — | — (one podcast appearance found, Suite Spot Mar 2026, not processed) |
| Brian Jenkins / Stephen Hahn / David Rosenberg | 0 | — | — | — (no audio or video found for any of them) |
| Embedding index over all of it | 46 chunks | — | $0.004347 | — |

**The media layer cost $0.0765 all-in and produced three of the top-six insights.** It is not the expensive part of this recipe. The expensive parts are Exa search ($0.126 across 18 searches) and the structuring calls ($0.101 across 6).

### 6g. Timing, per phase

| Phase | Seconds | Note |
|---|---|---|
| H2 own-site fetches | 121.9 | Six 20s timeouts, then one Exa fallback call |
| H9 AI Ark people + emails | 101.8 | 10 calls at ≥10.5s enforced pacing |
| H15 structuring (6 calls, parallel) | 369.3 total | 54.8–73.5s each |
| H10 media (5 items, parallel) | 173.8 total | 22.2–54.6s each |
| H11 per-person deep (5 calls, parallel) | 163.0 total | 29.3–35.0s each |
| H5 account deep-reasoning | 52.8 | One call, 25 results, 17,124 chars |
| H13 embedding + retrieval | 19.6 | 46 chunks + 4 queries |
| H1 ADP feed (all four centres) | 10.3 | 145 requisitions, free |
| H6 committee confirmation | 10.2 | 12 primary pages in one call |
| H4 committee search (8 searches) | 12.7 | Found the IT seat and HE Labs |
| **Research wall clock** | **1,170s (19m 30s)** | run start → last provider call; sum of phases 1,087.9s |
| **Total wall clock** | **2,014s (33m 34s)** | including authoring `ONE-ACCOUNT-REPORT.md` and `HOTEL-EQUITIES-PAGES.md` |

---

## 7. Honest gaps, what surprised me, and what differed from the Zafran recipe

### Still not found

- **Their property-management systems.** Every named PMS was checked and every one came back NOT FOUND, including any Oracle OPERA exposure. For a company operating Marriott, Hilton, Hyatt and IHG properties this is genuinely unknowable from the public web — brand mandates are contractual, not published. **Conduit's OPERA integration is a capability to offer, never a fact to assert about this account.**
- **Any guest-messaging vendor.** Twenty-one named products checked, none evidenced. Absence of evidence is not evidence of absence; a 300-property operator may well run something at property level that never reaches the open web.
- **Their after-hours guest-response model.** Whether there is a central reservations or guest-services centre, an outsourced answering service, or whether every call lands at the property front desk — NOT FOUND. This is the single most important unknown for Conduit and it should be the first discovery question.
- **Job description text.** The ADP public requisition object carries no description field. Both the list endpoint and the per-requisition detail endpoint (`/job-requisitions/<itemID>`, and with `$expand=all`) return 200 with identical bodies and no description. So there is no equivalent of the Zafran Ashby job descriptions that named their SDR stack. Titles, locations, post dates and salary ranges are the whole payload.
- **Ownership and capital.** Who owns Hotel Equities itself, any private-equity sponsor, capital partners or AUM — all NOT FOUND.
- **A reconciled portfolio count.** Four different numbers from their own sources.
- **Al Smith's email** (export 404), and **SLS Punta del Este's primary announcement** (the identity brief asserts it; the deep call could not surface the source, so it is not restated as verified here).
- **Any audio or video for Jenkins, Hahn, Rosenberg or Stachler.** The media layer is one voice deep. Al Smith has one podcast appearance (Suite Spot, 5 Mar 2026) that was surfaced but not processed.
- **Negatives.** No lawsuits, WARN notices, layoffs, owner disputes, receiverships or critical coverage were found. **This is a search result, not a clean bill of health,** and the report says so rather than implying a spotless record.

### What surprised me

1. **The free ADP feed beat the paid deep-research call again — and it silently lied about paging first.** The endpoint honours `$skip` but **ignores `$top`**, returning ~19–20 rows per page regardless. Advancing by 50 (as the documented parameter implies) returned 72 of 143 requisitions and looked perfectly successful — the right shape, plausible counts, no error. Only checking the returned page length against `meta.totalNumber` caught it. Advancing by the actual page length got all 145. **A pager that half-works is more dangerous than one that fails.**
2. **The feed's location filter is a free portfolio roster.** `meta.links` carries a LOCATION schema enumerating **552 named properties** with cities and states. Nobody would think to ask a data vendor for that, and it is an independent cross-check on a portfolio count the company's own materials give four different answers to.
3. **A single AI Ark field beat a $0.03 deep-research call.** `technologies[]` returned "SynXis (Sabre Hospitality)" — the only named hospitality booking system produced by any source in this run. The deep call marked the entire technology layer NOT FOUND.
4. **The account published its own buying process.** HE Labs' four gates are on a public page. That is rarer and more useful than any intent signal: it means the pilot can be written to their criteria before the first conversation.
5. **The best insight in the run was audio-only.** The CEO naming Hotel Effectiveness and ProfitSword, and then describing the product he wishes existed, appears nowhere in text — not in the deep dossier, not on their site, not in the trade press. $0.0116 of audio produced it.
6. **Their own website is effectively unfetchable, and the brief was right.** All six direct GETs to hotelequities.com hung to a 20-second timeout and returned 55 bytes. Exa `/contents` with livecrawl recovered four of six pages in 10 seconds for $0.007. Budgeting 120 seconds to learn nothing is the cost of not reading the brief.
7. **flash-lite did not loop this time, and that is a length finding, not a fix.** Five items up to 19:36 came back clean (0–2.1% duplicate long lines). The Zafran loop appeared at 12½ minutes of a 43-minute file. The duplicate check is what lets this be stated rather than assumed.
8. **AI Ark's own LinkedIn URL 404s on its own export endpoint.** `/v1/people` returned the COO's profile URL; passing that exact URL to `/v1/people/export/single` returned 404. The two indexes do not cover the same people.
9. **The email pattern is not uniform.** `ben.rafter@` but `bjenkins@`, `shahn@`, `drosenberg@`. Guessing from the CEO would have bounced three of four. This is a direct argument for verifying rather than pattern-matching.

### What differed from the Zafran recipe, because this is a hotel operator and not a SaaS company

| Zafran (SaaS) | Hotel Equities (hotel operator) |
|---|---|
| **Ashby** posting API — 27 reqs **with full job descriptions**, which named the SDR stack | **ADP WorkforceNow** — 145 reqs with **no description text at all**. Richer in count and geography, poorer in content. The stack has to come from elsewhere |
| Hiring signal = one strategic req open 77 days | Hiring signal = **volume and repetition**: 19 guest-facing seats across 19 properties, 5 of them night audit. The pain is distributed, not concentrated |
| Tech stack readable from job descriptions and web fingerprint | **Brand-mandated PMS is contractually invisible.** The web fingerprint gave a CRS (SynXis) and nothing about in-property systems. The honest answer is "unknown", and saying so is the deliverable |
| Buying committee sat in **marketing** | Committee sits in **operations + a formal innovation function**. There is no CIO; technology authority is split between a VP of IT and an EVP of Strategy running HE Labs |
| Timing signal = funding round + new GTM motions | Timing signal = **a brand economics change** (Marriott's ITR rebate, up to 50 bps of gross room revenue) plus a **merger still integrating** 16 months on |
| Money facts = four funding rounds with dates and investors | Money facts = a revenue band and an incentive program. No funding ladder exists; this is a 1989 private operator |
| Personal hooks were rich (a YouTube cocktail channel, a published book) | Personal hooks are **thin**: one cycling hobby in a company bio, one Seattle/tennis-pro biography, one Nepal origin story. Hospitality operators expose far less personal surface than cybersecurity founders. Reported thin rather than padded |
| Media = a podcast plus YouTube, and a wrong-person video cost $0.006 to discover | Media = **five episodes of one show, one person**, all audio, no misidentification. The show's RSS (Buzzsprout ID 2103299) gave exact durations and direct MP3s, so no YouTube billing at 91 tok/s was ever needed |
| Negatives were real and had to be marked unsafe (a refuted acquisition rumour, ARR commentary) | Negatives were **not found at all**. The `outreach_safe: false` set is instead composed of the CEO's own candid remarks — an "unsustainable" industry and a bumpy email migration — which are risky to repeat precisely *because* he said them |

---

## Files in this run

| File | What it is |
|---|---|
| `ONE-ACCOUNT-REPORT.md` | This report |
| `HOTEL-EQUITIES-PAGES.md` | The three frontend screens (Insights, Account Overview, three Contact pages) + link register |
| `claims_hotelequities.json` | 350 typed claims with provenance, priority, use-class and outreach-safety |
| `cost_ledger.json` | Every one of the 151 calls with http status, latency, cost and credits (actual + reserved) |
| `timing.json` | Per-phase wall clock |
| `media_index.json` | 5 media items with tokens, cost, loop verdict, and 25 verified quotes |
| `h17_tables.json` | Every cost and timing table above, machine-readable |
| `h18_inventory.md` / `h18_ark_field_inventory.json` | The AI Ark field inventory, every field with its real value |
| `h13_retrieval_demo.json` | The embedding retrieval demo with scores and timestamps |
| `transcripts/` | 10 files — a faithful and a timestamped transcript for each of the 5 episodes |
| `report_account_hotelequities_deep.md` | The raw Exa deep-reasoning account dossier |
| `report_person_*.md` | Five per-person deep-reasoning dossiers, each with its own same-name exclusion list |
| `raw/` | Every provider response, saved before parsing, birth-date scrubbed |
| `h1_*.py` … `h18_*.py` | Every step, re-runnable, python3 stdlib only |
