# ARV2 sample v3 — correct committee, per-person deep research, signal-ranked, two-layer frontend data

## Why v3 exists (read the v2 postmortem first)
V2 (`.context/arv2-clue-sample-v2/CLUE-SAMPLE-RUN.md`) passed on account depth and cost but
**failed on people**: it took Apollo's roster as the committee source (6 of 10 members unconfirmed,
same-name pet-insurance contamination) and deep-researched only one person. The founder's verdict:
"not the correct people." V3 fixes exactly that, plus three new founder rulings below.

## Founder rulings (binding)
1. **ICP tightened: Series A to Series A+ ONLY** (raised an A or A-extension, roughly within the
   last 24 months; NOT seed, NOT Series B+), US B2B vertical SaaS/AI selling into fragmented SMB
   verticals, **actively hiring** (open roles now, especially GTM), and showing **buying-intent
   signals** (GTM job reqs describing list-building/outbound, founder-led sales at scaling point,
   outbound tooling present or conspicuously absent, no ABM platform).
2. **Deep research on EACH committee person** (not just the primary), with **per-person cost**
   reported.
3. **Signal-prioritized output**: every claim gets a priority rank; the top signals must lead
   every view. Representation must be production-shaped (see the two-layer deliverable).

## Committee correctness protocol (the core fix — follow exactly)
1. **Ground truth from the open web FIRST**: company team/about page (+ /contents fetch), the
   Series-A announcement (investors + quoted execs), LinkedIn via Exa search
   (`site:linkedin.com/in` + company + role), founder posts. Build the committee from THESE.
2. Map each person to Clue personas: CEO/founder = economic buyer; growth/marketing/GTM lead =
   champion; sales lead = user; technical co-founder/CTO = technical evaluator. If a seat is
   vacant (e.g. head of marketing being recruited), record the VACANCY as a signal, not a person.
3. **Apollo is enrichment-only**: `people/match` by name+domain (and org id) for the CONFIRMED
   people → verified email, employment history. Never admit an Apollo-only person to the
   committee. Drop anything whose employer doesn't exact-match the account (the same-name trap).
4. Every member row carries: persona, identity-confirmation URL (non-Apollo), email + status (if
   matched), and confidence. **Correct beats many: 3-6 people.**
5. **Per-person deep research**: one Exa `deep-reasoning` call per confirmed member (3-6 calls),
   single-string-report schema, systemPrompt target-locked (exact person + exact employer),
   covering: identity, career with dates, education, public writing/talks, what they own at the
   company, evidence of how they buy/think (posts, podcasts), NON-SENSITIVE personal hooks,
   2-3 grounded openers. "Not found" over guessing.

## Signal prioritization rubric (apply in structuring; annotate every claim)
- **P1 (top, always shown):** active buying-intent — GTM hiring with quotes, fresh funding
  (amount/date/investors), vacant champion seat, tooling gap (no ABM/outbound platform), founder
  publicly committing to growth targets, timing events <6 months old.
- **P2 (supporting):** firmographics that qualify (size, vertical, customer counts, growth rates),
  committee composition, tech stack.
- **P3 (context):** history, culture/resonance, background facts, personal hooks (hooks are P3 at
  account level but P1 within their own contact view).
Structuring emits `priority: 1|2|3` per claim (a PROPOSED annotation — record the hypothesis:
it powers frontend ordering; check first whether `FieldDef.signal_class` already covers part of
this and say so in the report).

## Proven mechanics (reuse; do not rediscover — read these)
- `.context/arv2-clue-sample-v2/{clue_lib.py, cost_ledger.json, CLUE-SAMPLE-RUN.md §8 and §10}`.
- Exa deep: **one `deep-reasoning` call per subject with a SINGLE free-form string property**
  (`{"type":"object","properties":{"report":{"type":"string","description":"exhaustive cited
  markdown report"}}}`) — v2-proven; no-schema returns NO output; `deep` (lite) is a trap;
  cost scales with pages (16→$0.021, 25→$0.030); handle report as str or {"value":...}.
- Own-site `/contents` fetch first ($0.004 = richest artifact); qualifier probes are $0.007.
- Apollo: contract at `docs/specs/ARV2-apollo-api-contract.md`; org enrich 1cr; api_search 0cr
  (degraded shortlist — v3 uses it only to locate match ids); people/match 1cr email-only
  (NO phone reveal); same-name/org-id traps are live.
