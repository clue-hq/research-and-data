# ARV2 Clue-simulated sample run — execution brief (planner: Fable; executor: Opus 5)

## Mission
Simulate one full Clue account-research pass exactly as the future agent will run it, with the
founder-ratified division of labor: **Exa discovers the account → Apollo reveals the buying
committee + enrichment → Exa Deep Research produces the depth — ONE deep call per subject.**
Produce one structured .md the founder reviews, plus claims keyed to the platform's real schemas,
plus a complete cost analysis with alternatives. This is the go/no-go gate before we build the
real agent loop.

## The cost architecture being tested (the whole point)
The previous sample needed 7 deep calls because Exa's `outputSchema` has a hard 10-property /
depth-2 budget. This run inverts the design: **deep calls carry NO outputSchema** — one
free-form, citation-rich report per subject (maximum information per call) — and a **cheap
OpenRouter model pass** structures the reports into claim rows afterward. Targets:
- Account: exactly **1** Exa `deep-reasoning` call (+ ≤4 cheap `/search` or `/contents` gap-fills
  at ~$0.007 each, only for named critical gaps like fax numbers).
- Contact: exactly **1** Exa `deep-reasoning` call for the one selected contact.
- Apollo: org enrich (1 credit) + people api_search (0 credits) + people/match for ≤2 contacts
  (1 credit each; **no phone reveal** — needs a webhook we don't have).
- Structuring: OpenRouter cheap model — try `z-ai/glm-4.7` first (founder asked about GLM),
  fall back `openai/gpt-5-mini`; record actual model + token usage + cost.
- **Hard ceiling for the entire run: $2.00 and 12 Apollo credits.** Record every call's actual
  cost (`costDollars` from Exa, credits/headers from Apollo, usage from OpenRouter).

## Context the agent "ingests" (the Clue workspace — put this block at the top of the report)
**The client is Clue itself.** Clue is an AI-native ABM orchestration platform: agents discover
target accounts, enrich account/contact data, run dossier-grade deep research on accounts and
buying committees, draft personalized campaign content (including direct mail), and scale
artifacts across contacts. We are finding the right BUYERS FOR CLUE and their buying committees.

- ICP (hypothesis, stated in the report as such): US vertical B2B SaaS / AI startups, seed to
  Series B, ~10-200 employees, selling high-touch products into FRAGMENTED SMB/mid-market
  verticals (medical practices, dental, legal, logistics, construction back-office). Founder-led
  or first-GTM-hire sales motion; outbound + direct mail; no enterprise ABM platform installed
  (6sense/Demandbase absent = greenfield). The archetype customer is a company like Insight
  Health (an AI referral/fax-automation startup selling to GI practices) — but DO NOT research
  Insight Health itself (founder conflict; exclusion below).
- Priority signals: recent seed/Series A/B funding (budget + growth pressure); hiring for
  "founding AE", SDR, growth, demand gen, or GTM roles; outbound tooling in the stack (Apollo,
  Clay, Instantly, Outreach, HubSpot); founder/company content about outbound, personalization,
  or ABM pain; a named fragmented target vertical; direct-mail or field-marketing usage; small
  marketing team (0-3 people).
- Account priorities: sells into a fragmented vertical (their need for account research at scale
  is structural) > funded within ~18 months > actively hiring GTM > outbound stack present >
  founder-led sales visible.
- Buying-committee personas for Clue: CEO/co-founder (economic buyer at this company size),
  Head of Growth / Marketing / founding GTM lead (champion), sales lead / first AE (user,
  influencer), technical co-founder or CTO (technical evaluator / blocker on data + integrations).
- Exclusions: do NOT pick Insight Health or any Clue-affiliated entity; avoid huge companies
  (>1,000 employees) and pure consumer companies.
- The two dossiers (read them; they are the DEPTH AND STRUCTURE BAR — the domain differs, the
  section depth is the target):
  `.context/attachments/KUYDzB/digestive-healthcare-of-georgia-p-c.md`,
  `.context/attachments/MewEB3/eagle-physicians-associates-p-a.md`.

## Required reading before any call (all in /Users/shashank/conductor/workspaces/research-and-data/winnipeg)
1. `docs/specs/ARV2-apollo-api-contract.md` — verified Apollo endpoints/auth/response shapes/gotchas.
2. `docs/specs/ARV2-schema-impact-audit.md` §2–§3 — the claim stamping matrix (copy it exactly).
3. `.context/arv2-sample-20260825/run_sample3.py` + `SAMPLE-RUN-REPORT.md` — prior art + proven Exa wire facts.
4. The REAL field keys (schema authority — read via git, the branch is fetched):
   `git show origin/platform/comprehensive-account-contact-research:subsystems/research/clue_research/claimstore/packs.py` (CORE_PACK)
   `...:subsystems/research/clue_research/profiling/fields.py` (RESONANCE_PACK, FACET_PACK)
   `...:subsystems/research/clue_research/icp/packs.py` (HEALTHCARE_PRACTICE industry pack)
   `...:subsystems/research/clue_research/profiling/committee/fields.py` (committee fields)
   Claims MUST use an existing registered field_key when one fits. Anything that doesn't fit goes
   under **PROPOSED FIELDS** with: proposed field_key, value_schema, description (agent-facing),
   reuse_scope, and a one-paragraph hypothesis for why the platform needs it.

## Proven wire facts (do not rediscover)
- Exa: `POST https://api.exa.ai/search`, header `x-api-key` (key: `CLUE_EXA_API_KEY` in repo-root
  `.env`). Body: `{query, type: "auto"|"fast"|"deep"|"deep-reasoning", numResults, systemPrompt?,
  contents: {text:{maxCharacters:10000}, highlights:{query, maxCharacters:2000}}, stream:false}`.
  WITHOUT outputSchema the `output.content` may be a STRING (markdown report) — handle str|dict.
  `costDollars.total` per response. Rate limit 10 req/s (429 + plain-text error; retry w/ backoff).
  Deep calls last run: 3–12 s, $0.012–0.021 each (schema-bound; free-form may cost more — record it).
- Apollo: base `https://api.apollo.io/api/v1`, header `x-api-key` (key: `CLUE_APOLLO_API_KEY` in
  `.env`, just validated live). Endpoints for this run:
  `GET /organizations/enrich?domain=…` (1 credit; response wrapped `{"organization": {...}}`);
  `POST /mixed_people/api_search` (0 credits; response `people[]` is DEGRADED — obfuscated last
  names, has_* booleans — it is a shortlist, NEVER claim-store truth);
  `POST /people/match` (1 credit; full person incl. `email`, `email_status`, `employment_history[]`;
  do NOT set reveal_phone_number — webhook required);
  optional `GET /organizations/{id}/job_postings` (1 credit/page) for the hiring signal.
  Read rate-limit headers (`x-*-requests-left`); per-team limits.
  **Known trap (observed on the validation call):** domain-only people search on a small practice
  returned ONE person under a name-variant org ("Digestive Health Care Ga"). So: enrich the org
  FIRST, then people-search by `organization_ids` AND by domain, union results. If Apollo coverage
  is thin on the picked account, that is an honest finding — record it and let the Exa deep
  report's leadership section carry the committee (that is the expected pattern for small
  practices; Apollo's email enrichment is still the win).

## The run, step by step
1. **Discovery (Exa, ≤3 cheap searches, numResults 10):** query the Clue ICP above (e.g.
   vertical AI/SaaS startups selling into medical/dental/legal practices, recently funded,
   hiring GTM). Pick ONE account with a real domain that best matches the account priorities.
   Record every candidate with a one-line fit rationale (this simulates account prioritization).
2. **Apollo org enrich** on the picked domain → skeleton (employee count, address, phone,
   industry, linkedin, technographics/funding if present). Convert to claims (source_key
   `apollo`, tier 1, `api`).
3. **THE account deep call** (`deep-reasoning`, numResults 25, no outputSchema): systemPrompt =
   a target-locked research charter naming the exact company + domain, demanding: what they
   sell and to which vertical; funding history with dates/investors/amounts; team size and GTM
   team composition; GTM motion evidence (outbound, direct mail, ABM, founder-led sales) and
   tooling; hiring signals (open GTM roles with quotes); ownership/entity disambiguation
   (same-name traps); leadership names with roles (CEO, growth/marketing, sales, technical
   co-founder); operational pain and strategic moves; culture/resonance signals (blog tone,
   employee sentiment, public frustrations); timing signals with dates; every fact with a
   verbatim quote + URL; "not found" over guessing.
4. **Gap-fill (≤4 cheap calls)** only for named criticals still missing (e.g. funding round details, team page, open GTM roles).
5. **Committee:** merge deep-report leadership + Apollo people search (seniorities: founder,
   c_suite, vp, head, director). Map each member onto the Clue personas (economic buyer /
   champion / user / technical evaluator). Pick 1 primary contact (CEO or growth/GTM lead). `people/match` them (and at most one more) for work
   email + employment history. Every committee member in the report carries its source
   (apollo vs open-web) and identity-confirmation status.
6. **THE contact deep call** (`deep-reasoning`, no outputSchema) on the primary contact:
   identity confirmation, career, education, awards, NON-SENSITIVE personal hooks (hometown,
   alma mater, hobbies, tenure milestones, community; NEVER health/faith/politics/family
   tragedy), suggested openers grounded only in found hooks.
7. **Structuring pass (OpenRouter):** feed both reports + Apollo JSON + the field-key list;
   emit claim rows exactly per the stamping matrix (§3 of the schema audit): Exa-derived →
   `exa_research`/tier 4/`llm_synthesis`/UNVERIFIED/tenant_private (+ facet rows carry
   identity_binding STRONG only when identity-confirmed, and use_class); Apollo-derived →
   `apollo`/tier 1/`api`. Unmappable facts → PROPOSED FIELDS. Validate every row has
   source_url; quoted rows carry evidence_span.
8. **Deliverables** in `.context/arv2-clue-sample-v2/`:
   - **`CLUE-SAMPLE-RUN.md`** — THE file the founder reads. Structure: (0) ingested context
     block; (1) discovery table w/ prioritization; (2) the chosen account, section by section in
     dossier shape, every fact with quote+source, explicitly framed as "a human view over the
     claim rows below"; (3) committee table (name, title, source: apollo|web, confirmed?); (4)
     the enriched contact incl. email + email_status; (5) contact deep sections; (6) claims
     summary — counts by field_key, existing-vs-proposed split; (7) PROPOSED FIELDS with
     hypotheses; (8) **COST ANALYSIS** — per-call actuals table, per-account total, extrapolation
     to 10/100/1,000 accounts, Apollo credit math vs plan sizes, and alternatives comparison:
     GLM vs gpt-5-mini structuring (measured where possible), Exa deep vs deep-lite vs
     build-your-own loop (fast search + contents + model synthesis — estimate from this run's
     actuals), Parallel Task API, Firecrawl, with a clear recommendation for cheapest
     dossier-grade config; (9) verdict vs the dossier bar — an explicit section-by-section comparison table (dossier
     section -> this run's equivalent -> depth reached) + honest gaps.
   - `claims.json` — every row. Raw responses + the script(s).
9. **Honesty rules:** never fabricate; every cost number from a real response; UNVERIFIED where
   unsure; if the picked account turns out thin (tiny web footprint), say so and show what a
   second candidate would cost rather than padding.

## Hygiene
Work only in `.context/arv2-clue-sample-v2/` (gitignored). No DB writes, no commits, no pushes.
Never print API keys into any artifact. Python3 stdlib only (urllib), like run_sample3.py.
