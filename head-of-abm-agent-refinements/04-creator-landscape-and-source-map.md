# Creator Landscape & Source Map — Training Data for the "Head of ABM" Agent

**Prepared:** 2026-08-31
**Scope:** WHO to collect from, WHAT their best content is, WHERE it is reachable, and HOW reliable each acquisition route is.
**Consumer:** Clue (cluehq.ai) — domain-brain corpus for the "Head of ABM" agent.

---

## Executive summary

1. **The practitioner canon is small and highly concentrated.** Roughly 15 people/orgs produce the material an ABM agent actually needs to reason about account selection, buying committees, tiering, and signal-based plays. The other ~35 in this roster are useful for breadth, adjacent GTM mechanics, and negative examples (opinion-without-numbers).
2. **The single best corpus in the entire landscape is Fullfunnel.io's Substack** — full-text RSS, no paywall on recent posts, weekly cadence, and explicitly case-study-shaped (`[Case Study]` in the title). Confirmed 20 items × ~40–112 KB of `content:encoded` per item, plus an undocumented archive API for full backfill.
3. **Podcast transcripts are the highest-volume, lowest-friction win.** Four shows expose machine-readable `<podcast:transcript>` tags directly in RSS — Exit Five (259 transcripts), Full-Funnel B2B Marketing Show (223), GTMnow (257), Demandbase's *The Prompt* (218). Verified downloadable as plain `.txt`/`.srt`/HTML with no auth.
4. **LinkedIn — where most of this content is *born* — is the hardest surface and should never be the primary route.** The correct strategy is mirror-first: creator newsletters, agency blogs, podcast transcripts, and third-party republication carry ~80% of the same ideas in fetchable form.
5. **Case studies with real numbers are rarer than they look.** Only a handful publish named-client, quantified outcomes: Scrappy ABM, ColdIQ, strategicabm, Fullfunnel, Clay, AdRoll/RollWorks, Lavender, Growth Engine X. Most "top voices" lists are opinion-only.
6. **Several widely-cited names have moved.** Chris Walker has left demand gen for a neuroperformance company (ENCODED); his corpus is historical, not active. Kyle Coleman is at ClickUp, not Copy.ai. Sam Kuehnle left Loxo in Aug 2026. Corrina Owens is at BILL. Terminus is now inside DemandScience; RollWorks' content redirects to AdRoll; ITSMA→Momentum→Accenture.
7. **The Clay ecosystem is the fastest-growing content vein** and the most operationally specific (list-building, enrichment, waterfall logic, signal plumbing) — closest in shape to what Clue's own research subsystem does.
8. **Vendor research reports are the best source of hard buying-committee statistics** — 6sense's Buyer Experience Report (95% of wins are on the Day One shortlist), LinkedIn B2B Institute / Ehrenberg-Bass (the 95:5 rule).
9. **Fetchability is excellent for the open web, hostile on the social platforms.** 24/25 creator domains returned HTTP 200 to a plain browser-UA `curl`. But **Reddit's public `.json` API is dead (403 across every subreddit tested)**, X's logged-out HTML carries no tweet text and the Nitter mirrors were served a cease-and-desist on 2026-08-24, and LinkedIn post bodies could not be retrieved by any unauthenticated route.
10. **Recommended acquisition order:** (1) Substack/RSS full-text, (2) podcast transcript tags, (3) agency blog sitemaps, (4) YouTube auto-captions via yt-dlp (**verified working end-to-end**), (5) Reddit `.rss` low-and-slow + Arctic Shift dumps, (6) Common Crawl for bulk backfill, (7) LinkedIn mirrors last. **Drop X entirely.**

---

## Method, legend, and honesty notes

**Verification legend** — every entry below carries one of:

| Tag | Meaning |
| --- | --- |
| `[FETCHED]` | The page was retrieved and its content read in this session. |
| `[TESTED-curl]` | Retrieved via shell `curl` with a browser User-Agent; HTTP status and byte count observed directly. |
| `[SNIPPET]` | Seen only in a search-result summary or a third-party page; not independently opened. |
| `[BLOCKED]` | Fetch attempted and failed (auth wall, 402/403/999, empty JS-rendered body). |
| `[UNVERIFIED]` | Named in a source but not confirmed. Treated as a lead, not a fact. |

**What was actually run in this session:**
- Direct `curl` fetchability sweeps across 25 creator domains, 10 RSS/feed endpoints, 9 sitemaps, and 28 canonical URLs.
- The public **iTunes Search API** (`itunes.apple.com/search?entity=podcast`) to resolve real podcast RSS feed URLs, episode counts, and latest-release dates — this is a reliable, unauthenticated way to prove a podcast is *currently active*.
- RSS parsing to count `<item>`, `<content:encoded>`, and `<podcast:transcript>` elements per feed.
- YouTube channel-page scraping for channel IDs and subscriber counts.

**Known limits of this document:**
- **WebSearch budget was exhausted** partway through (200/200 session cap). Later verification is WebFetch- and curl-only. A few follower counts and X handles therefore remain `[SNIPPET]` rather than confirmed.
- **`yt-dlp` was installed mid-session** (`python3 -m pip install --user --break-system-packages yt-dlp` → **v2026.08.19**, now at `~/Library/Python/3.13/bin/yt-dlp`). YouTube claims below are therefore **real tool output**, including one end-to-end caption download. It was *not* present at session start — if you are on a different machine, install it first.
- **LinkedIn follower counts are volatile** and were mostly read from profile fetches that succeeded intermittently. Treat as order-of-magnitude.
- **Two YouTube subscriber counts initially disagreed** between HTML scraping and yt-dlp. yt-dlp is authoritative and was used to re-verify every channel (see §Group G). The one correction: **Clay is 16,800 subscribers, not the 5.44K an HTML scrape reported.** Do not trust regex-scraped YouTube counts.
- Several third-party "top N voices" lists were used as *lead generators* (exitfive.com, gtmepulse.com, theabmpulse.com, demandgeninsider.com, thegtmindex.com). These are self-published rankings, not neutral sources. Names sourced only from them are marked `[UNVERIFIED]`.

---

# PART 1 — THE CREATOR ROSTER

Grouped by primary platform / content home. 46 named entries.

---

## Group A — ABM-native practitioners and agencies (the core canon)

These are the people whose content maps most directly onto what a Head of ABM agent must know: account selection, tiering, buying-committee resolution, program design, and measurement.

---

### A1. Andrei Zinkevich — Co-founder, Fullfunnel.io
**The single highest-value source in this entire map.**

| Field | Value |
| --- | --- |
| Role | Co-founder, Fullfunnel.io (FullFunnel OÜ), founded 2017. Based in Spain. |
| LinkedIn | `https://www.linkedin.com/in/azinkevich/` — ~57,000 followers `[FETCHED]` |
| X | `@AZinkevich` — `https://twitter.com/azinkevich` `[SNIPPET]` |
| Substack | `https://fullfunnel.substack.com/` — 20,100+ subscribers per fullfunnel.io/about `[FETCHED]`; a separate reading of `substack.com/@azinkevich` showed 27,000+ `[FETCHED]` — the two figures disagree; use "20–27K" |
| YouTube | `https://www.youtube.com/@fullfunnel` — channel ID `UCaU5zej4RW3bW3B2E_EJ3sw`, **311 subscribers, 233 videos** `[TESTED-curl]` (note: very small YouTube footprint; the audience is on Substack + LinkedIn) |
| Podcast | Full-Funnel B2B Marketing Show — **185 episodes, latest 2026-06-08**, feed `https://www.spreaker.com/show/3073695/episodes/feed` `[TESTED-curl]` |
| Site | `https://fullfunnel.io/` — HTTP 200, 111 KB `[TESTED-curl]` |

**Company numbers (from `fullfunnel.io/about/`) `[FETCHED]`:** 30 years combined experience, **25+ published case studies**, 20,100+ newsletter subscribers, clients including Zoho, Siemens, Topdesk, Sirris.

**What they post about:** ABM program design end-to-end — ICP definition, account scoring and prioritization, buying-committee mapping, account warm-up cadences, intent-data tracking, ABM-vs-demand-gen orchestration, ABM budget forecasting.

**Why it matters for ABM intelligence:** This is the only source in the roster that consistently publishes *the full program mechanics* — not "here's a tactic," but "here's the 12-module operating system, here are the 17 templates, here is what the account list looked like and what it produced." It is the closest existing analogue to the reasoning a Head of ABM agent must perform.

**Canonical pieces (all URLs `[TESTED-curl]` HTTP 200):**
1. `https://fullfunnel.substack.com/p/our-abm-program-breakdown-case-study` — "Our ABM program breakdown [Case Study]", 2026-08-28. Their own program, decomposed.
2. `https://fullfunnel.substack.com/p/account-based-engagement-playbook` — "Account-Based Engagement Playbook", 2025-02-21 `[FETCHED]`. Six-step engagement sequence; explicitly anti-automation; three account lists (Cluster ICP / Future Pipeline / Active Focus) with distinct KPIs; batches of **7–10 priority accounts** over two-month campaigns.
3. `https://fullfunnel.substack.com/p/how-to-run-abm-for-a-new-enterprise` — "How to run ABM for a new enterprise product in a new market [ABM case study]", 2026-07-31.
4. `https://fullfunnel.substack.com/p/why-viral-abm-plays-fail-in-enterprise` — 2026-08-07. Failure-mode content; unusually valuable as negative training signal.
5. `https://fullfunnel.io/account-based-marketing-playbook/` — ABM Playbook 2.0 course outline (12 modules) `[SNIPPET]`.

**Case studies with numbers?** **YES — heavily.** Both the Substack (`[Case Study]`-tagged posts) and the course pages carry named-client numeric outcomes.

---

### A2. Vladimir Blagojević — Co-founder, Fullfunnel.io

| Field | Value |
| --- | --- |
| Role | Co-founder, Fullfunnel.io. Ex-Sony, EMC, Sirris; founded ScaleXL 2013 `[FETCHED]` |
| LinkedIn | `https://www.linkedin.com/in/vladimirblagojevic/` `[BLOCKED]` — HTTP 999 rate-limit; follower count unverified |
| Podcast | Co-hosts the Full-Funnel B2B Marketing Show with Zinkevich |
| Newsletter | Co-authors the Fullfunnel Substack (bylines confirm both names) `[FETCHED]` |

**What he posts about:** ABM measurement and attribution, pipeline velocity, content mapped to buyer-journey stage, hiring B2B marketers.

**Why he matters:** He is the measurement half of the Fullfunnel pair. For an agent that must justify tiering and report program impact, his measurement content is the complement to Andrei's program-design content.

**Acquisition note:** Do not try to collect him separately from Andrei — the same Substack and podcast carry both. Treat "Fullfunnel.io" as the collection unit.

**Case studies with numbers?** Yes, via the shared Fullfunnel corpus.

---

### A3. Mason Cosby — Founder, Scrappy ABM
**The most prolific ABM podcaster and the best source of "ABM without a big budget" reasoning.**

| Field | Value |
| --- | --- |
| Role | Founder, Scrappy ABM (agency + media). Whitestown, Indiana. |
| LinkedIn | `https://www.linkedin.com/in/masoncosby/` — ~26,000 followers `[FETCHED]` |
| X | `@scrappyabm` `[FETCHED]` via site footer |
| YouTube | `https://www.youtube.com/@scrappyabm` — channel ID `UCjYgN-sx_e0omSHoBQUwISA`, **50 subscribers, 235 videos** `[TESTED-curl]` (video output is high, subscriber base near-zero — the distribution is podcast-first) |
| Podcast | Scrappy ABM — **283 episodes, latest 2026-08-27**, feed `https://feeds.captivate.fm/scrappy-abm-pod/` `[TESTED-curl]`; Apple id `1693508482` |
| Newsletter | "The Scrapbooks", weekly — `https://scrappyabm.com/newsletter` `[FETCHED]` |
| Site | `https://scrappyabm.com/` — HTTP 200, 486 KB `[TESTED-curl]`; sitemap index → `post-sitemap.xml` with **156 URLs** `[TESTED-curl]` |

**Aggregate claims (`scrappyabm.com`) `[FETCHED]`:** $300M+ pipeline sourced, $100M+ sourced revenue, 1,000+ marketers trained, 200+ playbooks launched.

**Framework:** The **4D Framework** — Data, Direction, Distribution, Destination. Also "account-based podcasting" as an ABM channel (productised at ~$2,975/mo).

**Canonical pieces:**
1. `https://scrappyabm.com/case-studies/electric-era-turning-one-off-webinars-into-a-12m-pipeline-engine/` — Electric Era, $12M pipeline engine `[TESTED-curl]` HTTP 200.
2. `https://scrappyabm.com/case-studies/bamboo-hr/` — BambooHR, doubled outbound conversion rate on a dead-account database `[FETCHED]`.
3. `https://scrappyabm.com/case-studies/forward-studios-turning-a-cold-outreach-stall-into-a-150k-pipeline/` — cold-outreach stall → $150K pipeline `[FETCHED]`.
4. `https://scrappyabm.com/case-studies/andela-where-spontaneous-events-became-a-systematic-game-plan/` — event chaos → systematic ABM motion `[FETCHED]`.
5. Podcast: "$17M in 2 Years Through Account-Based Podcasting" (ep. 241), Apple id `1000744776321` `[SNIPPET]`.
6. `https://scrappyabm.com/podcasts/episode-79-simple-signal-based-abm-strategies/` — signal-based ABM `[FETCHED]`.

**Case studies with numbers?** **YES — the strongest per-account case-study library in the ABM group.** 9 published case studies, each with a named client and a headline number.

---

### A4. Declan Mulkeen — CMO, strategicabm
**The enterprise-ABM view: big logos, Forrester-recognised programs, formal ABM tiers.**

| Field | Value |
| --- | --- |
| Role | CMO, strategicabm (Strategic ABM Ltd, UK). ~20 years prior CMO experience. Based in Madrid. |
| LinkedIn | `https://www.linkedin.com/in/declanmulkeen/` — 23,000+ followers `[FETCHED]` |
| Podcast | **Let's talk ABM** — 85 episodes, **latest 2025-11-14** `[TESTED-curl]` — ⚠️ *appears dormant since Nov 2025*. Feed `https://anchor.fm/s/561ea694/podcast/rss`; Apple id `1562939683` |
| Second podcast | "ABM under the Hood" — `https://resources.strategicabm.com/abm-under-the-hood` `[FETCHED]` |
| YouTube | `https://www.youtube.com/@strategicabm` — channel ID `UCUXm6pfRqy5nlFAuVVGJ2RA`, **174 subscribers, 30 videos**; channel RSS returned 15 entries, **newest 2026-03-20** `[TESTED-curl]` |
| Blog | `https://insights.strategicabm.com` — HTTP 200, 108 KB; **RSS at `/rss.xml` works (290 KB)**; sitemap has **219 URLs** `[TESTED-curl]` |
| Magazine | "DashDot" monthly — `https://resources.strategicabm.com/dashdot/` `[FETCHED]` |

**Named clients:** SAP, Cloudflare, AVEVA (Forrester 2025 B2B Program of the Year winner), Acxiom, BICS, GlobalSign, BlueBotics, SNOW, Getac, Kineo, UiPath `[FETCHED]`.

**Canonical pieces (all `[TESTED-curl]` HTTP 200):**
1. `https://insights.strategicabm.com/video-case-study-acxiom-abm-sales-pipeline` — "How Acxiom Built a $2m Sales Pipeline in 120 Days". ⚠️ The older slug `/abm-in-action-how-acxiom-built-a-sales-pipeline-in-120-days` **301-redirects here** — use the canonical slug.
2. `https://insights.strategicabm.com/what-is-an-abm-center-of-excellence-in-2026` — ABM CoE structure.
3. `https://insights.strategicabm.com/peer-to-peer-abm` — peer-to-peer ABM as a play.
4. `https://insights.strategicabm.com/dark-funnel-vs-dark-social-how-to-track-hidden-traffic-in-2026` `[FETCHED]`.
5. `https://www.strategicabm.com/what-is-account-based-marketing/` — their definitional guide `[FETCHED]`.
6. `https://insights.strategicabm.com/account-based-marketing-glossary` — ABM glossary; useful as vocabulary grounding for an agent `[FETCHED]`.
7. YouTube: "Inside UiPath's ABM machine: making Enterprise deals bigger" (Episode 5), newest channel video 2026-03-20 `[TESTED-curl]`.

**Case studies with numbers?** **YES**, but unevenly — the homepage names logos without numbers; the *insights* subdomain carries the quantified case studies (Acxiom $2m/120 days being the clearest).

---

### A5. Bev Burgess — Co-founder & CEO, Inflexion Group
**The person who coined "Account-Based Marketing" (2003, at ITSMA Europe).**

