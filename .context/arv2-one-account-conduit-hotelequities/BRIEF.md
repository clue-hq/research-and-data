# ONE account, end to end — client CONDUIT, target HOTEL EQUITIES

**Date:** 2026-09-21. **Client (the "we"):** Conduit (conduit.ai) — read `client-context-conduit.md`
in this folder FIRST; it is the client's own profile. **Target account:** Hotel Equities
(hotelequities.com). **Working dir:** /Users/shashank/conductor/workspaces/research-and-data/winnipeg.
**Artifacts:** `.context/arv2-one-account-conduit-hotelequities/` ONLY. Never edit anything outside it.
Keys are in `.env` (CLUE_EXA_API_KEY, CLUE_AI_ARK_API_KEY, CLUE_GEMINI_API_KEY, CLUE_OPENROUTER_API_KEY)
and loaded by `z_lib.py` — never print or persist a key. **NO APOLLO. NO FIRECRAWL.** AI Ark is the only
structured-data provider. **Ceilings (enforced in z_lib):** $3.50 cash; **AI Ark ≤ 20 credits** (the free
tier is nearly spent — on any 402/exhausted response record it and stop AI Ark; emails before anything
else; never buy phones). Timing + cost ledgers per call and per phase are first-class deliverables.

This run repeats the Zafran recipe (`.context/arv2-one-account-aiark/BRIEF.md`, `ONE-ACCOUNT-REPORT.md`,
`z*.py`) for a different client and a different kind of target. Reuse the scripts' shape; do not
rediscover wire facts. Where this brief and the Zafran brief differ, this brief wins.

## What the founder wants back
"Find the decision-makers at Hotel Equities and deliver undiscovered insights, in the same format as
Zafran, on how Conduit could approach this company and make it really effective." Concretely:
1. **The buying committee** for a Conduit sale into a ~300-hotel third-party management company —
   confirmed from the open web first, enriched by AI Ark second (the v3 protocol below).
2. **Undiscovered insights**: facts a rep would not find on the homepage — hiring pressure at the front
   desk / guest services / night audit across the portfolio (the ADP feed), the PMS and guest-messaging
   tools in use (brand mandates: Marriott, Hilton, IHG), merger-integration timing, new divisions, executive
   quotes in their own voice from podcasts/talks/articles, and per-person hooks.
3. **The three pages** in the frontend format (Insights, Account Overview, Contact pages for the top 2–3
   people), every sentence with its inline dated source chip.
4. **Timing and money**, measured, with the per-account "full vs trimmed" table and the per-person media cost.

## Identity lock (already verified — do not re-derive)
Hotel Equities (Hotel Equities Group, LLC), Atlanta/Alpharetta GA. Hospitality management + development
company; ~300 hotels/resorts/outdoor destinations across US, Canada, Caribbean, Latin America; branded
(Marriott, Hilton, IHG, Choice), independent, resorts, outdoor ("Postcard Cabins"). Three divisions:
Full Service, Focused Service, Lifestyle. **Merged with Springboard Hospitality (Honolulu) in 2025**;
CEO **Ben Rafter** ("a technology entrepreneur with extensive experience scaling hotel platforms");
COO **Albert (Al) Smith** appointed July 2025; founder **Fred Cerrone** retired effective 2025-11-22;
**Brad Rahinsky** now Co-Chairman (former President & CEO); a **November 2025 wave of executive
appointments across the new divisions**. Marriott's #1 franchise management company on Intent-to-Recommend
four years running. Named operator of SLS Punta del Este (opening 2029). Blog posts worth reading: Al Smith
on "simplicity drives consistent luxury service at scale"; Ben Rafter in Hotel Executive on "the future of
hotel management". Same-name exclusions: "Hotel Equities" is also a generic phrase; there are unrelated
"Equity Hotels", "Hospitality Equities", "HEI Hotels". Lock every deep call to hotelequities.com + Atlanta.

**Own site fetch note:** direct HTTP GETs to hotelequities.com intermittently hang (a 2-minute stall was
observed). Use `z_lib.live_fetch` with timeout ≤20s and fall back to Exa `/contents` (livecrawl) for:
`/`, `/meet-our-team.htm`, `/careers`, `/blog/` and the leadership/merger/appointment posts.