- Structuring: **`openai/gpt-5-mini` with `reasoning: {"effort":"minimal"}`** (v2 winner) against
  the closed field catalog (`.context/arv2-clue-sample-v2/field_catalog.py` — reuse it; claims
  100% on registered keys, unmappables → PROPOSED FIELDS with hypotheses).
- OpenRouter real cost = `cost_details.upstream_inference_cost` (usage.cost is 0 under BYOK).
- Budget ceiling: **$2.50 cash, 12 Apollo credits**; cost_ledger.json for every call; 10 req/s Exa.

## The two-layer deliverable (the founder's explicit ask — this is the heart of the report)
The final `CLUE-SAMPLE-RUN.md` §on-representation must show, for each major view, **both layers
side by side**:
- **Layer 1 — "directly from the backend":** the exact production payload shapes. Read the real
  contracts in the worktree first: `apps/frontend/src/features/accounts/model/account-detail.ts`
  and `account-contact.ts` (Zod), `apps/frontend/docs/api-contracts/accounts.md`, and
  `platform/api/clue_api/frontend_read/account_detail.py` + `contacts.py` (serializers). Then
  render the run's claims AS those payloads: the accounts-list row, the account-detail JSON
  (`neutralFacts[]`, `projectSections[].insights[]` with fieldKey/value/provider, `committee[]`,
  `coverage`), and one contact-profile JSON (`professionalFacts[]`, `evidence[]`). Where a needed
  slot doesn't exist in the contract (e.g. priority rank, top-signals block, openers, prose), mark
  it `PROPOSED-SLOT` inline with one-line hypothesis — do NOT invent silently.
- **Layer 2 — "human-readable via a cheap model":** run **`openai/gpt-5.6-luna`** via OpenRouter
  (the platform already uses this model as a reviewer — it is the founder's "GPT Luna"; fallback
  `openai/gpt-5-mini` if unavailable, and say so) over the Layer-1 payloads to produce the display
  layer: (a) a 3-5 sentence account summary paragraph (the Lane-E `account.summary` analog),
  (b) a "Why now — top signals" card: the P1 signals as 3-5 crisp one-liners each with its quote
  chip + source domain, (c) humanized insight labels for every raw fieldKey/value pair ("Raised
  $35M Series A led by a16z — 3 months ago", not raw JSON), (d) per-contact overview paragraph +
  "How to open" lines. Record Luna's exact token usage + cost per account — this layer's price is
  part of the ask.
Show both layers in human-readable form in the .md (Layer 1 as fenced JSON per view, Layer 2 as
the rendered card text beside it). The point: prove the split "backend serves truth; a cheap
display model makes it human" works cleanly against OUR real contracts.

## Run plan (steps)
1. Discovery (Exa, ≤3 searches): the tightened ICP. Series-A recency is a hard filter — verify
   round + date before locking. Lassie (lassie.ai) remains eligible; pick the best fit and justify
   in a candidates table (include why runners-up lost). Exclude Insight Health + Clue.
2. Lock account: own-site /contents + funding-announcement fetch (identity + committee ground
   truth begins here). Apollo org enrich (1cr) for skeleton.
3. ONE account deep-reasoning call (single-string schema; charter covers: what they sell/vertical,
   funding exact, hiring with req quotes, GTM motion + tooling, leadership, ops pain, timing).
4. ≤4 cheap gap-fills for named criticals.
5. Committee per the correctness protocol (web-first; Apollo match ≤4 credits total emails).
6. Per-person deep calls (3-6).
7. Structuring (gpt-5-mini minimal) → claims.json with priority annotations; validate against
   field catalog; zero invented keys.
8. Layer-1 payload assembly (python, deterministic — NOT a model) → Layer-2 Luna pass.
9. `CLUE-SAMPLE-RUN.md`: ingested ICP block → candidates table → account sections (signal-ranked,
   P1 first) → committee table → per-person sections → **the two-layer representation section** →
   claims summary (registered vs proposed; priority histogram) → PROPOSED fields/slots with
   hypotheses → **cost analysis** (per-call ledger; per-account with per-person breakdown; the
   Luna display-layer cost; 10/100/1000 extrapolation; note the v1 qualifier-first option) →
   dossier-bar comparison → honest gaps.
Artifacts: `.context/arv2-clue-sample-v3/` only. claims.json + raw/ + scripts + cost_ledger.json.
No DB writes, no commits, no keys in artifacts. Honesty rules as before: never fabricate; every
number from a real response; UNVERIFIED where unsure.