| Field | Value |
| --- | --- |
| Role | Co-founder & CEO, **Inflexion Group** (founded May 2024) — *not* ITSMA/Momentum any more `[FETCHED]` |
| LinkedIn | `https://www.linkedin.com/in/bevburgess/` — ~5,000 followers; headline "Leading authority on Account-Based Marketing (ABM)"; writes a newsletter called **"The ABM-er"** `[FETCHED]` |
| X | `@BurgessBev` `[SNIPPET]` — unverified |
| Site | `https://inflexiongroup.com` — HTTP 200, 137 KB `[TESTED-curl]`. Runs "ABM Academy", 4 training levels, 17+ consultants. |
| Books | *Account-Based Marketing: The Definitive Handbook for B2B Marketers* (2025 ed.); *A Practitioner's Guide to Account-Based Marketing* (w/ Dave Munn); *Account-Based Growth*; *Executive Engagement Strategies* — Kogan Page author page `https://www.koganpage.com/authors/bev-burgess` `[FETCHED]` |

**Critical lineage note (worth encoding into the agent's ontology):** ITSMA → acquired by **Momentum** (2021) → "Momentum ITSMA" → **acquired by Accenture (2025)**. Burgess is *not* in that lineage today; Inflexion Group is a separate 2024 firm. Older articles pointing at ITSMA content are pointing at a brand that no longer operates independently.

**Why she matters:** Definitional authority. The one-to-one / one-to-few / one-to-many tiering vocabulary that the whole industry uses descends from her ITSMA work. An agent that gets the taxonomy right should be grounded here.

**Case studies with numbers?** **Mostly not** — framework, definitional, and benchmarking research rather than named-client numbers. The quantified benchmark work (Momentum ITSMA Global ABM Benchmark) sits with the Momentum/Accenture lineage, not with her current firm.

---

### A6. Sangram Vajre — Co-founder & CEO, GTM Partners; co-founder, Terminus

| Field | Value |
| --- | --- |
| Role | Co-founder & CEO, GTM Partners. Co-founded Terminus; ex-CMO Pardot. |
| LinkedIn | `https://www.linkedin.com/in/sangramvajre/` — ~60,000 followers `[FETCHED]` |
| Site | `https://www.gtmpartners.com/founders` — HTTP 200 `[TESTED-curl]`. Claims 160+ certified GTM OS partners, 75,000+ leaders trained, 2,000+ GTM teams assessed. |
| Books | *MOVE: The 4-Question Go-To-Market Framework* (WSJ bestseller); *Account-Based Marketing For Dummies*; *ABM is B2B* |
| Movement | Founded **#FlipMyFunnel**; 1,000+ podcast interviews under that banner `[SNIPPET]` |

⚠️ **Two disambiguations the agent must not get wrong:**
- **Terminus is now inside DemandScience.** `terminus.com/blog` **301-redirects to demandscience.com** `[FETCHED]`. Terminus no longer exists as an independent ABM content hub.
- **"GTMonday" (his newsletter, ~100–175K subscribers claimed) is NOT "GTMnow."** GTMnow is GTMfund's (a VC firm's) publication, run by Scott Barker, ~59K subscribers. Different orgs. The subscriber figure for GTMonday could not be confirmed on gtmpartners.com — mark `[UNVERIFIED]`.

**Case studies with numbers?** **Mostly not** — category-level frameworks and opinion leadership.

---

### A7. Jon Miller — Founder & CEO, Phave; co-founder of Marketo; ex-CMO/Chief Evangelist, Demandbase
**The best single source for buying-group theory.**

| Field | Value |
| --- | --- |
| Current role | Founder & CEO, **Phave** — AI-native marketing automation `[SNIPPET]` (`phave.com`) |
| Prior | Co-founder/CMO Marketo (→IPO); founder/CEO Engagio; CMO then **Chief Evangelist** at Demandbase — his Demandbase author page reads "Chief Evangelist and former CMO" `[FETCHED]` |
| LinkedIn | `https://www.linkedin.com/in/jonmiller2/` `[SNIPPET]` |
| X | `@jonmiller` `[SNIPPET]` |
| Blog | `https://www.jonmiller.com` — HTTP 200; sitemap has 50 locs `[TESTED-curl]`. Actively publishing into 2026. |

**Canonical pieces (all `[TESTED-curl]` HTTP 200):**
1. `https://www.jonmiller.com/blog/2026/3/16/beyond-the-mql-a-three-tier-model-for-b2b-qualification` — a three-tier qualification model to replace the MQL. **Directly relevant to Clue's tiering logic.**
2. `https://www.jonmiller.com/blog/2024/10/8/particle-physics-meets-pipeline-introducing-atomic-buying-journeys` — "Atomic Buying Journeys"; models the buying *group* rather than the lead.
3. `https://www.demandbase.com/blog/9-reasons-buying-groups-next-big-thing/` — 9 reasons buying groups are the next big thing in B2B. **The single best short argument for committee-level modelling.**
4. `https://www.jonmiller.com/blog/2024/1/20/the-marketing-playbook-i-helped-create-doesnt-work-anymore-heres-the-new-b2b-marketing-playbook` `[FETCHED]`.
5. `https://www.demandbase.com/blog/account-based-revolution-origins-to-ai-futures/` — ABM history → AI futures `[FETCHED]`.

⚠️ **Correction to a common attribution:** the phrase "ABM is dead" could not be verified as a Jon Miller quote. His actual framing is that classic ABM is "fishing with spears" and should give way to ABX. Do not train the agent on the misquote.

**Case studies with numbers?** **No** — pure framework/thought leadership. High conceptual value, zero quantified case value.

---

### A8. Kristina Jaramillo — President, Personal ABM

| Field | Value |
| --- | --- |
| Role | President, Personal ABM (with Eric Gruber, CEO). Raleigh-Durham area. |
| LinkedIn | `https://www.linkedin.com/in/kristinajaramillo/` — ~9,000 followers `[FETCHED]` |
| Podcast | "ABM Done Right — A Personal ABM Podcast", ~123 episodes, weekly. Buzzsprout `https://abm-done-right-podcast.buzzsprout.com/`; Apple id `1520450671` `[SNIPPET]` |
| Site | `https://www.personalabm.com` — ⚠️ **`[BLOCKED]`** — blog and podcast pages returned empty bodies on every attempt (likely JS-rendered or bot-gated) |

**What she posts about:** ICP definition, **MQAs (marketing-qualified accounts)** rather than MQLs, champion enablement, post-pipeline land-and-expand, moving past activity metrics.

**Why she matters:** The "MQA instead of MQL" and "post-pipeline expansion" framings are under-represented elsewhere in this roster and are directly relevant to an ABM agent that must score accounts, not leads.

**Acquisition route:** Skip the website (blocked). Use the **Buzzsprout podcast feed** and her LinkedIn posts via mirrors.

**Case studies with numbers?** **Unconfirmed** — enterprise guests are named (Challenger, Demandbase, Okta, Uniphore, Highspot, Gong) `[SNIPPET]` but no quantified case study could be fetched.

---

### A9. ABM Leadership Alliance (ABMLA)
`https://abmleadershipalliance.com` — HTTP 200, 50 KB `[TESTED-curl]`

Founding members **Demandbase** and **ForgeX** (Brandon Redlinger). Additional partners Iron Horse, NetLine. Publishes research/frameworks, an Account-Based Readiness Assessment, and deployment models (Enterprise ABM / Growth ABM / Deal-Based ABM).

⚠️ **"The ABM Consortium" — could not be found under that name.** Treat as non-existent; ABMLA is the real analogue.

---

### A10. Additional ABM names (leads, `[UNVERIFIED]` unless noted)

Sourced from `theabmpulse.com/voices/` and `convert.com` list fetches. **Each needs a current-employer re-check before use** — this space had heavy 2025–26 M&A churn.

| Name | Role / org as listed | LinkedIn slug |
| --- | --- | --- |
| Latané Conant | CRO (ex-CMO), 6sense; hosts *TalkingSense* `[FETCHED]` | `/in/latane-conant/` |
| Kerry Cunningham | Head of Research, 6sense — the buying-group data voice | `/in/kerrycunningham/` `[BLOCKED]` |
| Peter Isaacson | CMO, Demandbase | `/in/peterisaacson/` |
| Brandon Redlinger | Co-founder, ForgeX | `/in/brandonredlinger/` |
| Kathy Macchi | EVP & Co-founder, Inverta | `/in/kathy-macchi-aa148b/` |
| Patrice Greene | President & Co-founder, Inverta | `/in/patricegreene/` |
| Alisha Lyndon | Founder/CEO, Momentum(ABM)/ITSMA; author *The ABM Effect* | `/in/alishalyndon/` |
| Nani Jansen | VP of ABM, Snowflake | `/in/nanijansen/` |
| Charm Bianchini | VP Demand Gen, RollWorks | `/in/charmbianchini/` |
| Matt Heinz | President, Heinz Marketing | `/in/mattheinz/` |
| Craig Rosenberg | Chief Platform Officer, Scale VP | `/in/craigrosenberg/` |
| Samantha Stone | Founder, The Marketing Advisory Network | `/in/samanthagstone/` |
| John Common | CEO, Intelligent Demand | `/in/johncommon/` |
| Andy Bacon | ABM Specialist, B2B Marketing | `/in/andybacon/` |
| Eric Spett | Co-founder, Terminus (⚠️ now DemandScience) | `/in/ericspett/` |
| Tim Davidson | Founder/CEO, **B2B Rizz** — ABM + LinkedIn Ads consultancy; ex-Clay. `https://b2brizz.com/` HTTP 200 `[TESTED-curl]` | `/in/tadavidson41/` |
| Justin Rowe | Founder, **Impactable** — largest US LinkedIn-ads agency, 200+ enterprise clients. `https://impactable.com/` HTTP 200 `[TESTED-curl]` | `/in/justin-rowe-4043339b/` |
| Corrina Owens | ABM strategist — **now at BILL** (LinkedIn shows BILL, ~19K followers) `[FETCHED]`; ex-Gong/Navattic/Demandbase; co-hosts *Direct* (Motion.so) | `/in/corrina-owens/` |
| Tyler Pleiss | ⚠️ **Conflicting employers across two LinkedIn profiles** (`/in/tyler-pleiss-abm/` → Sr. Director ABM @ Sphera; `/in/tyler-pleiss/` → Movable Ink). ForgeX Executive Council; "The Pleiss is Right, LLC". **Unresolved — re-check before citing.** | see note |

**Justin Rowe canonical pieces `[SNIPPET]`:** `https://impactable.com/demand-gen-playbook-for-abm/`; `https://impactable.com/scale-your-abm-strategy-with-linkedin-ads/`; `https://www.factors.ai/conversations/decoding-abm-on-linkedin-with-justin-rowe`. Teaches the "surround sound" ABM retargeting layering and a 60/40 cold/retargeting budget split at $10–20K/mo.

---

## Group B — Outbound, cold email, and GTM engineering (the Clay ecosystem)

This group is the operational counterpart to Group A: where Group A designs programs, Group B builds the data plumbing. For Clue specifically — a platform that enriches accounts, resolves committees, and scores signals — **this is the closest-fit content in the entire landscape.**

---

### B1. Michel Lieben — Founder & CEO, ColdIQ
**Best-in-class at publishing receipts.**

| Field | Value |
| --- | --- |
| Role | Founder & CEO, ColdIQ (Belgium). 275+ outbound clients claimed. |
| LinkedIn | `https://www.linkedin.com/in/michel-lieben/` `[SNIPPET]` |
| X | `@MichLieben` `[SNIPPET]` |
| YouTube | `https://www.youtube.com/@MichLieben` — channel ID `UCvTZ9sU4PoYP6_uATOUCU3g`, **3.18K subscribers, 89 videos** `[TESTED-curl]` |
| Site | `https://coldiq.com/` — HTTP 200, 233 KB; **sitemap has 6,306 URLs** `[TESTED-curl]` ⚠️ note `/blog/rss.xml` 404s — use the sitemap |
| Blog | `https://coldiq.com/blog` `[FETCHED]` |
| Case studies | `https://coldiq.com/case-studies` `[FETCHED]` |

**Published case studies with hard numbers `[FETCHED]`:** Aircall (3,600+ new accounts enriched in 6 months), AirOps ($10.1M pipeline & revenue from ABM — a separate source cites $7.83M in 10 months; figures drift, cite the page not the number), Teikametrics ($300K+ pipeline in 9 months), Design Pickle (~10 → 58 demos in 14 days), Palico (6–15 positive replies weekly), Hemlane (830 qualified leads, 0.5% bounce), Playbook (0 → 20 opportunities in 20 days, 300+ replies), Keragon (2 partnership conversations/day).

**Verified case-study URLs `[TESTED-curl]` HTTP 200:** `https://coldiq.com/case-studies/aircall`, `https://coldiq.com/case-studies/airops`.

**Also publishes:** a tech-stack directory, AI-sales-tool roundups, and free tools (email finder, mobile finder, spam checker, "find similar companies" — the last is conceptually identical to lookalike discovery).

**Case studies with numbers?** **YES — the densest numeric case-study library in the outbound group.** Named client + named figure + named timeframe, consistently.

---

### B2. Eric Nowoslawski — Founder, Growth Engine X

| Field | Value |
| --- | --- |
| Role | Founder, Growth Engine X. Early Clay contractor (when Clay had ~4 employees) `[SNIPPET]` |
| ⚠️ Site | `https://www.growthenginex.com/` **301-redirects to `http://coldoutbound.com/`** `[TESTED-curl]` — the brand's web home moved. Both resolve, 81 KB, HTTP 200. |
| YouTube | `https://www.youtube.com/@ericnowoslawski` — channel ID `UC6ef5yDFz7gm8rARwX3HaDw`, **15.9K subscribers, 290 videos** `[TESTED-curl]` — the largest individual-creator YouTube footprint in the outbound group |
| LinkedIn (personal) | `https://www.linkedin.com/in/outboundphd/` `[SNIPPET]` |
| LinkedIn (company) | `https://www.linkedin.com/company/growth-engine-x/` `[FETCHED]` |
| X | `@ENowoslawski` `[SNIPPET]` |
| Newsletter | "Growth Drops" `[SNIPPET]` — URL unconfirmed |

**Scale:** email volume reported variously as 1.2M / 4M / 8M+ per month across sources `[FETCHED, inconsistent]` — a moving figure; do not pin a number. Named clients per the Clay partner directory: Forbes, Y Combinator, Refine Labs, Instantly, TestBox, ChurnZero `[FETCHED]`.

**Case-study numbers `[FETCHED]`:** Baton Market (30–100 positive responses/day), Heritage Wealth Capital (552 responses in 4 months), Sharf Enterprises (95 responses in 30 days), Gutter Kings (212 responses in 3 months).

**Why he matters:** Deliverability and infrastructure — the layer nobody else covers in depth. If the agent must reason about *why* an outbound motion fails mechanically (not strategically), this is the source.

**Case studies with numbers?** **Yes**, but reply-volume-shaped rather than pipeline-dollar-shaped.

---

### B3. Jordan Crawford — Founder, Blueprint GTM
**The "data IS the message" thesis — the most conceptually relevant person in the roster to Clue's claim-store bet.**

| Field | Value |
| --- | --- |
| Role | Founder, Blueprint GTM (Blueprint Labs LLC). Self-describes as a fractional GTM engineer who works in Claude Code `[FETCHED]` |
| Site | `https://jordancrawford.com/`; `https://blueprintgtm.com` `[FETCHED]` |
| Newsletter | **"On the Edge by Blueprint"** — `https://edge.blueprintgtm.com/` HTTP 200, 99 KB `[TESTED-curl]`. **`/feed` returns 20 items with 20 full-text `content:encoded` blocks (595 KB)** `[TESTED-curl]` — fully collectable. |
| LinkedIn | `https://www.linkedin.com/in/jordancrawford/` `[FETCHED]` |
| YouTube | `@BlueprintGTM` `[UNVERIFIED]` — page fetch returned generic footer only |
| X | **`[UNVERIFIED]`** — multiple namesakes; one is a former NBA player. Do not guess. |

**Frameworks:** **PQS** (Pain-Qualified Segments), **PVP** (Permissionless Value Props), **FIND** (Focus / Investigate / Narrate / Deploy).

**Why he matters most for Clue:** His entire thesis is that outbound quality is a function of *what you know about the account*, not of copywriting — i.e. the same bet as "verifiability is a property of the data model." His segment-definition reasoning (PQS) is a direct analogue of ICP-spec + field-registry design.

**Canonical pieces:**
1. `https://edge.blueprintgtm.com/` (and `/feed`) — the primary corpus `[TESTED-curl]`.
2. `https://gtmnow.com/gtm-133-build-your-ai-outbound-machine-with-chatgpt-jordan-crawford/` `[SNIPPET]`.
3. `https://bootstrappers.com/jordan-crawford-blueprint/` — origin story: built a GTM data business by scraping job boards `[SNIPPET]`.

**Case studies with numbers?** **No — framework/opinion.** High conceptual value, low quantified-case value.

---

### B4. Adam Robinson — Founder/CEO, RB2B & Retention.com
**The highest-reach individual voice in the roster.**

