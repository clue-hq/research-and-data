# ONE account, end to end — AI Ark for all structured data, Exa for research, Gemini for media

**Date:** 2026-09-02. **Account:** Zafran Security (zafran.io) — top researched intent from the
smoke test. **Working dir:** /Users/shashank/conductor/workspaces/research-and-data/winnipeg.
**Artifacts:** `.context/arv2-one-account-aiark/` ONLY. Keys in `.env`: CLUE_EXA_API_KEY,
CLUE_AI_ARK_API_KEY, CLUE_GEMINI_API_KEY (WORKING — verified: text gen, embedding-2, YouTube
ingest all OK), CLUE_OPENROUTER_API_KEY. **NO APOLLO CALLS. Zero.** The founder's ruling: AI Ark
is the database; Apollo is not used.
**Ceilings:** $3.00 cash; **AI Ark ≤ 25 credits** (free tier has ~37 left — if any call returns
402/exhausted, record it and stop AI Ark; do not buy phones unless ≤5 credits remain in budget
after emails). Timing + cost ledgers per call/phase are first-class deliverables.

## The founder's three questions this run must answer, with evidence
1. **"What exactly do we get back from AI Ark?"** → a FIELD INVENTORY: for every AI Ark endpoint
   you call, list every response field name with its real value for Zafran (business data — no
   redaction needed except: NEVER write `profile.birth_date` anywhere; drop it at parse time).
2. **"What information is actually fruitful for outreach?"** → a ranked top-15 of the single most
   useful facts/insights across the whole account+committee, each with: source (AI Ark / Exa
   search / Exa deep / Gemini media / free ATS API / own site), what it cost, and one line on
   why it moves outreach.
3. **"What does the trimmed recipe cost?"** → per-account cost table (full vs trimmed) with every
   line item measured, and the per-person media cost.

## Proven wire facts (reuse — .context/ai-ark-canary/canary.py, arv2-person-depth/p_lib.py, smoke b_lib.py)
- AI Ark: base https://api.ai-ark.com/api/developer-portal, headers X-TOKEN + Content-Type +
  browser User-Agent (Cloudflare 1010 otherwise), pace ≥10s between calls (free-tier 429s).
  `POST /v1/companies` {"account":{"domain":{"any":{"include":["zafran.io"]}}},"page":0,"size":3}
  (0.1cr/result) → inventory the company object (technologies, revenue, sic/naics, funding,
  employee metrics, locations, links). `POST /v1/people` domain-scoped size≤12 (0.5cr/result) →
  inventory the person object (profile, link, location, languages, educations, certifications,
  position_groups, skills, member_badges, company embed, department, statistics) — PLUS
  name-scoped lookups for the known committee (Vari Kaur, Nick Fisher, Sanaz Yashar + CTO/CRO
  if found) since the title filter is broken (smoke-test G2). `POST /v1/people/export/single`
  {"url": linkedin} (1cr found-only) for ≤4 people → inventory the email block (address, mx,
  domainType, status, subStatus, date, free, generic). Record every credit.
- Exa: search type=auto ≤10 w/ contents.text ($0.007); /contents ($0.004); deep-reasoning =
  single string property `report` + contents block, numResults 20, $0.02-0.03, ~40s; retry the
  silent-fail signature (≤9 results / ~$0.015) once. Free ATS API: Zafran is on Ashby —
  `https://api.ashbyhq.com/posting-api/job-board/zafran` (browser UA) for live reqs.
- Gemini (REST, key as ?key=): `POST /v1beta/models/gemini-3.5-flash-lite:generateContent` with
  parts [{"file_data":{"file_uri": youtube_url}}, {"text": prompt}] for YouTube (public only), or
  {"file_data":{"file_uri": mp3_url, "mime_type":"audio/mpeg"}} for a podcast MP3 enclosure (get
  the MP3 from the show's RSS feed); ask for MM:SS-timestamped transcript + speaker labels +
  verbatim quotes. Pricing 3.5-flash-lite: $0.30/1M input (audio ≈ 32 tok/s → ~$0.035/hour),
  $2.50/1M output. `POST /v1beta/models/gemini-embedding-2:embedContent` {"content":{"parts":
  [{"text":...}]},"taskType":"RETRIEVAL_DOCUMENT"|"RETRIEVAL_QUERY","outputDimensionality":768}
  ($0.20/1M text). Record usageMetadata tokens + computed cost per call. Media budget ≤ 2.5h.
- Structuring: OpenRouter gpt-5-mini reasoning minimal, one subject per call, closed field keys
  (`.context/arv2-clue-sample-v2/field_catalog.py`), cost = cost_details.upstream_inference_cost.
- python3 stdlib; save every raw response under raw/ before parsing; never print keys.

## Phases
1. **AI Ark company + people + emails** (the field inventories; reuse known identities from
   `.context/arv2-person-depth/person_*.md` and `.context/arv2-smoke-cluehq/` — don't re-derive).
2. **Free sources:** own site /contents (zafran.io key pages), Ashby live reqs (the 105-day ABM
   req — confirm still listed today), Exa cheap searches only for gaps (≤6).
3. **Exa deep-reasoning:** ONE account call (charter: what they sell, funding exact, GTM team,
   hiring w/ quotes, tooling, leadership, ops pain, timing, reputation incl. negatives — note the
   Calcalist/Cisco rumour is refuted and must be marked outreach_safe:false).
4. **Gemini media layer (the founder's explicit ask — run it for real):** find and process ≥2
   media items: Sanaz Yashar's podcast appearance (Apple Podcasts page → RSS → MP3; or a YouTube
   version) and Nick Fisher's cocktail-YouTube presence (channel/video URL); transcribe with
   timestamps; extract 3-5 verbatim quotes per item that reveal how the person thinks/what they
   value; then embed transcript chunks with embedding-2 and run 3 retrieval queries (e.g. "what
   does Sanaz say about how she buys or evaluates tools?", "what is Nick most proud of?") — show
   top hits with timestamps. Measure seconds and $ per item; also compute what embedding the raw
   audio would have cost (for the record: $0.00016/sec).
5. **Structure → claims_zafran.json** (account + ≤4 people incl. voice quotes with timestamps
   + media URLs; P1/P2/P3; use_class; outreach_safe; never birth_date).
6. **`ONE-ACCOUNT-REPORT.md`** (simple language): (0) "Was Apollo used?" — answer from the ledger
   (must be 0 calls) + the stack sequence actually executed; (1) AI Ark field inventory per
   endpoint with real values + credits; (2) what AI Ark alone gives vs what only Exa/Gemini give
   (a two-column "database vs research" comparison for this account); (3) the Gemini media
   layer: transcripts (excerpts), timestamped quotes, retrieval demo, measured cost per item and
   per hour; (4) the fruitful top-15 (ranked, sourced, costed); (5) committee table w/ emails +
   status; (6) cost tables: this run per provider + "full recipe" and "trimmed recipe" per
   account, and per-person media cost; (7) honest gaps + what surprised you. Plus claims JSON,
   transcripts/, raw/, scripts, timing.json, cost_ledger.json.
Honesty: never fabricate; every number from a real response; thin = reported thin.
