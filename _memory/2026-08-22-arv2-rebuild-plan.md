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