| Field | Value |
| --- | --- |
| LinkedIn | `https://www.linkedin.com/in/retentionadam/` — **~155K followers** `[SNIPPET]` (a separate list cites 142K+ and 55M+ impressions) |
| X | `@RetentionAdam` — ~10.6K followers `[SNIPPET]` |
| Newsletter | **`https://newsletter.rb2b.com/`** — HTTP 200, 647 KB; claims **100,000+ subscribers** `[FETCHED]`. Platform: beehiiv. ⚠️ `/feed` and `/rss.xml` both **404**; **sitemap.xml works — 158 URLs** `[TESTED-curl]` |
| Personal site | `https://theadamrobinson.com/` `[SNIPPET]` |

**Recent canonical posts `[FETCHED]`:**
1. `https://newsletter.rb2b.com/p/how-to-bootstrap-to-24m-arr-with-5-employees` (2026-08-29)
2. `https://newsletter.rb2b.com/p/what-does-the-ceo-of-a-32m-arr-business-do-all-week` (2026-08-21)
3. `https://newsletter.rb2b.com/p/the-death-of-signal-orchestration` (2026-07-15) — **directly relevant**: a critique of signal-based selling from its loudest proponent.
4. `https://newsletter.rb2b.com/p/we-invented-a-new-way-to-validate-emails` (2026-08-08)

**Why he matters:** He is the market's loudest voice on *website-visitor identification as an ABM signal* — precisely the intent-signal class Clue must reason about. Also the best available example of founder-led distribution mechanics.

**Case studies with numbers?** **Numbers-dense but self-reported.** ARR figures across sources are inconsistent ($22M / $24M / $32M) because the business is growing and the reporting is narrative. Treat as opinion-adjacent, not audited case study.

---

### B5. Clay (clay.com) — the platform and its content machine
**Not a person, but the single biggest content producer in this space.**

| Field | Value |
| --- | --- |
| Site | `https://www.clay.com` — HTTP 200, 502 KB; **sitemap has 16,796 URLs** `[TESTED-curl]` — by far the largest collectable surface in the roster |
| Blog | `https://www.clay.com/blog` — **RSS works: `https://www.clay.com/blog/rss.xml`, 75 KB, HTTP 200** `[TESTED-curl]` |
| LinkedIn | `https://www.linkedin.com/company/grow-with-clay/` — **186,785 followers** `[FETCHED]` |
| YouTube | `https://www.youtube.com/@GrowWithClay` — channel ID `UCHLTdPgm0KivyFFvKEWEQmQ`, **16,800 subscribers** (yt-dlp authoritative; an HTML scrape wrongly reported 5.44K), 163 videos; channel RSS returns 15 entries, newest 2026-08-22 `[TESTED-yt-dlp + TESTED-curl]`. **The largest official-brand channel in the roster.** |
| Clay University | `https://university.clay.com/courses` — HTTP 200, 206 KB `[TESTED-curl]`. **17+ courses** incl. "Signals & ABM", "AI-Powered GTM Automation", "CRM Enrichment", "Limitless Research", "Automated Outbound" `[FETCHED]` |
| Community | `https://community.clay.com` — HTTP 200, 241 KB `[TESTED-curl]`; 30K Slack members claimed |

⚠️ **Two disambiguation traps:**
- The YouTube handle **`@getclay` is a DIFFERENT company ("Calprop")** — verified 404-equivalent mismatch `[TESTED-curl]`. The correct handle is **`@GrowWithClay`**.
- There is a second company called Clay (`clay.earth`, a personal-relationship CRM). Not the same. Filter on `clay.com`.

**Canonical pieces:**
1. `https://www.clay.com/blog/gtm-engineering` — "GTM Engineering: What It Is and How to Hire in 2026" `[TESTED-curl]` HTTP 200, 752 KB. Defines the three-tier model — **data foundation → data modeling (propensity scores, ICP attributes) → data activation**. This maps almost exactly onto Clue's claim-store → scoring → handoff spine.
2. `https://www.clay.com/blog` — "How we turned a few thousand ad dollars into $1.3 million in pipeline" (2026-08-31) `[FETCHED]`.
3. "Top 1%: How Brex Scaled Its Outbound Engine" (2026-08-20) `[FETCHED]`.
4. "Practical ways GTM teams can use agents" (2026-08-27) `[FETCHED]`.
5. `https://www.clay.com/blog-category/case-studies` — case-study index (Northbeam, Saviynt, AlertMedia) `[FETCHED]`.

**Named practitioners surfaced in Clay's own content `[FETCHED]`:** Evan Peters (Notion), Alexander DeMoulin (Intercom), Robert Jones (Canva), Adam Wall (Anthropic), Davide Grieco (Verkada), Keyan Sarrafzadeh (Ramp). Clay University template creators: Bolaji Olayiwola, George Dilthey, Scott Tousley, Chris Viglietta, Alex Lindahl, Stan Stojanovic `[FETCHED]`.

**Programs:** Solutions Partner Program (agencies), Clay Club Hosts, Beta Program. The **Clay Creator Program is currently paused until March 2026** `[SNIPPET]`; certifications also paused `[FETCHED]`.

**Case studies with numbers?** **YES** — named client, named pipeline figure, consistently.

---

### B6. Understory — Alex Fine & Ali Yildirim
| Field | Value |
| --- | --- |
| Company | Understory — US "allbound" agency for B2B SaaS, ~26–34 people; one of the **top Clay Enterprise Partners** `[SNIPPET]` |
| LinkedIn | `https://www.linkedin.com/company/understory-agency` `[SNIPPET]` |
| Coverage | `https://thegtmengineer.substack.com/p/ai-first-gtm-execution-and-talent` (Alex Fine interview) and `/p/8-months-of-high-growth-gtm-agency` `[SNIPPET]` |
| Scale claim | Scaled $6K → multiple hundreds of thousands MRR since Oct 2023 `[SNIPPET]` |

Alex Fine came through Clay/outbound; Ali Yildirim through paid media/attribution. Their integrated paid + outbound + RevOps model is a good example of the "one system" thinking an ABM orchestration agent should encode. Naufal Nugroho listed as Head of GTM Engineering `[UNVERIFIED]`.

---

### B7. Will Allred — Co-founder & COO, Lavender
| Field | Value |
| --- | --- |
| LinkedIn | `https://www.linkedin.com/in/williamallred/` `[SNIPPET]` |
| X | `@WillAllred117` `[SNIPPET]` — x.com fetch returned HTTP 402 `[BLOCKED]` |
| Company | `https://www.lavender.ai/` `[SNIPPET]` |

**Canonical piece:** `https://lavender.ai/blog/the-cold-email-benchmark-report` — HTTP 200, 102 KB `[TESTED-curl]` (note: `www.lavender.ai` redirects to apex). **N = 231,818 emails across ~50K inboxes.** Reply rates broken out by department and seniority (e.g. Finance 6.1% "A"-grade rate but +79% reply lift when achieved; Engineering/Product 5.2% reply rate).

**Why it matters:** One of very few genuinely large-N empirical datasets in this space. Excellent grounding for persona-level messaging priors.

**Case studies with numbers?** **YES — benchmark research, the highest-quality numeric class in the roster.**

---

### B8. Other verified outbound / GTM-engineering creators

| Name | Role | Primary URLs | Verified? |
| --- | --- | --- | --- |
| **Sam Nelson** | Founder, Agoge Prospecting School; ex-Outreach.io SDR leader | `https://samnelson.substack.com/` — **/feed works, 20 items, 20 full-text blocks** `[TESTED-curl]`; `/in/realsamnelson/` | Yes |
| **Scott Barker** | GTMfund; hosts The GTMnow Podcast, writes The GTM Newsletter (50K+ readers) | `https://thegtmnewsletter.substack.com/` — **/feed works, 20 items full-text** `[TESTED-curl]`; ⚠️ `https://gtmnow.com` returns **HTTP 403** to curl `[TESTED-curl]`; `@scottbGTM` | Yes |
| **Jed Mahrle** | Founder, Practical Prospecting | ⚠️ LinkedIn slug is **`/in/outboundsales`**, not his name `[SNIPPET]` | Yes (moderate) |
| **Florin Tatulea** | GTM advisor; LinkedIn Top Voice 2023; posting through Aug 2026 | `/in/florintatulea` `[SNIPPET]` | Yes |
| **Kellen Casebeer** | Founder, The Deal Lab / GTM Cafe; coined "message-market fit"; 1,650+ operator community | `https://thedeallab.com/` `[SNIPPET]` | Yes |
| **Jared Waxman + Matteo Tittarelli** | GTM Engineer School (4-week cohort) | `https://gtmengineerschool.substack.com/`; podcast Apple id `1819567354` `[SNIPPET]` | Yes |
| **Nathan Lippi** | Bootprint (formerly Clay Bootcamp) | `https://claybootcamp.com/`; `/in/nathanlippi`; `@nathanlippi`; YT `@nathanlippi` `[SNIPPET]` | Yes |
| **Brandon Charleson** | Founder, Top of Funnel; 100+ Clay tutorials on YouTube | `https://www.clay.com/experts/partner/top-of-funnel` `[SNIPPET]` | Yes |
| **Patrick Spychalski** | Co-founder, The Kiln (acquired by 2X, Jan 2026); Clay's first marketing contractor | `/in/patrickspychalski/` `[SNIPPET]` | Yes |
| **Saurav Gupta** | Host, **The GTM Engineer Podcast** — 168 eps, latest 2026-08-21 `[TESTED-curl]` | feed `https://feeds.transistor.fm/the-gtm-engineer-podcast` | Yes |
| **Lead Gen Jay (Jay Feldman)** | Cold-email/lead-gen educator | YT `https://www.youtube.com/@leadgenjay` — **88.3K subscribers** `[TESTED-curl]`; TikTok `@leadgenjay`; `https://leadgenjay.com/` | Yes. ⚠️ The claimed Otter PR connection is `[UNVERIFIED]` |
| **Kyle Coleman** | ⚠️ **Now Global VP Marketing at ClickUp**, not Copy.ai | `/in/kyletcoleman/`; `https://clickup.com/blog/author/kyle-coleman/` `[SNIPPET]` | Yes, role corrected |
| **Charlotte Johnson** | ⚠️ **`[UNVERIFIED]` — likely name collision.** One profile is an AE posting outbound content; another is a Rubrik cybersecurity professional. **Do not include without disambiguation.** | — | No |

**Also relevant, org-level:** Apollo Academy (`https://www.apollo.io/academy`, Josh Garrison VP Content) `[SNIPPET]`; Smartlead blog (Satwick Ghosh) `[SNIPPET]`; Instantly's Cold Email Benchmark Report 2026 (`https://instantly.ai/cold-email-benchmark-report-2026`) `[SNIPPET]`; Pavilion (`https://www.joinpavilion.com/`, 10,000+ members) `[SNIPPET]`.

⚠️ **Two different "GTM Engineer" Substacks — do not conflate:**
- `https://thegtme.com/` = **"The GTM Engineer by Clay"**, ~8,000 subscribers. **/feed works — 19 items, 19 full-text blocks (804 KB)** `[TESTED-curl]`.
- `https://thegtmengineer.substack.com/` = a **separate** independent publication. **/feed works — 337 KB** `[TESTED-curl]`. This is the one that ran the Eric Nowoslawski and Alex Fine interviews.

---

## Group C — Demand generation, positioning, and B2B marketing at large

Broader than ABM but supplies the reasoning an ABM agent needs about messaging, measurement, and category.

---

### C1. Dave Gerhardt — Founder & CEO, Exit Five
**The best-instrumented single source: 40K newsletter, 397-episode podcast with 259 machine-readable transcripts, 7,000-member community.**

| Field | Value |
| --- | --- |
| Role | Founder & CEO, Exit Five. Ex-CMO Privy, ex-VP Marketing Drift. |
| Newsletter | `https://exitfive.com/newsletter/` — HTTP 200, 118 KB; **custom-built (not Substack/beehiiv)**; **2× weekly**; **40,000+ subscribers**; archive publicly readable `[FETCHED]` |
| ⚠️ RSS | `https://exitfive.com/feed` returns **HTTP 200 but an EMPTY channel — 0 items** `[TESTED-curl]`. `/rss.xml` and `/sitemap_index.xml` and `/wp-sitemap.xml` all **404**. **The newsletter is not syndicated — must be crawled from the archive index.** |
| Podcast | **The Dave Gerhardt Show (from Exit Five)** — **397 episodes, latest 2026-08-31** `[TESTED-curl]`. Feed `https://feeds.transistor.fm/exit-five-podcast`. **259 `<podcast:transcript>` tags** — plain-text `.txt`, e.g. `https://share.transistor.fm/s/6d137ece/transcript.txt` (verified: HTTP 200, 70,157 bytes, speaker-labelled with timestamps) `[TESTED-curl]` |
| Community | 7,000+ members (5,700+ paid per a second source); 30+ local chapters `[FETCHED]` |
| YouTube | `https://www.youtube.com/@exitfive` — channel ID `UC-Vl47nIsmqshrelzP5QnjQ` `[TESTED-curl]` (sub count not extractable) |
| X | `@davegerhardt` `[SNIPPET]` |
| Event | Drive 2026 — Stowe, Vermont, September 2026 `[FETCHED]` |

**Canonical pieces:**
1. `https://exitfive.com/articles/top-25-b2b-marketers-to-follow-on-linkedin/` — HTTP 200 `[TESTED-curl]`, published 2025-05-02 `[FETCHED]`. **Itself a source-map artefact** — the full 25-name table is reproduced in Appendix A below.
2. `https://exitfive.com/podcast/how-to-master-b2b-positioning-with-anthony-pierri-fletch-pmm/` (2026-01-22) `[SNIPPET]`.
3. `https://exitfive.com/podcast/how-to-make-outbound-work-and-build-pipeline-in-2026-with-jen-allen-knuth-founder-of-demandjen/` `[SNIPPET]`.
4. `https://exitfive.com/newsletter/marketing-to-b2b-buyers-who-arent-on-linkedin/` (2026-08-25) `[FETCHED]`.
5. `https://exitfive.com/newsletter/3-essential-b2b-marketing-lessons/` — "3 Lessons From a 15-Year CMO of a $700M Cyber Company" (2026-08-18) `[FETCHED]`.

**Case studies with numbers?** **Mixed-to-good** — frequent named-company tactical breakdowns (an episode on ABM at Ramp/Snowflake/Hightouch was surfaced) rather than agency-style case studies.

---

### C2. Chris Walker — ⚠️ HISTORICAL SOURCE, NOT AN ACTIVE 2026 VOICE

| Field | Value |
| --- | --- |
| ⚠️ Current | **CEO of ENCODED** — a *neuroperformance* company. LinkedIn `https://www.linkedin.com/in/chriswalker171/` shows company = ENCODED, **175K followers**, Austin TX; recent posts are about neuroperformance, metacognition, and AI's effect on knowledge work `[FETCHED]`. Author of *The Frequency Era*. |
| Prior | Founder, Refine Labs (sold ~2025); associated with Passetto (listed as an LP, not operating CEO, in one source `[SNIPPET]`) |
| Podcast | "Revenue Vitals" → became **GTM Live**, now hosted by Passetto's Carolyn Dilks & Trevor Gibson. **619 episodes, latest 2026-08-31**, feed `https://anchor.fm/s/1caa9814/podcast/rss`, **0 transcript tags** `[TESTED-curl]` |
| Related | **Stacking Growth** (Refine Labs) — 276 eps, latest 2026-08-26, feed `https://anchor.fm/s/79a37aa4/podcast/rss`, 0 transcript tags `[TESTED-curl]` |
| Sites | `https://passetto.com/` HTTP 200, 173 KB; `https://refinelabs.com/` HTTP 200, 45 KB `[TESTED-curl]`; YT `@passetto` channel ID `UCwuT68BhapMm42Nk1knWtiA` |

**Recommendation:** Collect his **2021–2024 corpus** (demand creation vs. demand capture, the "dark funnel," the anti-attribution-theater argument) — it is genuinely foundational and still the most-cited framework in demand gen. But **label it historical.** Do not present him as a current ABM/demand-gen voice, and do not attribute 2026 GTM Live episodes to him.

---

### C3. Kyle Poyar — Founder, Growth Unhinged
| Field | Value |
| --- | --- |
| Role | Founder, Growth Unhinged; co-founder of VC firm Tremont; ex-Operating Partner, OpenView (2016–2024) |
| Newsletter | **`https://kylepoyar.substack.com/`** — Substack, **85,000+ weekly readers** `[FETCHED]`. **/feed works: 20 items, 20 full-text blocks, 678 KB** `[TESTED-curl]` |
| ⚠️ Mirror domain | `https://www.growthunhinged.com/` returns HTTP 200 to browser-UA curl but **`/rss`, `/feed`, `/feed.xml` all return 403 behind a Cloudflare "Just a moment..." challenge** `[TESTED-curl]`. **Sitemap.xml works — 321 URLs.** One source says it migrated to beehiiv in Jan 2026 with 84K+ subs `[SNIPPET]`. |
| X | `@poyark` `[BLOCKED]` — HTTP 402 |

**Canonical piece:** `https://www.growthunhinged.com/p/b2b-gtm-playbook-for-2026` — "The B2B GTM Playbook for 2026: Motions, AI, Signals, and Pricing" `[SNIPPET]`. Also publishing a "2026 State of B2B Monetization" report.

