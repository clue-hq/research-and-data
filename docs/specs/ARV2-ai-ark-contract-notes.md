# ARV2 — AI Ark evaluation: verified contract, costs, and the A/B protocol vs Apollo

**Status:** review document, 2026-08-27. Verified live from ai-ark.com, docs.ai-ark.com (get-started,
people-search, people-export-single, mobile-phone-finder, people-analysis, llms.txt index,
pricing, about-us) plus one third-party review (coldemailkit.com). Companion to
`ARV2-apollo-api-contract.md`.

## 1. The company

AI Ark is a spin-out of **AI bees** (a B2B lead-gen agency): founders Brian (CPO) and Hamied
(CSO); concept 2020, team assembled 2022, **launched 2025**, ~30 people. Not disclosed anywhere:
legal registration, location, funding, SOC2. Claims: **70M+ companies, 400M+ profiles**, every
record refreshed within 30 days, emails verified in real time at export via **BounceBan**,
"aggregate data exclusively from public sources," "fully GDPR and CCPA compliant" (asserted, not
audited). The profile shape (position history, skills, badges, follower counts) is plainly
LinkedIn-derived at scale — same gray zone as every competitor, worth naming.

## 2. Verified API contract

Base `https://api.ai-ark.com/api/developer-portal`, headers `X-TOKEN: <key>` +
`Content-Type: application/json`. **5 req/s** (429 beyond). Keys from the app dashboard.

| Endpoint | Cost (credits) | Notes |
|---|---|---|
| `POST /v1/people` (People Search) | **0.5 / result** | Max 100/page, 10k/search cap, 300 values/filter. Returns a `trackId` (6h, single-use) for email enrichment. |
| `POST /v1/companies` (Company Search) | **0.1 / result** | Lookalike + semantic search; filter by 919 industries, 16k technologies, funding (type/amount/date), dept-level headcount growth, revenue, foundedYear. |
| `POST /v1/people/export/single` | **0.5 profile + 0.5 email, email part only if found** | Input: AI Ark `id` OR LinkedIn URL. **Synchronous.** Email block carries MX record, provider, `status: VALID`, free/generic flags (BounceBan). |
| Bulk export / find-emails by trackId | same unit costs | Async with statistics + results endpoints + **webhooks** for completion. |
| `POST /v1/people/mobile-phone-finder` | **5 / found, 0 otherwise** | Input: LinkedIn URL, or domain+full name. **Synchronous — no webhook required** (vs Apollo's mandatory webhook). No confidence/DNC metadata in the response. |
| `POST /v1/people/analysis` (Personality) | 4 / request | DISC + OCEAN + archetype + email-writing guidance + whatToSay/whatToAvoid + risk/decision-speed. Model-inferred. |
| Reverse lookup 0.5; Preview 1/page; lists & credit checks free | | MCP server + Clay templates exist (agent-native). |

**The headline difference vs Apollo:** AI Ark's *search* response is a **full profile** — real
full name, **LinkedIn URL**, title, headline, complete `position_groups` with dates, education,
certifications, skills, languages, follower/connection counts, `member_badges`
(hiring / open_to_work / premium), embedded company with technologies + revenue + SIC/NAICS —
for 0.5 credits. Apollo's 0-credit search is deliberately obfuscated (no last names, no
LinkedIn URL) and the full record costs a match call. AI Ark search **is** the identity surface
ARV2's v3 run had to reconstruct with targeted Exa LinkedIn searches — and the returned LinkedIn
URL directly addresses the v3 gap "startups have no registry-grade identity anchor."

**Red flags in the payload:** `profile.birth_date` exists — **never write it to the claim store**
(personal data with no outreach use-class; same rule as Melissa's Gender). Phone responses carry
no DNC status (Apollo's async payload does) — calling compliance stays ours.

## 3. Pricing

Free: 100 credits/mo, ≤25 records/search, no card. **Premium $49/mo: 5,000 credits**, rollover to
2× allowance, cancel anytime. Enterprise custom (third-party review: up to ~$9,999/mo for 5M
credits). Volume: **$2–$4 per 1,000 credits above 30k/mo**, i.e. **$0.002–0.004/credit** at
volume, ~$0.0098/credit on Premium.

Per ARV2 unit (Premium → volume): committee shortlist of 25 full profiles **$0.12 → $0.03**;
verified email **$0.01 → $0.002–0.004**; mobile phone **$0.05 → $0.01–0.02** (vs Apollo's
8 credits + webhook infrastructure); tech-stack/company lookup **~$0.001–0.01**. A 5-person
committee (shortlist + 5 emails + 2 phones) ≈ **$0.27 Premium / $0.07 at volume** — with full
profiles included, which in v3 cost extra Exa calls to recover.

## 4. What incorporation requires (small — the seam already exists)

1. `Secrets.ai_ark_api_key` + `CLUE_AI_ARK_API_KEY` env line (additive).
2. A seeds row: `source_key="ai_ark"`, tier 1, `extraction_method=api`,
   `identity_binding` prior STRONG when matched by LinkedIn URL (a real per-person anchor),
   WEAK on name+domain.
3. One client module (same shape as the ARV2 Apollo client): people_search, company_search,
   export_single (email), phone_finder, optional personality. Persist raw responses via the
   existing snapshot/artifact family; claims stamped per the ARV2 matrix; `source_url` = the
   returned LinkedIn URL (a real citable locator — better provenance than Apollo offers).
4. Personality output, if used, is **advisory annotation only** (charter: judgment annotates,
   never claims) — it is model-inferred, not quote-grounded, so it never becomes a sourced claim.
5. Rate limiter at 5 rps; 404-on-no-phone and email-found-only billing map cleanly onto our
   honest-empty semantics.

## 5. Honest caveats

- **One year in market**, agency spin-out, no disclosed funding/registration/SOC2; independent
  coverage is thin and one review shows an unexplained "Trust Score: 2%". Vendor risk is real:
  keep the provider-neutral seam so removal is a config flip.
- Coverage claims (95% ICP match, <1% bounce, +30-50% catch-all reach) are **marketing until our
  canary proves them**; LinkedIn-centric coverage likely shares Apollo's small-local-business
  weakness.
- GDPR/CCPA compliance is asserted; their data is scraped-public-web at scale. Same posture
  question as every provider in this class — our use-gate and facet rules stay the control.

## 6. Recommended decision protocol (before touching the Apollo integration)

**A/B canary on the free tier (100 credits, $0):** re-run the Probook committee through AI Ark
and score against the v3 ground truth — (a) are all 5 members found with correct titles +
LinkedIn URLs? (b) does it return the email Apollo missed (Kate Blumberg)? (c) email validity
(send-time bounce check) and phone hit-rate vs Apollo's; (d) same-name contamination behavior
(the pet-insurance-Lassie test); (e) profile freshness (Hoffman joined Feb 2026 — is he there?).
If AI Ark wins ≥3 of 5, it becomes the committee/enrichment provider and Apollo drops to
fallback (or is not renewed); if it loses, it cost nothing. Either way the ARV2 design is
unchanged — this is a resolver swap behind the same seam, which is exactly why the seam exists.
