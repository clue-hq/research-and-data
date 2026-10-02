# ARV2 smoke test — Clue's own ICP from cluehq.ai: two-agent brief

**Date:** 2026-08-31. **Working dir:** /Users/shashank/conductor/workspaces/research-and-data/winnipeg
**Artifacts:** `.context/arv2-smoke-cluehq/` ONLY. Keys in repo-root `.env` (CLUE_EXA_API_KEY,
CLUE_AI_ARK_API_KEY, CLUE_OPENROUTER_API_KEY). No DB writes, no git commits, no keys in artifacts.
**Ceilings:** $3.00 cash total, **50 AI Ark credits** (free tier has ~70 left — respect this hard).
**Timing is a first-class deliverable:** wrap EVERY phase and EVERY provider call with wall-clock
timing; maintain `timing.json` (phase → seconds) and `cost_ledger.json` (per call: provider, op,
elapsed, cost/credits) throughout. The founder explicitly asked "measure how much time it's taking
each and every time."

## Proven wire facts (do NOT rediscover — from 3 prior live runs)
- Exa: POST https://api.exa.ai/search, header x-api-key. Search type=auto numResults≤10 ≈ $0.007
  (billed per result). /contents for page text (~$0.004). Deep research = type="deep-reasoning"
  with outputSchema = ONE property {"report": {"type":"string","description":"exhaustive cited
  markdown report"}} + contents{text:{maxCharacters:10000},highlights:{query,maxCharacters:2000}}
  + numResults 20-25 + stream:false; NO-schema returns NO output; `deep` (lite) is a trap;
  output.content may be str or {"value":...}; costs $0.015-0.030, 10-30s; 10 req/s limit —
  pace ~1/s, retry 429 with backoff. Target-locked systemPrompt; verbatim quote + source url per
  fact; "not found" over guessing.
- AI Ark: base https://api.ai-ark.com/api/developer-portal, headers X-TOKEN + Content-Type +
  **a browser User-Agent (Cloudflare blocks default clients with 403 code 1010)**. Pace ≥10s
  between calls (free-tier 429s well under the documented 5rps). People search POST /v1/people
  body {"account":{"domain":{"any":{"include":["<domain>"]}}},"page":0,"size":N} at 0.5cr/result
  — **cap size at 12 per account**; full profiles incl. linkedin + position dates. Email export
  POST /v1/people/export/single {"url": "<linkedin>"} = 1cr found-only; email block carries
  status + domainType (record BOTH — verified only when SMTP+VALID). NO phone calls this run
  (save credits). Same-name discipline: only admit people whose current position matches the
  exact account.
- Structuring: OpenRouter POST /api/v1/chat/completions, Bearer key; model "openai/gpt-5-mini"
  with reasoning minimal; ONE SUBJECT PER CALL (batching destroys recall); closed field-key list
  (reuse `.context/arv2-clue-sample-v2/field_catalog.py`); real cost =
  cost_details.upstream_inference_cost.
- Prior art to reuse: `.context/arv2-clue-sample-v3/clue_lib.py` (transport), the v3 scripts,
  `docs/specs/ARV2-sources-and-variables-architecture.md` (the stack ruling).
- python3 stdlib only (urllib). Save every raw response under raw/ before parsing.

---

## AGENT A — "ICP Architect" (phases A1-A4)

### A1. Ground in the real product + the Exa-vs-live comparison (the founder's item 1)
Fetch **https://www.cluehq.ai** (and its key subpages: product/how-it-works/pricing/about if they
exist) TWO ways, timed separately: (a) live HTTP (urllib, browser UA); (b) Exa /contents on the
same URLs + Exa search for "Clue cluehq.ai ABM platform" to see what Exa's INDEX holds.
Deliverable `comparison-exa-vs-live.md`: side-by-side — is cluehq.ai in Exa's index at all? Is the
indexed copy current vs the live page? What does each method cost/take? Verdict in one paragraph:
what this means for using Exa on very young companies (Clue itself is one — this is the freshness
lesson made personal). If the live site blocks urllib, record it — that is the scraping data point.

### A2. Product context + buyer personas
From the site content (quote it), write `product-context.md`: what Clue actually sells (in the
site's own words), the jobs it does (account discovery, research, committees, personalized
campaigns/direct mail), and who buys: define 3-4 personas with THEIR pain in one line each —
Head of Growth / VP Marketing / ABM-or-GTM manager / founder-led-sales CEO. Persona mapping to
the platform's committee vocabulary (economic_buyer/champion/user/technical_evaluator).

### A3. The ICP, synthesized (`icp.md`)
Hard rules from the founder: **US, Series A and above, pain quantifiable**. You choose the
highest-potential verticals (B2B SaaS, healthcare-adjacent SaaS, agencies — justify). The ICP doc
must contain: firmographics; motion criteria (outbound/ABM-shaped GTM, high-ACV named-account
selling); **quantifiable-pain evidence classes** (GTM hiring reqs describing list-building/
research, no ABM tooling detected, founder posts about outbound pain, small marketing team + big
target market); disqualifiers (B2C, PLG-only self-serve, enterprise ABM platform already
installed, <Series A); and a 0-100 scoring rubric with weights.

### A4. Discovery + selection of 5 (queries are a deliverable)
Run 4-8 Exa searches (type=auto, ≤10 results each) across at least 3 angles (semantic ICP,
signal-first e.g. GTM job reqs, vertical-specific). **Record every query string verbatim with its
verbatim result list** in `discovery.md`. Exclusions: probook.ai, lassie.ai, avoca (already
studied), Insight Health, Clue. Dedup candidates. Score each candidate against the A3 rubric with
a one-line rationale (cheap evidence only — no deep calls in Agent A). Verify Series-A+ and US
for the finalists with cheap searches. Output `candidates.json`: ALL candidates scored +
`selected_5` with predicted fit scores and the specific signals that drove selection.
Write `A-handoff.md`: the 5 accounts, why, what Agent B should verify/deepen per account, and
your predicted intent ranking (to be compared against researched reality).

Agent A budget: ≤ $0.40, 0 AI Ark credits. Target wall-clock ≤ 12 min of provider work.

---

## AGENT B — "Research Executor" (phases B1-B5) — reads A's outputs first

### B1. Per-account research (all 5, timed per account)
For each account: own-site /contents read → 1 Exa deep-reasoning call (account charter: what they
sell/vertical, funding EXACT with dates+investors, GTM team + hiring with req quotes, tooling,
leadership names, ops pain, timing signals) → ≤2 cheap gap-fills → AI Ark people search (size≤12)
merged with web-found leadership (web-first rule; same-name discipline).

### B2. Contacts (deep research where needed — founder's words)
Top-3 accounts only (your intent ranking): 1 Exa deep call on the PRIMARY contact (growth/marketing
lead if exists, else CEO) + AI Ark email export for ≤2 contacts per top-3 account (≤6 emails
total, record status+domainType). Accounts 4-5: committee table + cheap evidence only.

### B3. Reputation/negatives pass (founder's item 11 "what negative things are reasonable")
Top-3 accounts: 1 cheap search each aimed at criticism (reviews, complaints, churn, layoffs,
controversy). Report findings honestly — including "none found" — and one line per account on
what negatives mean for the outreach approach (e.g. don't reference layoffs; a bad G2 thread
about their current tooling is an OPENER, not a landmine).

### B4. Structuring + the sample database
gpt-5-mini per subject → `claims_<account>.json` rows per the ARV2 stamping matrix (registered
field keys from field_catalog.py; P1/P2/P3 priority on every claim; quote + source_url mandatory;
unmappables → proposed_fields list). This is the founder's "sample database."

### B5. The final report — `SMOKE-TEST-REPORT.md` (THE deliverable, simplest language)
Assemble: (0) what this test was, one paragraph; (1) A1's Exa-vs-live comparison verdict;
(2) the ICP one-pager; (3) the exact queries table (query → what came back → kept/discarded why);
(4) the 5 accounts, one section each: fit score (predicted vs researched — call out where Agent A
was wrong), the insights with quotes+sources, the committee table (persona, confirmed-by, email+
status where bought); (5) **TOP-3 BY INTENT** with a 3-row scorecard each (buying intent / fit
intent / ICP intent, each 0-100 with the evidence line) + a plain-words "how to approach this
account" playbook per account (who first, what opener, which channel, what NOT to say per B3);
(6) the timing table (every phase + every account, seconds) and the money table (per provider,
per account, total; extrapolate per-account production cost); (7) **scraping verdict**: count
pages Exa served vs pages blocked/missing across the whole run; state whether Scrapling was
actually needed today, and the recommended structure (the fetch-ladder ruling) in 5 lines;
(8) honest gaps + what surprised you. Simple language throughout — the reader is a non-technical
founder.

Agent B budget: ≤ $2.60 cash, ≤ 50 AI Ark credits. If any ceiling nears, degrade gracefully
(fewer deep calls on accounts 4-5) and record the decision. Honesty rules: never fabricate;
every number from a real response; UNVERIFIED where unsure; a thin account is reported thin.