**Acquisition guidance:** **Use `kylepoyar.substack.com/feed`, not the growthunhinged.com domain.** The Substack mirror is unchallenged and full-text.

**Case studies with numbers?** **YES** — benchmark-heavy, original research, pricing teardowns.

---

### C4. Emily Kramer — Co-founder, MKT1
| Field | Value |
| --- | --- |
| Newsletter | **`https://newsletter.mkt1.co/`** — Substack, **85,000+ subscribers** `[FETCHED]`. **/feed works: 20 items, 20 full-text blocks, 1.51 MB** `[TESTED-curl]` — the largest per-fetch full-text payload in the roster |
| ⚠️ Main site | `https://mkt1.co` HTTP 200 (337 KB) but **`/feed` 404s** (Framer-hosted) `[TESTED-curl]` |
| Podcast | "Dear Marketers with Emily Kramer & Friends" — 12 eps, latest 2025-08-15, feed `https://api.substack.com/feed/podcast/218501/s/184227.rss` `[TESTED-curl]` |
| LinkedIn | `/in/emilykramer/` `[FETCHED]` |
| Prior | VP Marketing Carta; VP Marketing Astro (→Slack); built Asana's marketing team 1→25 |

**Why she matters:** MKT1 is the best source of *marketing-org and process design* content — how to structure a marketing team, how to sequence GTM investments. Useful for the agent's "what would a real Head of ABM actually be able to execute" grounding.

---

### C5–C14. Other verified demand-gen / positioning voices

| # | Name | Current role (verified where noted) | Key URLs | Case studies w/ numbers? |
| --- | --- | --- | --- | --- |
| C5 | **Sam Kuehnle** | ⚠️ **Just left Loxo (Aug 2026)** — LinkedIn now shows **Affect**; a visible post reads "Tomorrow is my last day at Loxo." Ex-VP Demand Gen, Refine Labs `[FETCHED]` | `/in/samkuehnle/` | Tactical/opinion |
| C6 | **Silvio Perez** | Founder, **AdConversion** (2023) — B2B paid-media agency + academy | `https://adconversion.com`; `/in/silvio-perez/`; 50+ hrs free YouTube tutorials `[SNIPPET]` | Claims $100M+ ad spend managed; testimonials only, **no verifiable client numbers** |
| C7 | **Canberk Beker** | Leads growth at **HockeyStack**; ex-LinkedIn/Google/Meta ad platforms; founder of "ROASted" | `/in/canberkbeker`; `adconversion.com/instructors/canberk-beker` `[SNIPPET]` | **No** — cites *other* companies' numbers, not his own attributed results |
| C8 | **Trinity Nguyen** | **UserGems** — sources split between "VP Marketing" and "CMO, AI GTM"; treat as senior marketing leader `[SNIPPET]` | `/in/trinitynguyen/`; `@trinity_nguyen`; `https://usergems.com` HTTP 200 `[TESTED-curl]` | **YES (one strong one)** — a controlled multithreaded-ads A/B on account groups showing higher win rates + shorter cycles `[FETCHED]` |
| C9 | **Corrina Owens** | ⚠️ **Now at BILL** (LinkedIn, ~19K followers) `[FETCHED]`; ex-Gong/Navattic/Demandbase; co-hosts *Direct* by Motion.so | `/in/corrina-owens/` | Opinion/critique ("why ABM fails", mid-market ABM) |
| C10 | **Nick Bennett** | ⚠️ **Now Founder/Owner, NB Marketing** (LinkedIn, **58K followers**) — pivoted from TACK Co-founder/CCO `[FETCHED]`. TACK's own hub `tackinsider.com` shows newest posts dated **Dec 2024** `[FETCHED]` — likely dormant | `/in/nickbennett1/` | Opinion / community-led growth |
| C11 | **Mark Kilens** | CEO & Co-founder, **TACK** (confirmed on tackgtm.com/about-tack) `[FETCHED]`; ex-CMO Airmeet, HubSpot/Drift alum | `https://tackgtm.com` | Opinion; ⚠️ TACK content appears stale |
| C12 | **Pranav Piyush** | Co-founder & CEO, **Paramark** (marketing measurement, MMM + incrementality; $6M seed) | `https://paramark.com/blog`; `https://paramark.com/manifesto`; podcast **Brandformance** — 69 eps, latest 2026-08-10, feed `https://rss.buzzsprout.com/2301271.rss`, 0 transcript tags `[TESTED-curl]`; `/in/pranavp/` | Framework/thesis; ⚠️ newsletter platform undetermined `[UNVERIFIED]` |
| C13 | **Peep Laja** | Founder — **CXL, Wynter, Speero**; active CEO of Wynter | `https://peeplaja.com/` (hosts *How to Win with Peep Laja* + a biweekly original-research newsletter — **platform/URL undetermined** `[UNVERIFIED]`); `https://wynter.com` HTTP 200 `[TESTED-curl]`; `@peeplaja` | **YES-ish** — Wynter is structured message-testing against real ICP buyers; the research output is the numeric asset. Wynter hit $2M ARR in 2 years `[SNIPPET]` |
| C14 | **Anthony Pierri** | Co-founder, **FletchPMM** — B2B homepage positioning; 400+ B2B startups; ranked #1 worldwide in product marketing on LinkedIn 2026 per Favikon `[SNIPPET]` | `https://fletchpmm.com/resource/` (⚠️ a specific deep link 404'd — use the index) `[BLOCKED]`; `@apierriPMM` `[BLOCKED - 402]`; `/in/anthonypierri/` | Teardown-style; positioning-specific |

**Additional verified names (lighter coverage):**

- **Devin Reed** — Founder/Owner, **The Reeder** (`thereeder.co`), **101K LinkedIn followers**; ⚠️ Stage2/Gong pages still list him at Clari — likely a fractional role. Treat "The Reeder" as primary `[FETCHED]`. Claim: "scaled Gong's brand from $20M to $200M ARR" — self-sourced, unverified.
- **Udi Ledergor** — **Chief Evangelist, Gong**, 44K followers `[FETCHED]`. Author page `gong.io/author/udi-ledergor`.
- **Anthony Kennada** — ⚠️ **joined Armada as CMO ~late Aug 2026** (his own LinkedIn post, 744 reactions) `[FETCHED]`; now Advisor at AudiencePlus. Ex-CMO Hopin, Front, Gainsight (category creation).
- **April Dunford** — positioning; *Obviously Awesome*, *Sales Pitch*; **The Positioning Show** podcast; Substack newsletter; `https://aprildunford.com` `[FETCHED]`; `@aprildunford`, YT `@positioningshow`.
- **Amanda Natividad + Rand Fishkin (SparkToro)** — `https://sparktoro.com` HTTP 200 `[TESTED-curl]`; *Zero Click Marketing* podcast + book (`sparktoro.com/book`); twice-monthly public Office Hours `[SNIPPET]`.
- **Camille Trent** — ⚠️ **now at Auror** (LinkedIn, 35K followers) `[FETCHED]`; older sources say Teal/PeerSignal — stale.
- **Jen Allen-Knuth** — Founder, **DemandJen**; buyer risk-aversion and outbound `/in/demandjen1/` `[SNIPPET]`.
- **Belal Batrawy** — LearnToSell.io; "Mic Drop Method"; **"Death to Fluff"** Substack, 10,000+ subs `[FETCHED]`.
- **Kipp Bodnar** — CMO HubSpot, 34K followers; book *Loop* launching 2026-09-22 `[FETCHED]`. Co-hosts *Marketing Against the Grain* (454 eps, latest 2026-08-25) `[TESTED-curl]`.
- **Sam Jacobs** — Pavilion, **126K followers** `[FETCHED]`.
- **Wes Bush** — ProductLed; *Product-Led Growth* 2nd ed. "rewritten for the AI era" `[FETCHED]`.
- **Sam Dunning** — host of **Breaking B2B**, 499 episodes (486 per his own site), latest 2026-08-20; YT `@samdunning` **3.45K subs, 890 videos** `[TESTED-curl]`; feed `https://feeds.simplecast.com/WtYkR7bN`, **0 transcript tags**.
- **George Coudounaris & Kevin Chen** — **The B2B Playbook**, 259 eps, latest 2026-08-23; the **5 BEs Framework** (Be Ready / Helpful / Seen / Better / The Best); YT `@theb2bplaybook` **1.9K subs, 459 videos**; feed `https://feeds.captivate.fm/the-b2b-playbook/`, **0 transcript tags** `[TESTED-curl]`.
- **Erik Jacobson** — CEO, Hatch; *95% Content* podcast (42 eps, latest 2026-08-20) `[TESTED-curl]`.
- **Katelyn Bourgoin** — "Why We Buy" / Customer Camp; ⚠️ `customercamp.co` → `learnwhywebuy.com` redirect but destination returned **empty content on repeated attempts** `[BLOCKED]`.
- **Liam Bartholomew** — Cognism VP Marketing `[UNVERIFIED]` — could not confirm this pass.

---

## Group D — Vendor research and category orgs (the hard-numbers layer)

These publish the empirical grounding an ABM agent needs about how B2B buying actually works.

### D1. 6sense — Buyer Experience Report
`https://6sense.com/science-of-b2b/buyer-experience-report-2025/`
⚠️ **HTTP 403 to plain curl, HTTP 200 via a full browser stack** `[TESTED-curl + FETCHED]` — bot-gated but not paywalled. Full report is readable on-page, no form gate `[FETCHED]`.

**Key findings (2025 edition, N > 4,000 buyers across NA/EMEA/APAC) `[FETCHED]`:**
- Average buying cycle compressed **11.3 months (2024) → 10.1 months (2025)**.
- First seller contact moved earlier: **69% → 61%** through the journey (6–7 weeks sooner).
- **"Ninety-five percent of the time, the winning vendor is already on the Day One shortlist."**
- Buyers fill **4 shortlist spots on Day One**; 94% rank the shortlist before engaging sellers.
- Buyers purchase from their preferred vendor ~80% of the time.
- 97% of the time buyers have prior personal experience with at least one shortlisted vendor; ~8–9 prior purchase journeys per category.
- **6–10 stakeholders** per purchase, with different priorities.
- 94% of buyers use LLMs (mostly to summarise reviews / analyse data); 89% bought AI-featured solutions; 58% engaged sellers earlier to evaluate AI.
- 49% said economic uncertainty shortened cycles; 62% engaged sellers sooner because of it.

**Why this is canon:** The Day-One-shortlist finding is the strongest available empirical argument for ABM as a discipline — if 95% of wins are decided before the RFP, then account-level pre-engagement is the whole game. An ABM agent should be able to cite this.

**Other 6sense assets:** `https://6sense.com/2025-b2b-buyer-experience-metrics-dashboard/` `[SNIPPET]`; podcast *Revenue Makers* (82 eps, **latest 2025-11-11 — likely dormant**) `[TESTED-curl]`; *TalkingSense* w/ Latané Conant. ⚠️ `6sense.com/resources/` **redirects to a PathFactory login wall** `[BLOCKED]`.

### D2. LinkedIn B2B Institute × Ehrenberg-Bass
`https://business.linkedin.com/advertise/resources/b2b-institute/how-b2b-brands-grow` — HTTP 200, 132 KB `[TESTED-curl]` (⚠️ the older `/marketing-solutions/...` path **301-redirects** here).

**The 95:5 rule** (Prof. John Dawes, Ehrenberg-Bass): only ~5% of target buyers are in-market at any time; categories turn over roughly every 5 years, so ~20%/year and ~5%/quarter are in-market. This is the theoretical justification for the "warm-up / out-of-market nurture" half of every serious ABM program — and for why intent signals matter more than volume.

### D3. Demandbase
`https://www.demandbase.com` — HTTP 200; sitemap index has 25 sub-sitemaps `[TESTED-curl]`.
- **Podcast *The Prompt*** — 593 episodes, latest 2026-08-06; feed `https://anchor.fm/s/300e904/podcast/rss`; **218 `<podcast:transcript>` tags** pointing at `transcript-files.spotifycdn.com/.../transcript.srt` `[TESTED-curl]`. **One of the four best transcript corpora in this map.**
- Reports: 2025 State of B2B Marketing (w/ The Harris Poll, 500+ leaders); 2025 State of ABM (w/ Demand Gen Report); named a Leader in the 2025 Gartner MQ for ABM Platforms (their own claim) `[SNIPPET]`.
- Stat worth capturing: "71% of practitioners now utilize an ABM strategy" (2025 ABM Benchmark Survey) `[SNIPPET]`.
- YT `@Demandbase` — channel ID `UCS2D3ArVM5Vhx6hz7_F2mxw`, **1.55K subs, 441 videos** `[TESTED-curl]`.

### D4. RollWorks → AdRoll
⚠️ **RollWorks' blog and guides URLs 301-redirect to `https://www.adroll.com/topics/abm`** `[FETCHED]` — content consolidated under the parent. That hub carries genuinely quantified case studies `[FETCHED]`:
- **Snowflake** — 75% increase in SDR-booked meetings, 3× meeting rate.
- **PitchBook** — 37.9% lower CPC, 14.9% faster sales cycle, 24.3% higher win rate.
- **Total Expert** — 100% closed-won deal attribution, 93% account reach.
- Aggregate: "$165 billion in revenue generated for customers," 5× average ROAS.
`https://www.adroll.com/topics/abm` — HTTP 200, 47 KB `[TESTED-curl]`.

### D5. Cognism
Three podcasts, all Captivate-hosted `[TESTED-curl]`: **Sales Signals** (113 eps, latest 2026-07-22, **3 transcript tags** — partial, JSON format at `transcripts.captivate.fm`), **The RevOps Review** (138 eps, latest 2026-05-08), **Marketing Dilemmas / The Loop** (111 eps, latest 2026-01-20). Blog at `cognism.com/blog`.

### D6. Terminus / DemandScience
⚠️ **Do not attempt to collect terminus.com** — `terminus.com/blog` 301-redirects to `demandscience.com` `[FETCHED]`. Terminus's historical ABM content may be partially lost; check the Wayback Machine if the pre-2024 Terminus corpus matters.

---

## Group E — Newsletters (ranked by collectability)

| # | Newsletter | Author / org | Platform | Subscribers | Feed status `[TESTED-curl]` | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| E1 | **Full-Funnel Insider** | Zinkevich & Blagojević | Substack | 20.1K–27K | `/feed` → **200, 1.27 MB, 20 items, full-text** (newest item 112 KB) | ⭐ **Best in class** |
| E2 | **MKT1 Newsletter** | Emily Kramer | Substack | 85K+ | `/feed` → **200, 1.51 MB, 20 items, 20 full-text** | ⭐ Excellent |
| E3 | **Growth Unhinged** | Kyle Poyar | Substack (+ beehiiv mirror) | 85K+ | `kylepoyar.substack.com/feed` → **200, 678 KB, 20/20 full-text**. ⚠️ `growthunhinged.com` feeds → **403 Cloudflare** | ⭐ Use the Substack |
| E4 | **The GTM Engineer (by Clay)** | Clay | Substack (`thegtme.com`) | ~8K | `/feed` → **200, 804 KB, 19/19 full-text** | ⭐ Excellent |
| E5 | **The GTM Newsletter** | Scott Barker / GTMfund | Substack | 50K+ | `thegtmnewsletter.substack.com/feed` → **200, 737 KB, 20/20** | ⭐ Excellent |
| E6 | **On the Edge by Blueprint** | Jordan Crawford | custom (`edge.blueprintgtm.com`) | — | `/feed` → **200, 595 KB, 20/20 full-text** | ⭐ Excellent |
| E7 | **the gtm engineer** (independent) | — | Substack | — | `/feed` → **200, 337 KB** | Good |
| E8 | **Sam Nelson** | Sam Nelson | Substack | — | `/feed` → **200, 177 KB, 20/20** | Good |
| E9 | **RB2B Newsletter** | Adam Robinson | beehiiv | 100K+ | ⚠️ `/feed` & `/rss.xml` → **404**. **`sitemap.xml` → 200, 158 URLs** | Medium — crawl via sitemap |
| E10 | **Exit Five Newsletter** | Dave Gerhardt | custom (WordPress) | 40K+ | ⚠️ `/feed` → **200 but 0 items (empty channel)**; `/rss.xml`, `/sitemap_index.xml`, `/wp-sitemap.xml` all **404** | Medium — crawl the archive index |
| E11 | **The Scrapbooks** | Mason Cosby | (undetermined) | — | not tested; site sitemap has 156 URLs | Medium |
| E12 | **The ABM-er** | Bev Burgess | LinkedIn newsletter | — | ⚠️ LinkedIn-native → auth-walled | Low |
| E13 | **Death to Fluff** | Belal Batrawy | Substack | 10K+ | not tested — Substack pattern should hold | Likely good |
| E14 | **DashDot** | strategicabm | custom | — | `resources.strategicabm.com/dashdot/` | Medium |
| E15 | **Claymation** | Alex Lindahl | beehiiv-style | — | no RSS auto-discovery found | Medium |
| E16 | **The GTME Pulse** | GTME Pulse | custom | — | `https://gtmepulse.com/newsletter/`; top-voices page HTTP 200 | Medium |
| E17 | **StackOptimise** | — | beehiiv | — | `https://stackoptimise.beehiiv.com/` `[SNIPPET]` | Untested |
| E18 | **GTMnow** | GTMfund | custom | 59K | ⚠️ `gtmnow.com` → **HTTP 403** to curl | Low direct; use the Substack (E5) and the podcast |
| E19 | **Paramark newsletter** | Pranav Piyush | `[UNVERIFIED]` | — | platform undetermined | Unknown |
| E20 | **Peep Laja biweekly research** | Peep Laja | `[UNVERIFIED]` | — | URL undetermined | Unknown |