## Free, typed hiring truth — the ADP feed (PROVEN, use it)
Hotel Equities runs ADP WorkforceNow with FOUR public career centres. JSON endpoint (browser UA,
`Accept: application/json`), pageable with `$top=50&$skip=N`, `meta.totalNumber` gives the count:
`https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions?cid=30fbf914-a807-419c-b19e-409fa2c6a5f6&ccId=<CC>&locale=en_US&$top=50&$skip=0`
with `<CC>` ∈ {9200396175623_2 (management/sales, 32 reqs), 9200402480447_2 (hourly/property, 97 reqs),
9200585439604_2 (Canada hourly, 8), 9200585441819_2 (Canada mgmt, 6)} — 143 open reqs on 2026-09-21.
Fields: `requisitionTitle`, `postDate`, `requisitionLocations[].nameCode.shortName`, plus (fetch per-req
detail if available) description text. Pull ALL pages of all four. Then compute the Conduit-relevant
view: count and list **Guest Services / Front Desk / Night Auditor / Front Office Manager / Rooms
Controller / Guest Service Agent** roles (the seats Conduit automates or relieves), GM openings (new
properties = onboarding moments), by brand and by geography; days-open; the freshest 7/30-day velocity.
This is the account's P1 pain signal — the equivalent of Zafran's Ashby ABM req.

## Committee protocol (web-first — follow exactly, from v3)
1. Ground truth from the open web FIRST: `/meet-our-team.htm` (Exa /contents), the July 2025 merger
   appointments post + Hospitality Net appointment notices, the Nov 2025 appointments post, LinkedIn via
   Exa search (`site:linkedin.com/in "Hotel Equities" <role>`), press quotes. Build the committee from
   THESE. Target seats for a Conduit sale (map to personas): **executive sponsor** = CEO Ben Rafter (a
   technology entrepreneur — the most important voice in this account); **economic buyer** = COO Al Smith
   (operations owns guest services); **champion** = the operations/guest-experience leader below the COO
   (SVP/VP Operations, VP Guest Experience, or a division President); **technical evaluator** = CIO / VP
   Technology / IT (who owns PMS + integrations); **adjacent** = Chief Commercial / Revenue leader (upsells,
   ancillary revenue). If a seat is vacant, record the vacancy as a signal. Correct beats many: 4–6 people.
2. AI Ark is enrichment-only: `POST /v1/people` **name-scoped + domain-scoped** (0.5cr each; the title
   filter is broken) for the confirmed people; `POST /v1/people/export/single {"url": linkedin}` (1cr,
   found-only) for ≤4 emails, priority order sponsor → buyer → champion → evaluator; `POST /v1/companies`
   for hotelequities.com (0.1cr). Never admit an AI-Ark-only person. Drop any employer mismatch.
   Pace ≥10s between AI Ark calls. **Never write `profile.birth_date`.**
3. Every member row: persona, identity-confirmation URL (non-AI-Ark), email + status, since-when, reach.

