# ARV2 Person-Depth run — dossier-grade personal research + the Google multimodal media layer

**Date:** 2026-08-31. **Why this run exists:** the cluehq.ai smoke test omitted the personal-hooks
charter (planner's fault). The founder wants every committee person researched to Insight-Health
dossier depth — life/background hooks, voice from podcasts/videos/talks, unique insights — and a
working demonstration of Google's multimodal models (Gemini Flash-Lite for audio/video → transcript;
`gemini-embedding-2` for indexing) inside the pipeline.

**Working dir:** /Users/shashank/conductor/workspaces/research-and-data/winnipeg. **Artifacts:**
`.context/arv2-person-depth/` ONLY. Keys in repo-root `.env`: CLUE_EXA_API_KEY, CLUE_AI_ARK_API_KEY
(≤5 credits this run — identities are already known), CLUE_OPENROUTER_API_KEY, and **maybe**
`CLUE_GEMINI_API_KEY` — **check for it at start AND re-read .env right before the media phase**
(the founder may add it mid-run). **Ceilings: $2.00 cash.** Timing + cost ledgers per call and per
phase are mandatory deliverables (timing.json, cost_ledger.json).

## The people (read from the smoke-test artifacts first)
`.context/arv2-smoke-cluehq/`: `b4c_committees.json`, `claims_*.json`, `report_contact_*.md`,
SMOKE-TEST-REPORT.md §4-5. Target **10 people**: Zafran — Vari Kaur, Nick Fisher, + CEO;
Cogent — Alexander Semien, Cameron Coles, + CEO (Vineet Edupuganti); Harmonic — Ana Corio,
Tyler Chonoles, + CEO; Uptiq — the top marketing/GTM contact. Skip Vendelux (disqualified).
Identity is already locked (LinkedIn URLs in the artifacts) — do not re-buy it.

## Proven wire facts (reuse; do not rediscover)
Exa search type=auto ≤10 results ≈ $0.007 (request `contents.text` — free at 1.5k chars);
`/contents` ≈ $0.004; deep-reasoning = ONE string property `report` schema + contents block +
numResults 20, $0.02-0.03, ~30-45s, pace ~1/s, retry 429. Structuring: OpenRouter gpt-5-mini
reasoning minimal, ONE person per call, closed field keys (`.context/arv2-clue-sample-v2/field_catalog.py`),
real cost = cost_details.upstream_inference_cost. python3 stdlib; browser UA; save every raw
response under raw/ BEFORE parsing (this saved us last run). Never print keys.

## The personal-depth charter (per person — this is what was missing)
Non-sensitive categories ONLY. Every item = verbatim quote + URL, or "not found". Categories:
- **Background:** hometown/where they grew up, alma mater (+ degree/year/activities), early career
  story, military/sports/arts backgrounds, languages.
- **Life outside work, as THEY state it:** hobbies, sports (marathons, climbing, etc. only if they
  posted/bio'd it), pets, family *milestones they announced themselves* (new baby/wedding posts are
  self-published; never dig further), causes/volunteering/boards, side projects, books/podcasts they
  recommend.
- **Voice:** what they say in long-form — podcasts, webinars, conference talks, interviews, AMAs,
  authored articles — 3-5 verbatim quotes with source (and timestamp for media).
- **Professional identity:** what they own, what they're proud of, pet peeves, how they buy/evaluate.
- **Unique insight:** the ONE thing about this person a generic enrichment tool would never surface.
- **Openers:** 3, each grounded in a specific hook with its URL.
- **Sensitivity floor (hard):** no health, faith, politics, sexuality, family tragedy, minors —
  recorded never, used never.