**Key structural finding — the Substack archive API.** Substack exposes an undocumented JSON endpoint that returns full post metadata and supports offset pagination:

```
GET https://<pub>.substack.com/api/v1/archive?sort=new&search=&offset=0&limit=12
```

Verified against Fullfunnel: **HTTP 200, 94 KB, 12 posts**, each with `post_date`, `title`, `canonical_url`, and `audience` (so paywall status is machine-readable — all recent Fullfunnel posts are `audience: everyone`) `[TESTED-curl]`. Paginate `offset` to backfill the whole archive; then fetch each `canonical_url`, or take full text straight from `/feed` for the most recent 20. **This is the single most efficient collection route in the entire map.**

---

## Group F — Podcasts (with verified feeds, episode counts, activity, and transcript status)

All rows verified this session via the iTunes Search API plus direct feed parsing `[TESTED-curl]`.

| Show | Host(s) | Eps | Latest | Feed | `<podcast:transcript>` tags | Status |
| --- | --- | --- | --- | --- | --- | --- |
| **The Dave Gerhardt Show (Exit Five)** | Dave Gerhardt | 397 | 2026-08-31 | `feeds.transistor.fm/exit-five-podcast` | **259** (plain `.txt`) | ⭐ Active, best transcripts |
| **GTMnow Podcast** | GTMfund | 652 | 2026-08-27 | `rss.buzzsprout.com/2090897.rss` | **257** (HTML) | ⭐ Active |
| **The Prompt** | Demandbase | 591 | 2026-08-06 | `anchor.fm/s/300e904/podcast/rss` | **218** (`.srt`) | ⭐ Active |
| **Full-Funnel B2B Marketing Show** | Zinkevich & Blagojević | 185 | 2026-06-08 | `spreaker.com/show/3073695/episodes/feed` | **223** (`.sr`) | ⭐ Active |
| **GTM Live** (was Revenue Vitals) | Passetto (Dilks & Gibson) | 619 | 2026-08-31 | `anchor.fm/s/1caa9814/podcast/rss` | 0 | Active, no transcripts |
| **Scrappy ABM** | Mason Cosby | 283 | 2026-08-27 | `feeds.captivate.fm/scrappy-abm-pod/` | 0 | ⭐ Active (rich show notes, ~4.3 KB newest) |
| **Breaking B2B** | Sam Dunning | 499 | 2026-08-20 | `feeds.simplecast.com/WtYkR7bN` | 0 | Active |
| **30 Minutes to President's Club** | Farrokh & Cegelski | 645 | 2026-08-27 | `feeds.megaphone.fm/30mpc` | 0 | Active |
| **Stacking Growth** | Refine Labs | 276 | 2026-08-26 | `anchor.fm/s/79a37aa4/podcast/rss` | 0 | Active |
| **Topline** | Pavilion | 266 | 2026-08-27 | `rss.libsyn.com/shows/470223/destinations/3981084.xml` | 1 | Active |
| **The B2B Playbook** | Coudounaris & Chen | 259 | 2026-08-23 | `feeds.captivate.fm/the-b2b-playbook/` | 0 | Active (rich notes, ~3 KB) |
| **The GTM Engineer Podcast** | Saurav Gupta | 168 | 2026-08-21 | `feeds.transistor.fm/the-gtm-engineer-podcast` | 0 | Active |
| **Marketing Against the Grain** | Bodnar & Flanagan | 454 | 2026-08-25 | `feeds.megaphone.fm/marketingagainstthegrain` | not tested | Active |
| **Sales Signals** | Cognism | 113 | 2026-07-22 | `feeds.captivate.fm/salessignals/` | 3 (JSON) | Active |
| **Brandformance** | Pranav Piyush | 69 | 2026-08-10 | `rss.buzzsprout.com/2301271.rss` | 0 | Active |
| **95% Content** | Erik Jacobson | 42 | 2026-08-20 | `feeds.transistor.fm/95-content` | not tested | Active |
| **Lenny's Podcast** | Lenny Rachitsky | 359 | 2026-08-23 | `api.substack.com/feed/podcast/10845.rss` | 0 | Active (10.7 KB show notes) |
| **Let's talk ABM** | Declan Mulkeen | 85 | **2025-11-14** | `anchor.fm/s/561ea694/podcast/rss` | 0 | ⚠️ **Likely dormant** |
| **Revenue Makers** | 6sense | 82 | **2025-11-11** | `fast.wistia.com/channels/wn3a2zs4kd/rss` | not tested | ⚠️ **Likely dormant** |
| **The RevOps Review** | Cognism | 138 | 2026-05-08 | `feeds.captivate.fm/the-revops-review/` | not tested | Slowing |
| **Marketing Dilemmas / The Loop** | Cognism | 111 | 2026-01-20 | `feeds.captivate.fm/the-loop/` | not tested | ⚠️ Slowing |
| **Dear Marketers** | Emily Kramer (MKT1) | 12 | 2025-08-15 | `api.substack.com/feed/podcast/218501/s/184227.rss` | not tested | ⚠️ Sporadic |
| **ABM Done Right** | Jaramillo & Gruber | ~123 | not tested | `abm-done-right-podcast.buzzsprout.com/` | not tested | `[SNIPPET]` |
| **Cooking up GTM** | CS2 | 200 | 2026-07-09 | `feeds.captivate.fm/cooking-up-gtm/` | not tested | Active |
| **Content, Briefly** | Superpath | 167 | 2026-08-26 | `rss.beehiiv.com/podcasts/019d4fe4-...xml` | not tested | Active |
| **Run the Numbers** | CJ Gustafson | 315 | 2026-08-27 | `anchor.fm/s/10e7a9a40/podcast/rss` | not tested | Active |

⚠️ **One flagged result:** the iTunes search surfaced *"B2B Marketing with Fexingo: Enterprise Demand Gen, ABM, and Long Sales Cycles"* (176 eps, latest 2026-08-31, feed `feeds.fexingo.com/business/b2b-marketing.xml`). Provenance is unclear and the cadence pattern is consistent with auto-generated content. **Marked `[UNVERIFIED]` — do not collect without a human listen-check.**

⚠️ **A guessed feed ID was wrong.** An early probe of `feeds.buzzsprout.com/2200449.rss` returned an unrelated wellness podcast. **Never guess podcast IDs — always resolve via the iTunes Search API.**

---

## Group G — YouTube channels (verified IDs and subscriber counts)

Subscriber counts below are **`[TESTED-yt-dlp]`** — pulled from `yt-dlp --skip-download --playlist-items 0 -J`, which reads `channel_follower_count` from the real player response. Video counts are from HTML scraping `[TESTED-curl]`.

| Channel | Handle | Channel ID | Subs (yt-dlp) | Videos | Auto-captions? |
| --- | --- | --- | --- | --- | --- |
| Lead Gen Jay | `@leadgenjay` | `UC5TQ0_ORokxOHLcybp1QlNA` | **88,300** | — | assumed yes |
| Clay (official) | `@GrowWithClay` | `UCHLTdPgm0KivyFFvKEWEQmQ` | **16,800** | 163 | ✅ **verified** |
| Eric Nowoslawski | `@ericnowoslawski` | `UC6ef5yDFz7gm8rARwX3HaDw` | **15,900** | 290 | ✅ verified |
| Sam Dunning (Breaking B2B) | `@samdunning` | `UC7OhjYB9-p0b6ZNnXMOzjLQ` | **3,450** | 890 | assumed yes |
| Michel Lieben (ColdIQ) | `@MichLieben` | `UCvTZ9sU4PoYP6_uATOUCU3g` | **3,180** | 89 | ✅ verified |
| Warmly (hosts Chris Walker interviews) | — | `UCDcAwdCG6XEJyLNVd8-6WWA` | **258** | — | ✅ verified |
| The B2B Playbook | `@theb2bplaybook` | `UCSVJMfQnOhd0kQzl7IG8dfQ` | **1,900** | 459 | assumed yes |
| Demandbase | `@Demandbase` | `UCS2D3ArVM5Vhx6hz7_F2mxw` | **1,550** | 441 | assumed yes |
| FullFunnel | `@fullfunnel` | `UCaU5zej4RW3bW3B2E_EJ3sw` | **311** | 233 | ✅ verified |
| strategicabm | `@strategicabm` | `UCUXm6pfRqy5nlFAuVVGJ2RA` | **174** | 30 | ✅ verified |
| Scrappy ABM | `@scrappyabm` | `UCjYgN-sx_e0omSHoBQUwISA` | **50** | 235 | ✅ verified |
| Exit Five | `@exitfive` | `UC-Vl47nIsmqshrelzP5QnjQ` | not exposed | — | ✅ verified |
| Passetto | `@passetto` | `UCwuT68BhapMm42Nk1knWtiA` | not exposed | — | — |

⚠️ **Chris Walker / Passetto has no meaningful standalone channel.** His video content exists as **guest appearances** on other channels — Warmly (`UCDcAwdCG6XEJyLNVd8-6WWA`, e.g. "How to Implement Signal-Based GTM in B2B – Chris Walker, CEO of Passetto") and Exit Five's channel `[TESTED-yt-dlp]`. Collect him via guest-search (`yt-dlp "ytsearch20:Chris Walker Passetto"`), not via a channel pull.

**Dead handles — do not use `[TESTED-curl]` 404:** `@AndriyZinkevich`, `@RefineLabs`, `@SamDunningB2B`, `@Clay-gtm`, `@coldiq`, `@breakingb2b`.
**Wrong-company trap:** `@getclay` resolves to **"Calprop"**, not Clay.
**Also flagged:** `@growthenginex` exists but has **2 subscribers / 2 videos** — Eric's personal `@ericnowoslawski` channel is the real one.

**Notable pattern:** ABM creators have *tiny* YouTube audiences relative to their influence (Scrappy ABM: 235 videos, 50 subs). YouTube for this cohort is a **video-hosting layer for podcasts**, not a distribution channel. Its value to us is transcripts, not reach.

---

## Group H — Reddit

> ⚠️ **MAJOR CORRECTION.** The commonly-repeated advice that "Reddit's public `.json` endpoints work if you set a proper User-Agent" is **no longer true.** This was tested twice, independently, in this session.

**What was actually observed `[TESTED-curl]`:**

| Route | Result |
| --- | --- |
| `reddit.com/r/<sub>/about.json` with a descriptive UA | **HTTP 403 on every subreddit tested** — B2BMarketing, sales, coldemail, gtmengineering, agency, marketing, SaaS, Entrepreneur, salestechniques, msp. Returns a ~190 KB client-rendered JS shell, not JSON. |
| `old.reddit.com/r/sales/about.json` | **302 → `/login/?reason=lor2...`** — Old Reddit's JSON path now hard-requires login. |
| `reddit.com/r/<sub>/` HTML | 200, but an **8.4 KB empty React shell** with zero embedded post or subscriber data. No SSR leak. |
| **`reddit.com/r/<sub>/.rss`** | ✅ **200 OK with real Atom XML** — r/B2BMarketing (55,272 B, 25 entries), r/sales (40,166 B), r/agency (53,589 B), r/marketing (55,352 B). |
| `.rss` under sustained load | Degrades to **429 Too Many Requests**, then to an explicit block page (*"whoa there, pardner! Your request has been blocked due to a network policy"*) after ~15 rapid requests — and stayed blocked even with 3–12 s gaps. Reddit applies **behaviour-based IP blocking to the RSS surface too.** |

**⚠️ `r/coldemail` IS BANNED.** Its `.rss` feed returns `<title>coldemail: banned</title>` `[FETCHED]`. This is a primary-source confirmation, not an inference. Remove it from any collection plan.

**Subreddit register (revised):**

| Subreddit | Status | Subscribers | Confidence |
| --- | --- | --- | --- |
| `r/B2BMarketing` | ✅ Active, `.rss` 200, 25 entries | not obtained (trackers 404) | High (existence) |
| `r/sales` | ✅ Active, `.rss` 200 | **~596,000**, ~12 posts/day, median 18.5 comments/post (reddiscout) | Medium `[SNIPPET]` |
| `r/agency` | ✅ Active, `.rss` 200 | not obtained | High (existence) |
| `r/marketing` | ✅ Active, `.rss` 200 | not obtained | High (existence) |
| `r/Entrepreneur` | Exists | **~1,196,626** (frontpagemetrics) | Medium `[SNIPPET]` |
| `r/gtmengineering` | Exists — listed on `thegtmindex.com/gtm-engineers/` `[FETCHED]` | unknown; `.rss` probe hit the block wall | Medium |
| `r/coldemail` | ❌ **BANNED** | — | High (primary source) |
| `r/SaaS`, `r/salestechniques`, `r/msp`, `r/RevOps` | Existence assumed; `.rss` probes hit the block wall before returning | unknown | `[UNVERIFIED]` |
| `r/gtm`, `r/AccountBasedMarketing`, `r/DemandGen` | **No such communities found** | — | Likely non-existent |

**Reddit Data API (official OAuth) — 2026 state `[SNIPPET, cross-corroborated across 3 sources]`:**
- OAuth mandatory; no anonymous or key-only path.
- Free tier: **100 QPM per OAuth client**, non-commercial only, averaged over a 10-minute window.
- Commercial: **$0.24 per 1,000 calls**; bundled tier ~$12,000/mo for 50M calls.
- The "Responsible Builder Policy" (updated 2026-06-05) requires **manual pre-approval** for new OAuth clients; one source reports self-service registration **closed entirely since November 2025**. Budget weeks, and assume rejection is possible.
- Public `.json` reportedly went fully 403 on **2026-05-30** — consistent with what was observed directly.

**Historical backfill — Arctic Shift is the surviving route `[FETCHED]`:**
Pushshift's public access was revoked 2023-05-02 and its Reddit-hosted successor is **verified-moderators-only**. The live successor is **Arctic Shift** (`github.com/ArthurHeitmann/arctic_shift`), actively maintained, offering: (a) bulk monthly dumps on **Academic Torrents** spanning 2005-06 → at least 2026-07 (one torrent listed at 3.97 TB), (b) a limited public query API, (c) a web search UI at `arctic-shift.photon-reddit.com`, (d) Python 3.10+ helper scripts for the compressed dump format.

**Why Reddit is still worth the friction:** it is the only source in this entire map with **negative and adversarial** content — practitioners reporting that a tactic failed, calling out vendor claims, and naming the constraints (budget, headcount, tooling) that the LinkedIn corpus systematically hides. For an agent that must give *realistic* advice rather than aspirational advice, this is disproportionately valuable per byte.

