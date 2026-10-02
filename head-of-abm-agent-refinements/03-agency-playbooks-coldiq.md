# Agency Playbooks: ColdIQ Teardown + the Wider ABM/Outbound Agency Landscape

**Purpose.** Seed the domain-expertise layer of Clue's AI "Head of ABM" agent. This document captures how the best outbound/ABM agencies *actually operate*: what they publish, how they scope and run engagements, the exact plays and numbers they claim, and — most important for steering an agent — **how they talk to clients**.

**Research date:** 2026-08-31. **Method:** direct WebFetch of primary sources (agency-owned domains) plus search-indexed secondary sources. Every claim carries a URL. Retrieval status marked per item: `[FETCHED]` = full page retrieved and content extracted; `[SNIPPET]` = only search-result/summary text obtained; `[GATED]` = page retrieved but the substantive content sits behind an email wall; `[BLOCKED]` = HTTP 403/404/504 or auth wall.

---

## Executive summary (read this if you read nothing else)

1. **ColdIQ is no longer primarily an agency — it became a product company, and the reason why is the single most strategically relevant finding for Clue.** Michel Lieben's own framing: "the biggest shift isn't replacing GTM tools. It's replacing the person who stitches them together." ([coldiq.com/blog/were-launching-a-unified-api-for-gtm](https://coldiq.com/blog/were-launching-a-unified-api-for-gtm))
2. Their diagnosis of why AI agents fail at GTM is, almost verbatim, Clue's thesis: agents fail for lack of **context** — "GTM skills and frameworks," "API keys for 8 to 12 different tools," "internal business context," and "past campaign data."
3. Scale claims: **$7M ARR, 275+ clients onboarded, 40,000+ monthly site visits, 100+ meetings/month, $5K–$10K/mo retainers**, closed in "2–3 Google Meet video calls."
4. Their onboarding is a **payment-triggered, 8-step automated pipeline** — "Nothing gets built for a client who has not paid, and everything gets built the second they have." Time-to-launch compressed from **8 weeks to 8 days**.
5. The highest-leverage sequencing rule they publish: **order email infrastructure on Day 0** because "warm-up is the longest lead time in the entire onboarding and it is not compressible."
6. The second: **map TAM before writing copy** — otherwise you discover post-launch "that the ICP as written contains 400 companies rather than the 40,000 the retainer assumed."
7. Their channel doctrine is **tier-first, not channel-first**: "Tier the target list first, assign channels accordingly — don't reverse the process." Tier 1 → LinkedIn + calls; Tier 2/3 → email at volume.
8. Multichannel sequencing has a specific, cheap, high-yield ordering: **profile view → connection invite → email**. "Resequencing LinkedIn ahead of email was the largest single lift" (1.8% → 4.3% positive replies).
9. Their copy doctrine separates **relevance from personalisation**: "I saw you have a dog" (bad) vs "As you mentioned [topic]" (good). And they explicitly distrust full-LLM email generation: "We don't trust GPT to write our emails for us."
10. Their data model is a published **8-layer taxonomy** (TAM → lookalikes → local → people enrichment → signals → technographic → live-web discovery → orchestration) that maps almost 1:1 onto Clue's resolver-waterfall architecture.
11. **Fullfunnel.io (Zinkevich/Blagojević) is the most rigorous ABM methodology in the landscape** and the best source for agent *strategy* logic: the 6A framework, three dynamic account lists (Cluster ICP / Future Pipeline / Active Focus), cluster-over-vertical targeting, and an explicit "AI-enabled, not AI-created" 80/20 rule.
12. Their proof point is deliberately small and honest: **46 accounts, 3 people, <$1,000/mo of tooling, 90 days → 43% engagement rate, 8.7% account-to-pipeline, 3 opportunities, 1 closed-won.** That is the realistic shape of an ABM pilot and the right benchmark for Clue's agent to quote.
13. **Growth Engine X (Eric Nowoslawski) is the volume/infrastructure extreme** — 8M+ emails/month, 52 concurrent clients, explicit qualification floors (TAM >100K, LTV >$5–10K) and a *free test campaign* as the pilot mechanism.
14. **Mason Cosby / Scrappy ABM is the credibility extreme** — "None, until you have a strategy" on tooling; publishes his price ($13,875 / 4 weeks); and the sharpest ICP-audit question in the corpus: "Run a report in your CRM right now. Add 'is customer' as a filter. If your ICP doesn't reflect your actual customer base, is it really your ICP?"
15. **Cross-agency pattern for the agent's voice:** every credible principal opens with *diagnosis*, quantifies the market before promising activity, sequences infrastructure ahead of creative, structures a *time-boxed pilot with leading indicators*, reports on account-level movement rather than volume, and names the failure mode explicitly. That's the persona to encode.

---

# PART 1 — ColdIQ deep teardown

## 1.1 Who they are

