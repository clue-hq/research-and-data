# 2026-08-26 — ARV2 sample run v3 (Probook): correct committee, per-person depth, two-layer representation

Artifacts: `.context/arv2-clue-sample-v3/` (git-excluded). Report: `CLUE-SAMPLE-RUN.md`.
Live spend **$0.23394** / 6 Apollo credits / 34 calls. No DB writes, no commits, no key leakage (verified).

## What it was for
v2 (`.context/arv2-clue-sample-v2/`) failed on people — Apollo's free people-search was used as the
committee *source*, giving 6 unconfirmed members of 10 and same-name contamination. v3 inverts the order
and adds three founder rulings: Series A–A+ only ICP, deep research on EACH committee member with
per-person cost, and signal-prioritised output; plus an explicit two-layer frontend-representation
deliverable.

## Account
**Probook (probook.ai)** — NY, 52 emp, founded 2024. $34M Series A led by a16z announced 2026-06-23
(+$6M Sequoia seed, $40M total). AI operating system for home-services contractors (plumbing/HVAC/
electrical), built around dispatch, ServiceTitan overlay. 13 open reqs, **6 GTM**. Apollo detects **no
CRM / no sales-engagement / no ABM platform** in 30 technologies; the SDR req's CRM instruction is
"maintain records **in Ashby**" (their ATS).

## The committee protocol that worked (reusable)
1. Own `/company` page + funding announcements via Exa `/contents` ($0.008 for 8 pages).
2. **Ashby public posting API is FREE and authoritative**:
   `https://api.ashbyhq.com/posting-api/job-board/<slug>?includeCompensation=true`.
   **403s on urllib's default UA — send a browser User-Agent.** Full `descriptionPlain` + `jobUrl` +
   `publishedAt` per req.
3. **The committee-discovery primitive:** Exa search with `includeDomains:["linkedin.com"]` +
   `includeText:["<Company>"]`, `numResults:15`. Returns the profile, the person's own joining post AND
   the company's announcement post — 3 corroborating artefacts per person, $0.012/call.
4. Apollo `people/match` by `linkedin_url` + `name` + `domain`, **hard gate on
   `organization.primary_domain == account domain`**. 5/5 admitted, titles exact-matched the web.
Result: 5 people, 5/5 web-confirmed BEFORE Apollo, 0 contaminants, 4/5 verified emails.

## Findings that must not be re-derived
- **The account deep-research charter CANNOT find the GTM leadership layer.** It returned "CRO and
  director-level growth/sales leaders: NOT FOUND" while the $0.024 dedicated LinkedIn search found all
  three (CRO, Director of Growth, Director of Sales & Development). Committee discovery is a *separate
  retrieval problem*, not a sub-goal of the account charter. **Do not fold it into the account call.**
- **Batching subjects into one structuring call destroys recall on rare high-value signals.** Measured on
  the identical prompt/model: 5-subjects-batched → 4 rows, all for subject 1, stopped at 604 completion
  tokens. **One-subject-per-call → 16 rows across all 5**, 1.5× the price. Confirms the orchestrator/
  worker-per-entity bet one level down: **one extraction call per subject, always.**
- **Schema validation cannot catch semantic field misuse.** `core.employee_range` was written as
  `{"label":"14 open positions listed","min":14,"max":14}` from the span "Open Positions (14)". Valid
  schema, wrong meaning, and both layers rendered it faithfully. Same class as v2's `employee_count: 23`.
  Needs a **semantic** write-time check.
- **Exa `output.grounding` is now POPULATED** (16 document-level `{url,title}` citations) — this
  **reverses v2 finding #3**. Still not span-level.
- **Exa neural search is billed PER RESULT** (10→$0.007, 15→$0.012). v2's "flat $0.007" was an artefact of
  only ever asking for 10.
- **Exa `deep-reasoning` = $0.015 flat at 10 pages** on all 6 calls (v2: 16p→$0.021, 25p→$0.030).
- **OpenRouter prompt caching now engages for gpt-5-mini** (17,536 cached tokens → **50% cost cut** on a
  repeat call). v2 measured 0. Largest available structuring saving, now quantified.
- `usage.cost` still 0 under BYOK — use `usage.cost_details.upstream_inference_cost` (now baked into the
  v3 `clue_lib.openrouter`).
- **A display model must never emit a URL** — Luna re-typed one LinkedIn slug and dropped a word (1/12,
  8% corruption). Pass an opaque `evidenceId`.