**Recommended route:** low-and-slow `.rss` polling with multi-second jittered delays for post discovery (⚠️ Reddit's own block message suggests UA-rotation can itself trigger blocks — do not rotate), plus **Arctic Shift dumps** for historical depth, plus an approved OAuth client if sustained live collection is genuinely required. **Do not build on `.json`.**

---

# PART 2 — PER-PLATFORM ACQUISITION ROUTES

---

## 2.1 LinkedIn — auth-walled; **mirror-first strategy required**

**Direct status:** LinkedIn *profile* fetches succeeded intermittently (several returned live headline + follower data — this is how the job-change corrections in Appendix B were found), but failures were common: **HTTP 999** (LinkedIn's rate-limit code) and country-domain redirects (`es.`, `uk.`, `lt.linkedin.com`).

**Post-body retrieval failed by every unauthenticated route tried `[TESTED-curl]`:**
- `linkedin.com/posts/<id>` → HTTP 404 for an invented id, but served a full 319 KB legitimate LinkedIn HTML page rather than a hard block — so LinkedIn does *not* slam the door on bare curl at the HTTP layer.
- `linkedin.com/pulse/<slug>` → HTTP 200, 98 KB, but `pageKey="d_klp_home"` shows it fell back to a generic directory page (the slug was invented). **The Pulse route therefore remains genuinely untested against a real article** — worth one clean test, since Pulse is LinkedIn's nominally-public long-form surface.
- **No real, existing LinkedIn post URL could be surfaced to test with.** Google returned a JS-only shell with no SSR snippets; Bing returned zero `linkedin.com/posts` or `/pulse` URLs across several query variants; DuckDuckGo HTML/Lite returned a CAPTCHA. **This is itself a finding: LinkedIn posts are not straightforwardly retrievable via unauthenticated search-index routes.**

**Legal note `[SNIPPET, cross-corroborated]`:** the **hiQ Labs v. LinkedIn** line ended substantially in LinkedIn's favour on remand (the 9th Circuit's earlier scraping-friendly ruling was narrowed, and LinkedIn prevailed on breach-of-contract grounds). LinkedIn's ToS prohibits automated scraping and enforcement is active. The X Corp C&D against XCancel (§2.4) is a live example of how these platforms are behaving in 2026.

**Reliability: LOW as a primary route. Do not build the pipeline on it.** A headless browser could likely render post bodies, but that is squarely the ToS-violating path and was deliberately not tested.

**The mirror strategy — in priority order:**

| Rank | Mirror route | Reliability | Notes |
| --- | --- | --- | --- |
| 1 | **Creator's own newsletter** | HIGH | Most LinkedIn-native creators recycle their best posts into their newsletter within days. Fullfunnel, MKT1, Growth Unhinged, RB2B, Blueprint all do this. |
| 2 | **Agency/company blog** | HIGH | strategicabm, ColdIQ, Clay, Scrappy ABM all publish long-form versions of their LinkedIn arguments. |
| 3 | **Podcast transcripts** | HIGH | The same person, saying the same things, at greater length, fully fetchable. Often *better* than the post. |
| 4 | **`linkedin.com/pulse` articles** | MEDIUM | LinkedIn's long-form article surface has historically been more search-indexed than feed posts. Test per-URL. `[UNVERIFIED]` this session. |
| 5 | **Third-party republication** | MEDIUM | Exit Five articles, `thegtmindex.com`, `gtmepulse.com`, and podcast show-notes quote LinkedIn posts verbatim. |
| 6 | **Search-index copies (Exa / Google cache)** | MEDIUM-LOW | Public post URLs *do* appear in search results (several `linkedin.com/posts/...` URLs surfaced in this session's searches), so the index has them — but retrieving the body is the hard part. |
| 7 | **Direct scraping** | LOW / legally fraught | The `hiQ v. LinkedIn` line of cases did not produce a clean green light, and LinkedIn's ToS prohibits it. **Not recommended.** |

**Practical rule:** for each roster entry, record a `linkedin_mirror` field naming *which* of routes 1–5 carries that person's thinking. If a creator has **no** mirror (e.g. Bev Burgess's "The ABM-er" is a LinkedIn-native newsletter), accept lower coverage rather than building a scraper.

---

## 2.2 X / Twitter — effectively closed

**Status — three independent blocks, all confirmed:**

1. **WebFetch against `x.com/*` → HTTP 402 Payment Required** `[BLOCKED]` (observed on `@WillAllred117`, `@poyark`, `@apierriPMM`).
2. **Raw curl against a logged-out profile → HTTP 200 but no content.** `x.com/elonmusk` returned 243,062 bytes, but grepping for `"full_text"`, `TimelineTweet`, and `"screen_name"` yielded **zero matches** `[TESTED-curl]`. It is a React-18 streaming-SSR shell (`$RC=`/`$RB` markers) with no server-rendered tweet text. **A 200 here does not mean you got data.**
3. **The Nitter mirror ecosystem is being legally shut down right now.** `[TESTED-curl]`:
   - `nitter.net` → 200, but its own meta description reads *"nitter.net is offline."*
   - `xcancel.com` → 200, 321-byte body carrying an operator notice: ***"On Monday 24th August at 8PM EST, we received a letter from X Corp. asking to cease and desist the service XCancel... The service XCancel is stopped until further notice."*** — a dated, primary-source C&D confirmation from **one week before this research run**.
   - `nitter.poast.org`, `nitter.privacydev.net` → connection failures (dead hosts).

**Syndication endpoint — inconclusive.** `cdn.syndication.twimg.com/tweet-result?id=20&lang=en` returned **200 with a literal `{}` body (2 bytes)**; with a fabricated ID + `token=abc` it returned **404** `[TESTED-curl]`. This was not a fair test — no confirmed-live tweet ID with a valid `token` was available. It may still work for embed widgets. **One controlled retest is warranted before writing it off entirely, but do not plan around it.**

**Reliability: LOW. Recommendation — drop X from this corpus.**

**Rationale beyond the technical block:** this cohort's centre of gravity is LinkedIn, not X. Of ~46 roster entries, only a handful have X as a meaningful channel, and every one of them has a fetchable newsletter or podcast carrying the same thinking at greater length. The content-per-unit-effort is the worst in the map, and the legal temperature (active C&Ds against mirrors) is the highest.

**If X is genuinely required:** the paid API is the only sanctioned route. All handles recorded in this document are `[SNIPPET]`-grade and unverified.

---

## 2.3 Reddit — `.json` is DEAD; use `.rss` + Arctic Shift

> ⚠️ **Do not follow the standard advice here.** "Append `.json` and set a User-Agent" **no longer works.** Verified 403 across 10 subreddits, twice, independently.

**What actually works:**

```bash
# ✅ WORKS — Atom XML, no auth, real post titles/links/timestamps
curl -sH "User-Agent: clue-research/1.0 (contact: <email>)" \
     "https://www.reddit.com/r/B2BMarketing/.rss"

# ❌ DEAD — HTTP 403, returns a ~190KB JS shell, not JSON
curl -sH "User-Agent: clue-research/1.0" \
     "https://www.reddit.com/r/B2BMarketing/about.json"
```

**Reliability: MEDIUM, and fragile.** The `.rss` surface is free and unauthenticated, but it yields **post titles, links, and timestamps only — no comment bodies and no subscriber metadata**, and it starts returning 429 and then an outright block page after roughly 15 rapid requests. Pacing of 3–12 s was *not* sufficient to recover once blocked.

**Operational rules:**
- Jittered multi-second delays; treat ~10 requests/minute as the ceiling and back off hard on the first 429.
- **Do not rotate User-Agents** — Reddit's own block message implies UA-swapping is itself a block trigger. Use one honest, contactable UA.
- Comments are the highest-value part of Reddit for this corpus and are **not** available via `.rss`. Getting them requires either OAuth or the Arctic Shift dumps.

**For anything sustained:** register an OAuth client (free tier 100 QPM, non-commercial; commercial $0.24/1k calls). ⚠️ Registration requires **manual pre-approval** under the June 2026 Responsible Builder Policy, and one source reports self-service has been closed since Nov 2025. **Start this process early — it may take weeks or fail.**

**For historical depth:** **Arctic Shift** (`github.com/ArthurHeitmann/arctic_shift`) — monthly bulk dumps on Academic Torrents covering 2005-06 → 2026-07, plus a limited query API and a web search UI. This is the only viable path to comment-level history since Pushshift went moderators-only in 2023.

**Recommended collection shape:** `.rss` for ongoing discovery; Arctic Shift for the backfill; keyword filters on `ABM`, `account based`, `buying committee`, `intent data`, `Clay`, `cold email`, `outbound` across the general subs. **Exclude r/coldemail — it is banned.**

---

## 2.4 YouTube — ✅ verified working end-to-end via yt-dlp

**Status: INSTALLED AND PROVEN THIS SESSION.** `yt-dlp` was absent at session start, installed via
`python3 -m pip install --user --break-system-packages yt-dlp` → **v2026.08.19**, now at `~/Library/Python/3.13/bin/yt-dlp`.

**The full pipeline was executed, not merely described:**
- `yt-dlp "ytsearch1:<query>"` to locate real channels (this corrected several wrong handle guesses).
- `--list-subs --skip-download` across 6 channels: **every one had NO manual subtitles but DID have auto-generated English captions.**
- An actual download: `yt-dlp --write-auto-sub --sub-lang en --skip-download --sub-format vtt` on the Clay video `TN1PVrq-pYk` produced a real **47,020-byte `.vtt`** with word-level timings, opening *"What's up, clay makers? Owen from Clay here, coming at you live from Clay..."* `[TESTED-yt-dlp]`.

**Production command:**
```bash
yt-dlp --skip-download --write-auto-sub --sub-lang en --sub-format vtt \
       --sleep-requests 2 \
       --output "%(channel)s/%(upload_date)s-%(id)s.%(ext)s" <channel_url>
```

⚠️ **One durability warning surfaced repeatedly:** *"No supported JavaScript runtime could be found... YouTube extraction without a JS runtime has been deprecated."* It still worked, but **install `deno` (or Node) before relying on this long-term** — YouTube is progressively requiring JS execution for extraction.

**Channel discovery — two routes:**
1. **yt-dlp search** (`ytsearch1:`) — preferred; it resolves handles correctly. Handle guessing produced several wrong hits (see the dead-handle list in Group G).
2. **Per-channel RSS** at `https://www.youtube.com/feeds/videos.xml?channel_id=<UC...>` — verified for Clay (15 entries, newest 2026-08-22) and strategicabm (15 entries, newest 2026-03-20) `[TESTED-curl]`. ⚠️ **Aggressively rate-limited** — sequential requests returned HTTP 500/404 until a 2.5 s delay was inserted. Exit Five and Passetto returned valid but *empty* feeds. **Throttle to ≤1 request per 3 s**, and prefer route 1.

**Do NOT** try to parse `captionTracks` out of the watch-page HTML — that returned **HTTP 500**; YouTube gates the player response for non-browser clients. yt-dlp handles it; naive scraping does not.

**Reliability: HIGH.** This is the most-proven route in the document.

**Priority channels (content volume, not audience):** `@samdunning` (890 videos), `@theb2bplaybook` (459), `@Demandbase` (441), `@ericnowoslawski` (290), `@scrappyabm` (235), `@fullfunnel` (233), `@GrowWithClay` (163), `@MichLieben` (89). Plus a **guest-appearance sweep** for Chris Walker, who has no channel of his own.

**Caveat on expectations:** most of these are small channels (50–16,800 subs). The value is transcript *volume and specificity*, not reach.

---

## 2.5 Newsletters — the best route overall

**Reliability: HIGH.** Three sub-routes, in order of preference:

**(a) Substack full-text RSS — `<pub>.substack.com/feed`.** Verified on 6 publications this session; every one returned HTTP 200 with 19–20 `<item>` elements and a matching count of `<content:encoded>` full-text blocks. Payloads 177 KB – 1.51 MB. **This is a complete, clean, no-auth corpus.**

**(b) Substack archive API — `/api/v1/archive?sort=new&offset=N&limit=12`.** Verified HTTP 200. Returns `post_date`, `title`, `canonical_url`, and `audience` (paywall status). **Paginate for full backfill** — RSS only carries the last ~20.

**(c) Sitemap crawl — for non-Substack platforms.** Verified working on: `newsletter.rb2b.com/sitemap.xml` (158 URLs), `growthunhinged.com/sitemap.xml` (321), `coldiq.com/sitemap.xml` (**6,306**), `clay.com/sitemap.xml` (**16,796**), `insights.strategicabm.com/sitemap.xml` (219), `scrappyabm.com/post-sitemap.xml` (156), `jonmiller.com/sitemap.xml` (50), `demandbase.com/sitemap.xml` (25 sub-sitemaps), `fullfunnel.io/sitemap_index.xml` (3 sub-sitemaps).

**Substack full-text RSS was confirmed twice, independently.** A second control test against `lennysnewsletter.com/feed` returned **HTTP 200, 395,886 bytes, 20 `<content:encoded>` items, first item 15,252 characters of real article HTML** — not a teaser `[TESTED-curl]`. Substack ships complete article bodies in RSS for public posts, with no paywall gate on the feed itself.

**Known gaps:**
- **beehiiv RSS could not be made to work by any route.** No `<link rel="alternate" type="application/rss+xml">` on any beehiiv page tested (RB2B, Growth Unhinged, GTME Pulse, Claymation); `/feed`, `/rss.xml`, `/rss/feed` all 404; a guessed centralised pattern `rss.beehiiv.com/feeds/<slug>.xml` also 404'd; and beehiiv's own docs page (`developers.beehiiv.com/docs/v2/rss`) 404'd. **Unresolved after 5+ attempts. Use the sitemap.** (Note: beehiiv *podcast* feeds at `rss.beehiiv.com/podcasts/<uuid>.xml` do exist — one was resolved for Superpath's *Content, Briefly* via iTunes — so the infrastructure exists; the newsletter path just isn't publicly discoverable.)
- **Exit Five's WordPress `/feed` is an empty channel** and it has no sitemap at the standard paths. Must crawl `exitfive.com/newsletter/` as an index.
- **Growth Unhinged sits behind a Cloudflare interstitial** on its feed paths — use `kylepoyar.substack.com` instead.
- **WordPress-hosted newsletters can be Cloudflare-blocked on the feed specifically.** `themarketingmillennials.com/feed/` returned **403 "Attention Required! | Cloudflare"** while the site itself loaded fine `[TESTED-curl]`. Test the feed path, not just the homepage.

---

## 2.6 Podcasts — show notes + transcript tags

**Discovery route (verified, unauthenticated):** the iTunes Search API returns the real RSS `feedUrl`, `trackCount`, and `releaseDate` (= latest episode) for any podcast:
```
https://itunes.apple.com/search?term=<show>&entity=podcast&limit=3&country=US
https://itunes.apple.com/lookup?id=<collectionId>&entity=podcast
```
**This also doubles as an activity check** — `releaseDate` is how "Let's talk ABM (latest 2025-11-14 → dormant)" and "Revenue Makers (2025-11-11 → dormant)" were identified.

**Transcript route (verified downloadable, no auth):** parse `<podcast:transcript url="..." />` from the feed. Confirmed formats and hosts:

| Host | Format | Verified example |
| --- | --- | --- |
| Transistor | plain `.txt`, speaker-labelled + timestamped | `https://share.transistor.fm/s/6d137ece/transcript.txt` → **HTTP 200, 70,157 bytes** `[TESTED-curl]` |
| Buzzsprout | HTML with `<cite>`/`<time>`/`<p>` | `https://www.buzzsprout.com/2090897/19711856/transcript` → **HTTP 200, 52,393 bytes** `[TESTED-curl]` |
| Spotify CDN (via Anchor) | `.srt` | `transcript-files.spotifycdn.com/.../transcript.srt` `[TESTED-curl]` (tag present) |
| Spreaker | `.sr` | `transcription.spreaker.com/starship/.../*.sr` `[TESTED-curl]` (tag present) |
| Captivate | JSON | `transcripts.captivate.fm/transcript/<uuid>/transcript.json` `[TESTED-curl]` (tag present) |

**Fallback for the ~60% of shows with no transcript tags** (GTM Live, Scrappy ABM, Breaking B2B, The B2B Playbook, 30MPC, Stacking Growth, Lenny's, Brandformance):
1. **Show notes from the feed** — often substantial: Lenny's newest item carries **10.7 KB** of `<description>`, GTMnow 4.3 KB, Scrappy ABM 4.3 KB, Topline 3.9 KB, GTM Live 3.6 KB, The B2B Playbook 3.0 KB. Worth collecting on its own.
2. **The YouTube version** — most of these shows publish video; use yt-dlp auto-captions.
3. **Whisper/ASR on the enclosure MP3** — the feeds carry direct audio URLs. Highest cost, complete coverage.

**Reliability: HIGH for discovery and show notes; HIGH for the 4 transcript-bearing shows; MEDIUM for the rest (requires ASR or YouTube).**

---

## 2.7 Open-web blogs — high reliability

24 of 25 creator domains returned **HTTP 200** to browser-UA curl `[TESTED-curl]`. Only `gtmnow.com` (403) failed outright; `6sense.com` returned 403 to curl but 200 to a full browser stack (bot-gate, not paywall).

**Route:** sitemap → filter to `/blog/`, `/case-studies/`, `/podcasts/` paths → fetch. Two domains alone (`clay.com` 16,796 URLs, `coldiq.com` 6,306 URLs) supply enormous volume, though both need heavy filtering (Clay's sitemap includes thousands of template and integration pages).

**Blocked / degraded:**
- `personalabm.com` — blog and podcast pages returned **empty bodies** on every attempt `[BLOCKED]` (JS-rendered or bot-gated). Use the Buzzsprout feed instead.
- `6sense.com/resources/` — redirects to a **PathFactory login wall** `[BLOCKED]`.
- `momentumabm.com` — **504 timeout** twice `[BLOCKED]`.
- `learnwhywebuy.com` (Katelyn Bourgoin) — repeated empty responses `[BLOCKED]`.
- `terminus.com/blog` → redirects to `demandscience.com`; historical Terminus content likely needs the Wayback Machine.

---

## 2.8 Public datasets — Common Crawl ✅ verified indexing our exact targets

**Common Crawl CDX API works and has recent captures of the roster domains `[TESTED-curl]`:**

```bash
curl -s "https://index.commoncrawl.org/CC-MAIN-2026-30-index?url=fullfunnel.io/*&output=json"
```
→ **HTTP 200** with real JSON records including `https://fullfunnel.io/abm-linkedin-bootcamp/` captured **2026-07-21**, plus the site root. A second check on `strategicabm.com` also returned records (captured **2026-07-15**, plus a 301 diagnostic record).

**Reliability: MEDIUM-HIGH.** Free, no auth, legitimate, and confirmed to index actual target sites as recently as the July 2026 crawl. Subject to normal Common Crawl limits: not exhaustive, not real-time, and WARC retrieval/filtering has a real compute cost. **Best used for bulk backfill of the open-web domains, not for freshness.**

**HuggingFace: nothing usable at scale `[TESTED via API]`.** A search surfaced `Gingiris/gingiris-reddit-marketing` (a "Reddit Marketing Playbook 2026" — an SOP document, not a raw corpus; it carries an unverified third-party claim that "Reddit's share of ChatGPT/Claude training data" is 40.11%, which should **not** be repeated) and `Greich/linkedin_posts` (44 downloads, <1,000 rows — a toy). **No serious pre-built B2B GTM corpus exists. This corpus has to be built, not found.**

**Wayback Machine — unexplored but recommended** for the pre-acquisition Terminus and ITSMA corpora, both of which are otherwise lost (see Appendix B).

---

# PART 3 — THE TOP 25 CANON

Ranked by value to a Head of ABM agent. Every URL below was HTTP-verified in this session unless marked otherwise.

| # | Piece | URL | What it teaches |
| --- | --- | --- | --- |
| 1 | **6sense 2025 B2B Buyer Experience Report** | `https://6sense.com/science-of-b2b/buyer-experience-report-2025/` | 95% of wins are already on the buyer's Day One shortlist; 4 shortlist spots filled on day one; 6–10 stakeholders; cycles compressed to 10.1 months. **The empirical case for ABM existing at all.** |
| 2 | **Fullfunnel — Account-Based Engagement Playbook** | `https://fullfunnel.substack.com/p/account-based-engagement-playbook` | The six-step engagement sequence, three account lists (Cluster ICP / Future Pipeline / Active Focus) with distinct KPIs, and the discipline of 7–10 accounts per two-month batch. **The best single operational ABM playbook on the open web.** |
| 3 | **Jon Miller — 9 Reasons Buying Groups Will Be the Next Big Thing** | `https://www.demandbase.com/blog/9-reasons-buying-groups-next-big-thing/` | Why the unit of B2B modelling is the committee, not the lead. Directly underwrites committee resolution. |
| 4 | **Clay — GTM Engineering: What It Is and How to Hire in 2026** | `https://www.clay.com/blog/gtm-engineering` | The three-tier model: data foundation → data modeling (propensity, ICP attributes) → data activation. The clearest articulation of the discipline Clue automates. |
| 5 | **LinkedIn B2B Institute × Ehrenberg-Bass — How B2B Brands Grow (95:5)** | `https://business.linkedin.com/advertise/resources/b2b-institute/how-b2b-brands-grow` | Only ~5% of buyers are in-market in a given quarter. The reason ABM must include out-of-market nurture, not just in-market capture. |
| 6 | **strategicabm — Acxiom: $2m Sales Pipeline in 120 Days** | `https://insights.strategicabm.com/video-case-study-acxiom-abm-sales-pipeline` | A complete enterprise one-to-few program with a real number and a real timeframe. |
| 7 | **Jon Miller — Beyond the MQL: A Three-Tier Model for B2B Qualification** | `https://www.jonmiller.com/blog/2026/3/16/beyond-the-mql-a-three-tier-model-for-b2b-qualification` | How to replace the MQL with account-and-committee-level qualification tiers. Maps onto two-pass tiering. |
| 8 | **Fullfunnel — Our ABM program breakdown [Case Study]** | `https://fullfunnel.substack.com/p/our-abm-program-breakdown-case-study` | A practitioner decomposing their *own* program, 2026-08-28. Rare first-person operational transparency. |
| 9 | **Lavender — The Cold Email Benchmark Report** | `https://lavender.ai/blog/the-cold-email-benchmark-report` | N=231,818 emails; reply rates by department and seniority. Empirical persona-level messaging priors. |
| 10 | **Scrappy ABM — Electric Era: one-off webinars → $12M pipeline engine** | `https://scrappyabm.com/case-studies/electric-era-turning-one-off-webinars-into-a-12m-pipeline-engine/` | Converting scattered activity into a repeatable account motion — the most common real-world ABM starting point. |
| 11 | **Fullfunnel — Why viral ABM plays fail in enterprise** | `https://fullfunnel.substack.com/p/why-viral-abm-plays-fail-in-enterprise` | **Failure modes.** The most valuable negative-signal document in the map: why LinkedIn-famous tactics break at enterprise scale. |
| 12 | **AdRoll/RollWorks ABM hub — Snowflake, PitchBook, Total Expert** | `https://www.adroll.com/topics/abm` | Three quantified programs: 75% more SDR meetings; 37.9% lower CPC + 24.3% higher win rate; 93% account reach. |
| 13 | **ColdIQ — Aircall case study** | `https://coldiq.com/case-studies/aircall` | 3,600+ accounts enriched in 6 months — enrichment-at-scale mechanics with a real client. |
| 14 | **Jon Miller — Atomic Buying Journeys** | `https://www.jonmiller.com/blog/2024/10/8/particle-physics-meets-pipeline-introducing-atomic-buying-journeys` | Modelling the buying journey as discrete committee-member interactions rather than a single funnel. |
| 15 | **Adam Robinson — The Death of Signal Orchestration** | `https://newsletter.rb2b.com/p/the-death-of-signal-orchestration` | A critique of signal-based selling *from its loudest advocate*. Essential counterweight to intent-data hype. |
| 16 | **strategicabm — What is an ABM Center of Excellence in 2026** | `https://insights.strategicabm.com/what-is-an-abm-center-of-excellence-in-2026` | How ABM is organisationally structured inside a large enterprise — who owns what. |
| 17 | **Jordan Crawford — On the Edge by Blueprint** | `https://edge.blueprintgtm.com/` | The "data IS the message" thesis; PQS / PVP / FIND. The conceptual parent of research-driven outbound. |
| 18 | **ColdIQ — AirOps case study** | `https://coldiq.com/case-studies/airops` | An ABM strategy producing eight-figure pipeline, with the mechanics disclosed. |
| 19 | **Fullfunnel — How to run ABM for a new enterprise product in a new market** | `https://fullfunnel.substack.com/p/how-to-run-abm-for-a-new-enterprise` | Cold-start ABM: no customer base, no proof, no list. The hardest and least-documented case. |
| 20 | **Clay — How we turned a few thousand ad dollars into $1.3M in pipeline** | `https://www.clay.com/blog` (2026-08-31) `[FETCHED]` | Paid + outbound + enrichment as one closed loop, with the arithmetic shown. |
| 21 | **Exit Five — Top 25 B2B Marketing Voices on LinkedIn** | `https://exitfive.com/articles/top-25-b2b-marketers-to-follow-on-linkedin/` | A curated, dated (2025-05-02) map of the practitioner graph — useful both as content and as a source-discovery seed. |
| 22 | **Scrappy ABM — BambooHR: doubled outbound conversion from a dead-account database** | `https://scrappyabm.com/case-studies/bamboo-hr/` | Reactivating closed-lost/dormant accounts — one of the highest-ROI, least-discussed ABM plays. |
| 23 | **strategicabm — The rise of Peer-to-peer ABM** | `https://insights.strategicabm.com/peer-to-peer-abm` | Account engagement through customer/peer networks rather than vendor broadcast. |
| 24 | **Demandbase — The Prompt (podcast, 218 transcripts)** | `https://anchor.fm/s/300e904/podcast/rss` | 591 episodes of practitioner interviews with machine-readable `.srt` transcripts. Bulk corpus, not a single argument. |
| 25 | **Exit Five — The Dave Gerhardt Show (259 transcripts)** | `https://feeds.transistor.fm/exit-five-podcast` | 397 episodes of B2B marketing leadership conversation, plain-text transcripts, active through 2026-08-31. |

**Honourable mentions** (strong but narrower): Fullfunnel's "The 2026 B2B content playbook"; Justin Rowe's `impactable.com/demand-gen-playbook-for-abm/`; Sam Nelson's Agoge Sequence; the 6sense 2025 metrics dashboard; Clay University's "Signals & ABM" course; Bev Burgess's *Account-Based Marketing: The Definitive Handbook* (2025 ed., not open web).

---

# PART 4 — WHO PUBLISHES REAL CASE STUDIES vs. OPINION

The distinction matters: an agent trained mostly on opinion will produce confident, unfalsifiable advice. The numeric sources are what make advice checkable.

### Tier 1 — Named client + hard number + timeframe (collect aggressively)

| Source | Evidence | Shape of numbers |
| --- | --- | --- |
| **Scrappy ABM** | 9 published case studies `[FETCHED]` | Pipeline $, revenue $, conversion-rate deltas. Parsable $3M/6mo; Electric Era $2M created + $10M accelerated; Forward Studios $150K |
| **ColdIQ** | 8+ case studies `[FETCHED]` | Accounts enriched, pipeline $, demos/week, reply rates, bounce %. Aircall 3,600+ accounts/6mo; AirOps $10.1M |
| **strategicabm** | Insights-subdomain case studies `[FETCHED]` | Pipeline $ + days. Acxiom $2m/120 days. Named enterprise logos (SAP, Cloudflare, AVEVA) |
| **Fullfunnel.io** | **25+ case studies** claimed on `/about/` `[FETCHED]`; `[Case Study]`-tagged Substack posts | Opportunities created, engagement %, deal counts. A LinkedIn post cited "3 enterprise opportunities, 43% engagement across 46 target accounts" |
| **Clay** | `clay.com/blog-category/case-studies` `[FETCHED]` | Pipeline $ per named client (Brex, Northbeam, Saviynt, AlertMedia) |
| **AdRoll / RollWorks** | ABM topic hub `[FETCHED]` | Meeting rate, CPC, cycle length, win rate, account reach — the most *metric-diverse* set |
| **Lavender** | Cold Email Benchmark Report `[TESTED-curl]` | **Large-N empirical research** (N=231,818). The highest evidential quality in the map |
| **Growth Engine X** | Site + partner pages `[FETCHED]` | Reply counts and rates per named client. Weaker (volume, not revenue) but real |

### Tier 2 — Numbers present but self-reported or aggregate-only (collect with a caveat flag)

| Source | Caveat |
| --- | --- |
| **Adam Robinson / RB2B** | Numeric-dense but **self-reported founder narrative**; ARR figures inconsistent across posts ($22M/$24M/$32M). Collect, but do not treat as audited. |
| **6sense / Demandbase** | Excellent survey and benchmark research, but **vendor-published** — the findings consistently support buying their category. Collect the methodology and N, flag the interest. |
| **Silvio Perez / AdConversion** | "$100M+ ad spend managed" is an aggregate self-claim; client evidence is testimonial, not numeric. |
| **Trinity Nguyen / UserGems** | One genuine controlled A/B (multithreaded ads vs. control) `[FETCHED]`, but the exact percentages were not stated in the fetched text. |
| **Peep Laja / Wynter** | The *product* generates real research data; the public content is more thesis than dataset. |
| **Sam Nelson** | The Agoge Sequence claims "2× response rates" — methodology-level, not per-client. |
| **Lead Gen Jay** | Income claims ("$700K/mo", "8 figures") are self-reported and unaudited. |

### Tier 3 — Opinion, framework, and thesis (valuable, but label it)

| Source | Why still worth collecting |
| --- | --- |
| **Jon Miller** | The best conceptual frameworks in the space (buying groups, atomic journeys, three-tier qualification). Zero case numbers. |
| **Jordan Crawford** | "The data IS the message"; PQS/PVP/FIND. Pure mental model — and the most Clue-aligned mental model in the map. |
| **Sangram Vajre** | Category-level frameworks (MOVE, GTM OS). |
| **Bev Burgess** | Definitional/taxonomic authority. Ground the vocabulary here. |
| **Chris Walker (historical)** | Demand creation vs. capture; dark funnel; anti-attribution-theater. Foundational, but **label as pre-2025**. |
| **Corrina Owens, Nick Bennett, Canberk Beker, Kyle Coleman, Devin Reed, April Dunford, Anthony Pierri** | Craft-level opinion and teardowns. Good for tone and judgment, not for evidence. |

### Explicit non-numeric warning
Third-party "top voices" lists (`gtmepulse.com/top-voices/`, `theabmpulse.com/voices/`, `demandgeninsider.com/voices/`, `leapd.ai`) are **self-published rankings by interested parties**. Use them only for name discovery. Do not train on their superlatives.

---

# PART 5 — FETCHABILITY REGISTER

Every row observed directly this session. `[TESTED-curl]` = shell `curl -L` with a Chrome User-Agent; status and byte count as returned.

## 5.1 Creator and org domains

| Domain | HTTP | Bytes | Retrievable? | Route |
| --- | --- | --- | --- | --- |
| `fullfunnel.io` | 200 | 111,333 | ✅ Yes | Sitemap index (3 sub-sitemaps) |
| `fullfunnel.substack.com` | 200 | 83,247 | ✅ **Best** | `/feed` full-text + `/api/v1/archive` |
| `scrappyabm.com` | 200 | 485,846 | ✅ Yes | `sitemap_index.xml` → `post-sitemap.xml` (156 URLs) |
| `strategicabm.com` | 200 | 94,170 | ✅ Yes | Direct crawl |
| `insights.strategicabm.com` | 200 | 108,247 | ✅ Yes | **`/rss.xml` works (290 KB)**; sitemap 219 URLs |
| `resources.strategicabm.com` | 200 | 147,500 | ✅ Yes | Direct crawl (podcast + DashDot) |
| `coldiq.com` | 200 | 232,843 | ✅ Yes | **Sitemap 6,306 URLs**; ⚠️ `/blog/rss.xml` 404 |
| `coldoutbound.com` | 200 | 81,111 | ✅ Yes | Direct (Growth Engine X's new home) |
| `growthenginex.com` | 200 | 81,111 | ✅ Yes | ⚠️ **301 → coldoutbound.com** |
| `exitfive.com` | 200 | 82,516 | ⚠️ Partial | ⚠️ `/feed` 200-but-empty; no sitemap. Crawl `/newsletter/` index |
| `clay.com` | 200 | 502,282 | ✅ Yes | **`/blog/rss.xml` works**; sitemap **16,796 URLs** |
| `university.clay.com` | 200 | 212,648 | ✅ Yes | Direct (`/courses`, 206 KB) |
| `community.clay.com` | 200 | 240,764 | ✅ Yes | Direct |
| `gtmnow.com` | **403** | 103 | ❌ **No** | Use `thegtmnewsletter.substack.com/feed` + Buzzsprout podcast feed |
| `thegtme.com` | 200 | 76,346 | ✅ Yes | `/feed` — 19 items, 19 full-text |
| `thegtmengineer.substack.com` | 200 | 76,303 | ✅ Yes | `/feed` — 337 KB |
| `growthunhinged.com` | 200 | 1,583,895 | ⚠️ Partial | ⚠️ feeds **403 Cloudflare**; sitemap 321 URLs. **Prefer `kylepoyar.substack.com/feed`** |
| `kylepoyar.substack.com` | 200 | — | ✅ Yes | `/feed` — 678 KB, 20/20 full-text |
| `mkt1.co` | 200 | 337,942 | ⚠️ Partial | `/feed` 404 (Framer). Use `newsletter.mkt1.co/feed` (1.51 MB) |
| `newsletter.mkt1.co` | 200 | — | ✅ Yes | `/feed` — 20/20 full-text |
| `newsletter.rb2b.com` | 200 | 647,110 | ⚠️ Partial | ⚠️ `/feed` + `/rss.xml` **404**. **`sitemap.xml` 158 URLs** |
| `edge.blueprintgtm.com` | 200 | 98,887 | ✅ Yes | `/feed` — 595 KB, 20/20 full-text |
| `b2brizz.com` | 200 | 105,722 | ✅ Yes | Direct |
| `impactable.com` | 200 | 104,640 | ✅ Yes | Direct |
| `passetto.com` | 200 | 172,885 | ✅ Yes | Direct |
| `refinelabs.com` | 200 | 45,145 | ✅ Yes | Direct (historical corpus) |
| `wynter.com` | 200 | 86,766 | ✅ Yes | Direct |
| `sparktoro.com` | 200 | 64,334 | ✅ Yes | Direct |
| `usergems.com` | 200 | 155,459 | ✅ Yes | Direct |
| `jonmiller.com` | 200 | — | ✅ Yes | Sitemap 50 locs |
| `demandbase.com` | 200 | — | ✅ Yes | Sitemap index, 25 sub-sitemaps |
| `6sense.com` | **403** to curl / 200 to browser | 5,789 / — | ⚠️ Bot-gated | Needs a real browser stack (Playwright). ⚠️ `/resources/` → PathFactory login wall |
| `adroll.com/topics/abm` | 200 | 47,121 | ✅ Yes | Direct |
| `abmleadershipalliance.com` | 200 | 50,513 | ✅ Yes | Direct |
| `inflexiongroup.com` | 200 | 136,912 | ✅ Yes | Direct |
| `gtmpartners.com` | 200 | 112,159 | ✅ Yes | Direct |
| `gtmepulse.com` | 200 | 67,545 | ✅ Yes | Direct (lead-discovery only) |
| `business.linkedin.com` (B2B Institute) | 200 | 131,995 | ✅ Yes | ⚠️ `/marketing-solutions/...` 301 → `/advertise/resources/...` |
| `lavender.ai` | 200 | 101,898 | ✅ Yes | ⚠️ `www.` → apex redirect |
| `personalabm.com` | — | empty | ❌ **No** | JS-rendered/bot-gated. Use the Buzzsprout podcast feed |
| `terminus.com` | 301 | — | ❌ **No** | Redirects to `demandscience.com`. Use Wayback for history |
| `momentumabm.com` | 504 | — | ❌ **No** | Timed out twice |
| `learnwhywebuy.com` | — | empty | ❌ **No** | Empty body on repeated attempts |
| `tackinsider.com` | 200 | — | ⚠️ Stale | Newest posts dated Dec 2024 |

## 5.2 Feeds and APIs

| Endpoint | HTTP | Result | Verdict |
| --- | --- | --- | --- |
| `fullfunnel.substack.com/feed` | 200 | 1.27 MB, 20 items, full-text | ✅ **Gold standard** |
| `fullfunnel.substack.com/api/v1/archive?...` | 200 | 94 KB, 12 posts + paywall flags | ✅ **Best backfill route** |
| `fullfunnel.substack.com/sitemap.xml` | 200 | 38 KB | ✅ |
| `newsletter.mkt1.co/feed` | 200 | 1.51 MB, 20/20 full-text | ✅ |
| `thegtme.com/feed` | 200 | 804 KB, 19/19 | ✅ |
| `thegtmnewsletter.substack.com/feed` | 200 | 737 KB, 20/20 | ✅ |
| `kylepoyar.substack.com/feed` | 200 | 678 KB, 20/20 | ✅ |
| `edge.blueprintgtm.com/feed` | 200 | 595 KB, 20/20 | ✅ |
| `thegtmengineer.substack.com/feed` | 200 | 337 KB | ✅ |
| `samnelson.substack.com/feed` | 200 | 177 KB, 20/20 | ✅ |
| `insights.strategicabm.com/rss.xml` | 200 | 290 KB | ✅ |
| `clay.com/blog/rss.xml` | 200 | 75 KB | ✅ |
| `exitfive.com/feed` | 200 | 896 B, **0 items** | ❌ Empty channel |
| `exitfive.com/rss.xml` | 404 | — | ❌ |
| `exitfive.com/sitemap_index.xml` / `wp-sitemap.xml` | 404 | — | ❌ |
| `newsletter.rb2b.com/feed` \| `/rss.xml` \| `/rss/feed` | 404 | — | ❌ |
| `newsletter.rb2b.com/sitemap.xml` | 200 | 158 locs | ✅ |
| `growthunhinged.com/rss` \| `/feed.xml` \| `/rss/feed` | 403 / 404 | Cloudflare challenge | ❌ |
| `growthunhinged.com/sitemap.xml` | 200 | 321 locs | ✅ |
| `mkt1.co/feed` | 404 | — | ❌ (Framer) |
| `coldiq.com/blog/rss.xml` | 404 | — | ❌ (use sitemap) |
| `coldiq.com/sitemap.xml` | 200 | 6,306 locs | ✅ |
| `clay.com/sitemap.xml` | 200 | 16,796 locs | ✅ |
| `scrappyabm.com/post-sitemap.xml` | 200 | 156 locs | ✅ |
| `insights.strategicabm.com/sitemap.xml` | 200 | 219 locs | ✅ |
| `itunes.apple.com/search?entity=podcast` | 200 | feedUrl + trackCount + releaseDate | ✅ **Best podcast discovery + activity check** |
| `youtube.com/feeds/videos.xml?channel_id=` | 200 (throttled) | 15 entries | ⚠️ Works, but ≤1 req / 3 s |
| `share.transistor.fm/s/.../transcript.txt` | 200 | 70,157 B plain text | ✅ **Transcripts confirmed** |
| `buzzsprout.com/<show>/<ep>/transcript` | 200 | 52,393 B HTML | ✅ **Transcripts confirmed** |
| `x.com/*` (WebFetch) | **402** | — | ❌ Payment required |
| `x.com/elonmusk` (curl) | 200 | 243,062 B, **0 tweet-text matches** | ❌ JS shell only |
| `cdn.syndication.twimg.com/tweet-result` | 200 / 404 | `{}` (2 B) | ⚠️ Inconclusive |
| `nitter.net` | 200 | "nitter.net is offline" | ❌ Dead |
| `xcancel.com` | 200 | 321 B — **C&D notice dated 2026-08-24** | ❌ Shut down |
| `linkedin.com/in/*` | 200 / **999** | intermittent | ⚠️ Rate-limited; country redirects |
| `linkedin.com/posts/*` | 404 (invented id) | 319 KB real LinkedIn page | ⚠️ No hard block, but no real post tested |
| `linkedin.com/pulse/*` | 200 (invented slug) | 98 KB, fell back to `d_klp_home` | ⚠️ **Genuinely untested** |
| `reddit.com/r/*/about.json` | **403** | ~190 KB JS shell | ❌ **Dead** |
| `old.reddit.com/r/*/about.json` | **302** | → `/login/` | ❌ Login required |
| `reddit.com/r/B2BMarketing/.rss` | 200 | 55,272 B, 25 entries | ✅ Works |
| `reddit.com/r/sales/.rss` | 200 | 40,166 B | ✅ Works |
| `reddit.com/r/coldemail/.rss` | 200 | `<title>coldemail: banned</title>` | ❌ **Subreddit banned** |
| `reddit.com/r/*/.rss` under load | **429 → block page** | after ~15 rapid reqs | ⚠️ Behaviour-based blocking |
| `index.commoncrawl.org/CC-MAIN-2026-30-index` | 200 | real records for fullfunnel.io + strategicabm.com | ✅ Works |
| `lennysnewsletter.com/feed` (Substack control) | 200 | 395,886 B, 20 items, 15,252-char first body | ✅ **Full text confirmed** |
| `themarketingmillennials.com/feed/` | **403** | Cloudflare | ❌ WP feed blocked |
| `rss.beehiiv.com/feeds/<slug>.xml` | 404 | — | ❌ Pattern doesn't exist |
| `developers.beehiiv.com/docs/v2/rss` | 404 | — | ❌ Docs gone |
| `saleshacker.com/podcast`, `salesgravy.com/sales-podcast` | **403** | 103 B block pages | ❌ WAF-blocked |
| `exitfive.com/podcast` | 200 | 82,405 B, episode markup, **no "transcript" string** | ⚠️ Metadata only |

## 5.3 Tooling status on this machine

| Tool | Status | Action needed |
| --- | --- | --- |
| `curl` | ✅ `/usr/bin/curl` | — |
| `python3` | ✅ 3.13.3 | — |
| `yt-dlp` | ✅ **INSTALLED THIS SESSION** — v2026.08.19 at `~/Library/Python/3.13/bin/yt-dlp` | Add that dir to `PATH`; caption pipeline verified working |
| JS runtime for yt-dlp (`deno`/Node) | ⚠️ **Absent** — yt-dlp warns *"YouTube extraction without a JS runtime has been deprecated"* | **Install `deno`** for durability; extraction still works today without it |
| Headless browser (Playwright/Puppeteer) | ❌ Not present | **Needed for 6sense and any Cloudflare-gated domain** |

---

# PART 6 — RECOMMENDED ACQUISITION PLAN

**Phase 1 — free, fast, highest quality (do first).**
Substack `/feed` + `/api/v1/archive` for E1–E8; podcast transcript tags for the four transcript-bearing shows (Exit Five 259, GTMnow 257, Full-Funnel 223, The Prompt 218); RSS for `insights.strategicabm.com` and `clay.com/blog`. **Estimated: several thousand full-text documents, zero auth, zero legal ambiguity.**

**Phase 2 — sitemap crawls.**
`scrappyabm.com` (156), `insights.strategicabm.com` (219), `newsletter.rb2b.com` (158), `growthunhinged.com` (321), `jonmiller.com` (50), plus filtered subsets of `coldiq.com` (6,306) and `clay.com` (16,796). Crawl `exitfive.com/newsletter/` as an index since it has no sitemap.

**Phase 3 — YouTube captions via `yt-dlp` (already installed and proven).** Pull the 8 priority channels in §2.4 plus a Chris Walker guest-appearance sweep. Install `deno` first for extraction durability. Use `ytsearch` for channel resolution, not handle guessing. Throttle channel-RSS discovery to ≤1 request / 3 s.

**Phase 4 — Common Crawl bulk backfill.** Query the CDX index for every open-web domain in §5.1 and pull WARC records. This is the cheapest way to get historical depth on `clay.com` (16,796 URLs) and `coldiq.com` (6,306 URLs) without hammering their servers. Verified working against fullfunnel.io and strategicabm.com.

**Phase 5 — Reddit, carefully.** ⚠️ **Not the JSON API — that returns 403.** Use `.rss` at ≤10 req/min with jittered delays and a single honest User-Agent (do not rotate), plus **Arctic Shift** Academic Torrents dumps for comment-level history. **Exclude r/coldemail (banned).** If sustained live collection is needed, start the OAuth pre-approval process immediately — it is manual, slow, and may be closed to new applicants.

**Phase 6 — ASR** (Whisper) over podcast enclosures for the ~60% of shows with no transcript tags, prioritising GTM Live (619 eps), Breaking B2B (499), Scrappy ABM (283), The B2B Playbook (259). Cheaper alternative: check whether each show has a YouTube simulcast first and use Phase 3 instead.

**Phase 7 — LinkedIn, last and least.** Mirror-first only. Accept coverage gaps for LinkedIn-native-only creators (e.g. Bev Burgess's "The ABM-er") rather than building a scraper. One clean test of a *real* `linkedin.com/pulse` article is worth doing before writing the surface off entirely.

**Not recommended at all: X/Twitter.** Blocked at the content layer, mirrors under active legal attack, and every relevant voice is reachable elsewhere.

---

# APPENDIX A — Exit Five "Top 25 B2B Marketing Voices on LinkedIn"
Fetched from `https://exitfive.com/articles/top-25-b2b-marketers-to-follow-on-linkedin/`, published **2025-05-02** `[FETCHED]`. Reproduced as a discovery seed; roles were current as of that date and several have since changed (see corrections throughout Group C).

Pranav P (`/in/pranavp/`) · Meryoli Arias (`/in/meryoliarias/`) · Diane Wiredu (`/in/dianewiredu/`) · Emily Kramer (`/in/emilykramer/`) · Tas Bober (`/in/tasbober/`) · Lashay Lewis (`/in/lashaylewis/`) · Natalie Marcotullio (`/in/natalie-marcotullio/`) · Chelsea Castle (`/in/chelseacastle/`) · Madhav Bhandari (`/in/madhavbhandari/`) · Devin Reed (`/in/devinreed/`) · Jason Bradwell (`/in/jasonbradwell/`) · Rob B.K. (`/in/heyrobk/`) · Rita Cidre (`/in/rita-cidre/`) · Jess Cook (`/in/jesscook-contentmarketing/`) · Chima Mmeje (`/in/chima-mmeje/`) · Meisha (`/in/marketingmeisha/`) · Kyle Coleman (`/in/kyletcoleman/`) · Mark Huber (`/in/markehuber/`) · Yi Lin Pei (`/in/yilinpei/`) · Christina (`/in/thesechapters/`) · Sam Kuehnle (`/in/samkuehnle/`) · Chelsea Lassen (`/in/chelsea-lassen/`) · Erik Jacobson (`/in/erik-jacobson-hatch/`) · Corrina Owens (`/in/corrina-owens/`) · Talya Heller (`/in/talyahellermba18/`)

---

# APPENDIX B — Corrections register
Stale facts commonly repeated in secondary sources, corrected here.

| Commonly stated | Actually (as of 2026-08-31) | Evidence |
| --- | --- | --- |
| Chris Walker runs Refine Labs / Revenue Vitals | **CEO of ENCODED** (neuroperformance); Refine Labs sold; Revenue Vitals → GTM Live, hosted by Carolyn Dilks & Trevor Gibson | LinkedIn `[FETCHED]`; iTunes feed `[TESTED-curl]` |
| Kyle Coleman is CMO of Copy.ai | **Global VP Marketing, ClickUp** | `[SNIPPET]`, multiple 2026 sources |
| Sam Kuehnle is VP Demand Gen at Loxo | **Left Loxo Aug 2026; LinkedIn shows Affect** | LinkedIn `[FETCHED]` |
| Corrina Owens is at RapidSOS / Gong | **BILL** | LinkedIn `[FETCHED]` |
| Nick Bennett is Co-founder/CCO of TACK | **Founder, NB Marketing**; TACK content stale since Dec 2024 | LinkedIn + tackinsider.com `[FETCHED]` |
| Camille Trent is Head of Content at Teal | **Auror** | LinkedIn `[FETCHED]` |
| Anthony Kennada leads AudiencePlus | **CMO at Armada** (announced ~late Aug 2026); Advisor at AudiencePlus | His own LinkedIn post `[FETCHED]` |
| Jon Miller is CMO of Demandbase | **Founder/CEO of Phave**; was Chief Evangelist at Demandbase | Demandbase author page `[FETCHED]` |
| Bev Burgess is at ITSMA | **Co-founder/CEO, Inflexion Group** (2024). ITSMA → Momentum (2021) → Accenture (2025) | `[FETCHED]` |
| Terminus is an independent ABM platform | **Inside DemandScience**; `terminus.com/blog` redirects | Redirect `[FETCHED]` |
| RollWorks has its own content hub | **Redirects to `adroll.com/topics/abm`** | Redirect `[FETCHED]` |
| Growth Engine X lives at growthenginex.com | **301 → coldoutbound.com** | `[TESTED-curl]` |
| Clay's YouTube is `@getclay` / `@clayhq` | **`@GrowWithClay`.** `@getclay` is "Calprop"; `@clayhq` is the *personal-CRM* Clay (clay.earth) | `[TESTED-curl]` |
| "GTMonday" and "GTMnow" | **Different publications.** GTMonday = Sangram Vajre / GTM Partners. GTMnow = GTMfund (VC), Scott Barker | `[FETCHED]` |
| "The ABM Consortium" | **Not found.** The real analogue is the **ABM Leadership Alliance** | `[FETCHED]` |
| Jon Miller said "ABM is dead" | **Unverified quote.** His framing is ABM-as-"fishing with spears" → ABX | `[FETCHED]` |
| Tyler Pleiss is Sr. Director ABM at Sphera | **Two conflicting LinkedIn profiles** (Sphera vs. Movable Ink). Unresolved | `[SNIPPET]` |
| Charlotte Johnson is an outbound creator | **Likely a name collision** with an unrelated cybersecurity professional. Do not include | `[SNIPPET]` |

---

# APPENDIX C — Open questions before build

**Resolved since the first draft:** Reddit's route status (`.json` dead, `.rss` works), yt-dlp installation and caption verification, Common Crawl viability, X/Nitter status, and the Clay subscriber correction are all now settled and reflected above.

**Still open:**

1. **Reddit subscriber counts for most target subs.** `r/B2BMarketing`, `r/agency`, `r/marketing`, `r/SaaS`, `r/salestechniques`, `r/msp`, `r/gtmengineering` sizes were never obtained — the `.rss` probes hit the block wall and third-party trackers 404'd. Retry after a cool-down, spaced over hours.
2. **Reddit OAuth approval.** Start the application now; it is manual, reportedly slow, and possibly closed to new applicants since Nov 2025. This is the long pole for any comment-level collection.
3. **`linkedin.com/pulse` against a REAL article** — the only test run used an invented slug and proved nothing. This is the single most valuable untested mirror route.
4. **X syndication endpoint** with a confirmed-live tweet ID + valid `token`. One controlled retest, then drop it.
5. **No headless browser present** → 6sense, Growth Unhinged's own domain, and any Cloudflare-gated source are currently uncollectable. Install Playwright if those matter.
6. **`deno` / JS runtime for yt-dlp** — extraction works today but YouTube has deprecated the no-JS path. Install before this becomes a silent failure.
7. **beehiiv RSS remains unsolved** after 5+ attempts including their own 404'd docs. Either accept sitemap crawling or find one confirmed beehiiv publication with a working feed and reverse-engineer the pattern.
8. **Podscan / Listen Notes APIs untested** — purpose-built for podcast transcript discovery and likely more reliable than scraping individual host sites (several of which returned 403: saleshacker.com, salesgravy.com).
9. **Wayback Machine** for the pre-acquisition Terminus and ITSMA corpora — unexplored, and those corpora are otherwise lost.
10. **Licensing and ToS review not performed.** Every route here is technically feasible; none has been legally cleared. Risk ordering, lowest to highest: Substack/RSS and podcast transcripts → Common Crawl → open-web sitemaps → YouTube captions → Reddit `.rss` → LinkedIn → X.
11. **Fullfunnel subscriber count** is reported as both 20,100+ and 27,000+ by two of their own surfaces — cite the range.
12. **Two "GTM Engineer" Substacks** must stay distinct in corpus metadata (`thegtme.com` = Clay's; `thegtmengineer.substack.com` = independent).
13. **Unverified third-party stat to NOT propagate:** a HuggingFace dataset card claims "Reddit's share of ChatGPT/Claude training data: 40.11%." No primary source. Do not repeat it.

---

*End of document. All HTTP statuses, byte counts, episode counts, transcript-tag counts, subscriber figures, and feed URLs above were observed directly on 2026-08-31 unless tagged `[SNIPPET]` or `[UNVERIFIED]`.*