## Research phases (parallelise the independent ones with background scripts — z_lib's ledger lock is
cross-process safe; record wall-clock per phase in timing.json)
1. **Free sources:** ADP feed (all four centres, all pages); own-site key pages; the blog posts named above.
2. **AI Ark** company object + name-scoped people + ≤4 emails (inventory the fields as Zafran did, briefly).
3. **Exa deep-reasoning, ONE account call** (single string property `report`, contents text 10k +
   highlights, numResults 20–25, stream false; retry once on the silent-fail signature ≤9 results/~$0.015).
   Charter, target-locked: what they manage (count by division/brand/region, owned vs third-party), ownership
   /capital partners, the Springboard merger (why, what Springboard brought — it was a technology-forward
   Hawaii operator; Rafter's background), **technology stack**: PMS by brand (Marriott/Hilton/IHG mandates,
   Oracle OPERA Cloud exposure — Conduit's June 2026 two-way OPERA integration is the wedge), guest
   messaging/texting tools in use or trialled (Canary, Kipsu, Akia, Revinate, Duve, HiJiffy, Asksuite),
   any AI initiatives or statements, contact-centre / after-hours guest response model, labor pressure,
   guest-satisfaction KPIs (ITR/GSS scores, Marriott #1 ranking), new openings and pipeline (SLS Punta del
   Este, Postcard Cabins, conversions), leadership changes with dates, awards, reputation incl. negatives
   (lawsuits, layoffs, review complaints, owner disputes) — negatives marked `outreach_safe:false`.
4. **Per-person deep-reasoning** (≤5 calls) for each confirmed member: the personal charter from
   `.context/arv2-person-depth/BRIEF.md` §"personal-depth charter" — identity + career with dates,
   education, public writing/talks/podcasts, what they own, how they buy/think (their words), NON-SENSITIVE
   hooks (hobbies, sports, causes, side projects, hometown, milestones as THEY state them), 2–3 grounded
   openers. **Sensitivity floor (hard):** no health, faith, politics, sexuality, family tragedy, minors —
   never recorded, never used. "Not found" over guessing.
5. **Media layer (Gemini + embeddings — the founder's explicit ask):** sweep for podcasts, YouTube, webinars,
   conference talks featuring Ben Rafter (hotel-tech podcasts: Hospitality Daily, No Vacancy, Lodging Leaders,
   Hotel Tech Report, Skift; Hotel Executive articles), Al Smith, and the champion/evaluator. Resolve to a
   playable source (YouTube URL public, or the show's RSS → MP3 enclosure). Process ≥2 items, ≤2.5h media
   total. **Two-model recipe (proven on Zafran):** `gemini-3.5-transcribe` for the faithful full transcript
   (text at `candidates[0].content.parts[0].audioTranscription.text`, no timestamps) + `gemini-3.5-flash-lite`
   for MM:SS-timestamped lines; run a duplicate-line check on flash-lite output (it silently loops on long
   audio after ~12 min) and keep only quotes that are exact substrings of the faithful transcript. Extract 3–5
   verbatim quotes per item that reveal how the person thinks about technology, guest experience, labor,
   consistency at scale, vendors. Then embed transcript chunks with `gemini-embedding-2`
   (RETRIEVAL_DOCUMENT, 768) and run 3 retrieval queries (e.g. "what does Ben Rafter say about AI or
   technology in hotel operations?", "what does Al Smith say frustrates consistency at scale?", "how do they
   choose or evaluate vendors and tools?"); show top hits with timestamps. Record tokens, $ and seconds per
   item, and the raw-audio-embedding counterfactual ($0.00016/s) for the record.
6. **Structure → `claims_hotelequities.json`** with gpt-5-mini (OpenRouter, `reasoning: minimal`, ONE
   subject per call, closed field keys from `field_catalog.py` + `PROPOSED::` for what the catalog lacks,
   real cost = `cost_details.upstream_inference_cost`). Every claim: entity, entity_key, field_key, value,
   evidence_span (verbatim), source_url, source_provider, observed_at, `priority` 1|2|3, `use_class`,
   `outreach_safe`, `claim_id` (`he-001…`). **Priority is keyed to CONDUIT's fit**, not Clue's: P1 = guest
   services/front desk/night audit hiring volume and velocity, PMS/OPERA facts, guest-messaging tool gaps,
   merger-integration and new-division timing, new openings, executive quotes on technology/guest experience/
   labor, vacant seats; P2 = portfolio composition, brand mix, ITR ranking, division structure, tech stack,
   committee composition; P3 = history, culture, background, personal hooks (P1 inside their own contact view).
   Voice quotes carry media URL + timestamp.
7. **Deliverables:**
   - `ONE-ACCOUNT-REPORT.md` (simple language, same seven sections as Zafran's): (0) stack actually executed
     + "Apollo used? 0 calls" from the ledger; (1) AI Ark field inventory (brief) + credits; (2) database vs
     research two-column comparison; (3) the media layer: items, timestamped quotes, retrieval demo, cost per
     item and per hour; (4) **the fruitful top-15 for Conduit** (ranked, sourced, costed, one line each on why
     it moves outreach); (5) committee table with emails + status + reach; (6) cost tables: this run per
     provider; full vs trimmed recipe per account; per-person media cost; timing per phase and per-call
     latency per provider; (7) honest gaps + what surprised you + **what differed from the Zafran recipe
     because the target is a hotel operator, not a SaaS company** (e.g. no Ashby; ADP instead; brand-mandated
     PMS; hourly hiring volume as the signal).
   - `HOTEL-EQUITIES-PAGES.md` — the three screens EXACTLY in the format of
     `.context/frontend-page-content/FRONTEND-SPEC-ZAFRAN.md` Parts 2–5 (read it first): **Insights** (Account
     insights grouped: Buying signals · Money & momentum · Tools they already use · How they operate, and who
     they serve; Contact insights one per member with → chips; 🔒 Context only), **Account Overview** (What
     Hotel Equities does · Why they fit Conduit ✓/✗ · Why now top-3 · Buying committee table · How to approach
     · 🔒 Watch-outs · Right rail Core/Custom/Contacts/Activity — numbers only, no provider names), and
     **Contact pages for the top 2–3 people** (H1s: Why this person · Their problem right now · Openers ·
     Angles · 🔒 Do not mention; H2 one line; body 2–5 sentences; every factual sentence carries
     `[domain](url) · posted d Mon yyyy · verified 21 Sep 2026` (or `· record <date>` for AI Ark facts, `· MM:SS`
     for media quotes); copy-lines as `> **In your email:** …  [Copy]`; empty section → "No {section}
     information found for {name}."). "We/us" = Conduit; openers sell Conduit (after-hours guest response,
     PMS write-back incl. OPERA, brand-over-property configuration for a 300-hotel portfolio, per-unit pricing,
     Haven 90% automation at 4.8–4.9 quality). End with the **link register** table (domain, URL, posted,
     verified, favicon URL).
   - `claims_hotelequities.json`, `timing.json`, `cost_ledger.json`, `transcripts/`, `raw/`, all scripts
     (`h1_*.py` … in phase order), `media_index.json`.
**Honesty rules:** never fabricate; every number from a real response; thin = reported thin; a same-name
stranger is excluded and named; unsafe facts only under Context only / Do not mention. When done, print a
10-line summary: committee (names/titles/emails found), top-3 insights, total cash, total credits, total
wall-clock, and any ceiling hit.