## Phase 1 — Multi-source sweep (per person, cheap: ~8-12 Exa searches ≈ $0.08)
Search angles, each recorded verbatim (query → results): (1) `"<name>" podcast|interview|guest`,
(2) `"<name>" site:youtube.com` and webinar/conference/"speaker", (3) `"<name>" <company>` with
`includeDomains` for apple podcasts/spotify/podchaser/listennotes, (4) authored articles /
Substack / Medium / guest posts, (5) alumni/university features, (6) awards/lists (e.g. "top
marketers", "40 under 40"), (7) personal site / GitHub (technical people), (8) X/Twitter + Threads
+ Bluesky indexed posts, (9) community/volunteer/board, (10) local press/hometown. Also
`/contents` on their LinkedIn URL (indexed copy) and personal site. Collect every **media URL**
(YouTube, MP3 enclosures via podcast RSS, video pages) into media_index.json with duration if
visible. Record per person a **source-coverage matrix**: which of the ~12 source types yielded.

## Phase 2 — The Google media layer (measure it; degrade honestly)
Pick the top 1-2 media items per person (≤12 total; prefer ≤45 min). Then:
- **If `CLUE_GEMINI_API_KEY` present:** call the Gemini API (generateContent) with
  `gemini-2.5-flash-lite` (fallback `gemini-3.5-flash-lite`/whatever the key lists): pass the
  **YouTube URL directly** (public videos supported) or the **MP3 URI** from the podcast RSS
  (remote URIs accepted; 32 tokens/sec of audio; ≤9.5h). Ask for a **timestamped transcript
  (MM:SS)** + speaker attribution where inferable + the passages where the target speaks. Record
  tokens + cost (2.5 Flash-Lite: $0.30/1M audio input, $0.40/1M output → ~4¢ per hour of audio).
  Then **`gemini-embedding-2`**: embed the transcript CHUNKS (text, $0.20/1M) — and, for ONE
  short clip (<3 min), embed the raw audio directly ($0.00016/sec) — then run 3 retrieval queries
  ("what does <name> say about ABM/outbound tooling?", "what are they proud of?", "how do they
  evaluate vendors?") against the chunk vectors (cosine in numpy/pure python) and show the
  top hits with timestamps. This is the cross-modal search demo; record cost + latency.
- **If NO key at media time:** fallback = YouTube caption tracks (the public timedtext endpoint —
  no key; try `https://www.youtube.com/api/timedtext?...` or the transcript list in the watch
  page's ytInitialPlayerResponse) + podcast transcript/show-notes pages via Exa `/contents`. Still
  extract timestamped quotes. And write the exact Gemini token/cost math for each media item you
  would have processed, so the founder sees the price of the missing key.
Never transcribe LinkedIn-native or X-native video (walled) — record them as `unfetchable_walled`.

## Phase 3 — One Exa deep-reasoning call per person (the personal charter above as the prompt)
Target-locked ("exact person at exact employer"; same-name exclusions listed), the charter
categories enumerated, "not found" over guessing. Feed the Phase-1 URLs into the prompt as
"already-known sources — read these first".

## Phase 4 — Structure + score
gpt-5-mini per person → `claims_people.json` rows: existing `contact.facet.*` keys
(alma_mater, stated_interests, causes, recent_post, public_appearances, communication_style,
nickname, career_history, awards) + PROPOSED (`contact.facet.hooks` w/ category, `contact.facet.
openers`, `contact.facet.voice_quote` w/ timestamp+media_url) — every row with quote + URL, P1/P2/
P3, `use_class` (professional-public | personal-public-non-sensitive), identity_binding STRONG.
Per person compute a **depth score 0-100** (categories filled × evidence quality) and compare to
the Insight-Health dossier bar (which averaged ~5 hooks/person).

## Phase 5 — Deliverables
`PERSON-DEPTH-REPORT.md` (simple language): (0) what changed vs the smoke test; (1) the Google
multimodal layer — what ran, measured cost/latency per media item, the retrieval demo results, OR
the exact math if no key, plus the ruling "transcribe cheap with Flash-Lite, embed text with
embedding-2, embed raw audio only for short clips"; (2) per person: background/life/voice/
professional/unique-insight/openers with quotes+URLs, source-coverage matrix, depth score, and an
honest "what we could not find"; (3) the segment truth — how much personal depth cybersecurity/SaaS
operators actually expose vs physicians, with numbers; (4) timing + money tables (per person, per
phase, per provider; production extrapolation per person); (5) recommendations: which source
angles earned their cost, which media types matter, what to add to the contact charter
permanently. Plus claims_people.json, media_index.json, transcripts/ (raw), raw/, scripts.
Honesty rules as always: never fabricate; a person with a thin footprint is reported thin.
