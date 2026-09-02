# 2026-08-22 — ARV2 account-research rebuild plan (planning session, no code)

Founder (Shashank) directive: tear down the account-research build and redo it from scratch for
the accounts section only — dossier-grade depth (Insight Health samples), Apollo for
account/committee identification, Exa retained, Sumble dropped (402s + 100x cost), MelissaData
for direct-mail addresses, claim-store schema and fleet shell unchanged, minimal mechanical
guardrails (Aryan's note: any surviving gate must return actionable feedback the deep agent can
act on). Deliverable this session: **`docs/specs/ARV2-account-research-rebuild-plan.md`** —
proposal awaiting founder ratification.

## What the audit established (five parallel agents + branch forensics)

- The live system is `origin/platform/comprehensive-account-contact-research` (411 commits ahead
  of main): M8D fleet + R11 DEEP bridge, 21-field account / 15-field contact profiles, prose
  synthesis, M12.1 positioner, FI-4 auth, design Part II. `CLUE_PRODUCT_PATH=integration_pilot`
  already forces verification + budget enforcement OFF; spend caps are record-only.
- The branch's own `_memory/2026-08-20-pipeline-guard-inventory.md` (~500 guards): the real
  problems are ~20 judgment gates (retire list), ~12 wrong-failure-species guards (suspend instead
  of recoverable refusal), 2 kill-switch inversions (judge-off makes typed interview values
  unwritable; inline Corroborator blocks field resolution), plus harness wedges (job-scoped
  settlement folds → permanent pending, checkpoint-replayed poison calls bypass the refusal
  renderer, encrypted-reasoning pins a job to its model). Truth/infra floors never fired wrongly.
- Committee emptiness is commercial: Sumble 402 on /people and /techs. Model capability is NOT the
  blocker (Grok forensics: correct research sequence unprompted, one-turn self-repair).
- Claim store already admits free-flowing writes: (field_key, value, source_url, quote) inserts;
  only C7's read gate (`research_view_governance.py:317-336`) is a non-toggleable verified-only
  gate. `FieldDef` has no description but `field_definition.description` exists via
  `register_field`.
- Apollo resolver EXISTS built-but-unwired (`resolvers/apollo/`, Clay-alternative reference);
  so do NPI/DUNS/CIK/LEI, ZoomInfo/Clay/BuiltWith, Parallel, Firecrawl. Melissa absent.
- Frontend renders new research fields with zero change (generic fieldKey rendering on
  /frontend/v1); prose needs prose claims; C7 nine-block view has no consumer.