| Fact | Value | Source |
|---|---|---|
| Founders | **Michel Lieben** (Founder & CEO), **Alex Vacca** (Co-Founder & COO) | [coldiq.com/consulting](https://coldiq.com/consulting) `[FETCHED]` |
| Origin | Affiliate content business about sales tools (Clay, Instantly, Expandi) | [coldiq.com/blog/how-coldiq-grew-...](https://coldiq.com/blog/how-coldiq-grew-from-an-affiliate-side-project-to-a-65m-arr-agency) `[FETCHED]` |
| First retainer | **$3,000/month**, ~1 day of work per week | same |
| ARR trajectory | $6.5M → **$7M+ ARR** | [the-anatomy-of-a-7m-arr-lead-gen-agency](https://coldiq.com/blog/the-anatomy-of-a-7m-arr-lead-gen-agency) `[FETCHED]` |
| Clients | 70+ active B2B clients; **275+ onboarded** all-time; "$50M+ ARR generated" | [coldiq.com](https://coldiq.com/) `[FETCHED]` |
| Team | 20+ people across marketing, sales, delivery | [the-anatomy-of-a-7m-arr-lead-gen-agency](https://coldiq.com/blog/the-anatomy-of-a-7m-arr-lead-gen-agency) `[FETCHED]` |
| Deal size | **"$5,000 to $10,000 per month"** per client | same |
| Sales cycle | **"2-3 Google Meet video calls"** to close | same |
| Consulting rates | Alex Vacca **$700/call**; Michel Lieben **€777/call** | [coldiq.com/consulting](https://coldiq.com/consulting) `[FETCHED]` |

### The founding story, verbatim

The origin is worth encoding because it is the archetypal "audience → service → product" arc, and because the agent will meet clients at every point on it.

> "ColdIQ was never supposed to be an agency" — Michel Lieben
> ([how-coldiq-grew-from-an-affiliate-side-project-to-a-65m-arr-agency](https://coldiq.com/blog/how-coldiq-grew-from-an-affiliate-side-project-to-a-65m-arr-agency)) `[FETCHED]`

They published educational content with affiliate links. Readers didn't click the links — they asked: *"Could you implement this for me?"* One reader made the offer that created the company:

> **"If I pay you 3K per month, will you just run this for me?"**

And the conclusion drawn:

> "The economics of done-for-you services crushed the economics of affiliate content." — Michel Lieben

### Positioning: own a sub-category, not the category

> "instead of positioning as 'the best outbound agency,' you carve out one under-tapped component" — and dominate it. ColdIQ chose **"the most technology-savvy outbound agency."**
> ([coldiq.com/guides/million-dollar-cold-email-agency-2026](https://coldiq.com/guides/million-dollar-cold-email-agency-2026)) `[GATED — steps 3–7 behind email wall]`

**Agent lesson:** when a client asks "how do we differentiate," the agency answer is never "be better." It is "pick an under-tapped component of the category and own it."

### Revenue timeline (from the gated $4M playbook's ungated preface)

| Date | Milestone |
|---|---|
| Jan 2023 | Side project launch |
| Feb 2023 | $7.8K MRR |
| May 2023 | $15.7K MRR (6 clients) |
| Oct 2023 | $30K/month |
| Jul 2024 | $150K MRR |
| Sep 2024 | First $200K month |
| Jan 2025 | $300K/month |

Source: [coldiq.com/guides/four-million-cold-email-agency-playbook](https://coldiq.com/guides/four-million-cold-email-agency-playbook) `[GATED — steps 3–8, SOPs, pricing models, team structure, discovery-call process all behind the email wall]`

They also publish their failures — e.g. "A client who never paid a $4.4K invoice" is listed among the mistakes. **That candour is itself a content strategy** (see §1.3).

---

## 1.2 THE PIVOT — agency → product (most strategically relevant section for Clue)

ColdIQ's homepage today is **not an agency homepage**. It is a developer-product homepage.

> **Headline:** "Build your Revenue Engine Inside Claude Code"
> **Subheadline:** "One API for all your GTM data. 40+ data providers. 700+ endpoints. Search leads, enrich contacts, find emails, track signals - all from your terminal or favourite coding agent."
> ([coldiq.com](https://coldiq.com/)) `[FETCHED]`

Value props, verbatim:
- "Replace hours of workflow design with 1 prompt"
- "40+ providers. One key"
- "Built for the terminal"
- "275+ clients. $50M+ ARR generated"
- **"Not just the best data. The best playbook to use it"**
- "Skip the dashboard. Ship from code"
- "Every data source your GTM team needs. One integration"

Their three-step "how it works":
1. "You describe what you need" (natural language, no filter configuration)
2. "The agent calls the right APIs" (agent selects providers by fit / cost / accuracy)
3. "You get structured, verified data" (ready for CRM / sequencer / script)

**Product pricing** (this is the product, not the retainer):

| Plan | Price | Credits |
|---|---|---|
| Free | $0 | 300 credits on signup (never expire) |
| Starter | $99/mo | 7,000 credits/mo |
| Pro (recommended) | $199/mo | 15,000 credits/mo |
| Scale | $499/mo | 40,000 credits/mo |
| Enterprise | Custom | Custom |

Paid-plan credits roll over 3 months. Source: [coldiq.com](https://coldiq.com/) `[FETCHED]`. (Note: `coldiq.com/pricing` returns 404 — pricing lives on the homepage. `[BLOCKED]`)

### Why they built it — verbatim, and why it matters to Clue

From the launch post ([coldiq.com/blog/were-launching-a-unified-api-for-gtm](https://coldiq.com/blog/were-launching-a-unified-api-for-gtm)) `[FETCHED]`:

> "the best GTM engineers and agencies have already moved off tools and interfaces" — they operate through "GitHub repos, terminals, and APIs instead."

> **"AI agents fail at GTM without context: skills, API keys for 8 to 12 tools, internal SOPs, and past campaign data"**

> "The interface layer that defined B2B software for a decade is quietly becoming optional"

> **"The real shift is replacing the operator who stitches tools together with an API that encodes that knowledge once"**

> "the biggest shift isn't replacing GTM tools. It's replacing the person who stitches them together."

> "the knowledge doesn't disappear. It gets encoded once and runs on demand."

Their example instruction — a single natural-language brief that spans four traditionally separate jobs:

> "Build a list of software CEOs in London, at companies with 25 to 100 people, pick up who's in buying mode, draft 3 angles for messaging, and upload it to my sequencer."

The four jobs it collapses: **People Finder → Intent Signals → Campaign Ideation → Delivery.**

**Direct implication for Clue.** ColdIQ ran a 275-client agency, learned exactly which knowledge is scarce, and then productised *that knowledge*, not the data. Their framing — "not just the best data, the best playbook to use it" — is precisely the claim Clue's Head-of-ABM agent must be able to make and defend. It also names our competitive frontier: ColdIQ is competing on *encoded operator knowledge + provider routing*; Clue competes on *verifiable, provenance-backed research + the argument built on it*. The agent should know the difference and be able to articulate it.

---

## 1.3 The content engine

### 1.3.1 The 11-tool stack behind 80,000 LinkedIn followers
Source: [coldiq.com/blog/the-11-tool-stack-behind-80000-linkedin-followers](https://coldiq.com/blog/the-11-tool-stack-behind-80000-linkedin-followers) `[FETCHED]`

**Grouped by job — this grouping *is* the playbook:**

| Job | Tools | What each does |
|---|---|---|
| **Ideation** | Taplio | Surfaces outperforming posts in the niche; filters by keyword, **60-day recency**, **400+ likes** threshold |
| | Scripe | Aggregates posts by creator to isolate best-performing content per individual |
| **Writing** | Grammarly | Real-time spelling/grammar before publishing |
| | Claude Code | Generates hook variations, recycles content, tests angles; maintains business context |
| | Conductor | UI between Claude Code and Codex; reduces friction in the writing environment |
| **Visuals** | Figma | Graphics with multiple elements readable at phone-thumbnail size |
| | Adobe Suite | Used by designers alongside Figma for control |
| | Canva | Beginner-friendly carousels; starting point before Figma |
| **Video** | Opus Clip | Long-form → short-form automatically |
| | Screen Studio | Mac recorder with auto-zoom on the active screen area, for walkthroughs |
| | Ezgif | Converts silent sub-15s videos to sub-10s GIFs for LinkedIn |
| **Planning** | Notion | Content hub: ideation, drafting, calendar |

**Verbatim principles:**

> "Opening a blank page every morning is the fastest way to burn out on content."

> **"None of these three write the post for me. They remove the parts of writing that do not need my judgment."**

> "Done right, they multiply a post's reach by up to 10X." (on infographics/carousels)

> "Posts I plan almost always outperform posts I think of on the morning of posting."

> **"Content gathers the attention. The warm outreach play is what turns it into revenue."**

**Build order — explicitly stated, and the reasoning is transferable:**

> "If you are building this from zero, the order matters more than the list itself. Start with ideation and a calendar, because publishing consistently is the only variable that compounds. Add visuals once the writing lands reliably. Add video last, when you have enough long-form material to cut from."

**The warm outreach play (3 steps) — this is the conversion mechanism:**

> "To convert our engagement, we filter ICP-fit leads that interacted with our publications, then reach out with individually personalized messages."

1. Pull everyone who liked or commented on a publication
2. Filter that list down to accounts matching ICP (using the **same buying signals as outbound qualification**)
3. Message each one individually, referencing what they engaged with

> "This warm outreach flow converts at **3X the rate** cold outreach does, and it can be built with 3-4 prompts via ColdIQ's MCP."

**And the crucial qualifier — which is exactly the kind of epistemic honesty Clue's agent must reproduce:**

> **"Engagement on its own is a weak signal, since plenty of people like a post without any intention of buying anything."**

Other numbers: 30 minutes/week across Taplio + Scripe generates daily publishing material; several AI-edited Opus Clip videos hit 50K+ views.

### 1.3.2 The content system at scale: 20M impressions/year
Source: [coldiq.com/blog/how-to-generate-20m-linkedin-impressions-a-year](https://coldiq.com/blog/how-to-generate-20m-linkedin-impressions-a-year) `[FETCHED]`

Headline claims: **20M annual impressions, $5M in new ARR** attributed to the content system. Method: treat content "as a system instead of chasing viral moments."

**The 9 steps:**

1. **Identify the ideal buyer** — define the exact target (GTM leaders); *exclude competitors* from audience strategy; focus on converters, not reach.
2. **Identify content spreaders** — write for operators/peers likely to share, not necessarily the buyer. "Operators share up the chain. Peers forward posts to peers." But ensure a cold-landing buyer still grasps relevance.
3. **Review existing content** — own top performers, competitor posts, gaps vs thought leaders.
4. **Build a swipe file** — Taplio + Scripe surface viral posts by keyword/niche. "Adapt the proven post or format...instead of inventing an angle from scratch."
5. **Identify winning formats** — lock "two or three weekly topics"; pair with repeatable formats (carousels, infographics, breakdowns). **"content does not need to be new to perform"** — recycle proven posts.
6. **Alternate funnel stages** — assign every post ONE job before writing: TOF (broad, useful, reach), MOF (show company thinking/capabilities), BOF (clear CTA: reply, booking, signup).
7. **Package with visual design** — preview in the LinkedIn feed before publishing; design earns "dwell time" the algorithm rewards.
8. **Expand to the team** — a single profile caps at ~1 post/day without reach penalty; scale via team distribution. **Result: 581 posts across 24 people in 90 days = $151,000 MRR.**
9. **Connect to pipeline** — **"Reach without a system to convert it is just noise."** Map impressions to booked revenue, not vanity metrics.

Copy rules stated here:
- Content must "earn the scroll-stop" via strong design.
- Every post carries "enough context that a buyer landing on it cold still understands why it matters."
- Topic consistency so readers "recognize our shape in the feed."
- No originality requirement: the audience "turns over constantly," so proven angles re-run successfully.

### 1.3.3 The data-backed hook rules: lessons from 6,750 posts
Source: [coldiq.com/guides/how-to-engineer-a-linkedin-gem](https://coldiq.com/guides/how-to-engineer-a-linkedin-gem) `[FETCHED]`

Dataset: **6,750 LinkedIn posts from 25 top creators** in GTM/sales/AI; **2,089 posts exceeded 500 likes**; baseline "viral rate" (200+ likes) = **28.4%**.

Structural findings:
- **"The median 500+ like post is ~260 words long (a normal post is 179)"**
- 400–500 words nearly doubles engagement odds
- Time investment: 30–45 minutes per post
- Opens with a **number 58%** of the time
- Includes a **single image 71%** of the time
- Uses **zero hashtags 85%** of the time

Viral rate by subject:
| Topic | Viral rate |
|---|---|
| Milestone / revenue | **44.8%** |
| Case-study format | **44.5%** |
| Hiring / team | 37.4% |
| AI / Claude / agents | 35.5% |
| Tactical cold-email content | 30.2% (weakest) |

Strongest CTA type: **comment-to-get (41.3% viral, 378 avg comments)**.

The honest caveat, verbatim:
> **"You stack the odds, the algorithm decides. No format guarantees a gem"**

**Agent lesson:** the two best-performing content categories are *milestone/revenue* and *case study* — i.e. **specific, numeric, verifiable claims about outcomes**. This is a direct argument for Clue's provenance-backed claim model as a content asset, not just a trust asset.

### 1.3.4 Employee advocacy: turning the team into distribution
Sources: [coldiq.com/guides/turn-employees-into-linkedin-influencers](https://coldiq.com/guides/turn-employees-into-linkedin-influencers) `[GATED — steps 3–8 behind email]`; [scripe.io/customers/coldiq-scripe-customer-story](https://scripe.io/customers/coldiq-scripe-customer-story) `[FETCHED]`

**Prerequisites they state:** a team of 5+, a **quarterly prize budget ($1,000 minimum)**, an in-house or freelance designer, leadership already active on LinkedIn.

**Step 1 — Quarterly posting competition.** $1,000 prize for most posts with 20+ likes. Result: 4M+ combined impressions, $80K+ in new MRR. Later iterations scored on engagement + follower growth with deeper prize distribution.

**Step 2 — Reduce friction.** Reuse high-performing posts and proven angles; designer support for visuals so **the team only has to write**; external validation drives organic motivation.

Headline result claimed: **581 posts across 24 team members in 85 days → 34,000 new followers and $151K MRR.**

From the third-party Scripe case study (verbatim, attributed):

> "LinkedIn has been our main lead gen channel since we started." — **Alex Vacca, Co-founder, ColdIQ**

> "It was mainly a time problem and an idea problem." — Alex Vacca

> "The workshops helped people figure out what content pillars." — Alex Vacca

> **"You don't need to reinvent the wheel. Just documenting what happens."** — Alex Vacca

> "Having analytics across the entire team was a game changer." — Alex Vacca

> **"At this point, +80% of our deals are influenced by LinkedIn."** — Alex Vacca

> "We were investing a lot of time into helping each person individually." — **Millie, Personal Brand Manager, ColdIQ**

Numbers from that story: 20–30 team members posting consistently; ~200–250 posts published against a 500+ target; **80% of deals influenced by LinkedIn**; **1,100+ sales meetings booked in 2024** through founder content; ~15 hrs/week saved for the Personal Brand Manager.

### 1.3.5 The personal-brand playbook (ColdIQ × Taplio)
Source: [coldiq.com/blog/the-linkedin-growth-playbook-by-coldiq-x-taplio](https://coldiq.com/blog/the-linkedin-growth-playbook-by-coldiq-x-taplio) `[FETCHED]`

1. **Profile optimisation (one-time).** Banner states ICP + value prop + CTA. Headline leads with **outcome, not job title** — example given: *"Helping B2B teams build pipeline without hiring SDRs."* Featured section: one proof asset + one action item only.
2. **Consistency over quality.** Cadence "three to five times per week." Post #31 went viral after 30 posts produced almost nothing — and converted to $15K/month.
3. **Four repeatable formats:** tool carousels (16K–36K impressions), client-win breakdowns, giveaway posts (300K+ impressions potential), journey/lessons posts (~30K impressions).
4. **Ideation:** 30 min/week in Taplio, keyword-filtering for 300+ like posts, reverse-engineering hooks and structures.
5. **Visuals:** "A well-designed carousel can 3x to 4x the reach."
6. **Strategic commenting:** 10–15 min/day on niche creators; stay active in your own comments for 30 min post-publication. In one experiment, commenting generated more profile views than posting alone.
7. **Calendar:** Sunday 30-min ideation; daily 30–60 min writing + 10–15 min commenting; 30 min engagement management on post day.
8. **Monthly review & repurposing:** recycle top performers 2–3 months later with fresh angles.

Results cited: 65K+ followers, 4M impressions in a quarter, **356 meetings booked**, $80K MRR from LinkedIn alone.

---

## 1.4 The funnel that books 100+ meetings/month
Source: [coldiq.com/blog/the-funnel-that-books-us-100-meetings-every-month](https://coldiq.com/blog/the-funnel-that-books-us-100-meetings-every-month) `[FETCHED]`

Headline metrics: **40,000+ monthly website visitors; 100+ meetings booked monthly; 70% of deals close through sales-led calls; funnel structure unchanged for 3 years.**

Their own summary of it:
> **"Nothing about it is exotic"** — and the structure "has not" changed in three years.

### Stage 1 — Lead generation (traffic sources and their volumes)

| Channel | Monthly visits | Mechanics |
|---|---|---|
| **Search/SEO** | ~12,000 | Standard SEO around buyer questions; **meta pages** (exhaustive resources, tool directories); **programmatic SEO** (thousands of templated pages on low-competition GTM queries); **free GTM mini-tools built with Claude Code** |
| **LinkedIn** | ~10,000 | 10+ team members publishing ~100 posts combined monthly; 120,000+ combined followers; Taplio MCP for post inspiration |
| **Cold outbound** | ~3,000 | Six parallel plays (below) |
| **Paid ads** | ~4,000 | ~$10,000/month budget ([anatomy article](https://coldiq.com/blog/the-anatomy-of-a-7m-arr-lead-gen-agency)) |
| **Other** (newsletter, YouTube, Instagram, webinars) | ~11,000 | YouTube 3,000+ subs (self-described underutilised); monthly webinars at **2,000–4,000 registrants** each, co-hosted with large GTM companies |

**The six outbound plays run in parallel** (this list is directly reusable as an agent's campaign-angle menu):
1. Value-based campaigns with lead magnets
2. Industry-centric campaigns (one vertical at a time)
3. Success-story lookalikes
4. Inbound-led outbound (prior touchpoints)
5. Social re-engagement
6. Signals layering (multiple triggers required to qualify)

Diversification rationale, verbatim:
> **"Losing one channel costs a share of the traffic rather than the whole funnel"**

### Stage 2 — Lead capture (four mechanisms)

1. **Contextual lead magnets** — trigger after "a few minutes of browsing," not on arrival. "Only interrupt after demonstrated interest."
2. **Email sequences** — nurture toward *meetings*, not more content. Run in Customer.io.
3. **Newsletter / e-book CTAs** — for prospects "not ready to talk to anyone yet." beehiiv runs the newsletter.
4. **De-anonymisation** — identify anonymous visitors using LLMs + ColdIQ's MCP, score and segment, re-engage by email or LinkedIn. On that last group: **"That last group is the largest one on any B2B site."**

### Stage 3 — Lead conversion

- **"70% of our deals are sales-led"**; closed on Google Meet, "one or two calls depending on the size of the package."
- **Claap** for call recording and coaching material; **Cobl** generates proposals from call transcripts.
- > **"Reviewing your own calls is the cheapest way to improve close rate"**

### Their own replicability advice (the thing to say to a small client)

Pick **one** generation channel → build the capture layer properly → add channels only after the first channel produces predictable results. "The structure scales; volume requires consistency and team effort."

---

## 1.5 The onboarding system behind 275 outbound clients
Source: [coldiq.com/blog/the-onboarding-system-behind-275-outbound-clients](https://coldiq.com/blog/the-onboarding-system-behind-275-outbound-clients) `[FETCHED]`

**This is the single most directly transferable artefact in the whole corpus** — it is an ABM/outbound engagement kickoff, fully specified, with the reasoning behind each ordering decision. Encode it near-verbatim.

Headline claim: **8 days vs 8 weeks** — the difference between the optimised and traditional onboarding.

### Step 1 — Payment fires the trigger
**When:** immediately on Stripe payment (not contract signature).
> **"Nothing gets built for a client who has not paid, and everything gets built the second they have."**

Why: removes the risk the ops team carries on unfunded deals; the payment event becomes the single source of truth for "is this client live."

### Step 2 — One form, filled once
**Who:** the sales team. **What:** a single new-client form capturing **retainer amount, scope, industry, specific requests**. **Where:** Airtable as the command centre.
> **"Client's information is captured once and then read by every system that needs it"**

Prevents fragmentation across CRM, proposals, and memory.

### Step 3 — The workspace builds itself
**Trigger:** n8n picks up the Airtable record. **Automated outputs:** Slack channel created + client invited; shared Drive folder containing **ICP matrix, copy templates, collateral**; client dashboard created and invite sent via Slack.
> **"Automating the boring provisioning is worth more than automating the interesting work"**

### Step 4 — Email infrastructure ordered on Day One
**When:** the same day as payment. **Provider:** Hypertide (automates provisioning and SPF/DKIM/DMARC).
> **"Warm-up is the longest lead time in the entire onboarding and it is not compressible"**

> **"This one change moved our average time to first send more than any copywriting improvement"**

> "There is no realistic scenario where you need fewer inboxes than the retainer implies"

**This is the most important sequencing lesson in the document.** Start the irreversible clock first; everything else runs parallel to it.

### Step 5 — Onboarding form sent and completed
**When:** day of client signature. **Fallback protocol:** if the form comes back empty or incomplete, the account manager fills it during the call.
> **"Treating the empty form as an expected outcome rather than a client failure is what keeps the timeline intact"**

**Agent lesson:** design for the client who provides nothing. (This maps exactly to Clue's "minimum-input, client-always-has-the-wheel" principle — a client who pastes only a URL must still reach a confirmed ICP and a running job.)

### Step 6 — Kickoff call → structured data
**Recording:** Claap (GTM-focused transcription). **Call activities:** brainstorm campaign angles, ideas, priorities *with* the client. **Automated outputs from the recording:** the **ICP matrix written by AI from the call recap**, a next-steps document, and campaign angles prioritised.

> **"ICP matrix written from the recording reflects what the client said, in their words, instead of what the account manager remembered three days later"**

> "Every downstream decision, the list, the copy, the tiering, inherits that document"

> **"An error introduced at the ICP stage is expensive and hard to detect"**

### Step 7 — TAM mapping BEFORE copy
**Tool:** GetLeads. The sequencing rule:
> **"Writing copy first produces messaging built for a market you have not sized"**

The failure mode they name:
> **"Discovering after launch that the ICP as written contains 400 companies rather than the 40,000 the retainer assumed"**

**How this changes the client conversation** (encode this — it is a *conversational move*, not a tactic): instead of asking the client to approve an abstract ICP definition, you **show them the market size** and let them decide to (a) widen the criteria, (b) tier the list, or (c) accept a smaller target. Secondary output: a Lookalike Finder identifies adjacent companies matching the client's best existing accounts.

### Step 8 — Build, launch, weekly sync
After angle approval and client review of list + copy. Email platforms: **Instantly** (email) and **lemlist** (multichannel). Weekly syncs examine what works and what doesn't; **Claap recordings serve as the documentation of agreement.**

> **"A churn signal in week six is a problem you can solve. The same signal read in week sixteen is a renewal you already lost"**

### The division of labour — quote this one to clients directly

> **"The humans in this process do two things: they run the kickoff call, and they decide which campaign angles are worth building. Everything else is provisioning, and provisioning is what software is for."**

### Timeline & roles summary

| Day | Event |
|---|---|
| Day 0 (payment) | Trigger fires; workspace builds; email infrastructure ordered |
| Day 1 | Client receives onboarding form |
| Pre-launch | Kickoff call → ICP matrix; TAM mapping; copy review |
| Launch | Campaign live |
| Ongoing | Weekly syncs |

Roles: **Sales** fills the new-client form. **n8n** provisions the workspace. **Account manager** runs the kickoff, decides which angles to build, joins weekly syncs. **AI/automation** generates the ICP matrix, next steps, and campaign angles from the call recording.

Tools referenced: Stripe, n8n, Hypertide, Airtable, Claap, GetLeads, Instantly, lemlist.

---

## 1.6 Channel doctrine: tier first, channel second
Source: [coldiq.com/blog/which-outbound-channel-books-more-meetings](https://coldiq.com/blog/which-outbound-channel-books-more-meetings) `[FETCHED]`

The thesis: no channel wins universally; **success depends on account tier, not channel selection.**
> "Ranking them in the abstract falls apart the moment you look at a real target list"

### Tier definitions, verbatim

> **Tier 1:** "the ones you cannot afford to burn. There are a handful of them, the deal size justifies real effort per contact"

> **Tier 2 and Tier 3:** "There are thousands of them, no single one changes your quarter, and the fastest way to learn which message works is to put it in front of enough people to get a signal back"

### Channel capacities

| Channel | Volume ceiling | Audience | Best for | Approach |
|---|---|---|---|---|
| **Cold email** | 500–2,000+/day; **~25 emails/day per mailbox** before spam risk climbs | Thousands | **Tier 2 & 3** | Direct pitch acceptable; test 5–10 variants |
| **LinkedIn DMs** | Safe ceiling ~100 DMs/connection requests **per week** (platform allows ~40 DMs + 25 invites/day, not recommended) | Hundreds | **Tier 1** | Relationship-building; skip the hard ask initially. "Reply rates are high" |
| **Cold calling** | 50–100 dials/day/rep | Rep-time bound | **Tier 1** | "Lowest connect rates" but **"highest conversion to meetings"**; requires direct mobiles |

### How each channel fails — verbatim

> **"LinkedIn fails through restrictions...Cold email fails through the spam folder...Cold calling fails through time."**

More specifically:
- LinkedIn — "Take too many actions in a day...and the platform limits the account."
- Email — "Reusing the same template across too many sends trains filters to recognize it"
- Calling — "The channel is time-heavy by nature, connect rates are low, and scaling it without a dialing setup and direct mobile numbers is close to impossible."

### The matching rule and the close

> **"Tier 1 rewards patience, research, and a channel where a human is visibly on the other end. Tier 2 and Tier 3 reward volume, variant testing, and a channel that scales with infrastructure rather than headcount."**

> **"Run one channel and you are choosing which half of your list to ignore. Run all three against the right tiers and each one covers the ceiling the others cannot reach."**

Conclusion stated: **tier the target list first, assign channels accordingly — don't reverse the process.**

**Agent lesson:** this is a complete, defensible answer to the most common client question ("which channel should we use?"). The correct agent response is to *refuse the framing* and re-ask the tiering question — exactly as ColdIQ does. And note that this doctrine is what makes Clue's two-pass, tier-gated research architecture commercially legible: research depth follows tier, and channel follows tier, so they're the same decision.

---

## 1.7 Multichannel sequencing: 1.8% → 4.3% replies
Source: [coldiq.com/blog/how-multichannel-outreach-took-replies-from-18-to-43](https://coldiq.com/blog/how-multichannel-outreach-took-replies-from-18-to-43) `[FETCHED]`

Result: **1.8% → 4.3% positive reply rate in 2 months.** General benchmark stated: "Multichannel outreach gets two to four times more replies than email alone."

### The exact ordering — and why

> **"The order we run is: view the profile → fire the connection invite → let the message arrive after."**

1. View the LinkedIn profile
2. Send the connection invite
3. Email arrives after — so the prospect has already seen the profile-view notification and the invite before reading the email copy

> **"Resequencing LinkedIn ahead of email was the largest single lift."**

**This is a nearly-free change with the largest effect they measured.** It works because it manufactures familiarity before the ask, using two zero-cost signals.

### Tiering, applied

| Tier | Treatment |
|---|---|
| **Tier 1** | Manual, hand-crafted messaging, multiple touches including phone |
| **Tier 2** | Multichannel, semi-automated (email + LinkedIn sequences) |
| **Tier 3** | Automated, one-to-many, email-first |

> **"Tiering the list was the change that made the Tier 1 effort affordable"**

> "Running one workflow removed the quiet losses nobody measures."

### The copy framework — verbatim

> **"Skip the introduction, because they will look at your profile anyway. Open with the relevance. Give one benefit tied to a KPI they own. Add one proof point, then one simple CTA."**

Decomposed, that is a five-slot message schema:
1. *(no introduction)*
2. Relevance opener
3. One benefit **tied to a KPI they own**
4. One proof point
5. One simple CTA

### Relevance ≠ personalisation (the most quotable distinction in the corpus)

| ❌ Personalisation (ineffective) | ✅ Relevance (effective) |
|---|---|
| "I saw you have a dog" | "As you mentioned [topic]" |

**Agent lesson:** encode this as a hard rule. Personal facts that do not bear on the buying decision are noise (and, per Clue's compliance model, often *unusable* noise). Relevance means the observation is load-bearing for the argument. This is exactly Clue's "appropriateness/use gate" expressed in agency language.

### Buying signals, in priority order

1. New hire in a relevant role
2. Active recruiting (job posting)
3. Profile view
4. Website visitors

### Tools for this play

lemlist (runs all three channels in one workflow), FullEnrich + lemlist (phone enrichment), Hypertide (multi-inbox sending infrastructure), PredictLeads (hiring/job-post signals), Knock2.ai and Warm AI (website-visitor signals), ColdIQ MCP (signal checking via Claude Code).

---

## 1.8 Tech-stack recommendations — the full catalog

ColdIQ's signature content form is the **stack teardown**. They publish (a) their own stack, (b) clients'/peers' stacks, and (c) a directory of individual operators' stacks at [coldiq.com/tech-stacks](https://coldiq.com/tech-stacks) `[FETCHED]` — featuring Michel Lieben, Charles Tenot (lemlist CEO), Eoin Clancy (AirOps), Benjamin Douablin (FullEnrich), Jaspar Carmichael-Jack (Artisan), Kai Brandt (Genesy), Eric Nowoslawski (Growth Engine X), Glenn Miseroy (Expandi).

### 1.8.1 ColdIQ's own stack (30+ tools, by job)
Source: [coldiq.com/blog/every-tool-we-use-to-run-a-400kmonth-outbound-agency](https://coldiq.com/blog/every-tool-we-use-to-run-a-400kmonth-outbound-agency) `[FETCHED]`

**1. Content** (generates 100+ inbound leads/month)
- **Taplio** — team-wide scheduling; manages 41K+ and 170K+ follower accounts
- **Notion** — editorial calendar
- **Kleo** — Chrome extension surfacing top-performing posts from creators
- **OpusClip** — long-form → short clips
- **Canva & Figma** — carousels, infographics, thumbnails

**2. Prospecting data**
- *Targeting:* **LinkedIn Sales Navigator** (campaign starting point — filters by title, seniority, size, geography, job changes, hiring signals); **Evaboot** (clean Sales Nav exports)
- *Email finding:* **Prospeo** (primary; waterfall across providers; Sales Nav integration); **FullEnrich** (aggregates additional email/phone providers, prioritises best mobile provider by geography); **LeadMagic** (verification before sequences)
- *Databases:* **Apollo** (free tier, account-level research); **Ocean.io** (bottom-up categorisation by what companies *do*; lookalikes)

> **"Unverified emails tank your domain reputation fast"**

**3. Email outreach** (900–1,000 emails/day)
- **Instantly** — primary; warmup, inbox rotation, analytics; done-for-you infra with secondary domains and 20+ managed mailboxes
- **lemlist** — multichannel sequences (email, LinkedIn, phone) incl. LinkedIn voice notes
- **HeyReach** — LinkedIn automation, flat pricing regardless of connected profiles

**4. Intent signals**
- **RB2B** — person-level anonymous visitor ID (US only): name, title, company, page visited
- **Clay** — central enrichment hub; pulls from Sales Nav, Prospeo, FullEnrich, LeadMagic; enriches, qualifies, scores
- **Common Room** — aggregates job changes, visits, mentions, news, hiring; Person 360
- **TeamFluence** — tracks LinkedIn profile viewers for timely follow-up

**5. Website & conversion**
- **Default** — auto-enrich, qualify, route inbound form leads instantly
- **beehiiv** — newsletter
- **Customer.io** — behaviour-based follow-up (downloads vs pricing visits trigger different paths)
- **VSL page** — video sales letter for 24/7 qualification

**6. Meetings & sales**
- **Attention** — call recording, transcription, cross-conversation pattern insights
- **Qwilr** — interactive proposals that track which sections prospects read
- **Attio** — CRM, "lightweight, modern"; **replaced HubSpot**; recommended for teams under 100

**7. Operations**
- **n8n** — the glue; routes leads Clay → enrichment → scoring → Instantly/lemlist
- **Airtable** — project tracking, onboarding checklists, campaign status boards
- **Stripe**, **Ramp**, **Slack**

**The architecture philosophy, verbatim:**
> **"Each tool solves one problem. The connections between them create the leverage"**

The stated flow: *Sales Navigator → Evaboot → Prospeo/FullEnrich/LeadMagic → Clay (enrich/score) → Instantly/lemlist → Attio → Attention → Qwilr → Stripe*, with intent signals from RB2B/Common Room/TeamFluence feeding Clay to prioritise, and n8n automating every handoff.

Elsewhere they list the delivery stack as **Airtable, n8n, Slack, Google Suite, Supabase** ([anatomy article](https://coldiq.com/blog/the-anatomy-of-a-7m-arr-lead-gen-agency)) and note that onboarding admin — "Slack invites, onboarding links, and secondary domain configuration" — "happen without anyone touching them."

> **"The key is not any single tool or any single hire. It is how tightly the pieces connect."**

### 1.8.2 The peer teardown: Explorium ($127M funded)
Source: [coldiq.com/blog/every-tool-explorium-uses-to-run-a-127m-funded-company](https://coldiq.com/blog/every-tool-explorium-uses-to-run-a-127m-funded-company) `[FETCHED]`

*Note the content mechanic itself: profile another company's stack, get their distribution, and demonstrate category authority without making a claim about yourself.*

| Function | Tools |
|---|---|
| **Inbound — paid** | Reddit, Google Ads, LinkedIn Ads; **Claude** generates ad creatives |
| **Inbound — GEO** (AI answer-engine optimisation) | Content distributed to G2, **ColdIQ**, Trustpilot, GitHub, LinkedIn, YouTube, Reddit; **Claude Code** scales production; **MCP listings** on Claude, ChatGPT, Perplexity, Manus AI |
| **Influencer/affiliate** | TikTok, Instagram, LinkedIn, X |
| **Cold outreach — intent** | **RB2B** (visitors), **Bombora** (in-market accounts) |
| **Cold outreach — execution** | Explorium (own platform), Vibe Prospecting (chat interface), **lemlist**, Claude Code (orchestration) |
| **Lead capture** | HubSpot forms on WordPress; **AI agent qualification within 90 seconds** post-submission, before a rep is involved |
| **Lead processing** | Explorium (enrich), **n8n**, **Claude agent** (scoring + MQL assignment), Salesforce, **LeanData** (routing), Slack bot (rep notification), account mapping for ABM expansion |
| **Deal closing** | Claude-based inbound agent, lemlist, Calendly, Gong |
| **Delivery** | Stripe, Databricks |
| **BI** | GA4, Mixpanel, PostHog, Datadog, Microsoft Clarity, **Peec AI** (AI search visibility), Claude Code (queries all BI) |

Two lines worth encoding:
> **"Every list they build gets built with the engine they sell, which makes their outbound a live demo of the product."**

> **"No human touches a lead until it is ready. That is the actual output of those engineering hours."**

Three consolidation patterns named: (1) intent precedes volume; (2) engineering complexity concentrates in middle-funnel routing; (3) Claude/Claude Code appears in content, outbound, scoring, closing, and BI.

### 1.8.3 What 2,774 outbound pros actually use
Source: [coldiq.com/blog/outbound-sales-tools-survey](https://coldiq.com/blog/outbound-sales-tools-survey) `[FETCHED]`

Method: Michel Lieben surveyed 2,774 outbound professionals (mostly SDRs/outbound specialists with 2+ years' experience); ~1/3 gave detailed recommendations.

Top 10 by mentions: **Sales Navigator (104), Salesloft (63), Outreach (61), HubSpot (60), Lusha (56), ZoomInfo (43), Salesforce (34), Apollo (31), Cognism (29), lemlist (28).**

**Agent lesson on the content mechanic:** run the survey, publish the ranking, become the reference. It's an authority asset that requires no client results.

### 1.8.4 The API-era catalogs (their new content line)

Since the product pivot, ColdIQ's tool content shifted from SaaS tools to **APIs**, with an explicit evaluation rubric worth copying.

**Account-intelligence APIs** — [coldiq.com/blog/best-account-intelligence-apis](https://coldiq.com/blog/best-account-intelligence-apis) `[FETCHED]`

| Provider | Best for | Pricing |
|---|---|---|
| ColdIQ | Unified access, 40+ providers / 700+ endpoints | $99–$499/mo |
| PredictLeads | Event-driven signals (jobs, news, tech detections, 2015+ history) | Free 100 calls/mo; $0.04/credit → $0.002 at volume |
| Sumble | Internal project + hierarchy mapping; MCP server | Free 500 credits; Pro $99/mo (9,900 credits) |
| Salesmotion | Public-market/filing signals (earnings, SEC, court records) | $85/mo platform; custom API |
| Harmonic | Startup/private-market coverage (35M companies, 195M people) | Custom |
| Ocean.io | Lookalike discovery | ~$99/mo; 1 credit = email, 10 = phone, 0.2 = search result |
| The Companies API | High-throughput domain enrichment (50M companies, 1,000 req/s) | $95–$595/mo |
| Diffbot | Custom knowledge graph, NL query, entity relationships | Free 10K credits/mo; $299–$899/mo |
| HubSpot Data Hub | HubSpot-native enrichment | Free tier; Starter $10/seat; Pro $800+/mo |
| 6sense | Enterprise predictive ABM | Custom, quote-only |
| Demandbase | Coordinated sales-marketing ABM | Custom |

**Their four screening criteria** (a good rubric for Clue's own resolver evaluation):
1. **Programmatic requirement** — real API access, not a dashboard with CSV export
2. **Pricing transparency** — vendor-published figures only; unpublished rates disclosed as such
3. **Account-shaped data** — company-level records as primary, not contact-incidental
4. **Current verification** — live-site confirmation (July 2026), not category reputation

**Their signal classification — encode this directly:**

| Predictive signals (budget-correlated) | Weak / commoditised signals |
|---|---|
| Hiring velocity and role openings | Generic web-visit counts without account resolution |
| Funding events | Shared cooperative intent topics visible to all competitors |
| Technology stack changes | Raw firmographic attributes without change events |
| Executive moves | |

**Their recommended onboarding sequence for any new data source:**
1. Test the free tier (validates the signal exists)
2. **Backtest against closed-won deals** (quantifies correlation)
3. Deploy a single workflow (validates causation)
4. Expand only post-validation

And the boundary statement:
> Account intelligence identifies *which* account to pursue and *why* — it does **not** provide contact details. That handoff to contact-data providers should occur **post-signal qualification**, to avoid wasting per-contact credits on out-of-market accounts.

**B2B data APIs** — [coldiq.com/blog/best-b2b-data-apis](https://coldiq.com/blog/best-b2b-data-apis) `[FETCHED]`

Four categories they define: **contact data / company data / signals / aggregation layers.** "Most teams need at least two of the four, which is where cost and integration burden actually come from."

Selection by use case (verbatim mapping): product building → People Data Labs; bulk enrichment → Bright Data ("undercuts per-record by ~100x"); growth-trajectory targeting → Coresignal or Crustdata; prospecting + outreach combined → Apollo; long-tail/non-US → Diffbot; European enterprise → Cognism; multiple data types → ColdIQ or Clay.

Waterfall guidance: "stop relying on a single database and combine sources instead"; **max ~3 vendors before an aggregation layer becomes cost-justified.**

Critical evaluation criteria: test on your own segment (200 accounts through free tiers); check the **charge-on-failure model** (most modern providers charge only on success; Seamless.AI charges even on misses); per-tier cost drops can be **39-fold** between cheapest and dearest; track compliance/deletion/processing-location documentation.

---

## 1.9 The 8 layers of B2B data — the taxonomy to steal
Source: [coldiq.com/blog/the-8-layers-of-b2b-data](https://coldiq.com/blog/the-8-layers-of-b2b-data) `[FETCHED]`

This maps almost perfectly onto Clue's trust-tiered source waterfall and field registry. Encode as the agent's mental model of data supply.

**Layer 1 — TAM mapping.** Providers: Apollo.io, AI Ark, DiscoLike.
> "This is where your list starts. TAM mapping answers the questions that decide whether a campaign is worth running: who exists in your category, how big the market is, and how many people you can expect to reach."

> **"We size the market at this layer before writing a single email. If the addressable list comes back too small, the campaign dies here instead of wasting a month of sending."**

Note the nuance: AI Ark and DiscoLike "extend coverage into segments where standard industry filters fall short, surfacing companies **by what they do rather than by the label a database assigned them**."

**Layer 2 — Lookalikes.** Provider: CompanyEnrich.
> **"your closed-won customers encode your real ICP better than any filter combination. Similarity expansion from a seed set of proven accounts surfaces fits that an industry-and-headcount filter would never find."**

**Layer 3 — Local (SMB).** Provider: Openmart.
> "Mainstream databases go thin below mid-market. Restaurants, clinics, contractors, gyms, local agencies: the businesses that dominate SMB selling barely register in the standard B2B databases." — "If you sell to SMBs, this is the layer everyone else skips, which makes it an advantage for the teams that use it."

**Layer 4 — People enrichment.** Providers: FullEnrich, Prospeo, BlitzAPI.
> "Company data tells you who to target. This layer tells you how to reach them."

> **"no single source has complete coverage, and single-source contact data leaves a large share of your list unreachable. Running a waterfall across FullEnrich, Prospeo, and BlitzAPI means one provider's miss becomes the next provider's catch."**

**Layer 5 — Signals.** Providers: PredictLeads, TheirStack.
> "Funding rounds, hiring spikes, leadership changes. This layer marks the shift from 'find leads' to 'find leads showing intent right now.'"

> "A company that just raised, just hired a new VP of Sales, or just posted five SDR openings has budget and urgency that a static list can never show you."

**Layer 6 — Technographic.** Providers: BuiltWith, TheirStack, Sumble. The *sourcing difference* is the insight:
> "BuiltWith scans the company's website, which reveals tracking pixels, scripts, and the platforms behind the site itself. TheirStack reads job postings, where engineers routinely name the databases, frameworks, and internal tools the company runs, surfacing technology that never appears on the website. Sumble rounds out coverage across additional sources."

> **"Knowing a company's stack changes the message you send. A team running your competitor's product gets a different email than a team running nothing at all."**

**Layer 7 — Discovery (live web).** Providers: Exa, Limadata, Serper.
> "When the company is too new or too niche to be in any database yet, you search the live web at scale instead." — "databases only contain what has already been indexed."

**Layer 8 — Orchestration.** Provider: ColdIQ API Marketplace (40+ providers).
> "Waterfall across every layer instead of betting on a single provider. Swap providers without touching your code. Stop maintaining eight separate integrations, keys, and billing relationships."

**Clue relevance:** Layers 1–7 are resolver classes; Layer 8 is Clue's `Resolver` protocol + registry. The commercially important line is Layer 1's — *size the market before writing anything* — because it converts an architecture decision into a client-facing conversation.

---

## 1.10 Copywriting principles — verbatim
Primary source: [coldiq.com/cold-email-guide](https://coldiq.com/cold-email-guide) `[FETCHED]`

### Length and format
> "Write messages as short as possible."
> "Avoid adding links, images, and documents."
> "Individually personalize emails for your recipients, so each email is different."
> "Always include spintax in your email."

### Sequence structure
> "Include several touchpoints, and follow-up at least 2-3 times minimum."
> "Reach out across several platforms using various formats."

### Targeting and personalisation
> "You want to identify people and companies struggling with a problem you can solve"
> Use "trigger events (such as the fact that they are hiring) or publicly available information"
> **"The goal is for each of your outreach messages to be unique. You want your recipient to think there is no way this was for someone else."**

### On AI — the most important rule for an AI product to internalise
> **"We don't trust GPT to write our emails for us. Most people can tell when something is written by AI"**

Their prescription: incorporate "AI into small snippets inside of an email" rather than full AI generation.

**Agent lesson (uncomfortable but essential):** the leading practitioners in this space do **not** believe in LLM-generated outreach copy at the message level. They believe in LLM-generated *research*, *segmentation*, *angles*, and *variable snippets*. That is precisely the boundary Clue's architecture already draws (research/claims/narrative owned here; content owned downstream). Clue's agent should sell **the argument**, not the prose — and should say so plainly, because saying so is a *credibility signal* to a sophisticated buyer.

### Deliverability rules
> "Never track open rates, this will impact your deliverability"
> "Send 30 emails a day maximum per domain, but stay slightly under"
> "Avoid using your main domain for outreach"

(Note the internal tension with the channel article's "~25 emails/day per mailbox" — 25–30/day/mailbox is the operating band. Also note: "avoid your main domain" and "never track opens" are load-bearing infrastructure rules, not stylistic preferences.)

### The annotated example structure
The guide shows one annotated email whose labelled parts are: **trigger-event observation → social proof (naming successful firms) → value offering (a 5-step guide) → personalisation (referencing LinkedIn specialisation)**. The full verbatim body is rendered as an image and was not extractable. `[SNIPPET — example body is an image]`

### The five-slot message schema (from the multichannel article, restated)
> "Skip the introduction, because they will look at your profile anyway. Open with the relevance. Give one benefit tied to a KPI they own. Add one proof point, then one simple CTA."

### Consolidated copy rule set for the agent

| # | Rule | Source |
|---|---|---|
| 1 | No introduction — they'll check your profile | multichannel article |
| 2 | Open with **relevance**, not personalisation | multichannel article |
| 3 | One benefit, **tied to a KPI the recipient owns** | multichannel article |
| 4 | One proof point | multichannel article |
| 5 | One simple CTA | multichannel article |
| 6 | As short as possible | cold-email guide |
| 7 | No links, images, or attachments | cold-email guide |
| 8 | Spintax always | cold-email guide |
| 9 | 2–3 follow-ups minimum, multiple channels/formats | cold-email guide |
| 10 | Anchor on a **trigger event**, not a demographic | cold-email guide |
| 11 | The reader must think "there is no way this was for someone else" | cold-email guide |
| 12 | AI writes snippets, not messages | cold-email guide |
| 13 | Never track opens; ≤25–30/day/mailbox; never the main domain | both |

---

## 1.11 How they run client engagements

### 1.11.1 The engagement shape

- **Trigger:** payment, not signature (§1.5).
- **Kickoff:** one recorded call, whose output is a **client-worded ICP matrix** that every downstream artefact inherits.
- **Pre-launch gate:** TAM mapping, with an explicit *choice* offered to the client (widen / tier / accept smaller).
- **Approval gates:** angles approved, then list + copy reviewed by the client, then launch.
- **Cadence:** weekly syncs, recorded, "recordings serve as agreement documentation."
- **Retention watch:** "A churn signal in week six is a problem you can solve. The same signal read in week sixteen is a renewal you already lost."
- **Commercials:** $5K–$10K/mo; closed in 2–3 Google Meet calls; proposals generated from call transcripts (Cobl) and tracked for section-level engagement (Qwilr).

### 1.11.2 Case-study anatomy (the structural template)

Every ColdIQ case study follows the same six-part shape. This is the report format an AI Head of ABM should produce:

1. **Company card** — name, employee count, location, sector, one-line description, notable logos they serve.
2. **Challenge** — 3–4 *named, enumerated* obstacles, ideally with a client quote stating the pain in the client's own words.
3. **Solution** — a numbered phase list (3–5 phases), each naming the tools used.
4. **Tools & platforms** — an explicit list.
5. **Results** — a table of hard numbers with a timeline.
6. **Key takeaways / lessons** — 3–4 generalised principles.

**Worked examples:**

| Case | Challenge framing | Solution phases | Headline results | Timeline |
|---|---|---|---|---|
| **AirOps** [FETCHED](https://coldiq.com/case-studies/airops) | PMF achieved but pipeline plateaued at **$536K/month for nearly a year** | (1) TAM→TAL with fit + intent, tiered 1–4; (2) CRM architecture in HubSpot mapping awareness→consideration→conversion; (3) demand gen: LinkedIn Ads **80% thought-leader / 20% BOFU** + outbound; (4) signal stack: Trigify + Clay for engagement, Fibbler + HubSpot for ad signals | **$7,831,160** qualified pipeline; **$1,518,758** closed-won; 164 deals created; 30 closed-won; 7,057 emails → 1,058 replies; best play = webinar "input request" (112 positive replies); LinkedIn Ads **15.21x pipeline ROI / 3.55x revenue ROI** on $233.8K spend | Dec '24 → Oct '25 (10 months) |
| **Aircall** [FETCHED](https://coldiq.com/case-studies/aircall) | Manual/fragmented regional lists; poor CRM hygiene; **no unified TAM or ICP tiers**; juggling ZoomInfo, Apollo, Salesforce, HubSpot, Lusha, Cognism | (1) **Foundation — "define before automating"**: a *field dictionary*, TAM built in a sandbox, governance + naming conventions; (2) **Structure**: Clay orchestration, 20+ enrichment fields synced to Salesforce, tiered ICP + territory segmentation, controlled update rules; (3) **Adoption**: pair-edit sessions with regional teams, weekly office hours, SOPs embedded in Clay, RevOps self-service refresh | **3,655+** accounts created & enriched; 20+ fields/record; self-refreshing TAM; RevOps enrichment cycle **weeks → hours** | 6 months (M1–2 foundation, M3–4 structure, M5–6 adoption) |
| **Playbook** [FETCHED](https://coldiq.com/case-studies/playbook) | No outbound motion; reliant on inbound/referrals; lean team; expanding into South African MedTech/Pharma/Biotech | (1) stack: WebScraper + ScrapeStorm → Clay → Instantly; (2) native-language messaging on compliance bottlenecks; (3) fast launch, iterative copy tests, **weekly leadership check-ins**; (4) 9 months of training the client's team to run it | **20 opportunities in first 20 days**; 300+ positive replies | Nov launch; 9-month training tail |
| **Teikametrics** [FETCHED](https://coldiq.com/case-studies/teikametrics) | ACV rising, reps closing well, but "we needed more pipeline… the old-school BDR model wasn't scalable in 2024" | (1) stack optimisation (Smartlead + Sales Nav + Clay + Smartscout API, HubSpot as anchor); (2) ICP refinement via custom Smartscout reports; (3) automated pain-point campaigns (ad overspend, stockouts); (4) **weekly performance reviews** adjusting subject lines, messaging, data filters | **$300K+** new pipeline; **100+ hours/month** saved; zero manual list-building | 9 months |
| **Palico** [FETCHED](https://coldiq.com/case-studies/palico) | Manual research + one-by-one emails; main-domain deliverability risk; <20 employees | Five layers: (1) infrastructure/deliverability via dedicated domains; (2) data collection/enrichment (WebScraper, ScrapeStorm, Crunchbase); (3) personalisation via Clay dynamic fields; (4) sequencing in Smartlead with A/B; (5) **weekly reports flagging high performers and suggesting angles** | **6–15 positive replies weekly**; daily leads; 3 clients closed from early replies | From week 2 onward |
| **Hemlane** [FETCHED](https://coldiq.com/case-studies/hemlane) | B2C-ish audience; internally-sourced contacts "weren't really becoming very fruitful"; below-benchmark open/reply/bounce | (1) ICP sharpened from "landlord" to **owners with active Zillow listings**; (2) Clay + Smartlead; (3) spintax variation + natural follow-up sequencing | **830 qualified leads**; **5.5%** reply rate; **0.5%** bounce; **70%** time saved | Nov '23–Apr '24, then Aug '24 onward |

**Client quotes to model tone on:**

> "Our sales reps did an awesome job at closing deals. Our ACV was going up. But the challenge was we needed more pipeline. Marketing returns were diminishing, and I knew the old-school BDR model wasn't scalable in 2024." — **Ben Ray, CRO, Teikametrics**

> **"Literally a week after we turned on our first major campaign, we got a hit from someone using a competitor....and we won the deal in a week. That single deal paid for the whole program."** — Ben Ray, Teikametrics

> "Everyone is doing outbound these days, right? The main problem that we kept running into is how to stand out in someone's inbox." — **Paloma Hernandez, Head of Sales, Palico**

> **"It's almost like expanding the sales team and having an extra resource in-house."** — Paloma Hernandez, Palico

> "Working with ColdIQ was great... They're really true partners, and they provided a lot of insights into how we could grow. **Always felt like we had a clear understanding of what was going on.**" — **Jesse Litwin, Sales Outreach Consultant, Hemlane**

> "The ColdIQ team is everything you'd want in a consulting partner—true experts with both strategic insight and hands-on execution." — **Dr. Nikolai Wessendorf, CEO, Playbook**

**Note what clients actually praise:** not creativity — **visibility** ("always felt like we had a clear understanding of what was going on") and **capacity** ("like expanding the sales team"). Those are the two emotional promises an AI Head of ABM must deliver, and both are *reporting* problems as much as execution problems.

**Note also the Aircall lesson**, which is the most ABM-mature statement in ColdIQ's corpus:
> **"ownership and governance drive adoption more than features ever will."**
> Plus: define the field dictionary early; sandbox → QA → production; respect regional legal/linguistic/naming nuance; maintain human ownership throughout.

### 1.11.3 Homepage social proof, as one-liners
From [coldiq.com](https://coldiq.com/) `[FETCHED]` — note the *format*: outcome + magnitude + time-box, always.
- Aircall — "3,600+ new accounts enriched in just 6 months"
- Airops — "$10.1M in pipeline & revenue"
- Teikametrics — "$300K+ pipeline in 9 months"
- Design Pickle — "From ~10 demos per week to 58 in 14 days"
- Palico — "6–15 positive replies every single week"
- Hemlane — "830 qualified leads with just 0.5% bounce"
- Playbook — "0 → 20 opportunities in 20 days"
- Keragon — "2 new partnership conversations every day"

---

## 1.12 What ColdIQ teaches an AI Head of ABM — distilled

| Principle | Why it transfers to an agent |
|---|---|
| **Size the market before writing anything** | A hard, checkable gate the agent can enforce, with a client conversation attached ("widen / tier / accept smaller") |
| **Start the irreversible clock first** (inbox warm-up) | Sequencing rule generalises: identify the longest non-compressible lead time and start it at t=0 |
| **Tier before choosing channels** | Converts an unanswerable question into an answerable one |
| **Profile view → invite → email** | Highest-ROI change they measured; cheap; fully automatable |
| **Relevance ≠ personalisation** | Gives the agent a rejection criterion for weak "personal" facts (and aligns with Clue's use-gate) |
| **Engagement alone is a weak signal** | Teaches the agent to qualify signals rather than celebrate them |
| **The empty client form is expected, not a failure** | Design for minimum input; never block on client diligence |
| **ICP matrix in the client's own words, captured from the recording** | Reduces the highest-cost error class ("expensive and hard to detect") |
| **Humans do two things: kickoff + angle selection** | A clean, honest autonomy boundary to offer clients |
| **Weekly sync, recorded, as the agreement record** | Reporting cadence + auditability; maps to Clue's provenance ethos |
| **Churn signals read at week six, not week sixteen** | Leading-indicator discipline |
| **AI writes snippets, not messages** | The credibility-preserving boundary for an AI product |
| **Publish the stack, publish the survey, publish the failures** | Authority is manufactured through specificity, not adjectives |

---

# PART 2 — The wider agency landscape

Selected for instructiveness, not size. Each entry: what they sell, published playbooks (URLs), signature methodology, and what an AI Head of ABM should imitate vs. leave to humans.

---

## 2.1 Fullfunnel.io — Andrei Zinkevich & Vladimir Blagojević
**The most rigorous published ABM methodology in the corpus. If the agent internalises one strategy framework, make it this one.**

**What they sell.** An agency + education hybrid: consulting/implementation plus on-demand courses. The ABM Playbook 2.0 course is **$997 individual / $7,497 team (50 seats)**, lifetime access, and includes **5 orchestrated ready-to-use playbooks** and **17 templates** (ICP, revenue analysis, intent-data tracking, account warm-up cadence, customer research, account scoring & prioritisation, ABM budget planning & forecasting, account planning, reports, personalised offers). Twelve modules span goal decomposition → ICP & account list building → ABM team formation → warm-up and activation playbooks → reporting → scaling → building a cohesive ABM + demand-gen function.
[fullfunnel.io/account-based-marketing-playbook](https://fullfunnel.io/account-based-marketing-playbook/) `[FETCHED]`

Their positioning copy: "Practical playbooks" avoiding theoretical models, "Ready-to-use templates," "Short explanation videos and how to examples," "Real examples of ABM campaigns" including "behind the scenes" of campaigns generating "+$50M in revenue." Background: 30 combined years, 100+ B2B companies since 2013.

### Signature methodology 1 — the 6A framework
[fullfunnel.substack.com/p/abm-strategy-30](https://fullfunnel.substack.com/p/abm-strategy-30) `[FETCHED]`

1. **Account Qualification** — criteria beyond firmographics: product-need signals and buying-committee details.
2. **Account Segmentation / Prioritisation** — three **dynamic** lists (below).
3. **Account Research** — map the buying committee and uncover strategic initiatives *before* outreach.
4. **Account Awareness** — targeted activities for visibility among the buying committee.
5. **Account Development** — continuous, meaningful **non-sales** touchpoints, mixing time-based and signal-based playbooks.
6. **Account Activation** — co-create personalised solutions; "bridge activities" that generate discovery calls.

### Signature methodology 2 — three dynamic account lists
| List | Definition |
|---|---|
| **Cluster ICP** | Cold but fit — meets qualification criteria, vendor-unaware |
| **Future Pipeline** | Engaged but product need unknown |
| **Active Focus** | High intent, strong signals |

Accounts *move between lists* on a weekly review. **This is the single most implementable ABM state machine in the corpus** and maps directly onto Clue's tiering + project-run phases.

### Signature methodology 3 — clusters, not verticals
The 2.0 → 3.0 shift: from vertical/industry/tier targeting to **cluster-based targeting** — grouping accounts that share identical strategic challenges and use cases, so one message serves new-logo, acceleration, and expansion accounts simultaneously.

**Cluster decomposition questions (use these verbatim as agent research prompts):**
- What are the primary challenges?
- Why do these challenges exist?
- What alternatives are being considered?
- What is the current status quo?
- What misconceptions exist about solutions?
- What resources would buyers appreciate?
- Which industry trends influence decisions?

### The other five pillars of ABM 3.0
4. **Playbooks for long sales cycles** — enterprise deals require "more than 400 touch points"; combine *time-based* (planned quarterly: roundtables, research, personalised outreach) with *signal-based* (reactive, trigger-driven) plays. Eight principles: optimise for sales-cycle length; multithread the committee; create constant touchpoint flow; align to buyer-journey stage; build playbooks compoundingly; co-create with sales; include clear steps; define metrics.
5. **Center of Excellence** — an **80/20 model**: 80% operationalisation, documentation, scaling, training; 20% innovation/experimentation. The COE "acts as coach rather than dictator."
6. **AI-enabled, not AI-created** — **80% of the legwork** (data collection, signal capture) to AI; **20% strategic insight and relationship building** to humans. Four rules: (a) establish quality standards and "what good looks like" *before* automating; (b) **develop detailed SOPs as the foundation for AI prompts**; (c) define what to automate (repetitive, data-heavy) vs keep human (strategic prioritisation, relationships); (d) create a **centralised vault library** of playbooks, benchmarks, prompts, templates, training.
7. **Holistic full-funnel measurement** — six leadership reports: revenue by program & tier; pipeline progress; program performance; sales engagement metrics; account engagement; account development progress.
8. **Operational rhythm** — **quarterly planning** (1–3 strategic levers, cluster + account selection, always-on sync), **quarterly retrospective** (operationalise / scale / refine / stop), **weekly planning & review** (account insights, 1:1 account planning, leading indicators, bottlenecks, pipeline), **daily 10–15 min standups**.

> **Pillar 6 is the most important paragraph in this entire document for Clue.** It is a leading ABM practice already articulating the exact division of labour Clue's product embodies — and it says the prerequisite for automation is a written SOP and a definition of "what good looks like." Clue's field registry, policy-as-data, and claim schema *are* that SOP made executable. The agent should say this out loud in client conversations.

### The published pilot — the benchmark to quote
[fullfunnel.substack.com/p/our-abm-program-breakdown-case-study](https://fullfunnel.substack.com/p/our-abm-program-breakdown-case-study) `[FETCHED]`

| Dimension | Value |
|---|---|
| Duration | **90 days** |
| Accounts | **46** |
| Team | **3 people** — Andrei (ABM lead / marketing), Vladimir (sales), Dagmara (PM / RevOps / tech). "Nobody else was involved. No other freelancers or agencies." |
| Tooling cost | **Under $1,000/month** — Leadfeeder, Apify, FullEnrich, Aligned, Goldcast, Encharge, Attio, Granola, Claude |
| **Engagement rate** | **43%** (accounts hitting the engagement threshold) |
| **Account-to-pipeline ratio** | **8.7%** |
| Opportunities | **3** |
| Closed-won | **1** — "the biggest project ever" |

> **"There is a misbelief that you need to have a big team, a big budget, and an expensive technology stack to launch the program."**

Qualification criteria used: firmographics (headcount, team size), product-need signals, **disqualification criteria / red flags**, buying-committee mapping (champions, decision-makers, influencers, blockers), distributed GTM teams as a priority indicator, regional presence (**>4 regions = higher revenue potential**), marketing/sales team size.

Cluster chosen: **B2B CMOs managing long sales cycles.** Narrative: *"Survive as a B2B CMO in the AI era and generate enterprise pipeline."*

Four parallel playbook types: **1:1** (individual account plans); **always-on** (account research, content distribution, content publishing, use-case air cover, sales-rep thought leadership); **time-based** (webinars, field events, market research); **signal-based** (track signals, engage reactively but *not* immediately promotionally, re-ignite threads value-first).

Account-plan components: point of view and narrative; messaging and content strategy; status-quo challenge; why the solution is a relevant fit; specific buyer playbooks (weekly activities, events, signal-based actions); defined roles for sales and marketing.

The problem the account plan solves, verbatim:
> **"Sales is not aware of all the marketing touch points and what they mean. Marketing doesn't get the sales insights."**

Activation tactics worth noting for the "what only humans can do" column: personalised content hubs containing an **ABM program prototype built without ever speaking to the account**; direct mail (specialty coffee from a private roaster to a prospect identified as a coffee lover via Instagram) bundled with a printed research report, delivered by DHL; personalised video clips answering specific questions; free strategy sessions.

### Their critique of conventional ABM
[fullfunnel.substack.com/p/killing-abm](https://fullfunnel.substack.com/p/killing-abm) `[FETCHED]`

Poll finding cited: **98.5% dissatisfied**, 49% "frustrated." Six "dark truths": ABM as rebranded lead gen (1:many + programmatic ads); technology-first thinking; generic vendor content that "mysterifies" the discipline; widespread failure; the **obsolete 1:1/1:few/1:many tiering theory**; and ABM siloed from demand gen.

**Old vs New, seven pillars:**

| Pillar | Old ABM | New ABM |
|---|---|---|
| Goals | "We need more leads" | High-probability new logos; pipeline acceleration; expansion; churn prevention |
| ICP | Broad firmographics + job titles | Specific firmo/technographics, qualification criteria, tier segmentation, detailed buying committees, account enrichment |
| List building | Sales wish lists + databases | **First-party intent + engagement data** aligned with ICP |
| Personalisation | Vertical/role messaging via programmatic | In-depth account research; buyer-journey alignment; personalisation tied to research |
| Warm-up | Programmatic display + "21-touch" outbound | Multithreaded committee engagement; 1:few/1:1 events; content co-creation |
| M&S playbooks | Lead handoff on click/download | Joint GTM alignment, unified playbooks, joint reporting and reviews |
| Metrics | Lead volume | Revenue by motion; pipeline velocity; ACV, win rate, cycle length; leading indicators |

**Eleven fatal mistakes** (a superb pre-flight checklist for the agent to run against any proposed program):
1. Targeting thousands of accounts — "spray and pray," not ABM
2. Expensive stacks on pilot programs — **"Software ≠ ABM"**
3. Targeting wish lists — Fortune 500 logos without demonstrated buying signals
4. Missing sales alignment — ABM requires "coordinated actions of marketing and sales"
5. No qualification criteria — no patterns extracted from lost deals
6. **Cold account targeting** — start with "aware" accounts showing "product-need / buying signals"
7. Insufficient account research — the committee cares about "jobs-to-be-done," hitting targets, and strategic alignment, **not product features**
8. Decision-maker-only targeting — C-suite ignores bulk cold outreach; gatekeepers block calls
9. No human engagement — "Programmatic display ads and automated outbound" cannot warm anyone up; requires "meaningful engagement," "content co-creation," "1-1 conversations"
10. Missing leading indicators — programs get killed prematurely without early signals
11. **Choosing new pipeline for the pilot** — proof-of-concept succeeds faster with "pipeline acceleration and expansion programs with accounts that are already aware"

Their conclusion, which the agent should be honest enough to repeat:
> **"It requires a lot of manual work. But this is the only way to generate enterprise, 6-7 figure deals."**

### Their full-funnel framework (the parent model)
[fullfunnel.substack.com/p/full-funnel-marketing-fundamentals](https://fullfunnel.substack.com/p/full-funnel-marketing-fundamentals) `[FETCHED]`

Four stages: TOF ("Create consistent presence on the channels where buyers learn" / "Speak about their jobs-to-be-done, challenges and needs") → MOF (account-based engagement: engagement signals, progressive profiling, multithreading) → BOF (buyer-enablement content, personalised solutions, bridge activities) → post-sale (success, expansion, advocacy).

Six pillars: strong GTM fundamentals (audit of goals, skills, stack, ICP, processes); cross-functional teams (**minimal viable team = 1 marketing manager + 1 SDR + 1 content marketer + 1 SME**, shared KPIs and accounts); influencing the entire buyer journey ("Enterprise buyers take **9-24 months** from problem awareness to vendor selection"); holistic measurement; the **POS framework (Pilot → Operationalize → Scale)**; and an **80/10/10 portfolio** (80% always-on, 10% short-term ROI, 10% experiments).

Their six-stage measurement ladder — **use this as the agent's reporting spine:**

| Stage | Description | Primary indicator |
|---|---|---|
| Revenue | New, expansion, renewals | Pipeline velocity |
| Opportunities | Pre-pipeline accounts | Discovery calls booked |
| Active Focus | High conversion likelihood | Pipeline value co-created |
| Future Pipeline | Above engagement threshold | Account insights collected |
| Cluster ICP | Cold, fit accounts | Light engagement tracked |
| Brand | Awareness building | Mentions, traffic, speaking invites |

Cited pilot: **BenchPrep's 3-person pilot** → "40% of accounts moved from vendor-unaware to vendor-aware" and "3 qualified enterprise opportunities."

**Imitate:** the 6A loop, three dynamic lists, cluster decomposition questions, 11-mistake pre-flight check, the measurement ladder, the POS sequence, the 80/10/10 portfolio.
**Leave to humans:** content co-creation with executives, 1:1 events, direct mail with genuine personal insight, the free strategy session.

---

## 2.2 strategicabm — Declan Mulkeen
[strategicabm.com](https://insights.strategicabm.com) `[FETCHED — insights/resources subdomains]`

**What they sell.** Full-service ABM for enterprise B2B, structured as one-to-one (Tier 1), one-to-few (Tier 2, typically **15–20 account clusters**), one-to-many (Tier 3). They run *Let's talk ABM*, the leading ABM podcast — a content asset that doubles as an account-based podcasting play (see Mason Cosby, §2.4).
[insights.strategicabm.com/account-based-marketing-playbook](https://insights.strategicabm.com/account-based-marketing-playbook) `[FETCHED]`

**Signature move — outcome-first, not format-first.** Declan Mulkeen's observation: customers never ask for "one-to-one" or "one-to-many" programs; they bring **business problems**. So strategicabm moved from rigid frameworks to **outcome-based playbooks** — define the outcome first, work backwards to the strategy. The four outcomes named: win new strategic accounts; cross-sell/upsell within existing customers; defend accounts against competitors; build long-term advocacy and lifetime value. `[SNIPPET — via search summary of the Demandbase podcast + strategicabm insights]` ([demandbase.com/resources/podcast/modern-abm-outcomes-ai-buying-groups](https://www.demandbase.com/resources/podcast/modern-abm-outcomes-ai-buying-groups/))

**Their tactic-selection rule** — tactics depend on exactly three criteria (Mulkeen):
1. ABM objectives (win / nurture / grow / perception change)
2. Program type (one-to-many / one-to-few / one-to-one)
3. Buyer-journey stage (TOFU / MOFU / BOFU)

TOFU tactics (Alex Olley): display advertising with "reverse IP engineering"; remarketing; LinkedIn ads; social selling. MOFU (Mulkeen): personalised industry-relevant content on specific pain points; case studies "relatable to your Target Accounts"; SDR/BDR sequences; InMails, conversational messaging, one-to-one video, voicemails. Plus **direct mail/gifting** to "make a physical impression" — virtual wine tastings, e-gifting for lunch-and-learns, coordinated "unity campaigns" engaging multiple executives.

The line to encode as an agent temperament setting:
> **"Not everyone is ready to buy and that's okay. You're just looking to find those accounts and those individuals within those accounts that are looking to have a conversation."**

### Building an ABM program from scratch — their 7 tips
[insights.strategicabm.com/lets-talk-abm-building-abm-program-from-scratch](https://insights.strategicabm.com/lets-talk-abm-building-abm-program-from-scratch) `[FETCHED]`

1. **Cultivate executive buy-in** — start with a high-performing pilot rather than launching broadly.
2. **Data-backed account selection** — intent data + third-party + first-party; **prioritise relevance over brand size**.
3. **Go deep on insights and research** — beyond basic LinkedIn info, into decision-makers' challenges and priorities.
4. **Build a messaging framework** — with AEs and Sales; address business challenges, not brand.
5. **Create account playbooks for Sales.**
6. **Use MarTech to automate** (6sense, Cyance, Cognism) — but only with the expertise to use it.
7. **Create a Center of Excellence.**

Verbatim, **Becks Powell (Showpad)**:
> "You must have executive buy-in...it gets the whole business on the same page of doing ABM"
> **"I think most of the time is spent in developing what accounts we're going to target and then the research on those accounts."**
> "You have to have the people and the resource who know how to use MarTech properly."

**That middle quote is the commercial thesis for Clue in one sentence, spoken by a practitioner:** most of the time goes into account selection and account research. That is exactly the work Clue automates.

### Insights-powered ABM
[resources.strategicabm.com/videos/lets-talk-abm/insights-powered-abm](https://resources.strategicabm.com/videos/lets-talk-abm/insights-powered-abm) `[FETCHED]`

**Gabrielle Pirzad** on what it means:
> "we know that you are really interested in this topic, or we've seen you at events on public platforms talking about this topic"
> **"it's about being relevant to the customer, not pitching something that they don't necessarily want to buy."**
> **"you've got to find those niche topics to engage them with"**

Research layers she describes: social & public intelligence (platforms, events, PR); internal resources (install base, competitive positioning); external expertise (commissioned research agencies for deep persona profiling); direct customer engagement — visiting sites to learn "the language they use, the structure of the company and their challenges."

Insight types gathered: individual persona interests and career trajectories; organisational challenges and pain points; **spending-trajectory predictions (increasing vs decreasing budgets)**; competitive and press-driven developments. Application method: match *your* SMEs to *their* contacts by shared topical interest — sustainability expert to sustainability decision-maker — rather than sales outreach.

### Sales–marketing alignment
[insights.strategicabm.com/sales-marketing-alignment-best-practices](https://insights.strategicabm.com/sales-marketing-alignment-best-practices) `[FETCHED]`

1. **Speak the language of accounts** — use Sales vocabulary: "Accounts," "Sales pipeline," "ACV," "Deal Velocity," "Win Rate," "Average Profit Margin."
2. **Enable Sales** — "76% of content marketers forget about sales enablement." Account Playbooks document the ABM strategy, impact, target accounts, account experience, timelines, required actions, messaging guidance.
3. **Share the same goals** — joint objectives, documented success definition, shared dashboards.
4. **Make alignment real** — cadence: **monthly with Head of Sales, bi-monthly with Account Directors, weekly with SDRs/AEs**.
5. **Exploit your content** — interview Sales about prospect pain points; repurpose; distribute via dedicated Slack channels.
6. **Celebrate successes.**

### Customer-lifecycle ABM
[resources.strategicabm.com/videos/lets-talk-abm/customer-lifecycle-abm](https://resources.strategicabm.com/videos/lets-talk-abm/customer-lifecycle-abm) `[FETCHED]`

**Marcelo Fernandes (SAP)** describes three motions — **deal acceleration, customer adoption, account expansion** — and why adoption matters in cloud models: buy 20 licences, use 10, renew at 10 unless adoption improves.

On measurement:
> **"Measurement is a nightmare. It's not, you know, it's very complicated."**

Their methods: activity attribution (monitor pipeline movement **60 days post-activity**); **CRM ID tracking** (dedicated identifiers for targeted accounts, enabling automated attribution); stage-progression monitoring.

On account selection:
> **"Less is more"** — focus on "this small group of customers here because they have high revenue expectations."

On what ABM is *not*:
> **"ABM shouldn't be segment-based, audience-based...when you really work with a large group of accounts"** without understanding individual circumstances, **"it becomes a segmentation play."**

> "The beauty of ABM is really when you start to dig down and understand that particular situation"

**Imitate:** outcome-first scoping; the three-criteria tactic-selection rule; the alignment cadence table; insights-powered research layers; the 60-day post-activity attribution window.
**Leave to humans:** site visits to learn a customer's internal language; SME-to-SME matchmaking; executive relationship building.

---

## 2.3 Momentum ITSMA / MomentumABM
[momentumabm.com](https://momentumabm.com) `[BLOCKED — 504 Gateway Timeout on two attempts, both /account-based-marketing/ and /global-account-based-marketing-benchmark]`

**What they sell.** The research/benchmarking authority of the ABM category plus enterprise ABM consulting. ITSMA effectively defined the one-to-one / one-to-few / one-to-many taxonomy that the whole industry uses.

**Frameworks (via search-indexed summaries) `[SNIPPET]`:**
- **Four stages of ABM adoption: Exploring → Experimenting → Expanding → Embedding**, used as "a rapid diagnostic process to help assess gaps in your program compared to a benchmark of comparable companies."
- The **Momentum ITSMA Account-Based Marketing Adoption Framework** outlines **21 ABM success factors across seven key competencies**.

**Benchmark statistics** (6th annual ABM Benchmark Study with the ABM Leadership Alliance; **279 ABM heads and practitioners** surveyed) `[SNIPPET]`:
- **Three in five organisations run more than one type of ABM** (one-to-one, one-to-few, one-to-many)
- **81% of marketers report higher ROI from ABM** than from other marketing initiatives
- Mature ABM programs generated **171% more qualified pipeline** from target accounts vs matched non-ABM controls within 12 months of activation

Sources: [demandbase.com press release](https://www.demandbase.com/press-release/the-abm-leadership-alliance-and-momentum-itsma-release-sixth-annual-abm-benchmark-report/), [prnewswire release](https://www.prnewswire.com/news-releases/momentum-itsmas-annual-abm-benchmarking-study-shows-no-signs-of-slow-down-for-account-based-marketing-301760194.html), [momentumabm.com/global-account-based-marketing-benchmark](https://momentumabm.com/global-account-based-marketing-benchmark) `[BLOCKED]`

**What this teaches the agent.** Momentum is the source of the *legitimising statistics*. An AI Head of ABM should be able to cite the 81% ROI figure, the 171% pipeline lift, and the four maturity stages when a client asks "does this even work?" — and should be able to place the client on the Exploring/Experimenting/Expanding/Embedding ladder as a diagnostic opener.
**Leave to humans:** none of this is execution; it's positioning ammunition.

---

## 2.4 Scrappy ABM — Mason Cosby
[scrappyabm.com](https://scrappyabm.com/) `[FETCHED]`

**What they sell.** Repeatable, low-budget ABM plays for **mid-market SaaS**, explicitly designed to be handed back:
> **"We build repeatable account-based marketing plays for mid-market SAAS brands, teach you how to own them, and graduate you when you're ready so you can bring ABM in-house."**

Headline: **"Build Your First Successful ABM Program."**

**Service lines:** ABM Programs; **Account-Based Podcasting** (from $2,975/mo); "ABM in a Day" workshop (full-day, produces a personalised 6-month roadmap).

**Methodology — the 4D framework:**
- **DATA** — identify target accounts and the reasoning
- **DIRECTION** — track meaningful metrics and sales interactions
- **DISTRIBUTION** — deliver messages through appropriate channels
- **DESTINATION** — provide proof-of-value through case studies and content

**Process:** (1) Discovery call to assess team, goals, setup → (2) Build and launch a custom play **using the existing tech stack** → (3) **Graduate** to in-house management with playbooks.

**Results claimed:** $300M+ pipeline sourced; $100M+ sourced revenue; 200+ playbooks launched; **35+ teams graduated**; 1,000+ marketers trained. And the framing stat: **"78% of ABM programs failed since 2020."**

**Testimonials:**
> "Scrappy ABM has one of the best ABM systems for B2B that we've seen come through our doors." — **Ned Arick, Acquisition.com**
> "Over $3M in Qualified Pipeline in Just 6 Months" … "immediate value add" — **Steph Byce, Director of Demand Generation, Parsable**
> "$1.5M in Revenue in Year 1 on our Podcast" — **Jay Schwedelson, CEO, Guru Events & Subjectline.com**
> "Their highly-collaborative team took the time to gain deep understanding...extremely responsive in delivering quality assets." — **Lance Garms, VP Marketing, Geoforce**

### Pilot structure and — rare in this industry — published pricing
[scrappyabm.com/services/abm-pilot](https://scrappyabm.com/services/abm-pilot/) `[FETCHED]` · [scrappyabm.com/blog/scrappy-abm-costs](https://scrappyabm.com/blog/scrappy-abm-costs/) `[FETCHED]`

- **Timeline:** first **6 weeks** = custom ABM framework build; then execution; **graduation expected within 18 months**.
- **Three phases:** Discovery Call ("Book a quick call to map out your goals and how ABM can help") → Build and Launch ("We design targeted, high-impact campaigns around your top accounts") → Graduate ("Launch and run your ABM plays, then scale what works").
- **Deliverables:** "Custom ABM plays built around your goals, not generic templates"; "Execution across content, strategy, and ops (**no extra hires or new tools required**)"; "Track what matters, double down on what works, and scale with confidence"; partner network access; training for in-house execution.
- **Price: $13,875 every four weeks.** Justification given: cheaper than one experienced ABM hire once you count "salary, benefits, ramp time, and the risk of a bad hire," and better than buying more tools without execution discipline.
- Podcast tiers: Production from **$2,975/mo**; The Account-Based Podcast from **$4,675/mo** (adds automated guest sourcing, episode prep, newsletters, strategy support); The Content Engine (webinars, YouTube-first editing, expanded clips, weekly strategy). **Terms: six-month initial commitment, then 60-day out.**

**Notable transparency stance, verbatim:**
> "Yes, we customize everything after a conversation, but **you shouldn't have to book a call just to understand our pricing approach**"

### Mason's operating doctrine
[abmanswered.com/post/behind-the-scenes-at-scrappy-abm-strategy-over-software](https://www.abmanswered.com/post/behind-the-scenes-at-scrappy-abm-strategy-over-software) `[FETCHED]`

On tech: asked which ABM technology to buy —
> **"None, until you have a strategy."**

His sequence: map the buyer journey → identify data gaps → distribute content → *then* select tools.

Operating tactics: 100–200 manual LinkedIn connections per week from target-account lists; **blank connection requests outperform templated ones**; LinkedIn Events as an audience-warming mechanism; progression from broad awareness to 1:1 personalisation **based on engagement signals**.

Podcast as pipeline engine:
> **"Every 10 podcast interviews we do, 50% lead to a pipeline within 90 days."**

The "Fix Your Site" model: broad webinar → individualised video website audits. His case: **40 audits, 60 hours of recording, 8 customers in 60 days** — intentionally unscalable, deliberately conversion-focused.

Low-cost stack: RB2B or Vectara (anonymous tracking), PhantomBuster (~$140/mo), StreamYard (live webinars), Zoom + unlisted YouTube videos.

On attribution:
> **"Awareness brings them in. One-to-one content gets them across the line. That's where you measure ABM impact."**

On ICP — **the single best diagnostic question in this entire document:**
> **"Run a report in your CRM right now. Add 'is customer' as a filter. If your ICP doesn't reflect your actual customer base, is it really your ICP?"**

On pilots: start with **existing customers or in-flight pipeline deals**, not new logos — "You already have the data and trust. It's the perfect sandbox." `[SNIPPET]` (This independently corroborates Fullfunnel's mistake #11.)

**Imitate:** the CRM ICP-audit question; strategy-before-software as an opening posture; the graduation model as an honesty signal; published pricing; engagement-triggered escalation from 1:many to 1:1; starting the pilot on warm accounts.
**Leave to humans:** the 60-hours-of-video "unscalable" play; blank LinkedIn connection requests at 100–200/week; podcast interviews as relationship instruments.

---

## 2.5 Growth Engine X — Eric Nowoslawski
[growthenginex.com → coldoutbound.com](http://coldoutbound.com/) `[FETCHED — via 301 redirect]`

**What they sell.** High-volume, infrastructure-heavy B2B cold outbound. The headline is the positioning:
> **"We Send 8 Million+ Emails Per Month. We Know What Converts."**

Founded by Eric Nowoslawski, Clay's first marketing contractor (when Clay had four employees). One of the first Clay agencies; **Clay's largest user by enrichment volume**; ~52 concurrent clients. `[SNIPPET/FETCHED — mixed]` ([clay.com/experts/partner/growth-engine-x](https://www.clay.com/experts/partner/growth-engine-x) `[FETCHED]`)

**Services:**
- *Enterprise cold email infrastructure* — 8M+/month capacity; up to 5,000 emails/day per client; **backup domains warming continuously**; weekly monitoring with instant domain swaps
- *List building & enrichment* — unlimited LinkedIn + B2B email data; analysis of the client's best customers to find lookalikes; **20+ data points per prospect**; AI-powered batch scoring
- *Campaign strategy* — **three tiers: Broad (scalable evergreen), Focused (trigger-based), Niche (100–500 contacts)**; **15–20 campaign concepts from launch**; continuous testing; CRM integration

**The process — a clean 5-step engagement arc:**
1. **Free test** — launch and evaluate campaigns
2. **Weeks 1–2: Onboarding** — setup and inbox warm-up
3. **Weeks 3–4: First campaigns**
4. **Month 2: Scale winners**
5. **Ongoing: Optimize**

**The guarantee mechanism** — a free test campaign for qualifying companies:
> **"If it works, we partner. If not, you've lost nothing and learned more."**

**Qualification criteria, published openly** (the agent should hold an equivalent):

| Best fit | Usually NOT best fit |
|---|---|
| B2B | Under **40K** contacts in the target market |
| **100K+ contacts** in the target market | Under **$3K** lifetime profit per customer |
| **$5K+** lifetime gross profit per customer | No sales system to leverage the leads |
| Sales team already in place | |

From his podcast appearance: TAM > 100,000; LTV > $10,000; CAC:LTV ideally **1:10**, minimum **1:3**. ([thegtmengineer.substack.com/p/the-winning-cold-outbound-formula](https://thegtmengineer.substack.com/p/the-winning-cold-outbound-formula) `[FETCHED — episode summary only, no transcript]`)

> **"Paying an agency for a 4,000 account TAM doesn't make sense."** — Eric Nowoslawski ([thesignal.club](https://www.thesignal.club/p/inside-eric-nowoslawskis-ai-powered-cold-outbound-machine) `[FETCHED]`)

**Results claimed:** 62K+ positive responses in 2025; clients range from 2–3 to 30–100+ positive responses daily; one client 552 responses in 4 months, another 212 in 3 months. Named logos: Instantly.ai, Clay, Notion, Snitcher, Donut, Numeral, Arketa, Bissell Vacuums, Oren Klaff, and others.

**Testimonials:**
> "Eric has forgotten more about cold email than other people we've worked with." — **Kyle Mallien, Founder, Heritage Wealth Capital**
> "Eric is one of the most creative minds in outbound today…one of the most respected agency owner[s]." — **Varun Anand, Co-Founder, Clay**
> "Our work with Growth Engine X has led to our cold emails getting a better ROI than our branded Google ad keywords." — **Leon, Snitcher**

### His technical doctrine — the most operationally advanced in the corpus
[thesignal.club/p/inside-eric-nowoslawskis-ai-powered-cold-outbound-machine](https://www.thesignal.club/p/inside-eric-nowoslawskis-ai-powered-cold-outbound-machine) `[FETCHED]`

**Scale:** 2 billion tokens/day through OpenAI; **250 Clay tables running simultaneously**.
**Stack:** Prospeo, Clay, Claude Code + Cursor, Apify, Exa, Parallel.ai, Supabase, Railway, Trigger.dev, SmartLead.

**Claude Code vs Clay — the division of labour:**
> **"Claude Code handles TAM building and email finding. Then everything flows into Clay for final mile delivery."**

Clay remains essential for API rate-limit management, edge cases, visual building, and pre-negotiated data-provider contracts. *(This is a real architectural insight: the agentic layer does discovery and enrichment planning; the orchestration platform does delivery, rate limits, and vendor economics.)*

**Three core LinkedIn plays:**
1. Monitor engagement on **case-study companies'** content; contact prospects who engage
2. Website-visitor de-anonymisation (Leadfeeder, Snitcher, RB2B)
3. **Competitor-content engagement outreach — without mentioning the engagement**

> **"Don't orchestrate LinkedIn with email"** — because of volume differences and account safety.

*(Note: this directly contradicts ColdIQ's profile-view → invite → email sequencing. Both are defensible; the difference is volume tier. ColdIQ's play is Tier-1/Tier-2; Eric operates at Tier-3 volume where LinkedIn action limits make orchestration a liability. An AI Head of ABM should be able to hold **both** positions and pick by tier — that nuance is exactly the kind of judgment that reads as expertise.)*

**Email as an advertising platform:** run **20–50 simultaneous campaigns**, testing subject lines, CTAs, case studies, and offers — treat cold email like Facebook ad testing.

**Domain management as a discipline:** track reply rates across **7-day and 14-day windows**, flag anything **below 0.7% reply rate**, rotate backup domains programmatically. Maintain **backup inboxes equal to sending capacity**.
> **"Domains are getting burned quicker than ever before."**

**Cost engineering** (he cut a $15K/month OpenAI bill): Batch API for high-volume clients; **cached inputs by restructuring prompts — moving variable data to the end**; GPU rental via Vast.ai (~$0.60/hour) for compute-heavy tasks.

**On offers vs personalisation** — his signature position:
> Offers matter more than personalisation. He crafts offers by asking **"what he could say that competitors can't say,"** aiming to make the discovery call itself valuable.

**The "creative ideas campaign"** — his best-performing play across all clients: use AI to generate **"three specific ways your product can help each prospect's business,"** while keeping outputs consistent by constraining them to *predetermined value propositions* rather than free-form suggestions.

> **"signals aren't a silver bullet"** for sustainable growth — contrary to popular opinion.

**The line to put on the wall:**
> **"AI doesn't replace people; it scales whatever you already have. If you're good at writing emails, AI scales good emails. If you're sending bad emails, it scales bad emails."**

**Building internal tools:** a "marshmallow test" approach — build micro-steps sequentially, verify each independently, then compound. Plus the **"Loom transcript trick"**: narrate the manual work aloud, share the transcript with Claude to produce the automation documentation. *(This is SOP-generation-by-narration — directly relevant to how Clue could bootstrap client-specific playbooks.)*

**Imitate:** published qualification floors; the free-test pilot; three campaign tiers; 15–20 concepts at launch; 20–50 parallel campaigns as an experimentation regime; the 0.7% reply-rate domain-health threshold; the **constrained** creative-ideas generation pattern (AI generates *within* a fixed value-prop set — a direct analogue of Clue's claim-bounded narrative).
**Leave to humans:** the offer design itself ("what can I say that competitors can't"), vendor contract negotiation, and the taste judgment behind campaign concepts.

---

## 2.6 The ABM Agency
[abmagency.com](https://abmagency.com/) `[FETCHED — /why-work-with-us/; /abma-overview/ returned thin content]`

**What they sell.** Enterprise **1:1 and 1:few** ABM, full-service. Operating since 2009 with "hundreds of ABM campaigns." Verticals: industrial manufacturing, SaaS, fintech, supply chain & logistics, technology, cybersecurity, pharmaceutical, healthcare. Regions: NOAM, LATAM, EMEA, APAC. `[SNIPPET for verticals/regions]`

**Differentiators, verbatim:**
1. Specialisation in 1:1 and 1:few — "Focused on the accounts that matter" with "decades of experience"
2. "Works closely with your sales team to ensure more account wins"
3. Since 2009, "hundreds of ABM campaigns"
4. "All the ABM expertise and services you need in one place"
5. **"100% tech agnostic—tech never gets in the way"**

**Engagement methodology:** workshops to align teams and set priorities; training; **weekly syncs** for sales enablement throughout campaigns; account selection; strategy development; coordination with sales from discovery through personalisation.

**Deliverables named** — this is the most complete deliverables list in the corpus and a good template for an agent's statement-of-work:
- **RACIs** clarifying roles and responsibilities
- Campaign timelines
- **KPI frameworks**
- Orchestration planning and playbooks
- Messaging frameworks
- Creative assets
- **Reporting dashboards**

**Pilot speed:** "In most situations, The ABM Agency can launch a pilot campaign **within 21 days**." `[SNIPPET]`

**Outcome language:** "Drive higher win rates, larger contract sizes, and shorter sales cycles." Claimed proof: "**32% higher win rates, 10x ROI**"; "$138M deal for Palo Alto Networks, $68M revenue for Dassault, and 11X ROI for DuPont's Chemours division."

**Imitate:** the deliverables list (especially RACI + KPI framework + reporting dashboard as *named artefacts*); the 21-day pilot promise; tech-agnostic positioning.
**Leave to humans:** workshops, and the enterprise politics that RACIs exist to manage.

---

## 2.7 Clay-ecosystem agencies (the "GTM engineering" cohort) — pattern note

Growth Engine X is the archetype, but the whole cohort shares a shape worth naming because Clue will be sold into it and against it:

- **Positioning by volume or by tooling mastery**, not by industry ("We send 8M+ emails per month"; "Clay's largest user by enrichment volume").
- **The free test / paid pilot as the first commercial step**, replacing the traditional proposal.
- **Published qualification floors** that disqualify prospects loudly (TAM, LTV, CAC:LTV, sales-team presence).
- **Infrastructure as the product** — domains, inboxes, warm-up, rotation, deliverability monitoring — because that's the part clients cannot buy off the shelf and cannot run themselves.
- **A rapid migration into agentic tooling** — Claude Code for TAM building, Supabase for own data, Trigger.dev for workers, MCP servers as distribution.

The strategic read for Clue: this cohort is *already* moving up the stack from "we run your sequencer" to "we build your GTM data layer." ColdIQ went all the way to selling the API. Clue's differentiation must therefore be the thing none of them have: **verifiable, provenance-bound research and the persona-keyed argument built on it** — i.e. quality and defensibility rather than throughput.

---

## 2.8 Adjacent reference points

- **Demandbase / 6sense** — platform vendors whose content sets the category vocabulary (buying groups, intent blending, predictive scoring). ColdIQ's own verdict on them: 6sense is "overkill for teams below thousands of accounts"; Demandbase implies "full ABM commitment rather than data source." ([best-account-intelligence-apis](https://coldiq.com/blog/best-account-intelligence-apis) `[FETCHED]`)
- **Clay** — not an agency, but the infrastructure most of this cohort is built on, and the operator of a partner directory that functions as the agency market's index. ([clay.com/experts](https://www.clay.com/experts/partner/growth-engine-x) `[FETCHED]`)
- **thecmo.com's write-up of the Scrappy ABM playbook** — `[BLOCKED — HTTP 403]` ([thecmo.com/demand-generation/abm-playbook](https://thecmo.com/demand-generation/abm-playbook/))

---

# PART 3 — SYNTHESIS: how to speak and operate like an agency principal

This is the steering layer. Everything above is evidence; this is the behaviour to encode.

## 3.1 The universal engagement arc (composite across all 8 agencies)

| Phase | What the principal does | Evidence |
|---|---|---|
| **0. Qualify — publicly and loudly** | State the floors before the call. TAM, LTV, sales-team presence, awareness level. Disqualify fast. | GEX best-fit/not-fit table; Eric's TAM>100K / LTV>$10K / CAC:LTV 1:3–1:10 |
| **1. Diagnose, don't pitch** | Open with the client's *business problem* and the outcome, not with program format. | strategicabm: customers "bring business problems to solve"; outcome-first playbooks |
| **2. Audit reality against belief** | Test the client's ICP against their own closed-won data. | Cosby: "Add 'is customer' as a filter…is it really your ICP?"; Fullfunnel: mistake #5, no patterns from lost deals |
| **3. Size the market before promising activity** | Quantify TAM; present the widen/tier/shrink choice back to the client. | ColdIQ step 7; ColdIQ Layer 1: "If the addressable list comes back too small, the campaign dies here" |
| **4. Start the longest lead time at t=0** | Infrastructure before creative. | ColdIQ step 4: warm-up "is not compressible"; GEX weeks 1–2 = warm-up |
| **5. Capture requirements once, in the client's words** | Recorded kickoff → structured artefact everything inherits. | ColdIQ step 6; "in their words, instead of what the account manager remembered three days later" |
| **6. Tier the list; assign treatment by tier** | Depth of research and choice of channel both follow tier. | ColdIQ tier doctrine; Fullfunnel three dynamic lists; strategicabm 1:1/1:few/1:many |
| **7. Time-box a pilot on *warm* ground** | Pilot on existing customers or in-flight pipeline, not cold new logos. | Fullfunnel mistake #11; Cosby "perfect sandbox"; Fullfunnel POS = Pilot→Operationalize→Scale |
| **8. Launch a portfolio of variants, not one campaign** | 15–20 concepts (GEX); 20–50 parallel campaigns; 5–10 email variants (ColdIQ Tier 2/3); six parallel outbound plays | ColdIQ + GEX |
| **9. Weekly review with leading indicators** | Recorded, with explicit "what works / what doesn't" and account list movement. | ColdIQ step 8; Fullfunnel weekly planning; Teikametrics weekly reviews; strategicabm cadence table |
| **10. Report on accounts and revenue, never activity** | Pipeline, engagement rate, account-to-pipeline ratio, velocity — not sends. | Fullfunnel six-stage ladder; strategicabm "speak the language of accounts" |
| **11. Hand over / graduate** | Train the client to run it; make graduation the stated goal. | Scrappy ABM graduation model; Aircall phase 3 "adoption"; Playbook's 9-month training tail |

## 3.2 The discovery questions an agency principal actually asks

Compiled and consolidated from the sources above. **These belong in Clue's Stage-0 / reverse-profiling interview.**

**Market & fit**
1. How large is the addressable market for this ICP, in accounts and in reachable contacts? *(ColdIQ L1; GEX floor)*
2. What is lifetime gross profit per customer, and what's your CAC:LTV? *(GEX: LTV >$5–10K; 1:3 minimum)*
3. Run the "is customer" filter on your CRM — does the resulting profile match the ICP you just described? *(Cosby)*
4. What patterns exist in your **lost** deals? What are your disqualification criteria / red flags? *(Fullfunnel qualification)*
5. Which of your closed-won accounts would you clone if you could? *(Lookalike seeding — ColdIQ L2: "your closed-won customers encode your real ICP better than any filter combination")*

**Account & committee**
6. Who sits on the buying committee — champion, economic buyer, technical evaluator, blocker? *(Fullfunnel: champions, decision-makers, influencers, blockers)*
7. What are the buying committee's jobs-to-be-done, KPIs, and current challenges — not what they'd like about your product? *(Fullfunnel mistake #7)*
8. Which accounts are already **aware** of you, and which are cold? *(Fullfunnel three lists; mistake #6)*
9. What signals do you already have — hiring, funding, tech changes, exec moves, site visits? *(ColdIQ L5; signal priority order)*

**Cluster / narrative**
10. What challenge do your best accounts share, regardless of industry? *(Fullfunnel cluster targeting)*
11. Why does that challenge exist? What's the status quo? What alternatives are they weighing? What misconceptions exist? *(Fullfunnel cluster decomposition)*
12. **What can we say that your competitors cannot say?** *(Nowoslawski — offer design)*

**Motion & resource**
13. What outcome are we buying: new logos, pipeline acceleration, expansion, defence, or advocacy? *(strategicabm outcome-first)*
14. Who owns this internally, and who from Sales will co-own the playbook? *(Fullfunnel pillar 2; mistake #4)*
15. What is the sales cycle length? *(Determines touchpoint count — Fullfunnel: enterprise needs "more than 400 touch points")*
16. What does "graduation" look like — do you want to run this in-house eventually? *(Scrappy ABM)*
17. Where are you on Exploring / Experimenting / Expanding / Embedding? *(Momentum ITSMA adoption stages)*

**Infrastructure & constraints**
18. What domains and inboxes exist today, and is your main domain in the send path? *(ColdIQ: "Avoid using your main domain")*
19. What's in the current stack, and what data do you already own that we're not using? *(Aircall field dictionary; Cosby "None, until you have a strategy")*
20. What is the budget cap and the reporting cadence you need? *(ColdIQ cost governance; strategicabm cadence)*

## 3.3 How to structure a pilot (the composite template)

| Element | Recommended | Evidence |
|---|---|---|
| **Duration** | 90 days (Fullfunnel), or 6-week build + execute (Scrappy), or 21-day launch (ABM Agency) | all three |
| **Account count** | 30–50 (Fullfunnel ran 46). Emphatically **not** thousands. | Fullfunnel mistake #1 |
| **Account type** | Warm — existing customers or in-flight deals | Fullfunnel #11, Cosby |
| **Team** | Minimal viable: ABM/marketing lead + sales lead + ops/PM (3). Or 1 marketing manager + 1 SDR + 1 content marketer + 1 SME | Fullfunnel case study; full-funnel pillar 2 |
| **Budget for tooling** | Under $1,000/month is provably sufficient | Fullfunnel case study |
| **Commercials** | $5K–$10K/mo (ColdIQ) or $13,875/4 weeks (Scrappy); or free test → paid (GEX) | all three |
| **Leading indicators** (report these from week 1) | Engagement rate (target 43%); accounts moving Cluster ICP → Future Pipeline → Active Focus; account insights collected; personalised connections; non-sales touchpoints | Fullfunnel measurement ladder |
| **Lagging indicators** (report these from ~week 8) | Account-to-pipeline ratio (8.7% is a real benchmark); opportunities; pipeline value; closed-won | Fullfunnel case study |
| **Failure protocol** | Read churn/underperformance signals by **week 6**, not week 16 | ColdIQ |
| **Exit** | Operationalize → Scale, or graduate to in-house | Fullfunnel POS; Scrappy graduation |

## 3.4 How agency principals talk — voice rules for the agent

1. **Lead with a number, close with a constraint.** Every claim in this corpus is "outcome + magnitude + time-box" ("0 → 20 opportunities in 20 days"), and every playbook names its own failure mode ("Each channel fails in a predictable way").
2. **Refuse bad framings politely and re-ask.** "Which channel is best?" → "Which tier are we talking about?" That move *is* the expertise.
3. **Name the failure mode before the client discovers it.** "Discovering after launch that the ICP as written contains 400 companies rather than the 40,000 the retainer assumed."
4. **Quantify before you promise.** No campaign proposal without a market size behind it.
5. **Present choices, not verdicts.** After TAM mapping: widen the criteria / tier the list / accept a smaller target. The client decides. *(Matches Clue's "client always has the wheel.")*
6. **State the human/machine boundary explicitly.** "The humans in this process do two things: they run the kickoff call, and they decide which campaign angles are worth building. Everything else is provisioning, and provisioning is what software is for."
7. **Be honest about weak evidence.** "Engagement on its own is a weak signal." "You stack the odds, the algorithm decides." "signals aren't a silver bullet." "Measurement is a nightmare." Sophisticated buyers trust the vendor who volunteers the limitation.
8. **Prefer relevance over familiarity.** Never "I saw you have a dog."
9. **Talk in the language of Sales.** Accounts, pipeline, ACV, deal velocity, win rate, margin — never impressions, opens, or MQLs alone.
10. **Publish the price or explain why not.** "you shouldn't have to book a call just to understand our pricing approach."
11. **Make the work visible.** What clients praise is not brilliance but transparency: "Always felt like we had a clear understanding of what was going on."
12. **Offer graduation.** The most trustworthy positioning in the category is the one that plans its own exit.

## 3.5 What only humans can do (the honest boundary the agent must respect)

Encode these as tasks the agent **routes to a human**, not tasks it attempts:

- **Offer design** — "what can we say that competitors can't." This is a strategic act of positioning, not a synthesis task.
- **Executive relationship-building** — content co-creation with a target CMO, SME-to-SME matchmaking, 1:1 events.
- **Physical and experiential touches** — direct mail with genuine personal insight (the coffee-from-a-private-roaster play), printed research delivered by DHL.
- **The kickoff conversation itself** — ColdIQ automates everything around it and keeps this.
- **Campaign angle selection** — the second thing ColdIQ's humans keep.
- **Message-level prose for Tier 1** — per ColdIQ's own rule, AI writes snippets, not messages.
- **Deliberately unscalable conversion plays** — 60 hours of personalised video audits.
- **Internal political navigation** — RACIs, executive buy-in, the Center of Excellence coaching role.

## 3.6 Direct implications for Clue's Head-of-ABM agent

1. **Adopt the three-list state machine** (Cluster ICP / Future Pipeline / Active Focus) as the agent's account-state vocabulary. It's better than static tiers and it moves weekly — which fits Clue's project-run phases and re-research cadence.
2. **Make TAM sizing a hard gate before any content work** and surface the widen/tier/shrink choice as a first-class client decision. This is a product surface, not a prompt.
3. **Encode the tier→channel→depth mapping** so that research depth, channel selection, and personalisation budget are one decision, not three.
4. **Ship the "relevance vs personalisation" test as an actual gate.** Clue already has an appropriateness/use gate; add relevance-to-the-argument as a sibling criterion, and make the rejection explainable.
5. **Report on the Fullfunnel six-stage ladder,** not on claims produced or accounts researched. Volume metrics read as vendor metrics; account movement reads as agency metrics.
6. **Constrain generation the way Nowoslawski does** — "three specific ways your product can help each prospect's business," bounded to predetermined value propositions. That is exactly Clue's persona-keyed claim bundle + value narrative, and it's the pattern that survives contact with sophisticated buyers.
7. **Position against ColdIQ explicitly:** they encode the operator's *routing* knowledge; Clue encodes the *evidence*. When a client asks "why not just use the unified API," the answer is that an API returns data, and what the client is buying is a defensible argument with a source behind every claim.
8. **Say the quiet part out loud in the pitch:** "AI writes the research and the argument. Humans write the Tier-1 message and choose the offer." That boundary, stated confidently, is more persuasive than claiming full autonomy — and it is what the best practitioners in the category already believe.

---

# PART 4 — Fetchability register

For the later scraping plan. **Verdict** describes whether full content is programmatically retrievable via plain HTTP fetch (no JS execution, no auth).

## 4.1 Primary targets — fully open

| Domain | Verdict | Notes |
|---|---|---|
| `coldiq.com/blog/*` | ✅ **FULLY FETCHABLE** | All article bodies render server-side. No bot-blocking, no rate limiting observed across ~20 fetches. **Highest-value scrape target in this corpus.** |
| `coldiq.com/case-studies/*` | ✅ **FULLY FETCHABLE** | Consistent structure (company card / challenge / solution / tools / results / takeaways) — well-suited to structured extraction. |
| `coldiq.com` (homepage) | ✅ **FULLY FETCHABLE** | Product positioning, pricing table, integration catalog, social proof one-liners. |
| `coldiq.com/tech-stacks` + `/tech-stacks/people/*` | ✅ **FULLY FETCHABLE** | Directory of operator stacks. Individual pages at `/personal-stacks-<name>`. |
| `coldiq.com/cold-email-guide` | ✅ **FETCHABLE** | Rules extractable; ⚠️ the annotated example email body is **rendered as an image** — needs OCR or vision. |
| `coldiq.com/consulting` | ✅ **FETCHABLE** | Consultant rates ($700 / €777). Testimonial section header present but individual testimonials did not render in text. |
| `coldiq.com/guides` (index) | ✅ **FULLY FETCHABLE** | Complete guide index with URLs and categories. |
| `scrappyabm.com` + `/services/*` + `/blog/*` | ✅ **FULLY FETCHABLE** | Includes published pricing at `/blog/scrappy-abm-costs/`. |
| `fullfunnel.substack.com/p/*` | ✅ **FULLY FETCHABLE** | Long-form, high-density. Best strategy-content source in the corpus. |
| `fullfunnel.io/*` | ✅ **FETCHABLE** | Course pages with curricula, template lists, pricing. |
| `insights.strategicabm.com/*` | ✅ **FULLY FETCHABLE** | Blog/insights with speaker-attributed quotes. |
| `resources.strategicabm.com/videos/*` | ✅ **FETCHABLE** | Video pages carry usable transcript/summary text with attribution. |
| `coldoutbound.com` (ex `growthenginex.com`) | ✅ **FETCHABLE** | ⚠️ `growthenginex.com` 301-redirects; follow to `coldoutbound.com`. Full services, process, qualification criteria, testimonials, client logos. |
| `thesignal.club/p/*` | ✅ **FULLY FETCHABLE** | Substack; deep operator interviews. |
| `thegtmengineer.substack.com/p/*` | ⚠️ **PARTIAL** | Episode summary/highlights render; **full podcast transcript does not**. Audio would need separate transcription. |
| `abmagency.com/*` | ⚠️ **PARTIAL** | `/why-work-with-us/` fetched well; `/abma-overview/` returned thin/incomplete text (likely JS-rendered sections). |
| `scripe.io/customers/*` | ✅ **FETCHABLE** | Third-party case study on ColdIQ with attributed quotes. |
| `clay.com/experts/partner/*` | ✅ **FETCHABLE** | Agency directory profiles: services, minimums, client logos. |
| `abmanswered.com/post/*` | ✅ **FETCHABLE** | Good source for practitioner quotes. |
| `demandbase.com/press-release/*`, `prnewswire.com` | ✅ **FETCHABLE** | Benchmark statistics with methodology. |

## 4.2 Gated (page loads; substance behind an email wall)

All of these are `coldiq.com/guides/*`. The pattern is consistent: **steps 1–2 visible, steps 3–N gated.** Preface material (revenue timelines, prerequisites, positioning) is usually ungated and worth harvesting even when the body is not.

| URL | What's visible | What's gated |
|---|---|---|
| `/guides/four-million-cold-email-agency-playbook` | Revenue timeline Jan'23→Jan'25, 4 prerequisites, steps 1–2 | Steps 3–8, SOPs, pricing models, team structure, discovery-call process |
| `/guides/million-dollar-cold-email-agency-2026` | Positioning strategy, $3K first retainer, prerequisites | Steps 3–7, delivery process, team structure |
| `/guides/b2b-lead-generation-strategy` | Steps 1–2, the two automated plays, prerequisites, 62 meetings in June 2024 | Steps 3–7 |
| `/guides/identify-anonymous-website-visitors` | Steps 1–2 (RB2B pixel, Clay webhook), prerequisites | Steps 3–7, filtering logic, message templates |
| `/guides/ai-funnels-masterclass` | 3-stage funnel model, steps 1–2, $0→$3M in 22 months | Steps 3–9 |
| `/guides/best-linkedin-tools-tested` | Steps 1–2 (Taplio, Kleo) | Steps 3–10, pricing, verdicts |
| `/guides/turn-employees-into-linkedin-influencers` | Prerequisites, steps 1–2 (competition mechanics, friction reduction), 581 posts/24 people/85 days | Steps 3–8, workflow, review process, roles |
| `/guides/how-to-engineer-a-linkedin-gem` | ✅ Appears **ungated** — full statistical findings extracted | — |

**Scraping-plan note:** the gate is an email wall, not a paywall. Content is likely present in the DOM or fetchable post-submission; a JS-capable browser (agent-browser) with a burner email would likely retrieve the full set. Assess separately whether that's within acceptable-use bounds before doing it.

## 4.3 Blocked / failed

| URL | Status | Notes |
|---|---|---|
| `thecmo.com/demand-generation/abm-playbook/` | ❌ **403 Forbidden** | Bot-blocked. Content on Mason Cosby's playbook available only via search snippets. Would need a real browser + residential path. |
| `momentumabm.com/account-based-marketing/` | ❌ **504 Gateway Timeout** ×2 | Also 504 via the `momentumitsma.com` 301 redirect. Site appears slow/unstable rather than deliberately blocking; **retry with a longer timeout**. |
| `momentumabm.com/global-account-based-marketing-benchmark` | ❌ **504 Gateway Timeout** | Same. High-value benchmark data — worth a retry pass. |
| `coldiq.com/services` | ❌ **404** | Path does not exist; services content has migrated to `/consulting` and the product homepage. |
| `coldiq.com/pricing` | ❌ **404** | Pricing lives on the homepage. |
| `linkedin.com/*` (all) | ❌ **AUTH-WALLED** | As expected. All LinkedIn-native content in this document was reached via republication (coldiq.com, scripe.io, abmanswered.com) or search snippets. |
| `podcasts.apple.com/*` | ⚠️ **Not attempted** | Scrappy ABM podcast episodes; would require audio transcription. |
| `open.spotify.com/episode/*` | ⚠️ **Not attempted** | Eric Nowoslawski episode; same. |

## 4.4 Recommended scraping plan (priority order)

1. **`coldiq.com/blog/*` — full crawl.** Enumerate via `/blog` and the six category pages (`/blog-categories/{b2b-sales, ai-sales, list-building, cold-emailing, lead-generation, sales-tools}`). Highest density of playbooks, numbers, and verbatim principles. Fully open.
2. **`coldiq.com/case-studies/*` — full crawl, structured extraction.** Uniform six-part schema; ideal training data for case-study *generation*.
3. **`fullfunnel.substack.com` — full archive crawl.** The best ABM strategy corpus available anywhere at this depth. Fully open.
4. **`insights.strategicabm.com` + `resources.strategicabm.com`** — practitioner quotes with named attribution; excellent for voice modelling.
5. **`coldiq.com/tech-stacks/*`** — the operator-stack directory; a ready-made tool→job mapping.
6. **Retry `momentumabm.com`** with extended timeouts for the benchmark statistics (the category's legitimising numbers).
7. **`thesignal.club`, `abmanswered.com`, `clay.com/experts/*`** — targeted single-page fetches, no crawl needed.
8. **Decide policy on the ColdIQ email gate** before attempting the `/guides/*` bodies.
9. **`thecmo.com`** — needs a real-browser path; low marginal value given Mason Cosby's own site is fully open.

---

## Appendix A — Consolidated numbers reference

| Metric | Value | Source |
|---|---|---|
| ColdIQ ARR | $7M+ | [anatomy](https://coldiq.com/blog/the-anatomy-of-a-7m-arr-lead-gen-agency) |
| ColdIQ clients onboarded | 275+ | [onboarding](https://coldiq.com/blog/the-onboarding-system-behind-275-outbound-clients) |
| ColdIQ retainer band | $5K–$10K/mo | [anatomy](https://coldiq.com/blog/the-anatomy-of-a-7m-arr-lead-gen-agency) |
| ColdIQ close process | 2–3 Google Meet calls | same |
| ColdIQ monthly traffic | 40,000+ visits | [funnel](https://coldiq.com/blog/the-funnel-that-books-us-100-meetings-every-month) |
| ColdIQ meetings/month | 100+ | same |
| ColdIQ sales-led share | 70% of deals | same |
| Onboarding time-to-launch | 8 days (vs 8 weeks) | [onboarding](https://coldiq.com/blog/the-onboarding-system-behind-275-outbound-clients) |
| Multichannel reply lift | 1.8% → 4.3% in 2 months | [multichannel](https://coldiq.com/blog/how-multichannel-outreach-took-replies-from-18-to-43) |
| Warm vs cold conversion | 3× | [11-tool stack](https://coldiq.com/blog/the-11-tool-stack-behind-80000-linkedin-followers) |
| Carousel reach lift | 3–4× (up to 10× for visuals) | [Taplio playbook](https://coldiq.com/blog/the-linkedin-growth-playbook-by-coldiq-x-taplio), [11-tool stack](https://coldiq.com/blog/the-11-tool-stack-behind-80000-linkedin-followers) |
| Employee advocacy | 581 posts / 24 people / 85–90 days → $151K MRR, 34K followers | [20M impressions](https://coldiq.com/blog/how-to-generate-20m-linkedin-impressions-a-year) |
| Deals influenced by LinkedIn | 80%+ | [Scripe story](https://scripe.io/customers/coldiq-scripe-customer-story) |
| Median 500+ like post | ~260 words (normal: 179) | [LinkedIn gem](https://coldiq.com/guides/how-to-engineer-a-linkedin-gem) |
| Best-performing post topics | Milestone/revenue 44.8%, case study 44.5% | same |
| Email/mailbox/day ceiling | 25–30 | [channel](https://coldiq.com/blog/which-outbound-channel-books-more-meetings), [cold email guide](https://coldiq.com/cold-email-guide) |
| LinkedIn safe ceiling | ~100 DMs/invites per week | [channel](https://coldiq.com/blog/which-outbound-channel-books-more-meetings) |
| Cold call volume | 50–100 dials/day/rep | same |
| Fullfunnel pilot | 46 accounts, 3 people, <$1K/mo, 90 days | [case study](https://fullfunnel.substack.com/p/our-abm-program-breakdown-case-study) |
| Fullfunnel engagement rate | 43% | same |
| Fullfunnel account-to-pipeline | 8.7% | same |
| Enterprise buyer journey | 9–24 months | [full-funnel fundamentals](https://fullfunnel.substack.com/p/full-funnel-marketing-fundamentals) |
| Enterprise touchpoints needed | 400+ | [ABM 3.0](https://fullfunnel.substack.com/p/abm-strategy-30) |
| ABM dissatisfaction | 98.5% dissatisfied / 49% frustrated | [Killing ABM](https://fullfunnel.substack.com/p/killing-abm) |
| ABM programs failed since 2020 | 78% | [scrappyabm.com](https://scrappyabm.com/) |
| ABM ROI vs other marketing | 81% report higher | Momentum ITSMA benchmark `[SNIPPET]` |
| Mature ABM pipeline lift | 171% vs matched controls | same |
| Scrappy ABM pilot price | $13,875 / 4 weeks | [costs](https://scrappyabm.com/blog/scrappy-abm-costs/) |
| Scrappy podcast pricing | $2,975 / $4,675 per month | same |
| GEX email volume | 8M+/month | [coldoutbound.com](http://coldoutbound.com/) |
| GEX qualification floors | TAM 100K+, LTV $5–10K+, CAC:LTV 1:3 min | same + [gtmengineer](https://thegtmengineer.substack.com/p/the-winning-cold-outbound-formula) |
| GEX domain-health threshold | flag below 0.7% reply rate | [thesignal.club](https://www.thesignal.club/p/inside-eric-nowoslawskis-ai-powered-cold-outbound-machine) |
| Fullfunnel course pricing | $997 individual / $7,497 team | [fullfunnel.io](https://fullfunnel.io/account-based-marketing-playbook/) |
| ABM Agency pilot launch | within 21 days | abmagency.com `[SNIPPET]` |
| Cosby podcast→pipeline | 50% of every 10 interviews within 90 days | [abmanswered](https://www.abmanswered.com/post/behind-the-scenes-at-scrappy-abm-strategy-over-software) |

---

*Compiled 2026-08-31. ~40 primary-source fetches across 16 domains. Every claim above carries a source URL; retrieval status marked throughout. Search budget for this session was exhausted at 200 calls; remaining gaps (Momentum ABM 504s, thecmo.com 403, ColdIQ gated guides) are documented in §4.3 with recommended retry paths.*