## Costs (recommended production config, 5-person committee)
**$0.1564 + 6 Apollo credits per account** = research $0.1471 + display $0.0093.
Per committee member: **$0.01688 + 1 credit** ($0.015 Exa deep + $0.00188 structuring).
Committee depth = 54% of cash, 83% of credits. Two-pass tiering at 20% deep: **$39.68 / 2,200 credits per
1,000 accounts** (4.0× cheaper on cash, 2.7× on credits, than uniform depth).
Layer-2 display (`openai/gpt-5.6-luna`): ≈$0.30/M in, $1.20/M out → **$0.0093/account**.

## The two-layer representation (Layer 1 read off the REAL contracts)
Contracts read: `apps/frontend/src/features/accounts/model/{account,account-detail,account-contact,
vocabulary}.ts`, `apps/frontend/docs/api-contracts/accounts.md` §As-built FI-2 slice 1,
`platform/api/clue_api/frontend_read/{accounts_list,account_detail,contacts,committee}.py`,
`libs/clue-core/clue_core/contact_research.py::CONTACT_PROFESSIONAL_FIELD_KEYS`.

Three contract gaps found, all real and all phase-1 integration decisions:
1. **`projectSections[].insights[]` is empty for any account without a `project_relative` pack.**
   `account_detail.py:411-419` — the FI-1-era insight families are all `project_neutral`, so `insights`
   means "a pack field that declares itself relative" and nothing else. Every P1 buying-intent signal is
   therefore flattened into `neutralFacts` or homeless.
2. **`neutralFacts[]` has no rank and no quote.** 8 P1 rows sort alphabetically among 15 P2/P3 rows;
   `evidence_span` is on no wire anywhere.
3. **The contact-profile wire serves 4 Apollo firmographics and nothing else.**
   `CONTACT_PROFESSIONAL_FIELD_KEYS` is exactly six keys and includes NEITHER `core.work_email` NOR any
   `contact.facet.*`. **Ten researched facts about the champion have no production surface**, including
   the email a credit was paid for. `signals.typeCount` (an int, whitelisted to 2 fields) is the only hint.
   Consequence measured: Luna wrote "a verified work email is available" for the one contact whose email
   is `unavailable` — **a fact with no slot cannot be denied either.**

A/B measured: same model, same prompt, as-built payload vs a payload with `priority` + `topSignals[]` +
the `vertical_saas.*` pack → the proposed version costs **$0.0002 less** and turns two filler lines into
the SDR-req quote and the tooling-gap line. **The display layer was never the bottleneck; the payload was.**

## PROPOSED (details + schemas in the report §7)
- `claim.signal_priority` (smallint 1–3). **Checked `FieldDef.signal_class` first — it does NOT cover
  this**: `signal_class` is a *field-level theme name* pairing a Pass-A proxy with its Pass-B narrative
  (`field.py:167-171`); priority is per-**claim**, per-**ICP** and time-decaying. Orthogonal, both needed.
- Wire: `neutralFacts[].priority`, `account.topSignals[]` (needs the quote AND a path to CONTACT claims).
- `vertical_saas.*` pack **[v2, re-confirmed on a 2nd account]** — especially `gtm_stack` with its
  `absent[]` array (`core.primary_tech_stack` is a flat `list[str]` and **cannot encode absence**, which
  is the qualifying signal) and `open_gtm_roles`.
- `contact.facet.tool_evaluation` (new) — the champion publicly comparing Riveter vs Clay for ABM list
  building, 4 weeks before the run, currently degrades to free-text `recent_post`.
- Widen the contact-profile wire (a parallel `researchFacts[]`, keeping the frozen six frozen).
- `contact.facet.openers` **[v2, re-confirmed]** — 15 grounded openers produced, still no field.
- `evidenceId` + resolution endpoint (also fixes the URL-corruption class). Ordering constraint:
  `CLAUDE.md` [B2×presign/frontend] requires the presign scope gate first.
- `Persona` enum still missing `USER` **[v2, re-confirmed]** — a smaller committee concentrated the
  problem rather than removing it.

## Operator error to not repeat
`step10_merge_validate.py` imported `step9_structure` to reuse its stamp helper; step9's module body is
unguarded and **re-executed both OpenRouter structuring calls — $0.01682 unintended spend (7% of the
run)**. Fixed by appending `--from-cache` to `sys.argv` before the import. Any future step-script that
imports another step must guard the import.