- Vendor verification (2026): Apollo org search/enrich/job-postings/people-search(0-credit)/
  people-match(+8cr mobile, webhook); master keys tier-gated; LinkedIn-centric quality (weak on
  small/local businesses — verify-don't-trust for medical practices). Exa research API removed
  2026-05-01 → /search type=deep|deep-reasoning with outputSchema + grounding citations ($12-15/1k).
  Melissa Business Coder + Global Address Verification, REST JSON, credits (~$40/10k 3P), docs
  crawler-blocked. ZoomInfo enterprise-gated (~$50k/yr) — out.

## Plan shape (see the spec for detail)

Keep: claim store schema/DB, fleet shell + entity_research_* durable schema, agent runtime
(create_agent + AsyncPostgresSaver), deepagent anatomy + packs-with-descriptions, human gates,
tenancy/append-only/artifact substrate, frontend contracts, Lane-E prose + M12.1.
Rebuild: source stack (Apollo + Exa + NPI + Melissa; no waterfall/tier routing), an 11→new direct
tool surface (search_web / fetch_page / research_deep / apollo_* / lookup_registry / write_claims /
verify_links / finalize), ICP-compiled dossier pack replacing the fixed 21/15 profiles, guardrail
charter (2 gates: write-shape validation with actionable refusals + human authority; failure-
species law; judgment annotates never vetoes; SENSITIVE-never-outreach floor kept).
Delete/quarantine: Sumble stack (R1 pattern), the 20 judgment gates, the 2 inversions, waterfall/
tier plans, six still-blocking money guards → record-only.
Base: new branch cut from platform/comprehensive-account-contact-research (NOT main, NOT a fresh
repo — cost argument in spec §4). Phases 0-6 each with live browser exit gates; acceptance
fixtures = the two Insight Health dossiers.

## Open (founder decisions, spec §9)

Branch base ratification (needs Aryan), Apollo plan purchase + master-key confirmation, Sumble
cancellation date, research model + relaunch-over-resume, Melissa trial, the §7 rulings
(inversions/C7 gate/money guards), sensitive-hook posture, old-lane disposition.

## Session hygiene

No code changed. Working tree: this note + the spec only. Nothing pushed. The five audit briefs
were session-ephemeral; their content is condensed into the spec's §1.

## Addendum 2026-08-23 — critical re-evaluation (founder pushback)

Founder challenged the v1 plan; produced three review docs (all committed):
- `docs/specs/ARV2-deep-agent-build-runbook.md` — six recorded revisions of the v1 plan (Day-1 is
  the Exa-only agent since Exa/OpenRouter keys exist and Apollo needs a purchase; zero old-lane
  file edits — quarantine, don't refactor; ICP-compiled qualifier fields deferred; Melissa + C7
  governance dropped from build scope; the stamping matrix + explicit durable-layer split were the
  two under-specifications that would have reproduced "mechanical failures"), plus the job-by-job
  line-by-line runtime walkthrough and the day-1/2/3 deliverables checklist with exit gates.
- `docs/specs/ARV2-schema-impact-audit.md` — ZERO Alembic migrations; head stays 612428f3731f;
  all ~14 claim CHECKs/triggers mapped to born-valid stamping rules; new source keys exa_search/
  exa_research to dodge the exa_deep/sumble per-source-key lineage CHECKs; R4/R5 authority/
  settlement tables left dormant (trade-off documented); the single existing-test edit is the
  seeds frozen fixture.
- `docs/specs/ARV2-apollo-api-contract.md` — live-doc-verified Apollo contract. The repo's
  resolvers/apollo assumed contract is wrong on 6 counts: base URL (/api/v1 not /v1), auth
  (x-api-key header not query param), response wrappers ({"organization":{...}}, person+request_id),
  work_email mapped onto the org endpoint (emails only via people/match), funding field names
  (total_funding not funding_total_usd), and nonexistent apollo_url/confidence keys. Also:
  people api_search is deliberately degraded (obfuscated last names, 0 credits) — shortlist only,
  never claim-store truth; phones are webhook-only with _cd-suffixed async field names; rate
  limits are per-team; org search returns organizations[] AND accounts[] (merge both).

## Addendum 2026-08-23b — Melissa verified (docs blocked; OpenAPI specs used instead)

`developer.melissa.com` / `docs.melissa.com` BLOCK our fetcher. Authoritative substitute found:
Melissa's own GitHub org publishes machine-readable specs —
`MelissaData/MelissaCloudAPI-OpenAPI-Specifications`, `openapi/apis/*.yaml` (people-business-search,
global-address-verification, us-business-coder, personator-consumer, personator-search). Use `gh api`
+ raw.githubusercontent for these; result-code tables and pricing remain blocked-doc only.

Doc written: `docs/specs/ARV2-melissa-address-contract.md`. Verdict:
- **Contact Search (the founder's link) is the WRONG tool and ARV2 will not use it.** Server
  `search.melissadata.net/V5/WEB/contactsearch`, GET/POST `/docontactSearch`, auth `id`=license key.
  Input sets: address / phone / (full|last|anyname|comp)+adminarea|postal. Response `Consumer` block
  has NO title, NO email, NO employer join; `Address` block has NO DeliveryIndicator (no R/B flag).
  So "person X at company Y → their office address" is not expressible; you get a name+geography
  match with `MatchLevel` (<80 = questionable) against a consumer index = WEAK identity binding,
  typically a home address. Personator Search is explicitly skip-tracing (current/previous address,
  DOB/DOD) — same family, also out.
- **Right tools:** Global Address Verification (`address.melissadata.net/V3/WEB/GlobalAddress`,
  `/doGlobalAddress`, POST batch maxItems=100) → `FormattedAddress`, `SubPremises`, ZIP+4 appended
  when verified, **`DeliveryIndicator` R/B/U**, `MelissaAddressKey`, `Results` AV/AC/GS codes; plus
  **US Business Coder** (`businesscoder.melissadata.net/WEB/BusinessCoder`, `/doBusinessCoderUS`)
  which accepts **`web`=domain** (Apollo gives us this) and returns `Suite`, `Plus4`,
  `CurrentCompanyName` (identity cross-check), **`LocationType` 0=HQ/1=Branch/2=SubHQ/3=Single**,
  `MelissaEnterpriseKey`, EIN/SIC/NAICS/Employees/Sales. Its `Contacts[]`
  {NameFirst,NameLast,Gender,Title,ContactPhone,Email} exists but ARV2 does NOT use it for committee
  discovery; `Gender` must never be written.
- Melissa = verifier, not locator: Apollo/Exa decide who + which site; Melissa proves the address is
  deliverable. Mail goes to the verified BUSINESS address with the person as the Attn line.
- Claim store: still zero schema change — new `core.mailing_address` object field row + `melissa`
  source seed; no citable URL from Melissa (use snapshot + MelissaAddressKey as provenance).
- **Sequencing recommendation: defer Melissa to the direct-mail export epic (Phase 5).** There is no
  recipient-address slot in the design/content schema and no mail-merge consumer today, so buying it
  now ships a field nobody reads.
- Founder to check in-portal (blocked for us): per-endpoint credit costs, whether People/Business
  Search is separately contracted (permissible-use terms), and the AV/AC + AS/DA/FS result-code
  tables so we can pin the "safe to mail" allow-list.

## Addendum 2026-08-24 — Eve.dev evaluated and declined

Founder brought a ChatGPT-agent review of Eve.dev (Vercel beta TS filesystem-first durable-agent
framework) asking whether ARV2 should be built on it. Re-verified Eve docs directly. Decision note:
`docs/specs/ARV2-eve-framework-decision.md`. Verdict: NO — the reviewer's own rule (Python+LangGraph
backend ⇒ don't add a Node runtime) plus the repo-context mapping: every Eve capability (durable
steps/replay, filesystem catalog, parked approvals, isolated subagents, sandboxes, evals) already
exists in the platform runtime, and Eve lacks exactly what Clue has (tenancy, rate limits, caching,
audit). Eve replay semantics verified: completed steps replay recorded results; interrupted steps
RE-RUN ⇒ idempotency keys — same law our snapshots already implement. Kept from the review: the
10-account benchmark (accuracy/citation coverage/latency/cost), pointed at ARV2 instead of Eve.
Backlog ideas: schedules for freshness re-research; evals-directory convention over M9.6.

## Addendum 2026-08-25 — live sandbox sample PASSED (+2 founder rulings)

Founder rulings this session: (1) **discovery is Exa's job; Apollo is committee-only** (revises the
v1 plan's Apollo-primary discovery); (2) three principles pinned: find accounts -> deep research
(with user confirmation between) -> populate the frontend through the DB schemas. Eve stays
declined; adopt its compaction-policy + context-layout + evals-directory ideas only.

Ran the live ARV2 pipeline sample in `.context/arv2-sample-20260825/` (Exa key from workspace .env;
Apollo key still absent -> dry request emitted). 7 schema-bounded deep calls + discovery, $0.101
total, 19 claims with quote+URL, stamped per the matrix. **Headline: caught the CEO transition the
static dossier missed — Gaye Pennington retired June 2026; Erika Noll is the new CEO** (practice FB
video + her LinkedIn). Answer-key comparison + wire-contract lessons in RESULTS.md there; the
critical ones: Exa outputSchema hard budget = 10 properties/depth 2 (400 otherwise), output.content
is a dict, 10 req/s account limit, deep calls 3-12s at $0.012-0.021. One quote/URL-mismatch row
observed -> validates the verify_links audit skill. Day-1 build de-risked: the exact tool payloads
are now proven against the live API.

## Addendum 2026-08-25b — two Opus sample runs complete (medical validation + Clue-ICP deliverable)

Founder correction mid-stream: the sample client is CLUE ITSELF (find buyers for Clue), not the
dossier's medical ICP. Run 1 (.context/arv2-clue-sample/, Charleston GI) kept as architecture
validation — headline: picked account DISQUALIFIED (runs gGastro, proven 3 ways for $0.007 after
the deep call said NOT FOUND; Apollo technographics independently showed Klara). Run 2
(.context/arv2-clue-sample-v2/, THE deliverable): **Lassie (lassie.ai)** — dental-practice AI
startup, $35M a16z Series A 3mo ago, 16 open roles/4 GTM, no ABM stack in 60 technologies, sales
headcount 0, champion seat (Head of Mktg) VACANT, GTM Associate job req literally describes Clue's
product. Committee: 10 mapped to personas; CEO steijn@lassie.ai + founding GTM max@golassie.com
(NOTE different domain — deliverability trap) both VERIFIED emails, 2 credits. 52 claims, 100% on
registered field keys, 0 check_claim_writable failures, all with quote+URL. 9 proposed fields
(vertical_saas pack + canonical account.customer_count etc.) + **Persona enum lacks `user` — core
contract-delta needed**. Dossier-bar verdict: met on structure/evidence/depth; one structural gap =
no registry-grade person identity anchor for startups (no NPI equivalent; LinkedIn URL is closest).

Costs (measured): run 2 spend $0.23 + 3 credits. Production: **$0.090/account + 3 credits**;
two-pass tiering @20% deep = **$0.025/account**; run-1 qualifier-first probe makes a disqualified
account cost $0.0077 + 0 credits. 100 accounts ≈ $7.82-14.52.

ARV2 build corrections learned (paid for, do not relearn):
1. Exa deep WITHOUT outputSchema returns NO output at all (billed anyway). THE pattern: one
   deep-reasoning call with a SINGLE free-form string property ("report") — uncapped cited
   markdown, dodges the 10-property budget. `deep` vs `deep-reasoning` output shapes differ
   (string vs {"value":...}); handle both. Cost scales with pages retrieved (16→$0.021,
   25→$0.030), not list price. `deep` (lite) is a trap: cost-similar, asserted stale facts run 2's
   deep-reasoning refused.
2. Structuring: disable reasoning tokens for extraction (gpt-5-mini reasoning:minimal = 35%
   cheaper, 1.7x faster, +75% claims; GLM-4.7 slower/pricier and emitted wrong JSON keys run-2;
   GLM silently returned EMPTY with reasoning on run-1). Structuring is 82% of wall clock.
3. write_claims MUST take a closed field-key enum from the registry (run-1's free-text key let the
   model invent 65 one-off keys); run-2's field_catalog approach → 100% registered keys.
4. Own-site /contents fetch FIRST ($0.004 = richest artifact), then qualifier probe, then Apollo,
   then the one deep call. Don't build own search loop ($0.061 vs $0.021 measured).
5. Apollo: same-name org contamination live (pet-insurance Lassie people in committee);
   departmental_head_count contradicts its own people index; match can return people under a
   different org id. OpenRouter BYOK: real cost is cost_details.upstream_inference_cost
   (usage.cost=0 under-reports 24%).

## Addendum 2026-08-27 — AI Ark evaluated (docs/specs/ARV2-ai-ark-contract-notes.md)

Founder surfaced ai-ark.com as a cheaper Apollo/ZoomInfo alternative. Verified live: AI bees
spin-out (launched 2025, ~30 ppl, founders Brian/Hamied, no disclosed funding/SOC2). Contract:
base api.ai-ark.com/api/developer-portal, X-TOKEN header, 5rps. People search 0.5cr/result
returns FULL profiles (real names, LinkedIn URLs, position history, education, skills,
open_to_work/hiring badges, embedded company w/ technologies+SIC/NAICS) — vs Apollo's obfuscated
search; this closes v3's "no identity anchor" gap. Email export 1cr found-only w/ BounceBan
MX/status detail; phones 5cr SYNC no webhook (vs Apollo 8cr+webhook); personality DISC/OCEAN 4cr
(advisory-only per charter). $49/5k credits; $2-4/1k at volume. 5-person committee ≈ $0.27→$0.07.
Red flags: birth_date in payload (never write), no DNC on phones, 1yr-old vendor, asserted-only
compliance, one review shows unexplained "Trust Score: 2%". Ruling proposed: $0 free-tier A/B
canary re-running the Probook committee vs v3 ground truth (5 checks incl. the Blumberg email
Apollo missed) before touching the Apollo integration; either way it's a resolver swap behind the
same seam. Committed locally, NOT pushed.

## Addendum 2026-08-27b — AI Ark canary check (b) PASSED (founder manual test)

Founder ran Kate Blumberg (linkedin.com/in/kibrady12 — the maiden-name-slug record where Apollo
matched the profile but returned a NULL email while charging the credit) through the AI Ark
studio: **returned `kate@probook.ai`** — matching the verified firstname@ pattern of her four
teammates. Strongest possible single-record signal (the exact Apollo failure case). Remaining
canary checks before any provider decision: validity metadata (BounceBan status VALID vs
catch-all on probook.ai), all-5-committee retrieval, same-name contamination test, freshness
(her Jun 2026 start date), phone hit rate. Protocol in docs/specs/ARV2-ai-ark-contract-notes.md §6.

## Addendum 2026-08-29 — AI Ark live canary 5/5 PASSED → takes the committee/enrichment slot

Founder supplied API key (in .env as CLUE_AI_ARK_API_KEY, gitignored). Full battery vs Probook
ground truth in .context/ai-ark-canary/: all five checks passed (roster 59 ppl incl. possible 3rd
co-founder Ben Cervantez + visible GTM hiring wave; kate@probook.ai; SMTP-vs-CATCH_ALL metadata;
464→1 same-name discrimination; Jun-2026 freshness; Mark Hoffman mobile via sync domain+name call,
5cr). Ruling recorded in ARV2-ai-ark-contract-notes.md §7: AI Ark = committee/enrichment provider,
Apollo = fallback. Wire lessons: needs browser UA (Cloudflare 1010), free-tier rate limit ≪ 5rps
(pace + backoff), phone endpoint needs {domain,name} not URL, credit endpoint 401-unknown,
personality API canned — skip. Email claims must carry domainType+status (verified only when
SMTP+VALID). Deep research remains Exa's job — AI Ark returns no quotes/signals/job-req text.

## Addendum 2026-08-31 — cluehq.ai smoke test COMPLETE (two Opus agents, $0.51, 10.4 min provider time)

Full report: .context/arv2-smoke-cluehq/SMOKE-TEST-REPORT.md. Agent A (ICP Architect) derived
Clue's ICP from www.cluehq.ai (Exa index = byte-identical to live; site's /privacy + /terms 404 —
tell founder); signal-first job-board search won discovery (20/20 real companies; generic semantic
search returns competitors' blogs; founder-pain angle = pure vendor SEO — demoted). Picked 5:
Zafran 81 / Cogent 80 / Harmonic 79.5 / Uptiq 67.5 / Vendelux 66.5 (honesty: only 3 cleared its
own >=75 bar). Agent B researched all 5, tested A's predicted intent ranking:
- **Zafran 4th->1st** (buying 90): ABM req live on Ashby API, 105 days unfilled, ad describes
  Clue verbatim ("Own ABM from the ground up: 1:1... 1:few... 1:many"); required-tools list has
  no ABM platform. A's own falsification probe worked as designed.
- Cogent held #2/#1 (88/92.5/90): 6 new marketing reqs; Head of Growth public "need more
  teammates" post 8/14.
- **Harmonic dropped to #3** (62): the ABM req was CONVERTED to a BDR seat — but the hiring
  manager's ad listed "account mapping, outreach, direct mail, events" = 4 of Clue's 5 agents.
  Also corrected A's funding misparse (17.5M Next47 Oct-2024, not Apr-2025).
- **Vendelux DISQUALIFIED as competitor** (their Meetings product = AI attendee targeting) —
  caught before any outreach would have gone out.
Emails 5/6 found, ALL SMTP+VALID (vari@/nick@zafran.io, cameron@cogent.com, ana@/tyler@
harmonic.security), 5cr; 1 AI Ark provider defect (search finds Semien, export 404s same URL).
53 people mapped, 32.5cr total (credits were the binding constraint, not cash). One same-name
contamination caught.
Costs: $0.507 total; per-account $0.076-0.173; production ~$0.155 full / ~$0.015 cheap pass.
Latencies: Exa deep 46.3s, gpt-5-mini 21.6s, AI Ark 1.3s, direct fetch 0.22s.
**Scraping verdict: Scrapling needed ZERO times** (40 free fetches, 0 blocked; Exa 16/17 = urllib
16/17, the miss a genuine 404). **Free public ATS APIs (Ashby/Greenhouse/Lever) were the star —
$0, 1.3s, and drove every ranking change** -> first-class pipeline source. Ladder ratified:
direct GET -> ATS API -> Exa contents -> Exa deep -> stealth (403-triggered only).
System lessons: (1) schema gap — no home for GTM hiring; proposed account.hiring.gtm_open_roles
(P1 signals squeezed into prose without it); (2) A's hiring detector blind to non-ATS companies
(Arintra had 5 GTM roles on its own /careers — A said zero); (3) the research model REFUSED an
operator-asserted false fact (Vendelux CEO) citing sources — trust point; (4) 6% paraphrased
quotes flagged not hidden -> verify_links audit earns its place; (5) Series-A rule blind spot
(Oscilar self-funded $20M, excluded as written — founder ruling wanted); (6) 3/5 picks were
cybersecurity unprompted; healthcare = build-mode, zero GTM hiring. 203-claim sample DB, 0
unregistered fields. Sample DB + report ready as ARV2 acceptance evidence for wiring the new
toolbelt into Head of ABM.

## Addendum 2026-08-31b — Person-Depth run COMPLETE ($1.29, 8.8 min, 10 people)

Founder correction: the smoke test omitted the personal-hooks charter (planner's omission). Re-run
with the full dossier charter + Google media layer: .context/arv2-person-depth/PERSON-DEPTH-REPORT.md.
**Results:** avg depth 61/100, avg 7.2 hooks/person, **8/10 at or above the Insight-Health bar
(~5 hooks)**; alma mater 10/10, unique insight 10/10, hobby/book/side-project 7/10, long-form
spoken voice 3/10 (all CEOs — the marketing buyers are the least researchable). Standouts: Nick
Fisher = cocktail YouTuber with a published book; Sanaz Yashar = 15y Unit 8200 + Thai boxing;
Vineet Edupuganti = 2016 Siemens Grand Prize (full transcript); Tyler Chonoles = Bowdoin golf
roster (guitar/skiing); Alastair Paterson = $160M ReliaQuest exit + school-band concert at 15.
5/10 zero hometown; 0/10 any X/Bluesky/Threads/Reddit presence.
**Media layer:** NO Gemini key present (checked twice). Hard finding: YouTube public timedtext
endpoint is DEAD (200/0 bytes across 7 request forms) — delete that path. Rescue: **Exa /contents
on the YouTube watch URL returns the full ASR transcript for 4/5 videos at ~$0.001-0.004, no
timestamps**. Exact Gemini math for the 12 items (5.04h audio): transcribe $0.20 + embed text
$0.014 + raw-audio-embed 2 short clips $0.036 = **$0.25 total = $0.04/hour**; raw-audio-embedding
everything = $2.90 (13.5x). Ruling confirmed: transcribe with Flash-Lite, embed text with
embedding-2, raw audio only <3 min. gemini-embedding-2 IS multimodal (correction to earlier
sessions). Key still needed for timestamps + the two CEO podcast interviews.
**Money:** $1.286 (Exa $1.188 = 133 searches $0.924 + 11 deep $0.241 + contents; OpenRouter
$0.098); **$0.129/person, trimmed recipe $0.07/person** (400-person sweep ≈ $28). 0 AI Ark credits.
**Angles:** winners = prior-employer+long-form-voice, podcast, authored, alumni; CUT video-search,
podcast-directories, Substack/Medium, awards, social = 27% of cost, zero unique yield.
`includeDomains` is a trap (forces same-name strangers).
**Surprises:** (1) the deep call beats the sweep feeding it — 16% of cited URLs unseen by 120
sweep queries, incl. the best hook; (2) Exa deep-reasoning fails SILENTLY — signature = 9
results/$0.015 vs 18-20/$0.023 — add an auto-retry guard; (3) structuring conservatism said
"thin footprint" for 7/10 people whose dossiers held gold — one narrow $0.002 question per person
fixed it 3/10 → 10/10.
**Governance in code:** minors clause stripped a self-published post mentioning a CEO's children;
Yashar's first-person intelligence-origin line barred from hooks (`outreach_safe: false`) while
career kept as background; 2 quote-less rows auto-purged; 119 claims, 0 missing quote/URL.
Recommend `outreach_safe` as a permanent facet field (accuracy ≠ appropriateness).
