# ARV2 — Sources & variables: production architecture for custom variables, industry packs, the awareness layer, and frontend placement

**Status:** review document for the founders, 2026-08-30. Grounded in: the account-section
screenshot (2026-08-30), the verified pack anatomy on Aryan's branch (`icp/packs.py`,
`icp/catalog.py`, `claimstore/registry.py`), the frontend contract rulings
(`apps/frontend/docs/api-contracts/accounts.md` D-7/§877), the durable crawl plan
(`FI-stage0-durable-official-site-crawl-plan.md`), and the three live sample runs.

---

## 1. The account page, region by region — what produces each pixel

From the founder's screenshot (OpenAI example):

| Region | What it is | Produced by |
|---|---|---|
| **Account summary** + **About their business** | prose paragraphs | Luna display pass stored as prose claims (Lane-E pattern) over the account's claims |
| **Overall fit: High** + ✓/✗ bullets (headline + supporting sentence, incl. the honest ✗ "not publicly disclosed") | the fit assessment | fit claims with rationale (M12.1-style positioner over P1/P2 signals); the ✗ row is an honest-empty rendered as a negative — a feature, not a failure |
| **Insights & evidence** (dated headlines with links) | the signal feed | P1/P2 claims ordered by priority + date, each linking its `source_url` |
| **Core** rail (Account, Industry chips, Headcount, Revenue, Website, socials, Locations) | fixed variables | `core.*` claims — AI Ark skeleton + Exa; socials come free in AI Ark's `link` block |
| **Owner** | a human assignment | CRM datum, not research — user-set, never agent-written |
| **Research status: "Fully enriched"** | run state | the research job's finalization state projected per account |
| **Overall buying fit / Fit Score 75** | scores | score claims (`account.scoring.*`, reserved tenant-private) |
| **Custom** section ("Recall fit — Medium" with the ⚡ agent mark) | **registered custom fields** | §2 — the field registry; rendered generically off `fieldKey` (already built, ruling D-7) |
| **Contacts** | the committee | committee claims + contact entities (web-first + AI Ark) |
| **Activity** | events | run/claim events projection |

**The load-bearing fact:** the frontend contract already rules (accounts.md §735–746, §877) that
industry-pack/custom fields arrive **dynamically off `fieldKey` with no schema change and no
adapter** — the fixture placeholders were deliberately dropped for exactly this. The Custom
section in the screenshot is that ruling rendered. Nothing new is needed for custom variables to
*display*; what §2 defines is how they come to *exist* and get *researched*.

## 2. Custom variables ARE the field registry — the end-to-end mechanism

There is no second system to build. A "custom variable" is a `field_definition` row, which is
exactly what Aryan's `_field(...)` pack entries author. One row carries everything research needs:

`field_key` (namespaced) · `value_schema` (typed, validated at write) · **`description` (the
agent-facing meaning — this is what the research charter quotes)** · `pass_kind` (cheap-scoring vs
deep) · `freshness_ttl` · `reuse_scope` (privacy class) · `research_scope` (project-neutral vs
project-relative) · optional source hints.

**How one is born — two doors, same row:**
1. **Settings (manual):** the user defines "Recall fit" → the platform registers
   `gi.recall_fit` (their pack namespace) with an agent-assisted `value_schema` (enum
   low/medium/high) and a description written *for the researcher* ("Does the practice run an
   automated colonoscopy recall program? Medium = manual recall staff exists, no automation.").
2. **The agent (proposed):** during research the structuring pass hits a fact with no home → it
   files a **field proposal** (the v3 propose-field channel) → the user approves in Settings →
   same row. The agent never silently invents keys (the closed-enum lesson, paid for in run 2).

**How research populates it:** the per-workspace **field catalog** is compiled from the registry —
core pack + active industry packs + the workspace's custom fields — and that catalog is what (a)
the research charter enumerates ("research these fields; here is each one's description") and (b)
the `write_claims` tool accepts as its closed key enum. So the loop closes with zero new
machinery: **user adds the variable → next run researches it → claim lands with quote + source →
the Custom section shows it.** The ⚡ mark in the screenshot = claim-backed value (with its
provenance one click away); a manually-set value renders without it.

**Scoping rule (zero migrations):** custom fields live in a per-client pack namespace (or the
`client.*` class, already workspace-scoped by convention in `icp/catalog.py`); their **claims**
are always `tenant_private`. The *definition* being globally visible is harmless — collisions are
avoided by namespace; two clients wanting the same key with different meanings get suffixed
namespaces. No `field_definition.workspace_id` column is needed for V1; revisit only if
definition-privacy itself becomes a requirement.

**Quality rule that matters more than any code:** the `description` IS the research instruction.
A vague description produces vague claims. Settings should treat writing it like writing a prompt
— and the agent-assisted authoring step exists to make that good by default.

## 3. Industry packs — what is actually in them, and how they change research

Verified anatomy (three starter packs ship today, deliberately skeletal):

- **`frontier_ai`** — `frontier_ai.arxiv_activity` (int, scoring, arXiv/Semantic-Scholar sourced,
  public-footprint) + a canonical resonance contribution `account.resonance.research_prestige`
  (deep). Source profile: arXiv HI, Semantic Scholar HI, GitHub HI, research-X HI, press MED,
  Glassdoor LO.
- **`healthcare_practice`** — `healthcare.npi` (deterministic registry id, tier-1, 180d TTL).
  Source profile: NPI HI, CMS HI, Google/Places HI, job boards HI, journals LO.
- **`data_infra`** — `data_infra.migration_signal` (deep technographic). Source profile: job
  postings HI, BuiltWith HI, engineering blogs MED.

Three design ideas in there that ARV2 keeps and amplifies:
1. **A pack = a pre-authored bundle of custom variables + a source-weighting profile.** Loading a
   pack for a client is `load_pack` (INSERT rows) — never a pipeline fork.
2. **The `source_profile` is Aryan's own "where to look" design** — per-vertical weights over
   source *classes* (reviews LO for AI labs, job boards HI for healthcare). ARV2's research
   charter honors these weights as retrieval-angle priorities. The old `tier_plan` waterfall
   routing is retired; the field's source hints become advisory charter input, not authority.
3. **Packs may contribute canonical fields** (`pack=None`) — a vertical can extend the shared
   resonance vocabulary without forking it.

**What changes for research when a pack loads:** the field catalog grows (the charter now names
`healthcare.npi` and quotes its description → the registry tool gets called), the source weights
shift (job boards rise, journals fall), and the Custom section of every account in that workspace
gains the pack's columns as claims land. The packs need **filling out** — each starter pack has
1–2 fields where a real vertical wants 8–15 (the Insight Health dossier implies the full
healthcare set: `gi.ehr_vendor`, `gi.runs_ggastro`, `gi.owned_endoscopy_centers`,
`gi.referral_intake_mode`, `gi.prior_auth_workload`, `gi.recall_fit`…). Authoring those rows is
data work the agent can draft and the founder approves — no code.

## 4. The awareness layer — "we don't have enough sources" → what we create

Founder rulings encoded: **Firecrawl is OUT of account research** (it remains only as a stage-0
crawl alternative). The account-research fetch stack is **Exa + Scrapling**. What gets created is
four things, none of them a new subsystem:

### 4a. The fetch ladder (one `fetch_page` tool, three rungs)
1. **Exa `/contents`** — the indexed copy: instant, $0.004, the best-value call in every run.
2. **Scrapling** (`ScraplingPageFetcher` — already built, credit-free, BSD, stealth incl.
   Cloudflare-Turnstile bypass, adaptive selectors) — when the page is unindexed, stale, or
   bot-walled. This is how review pages, job boards, and blocked practice sites get fetched.
3. There is no rung 3 in account research (per ruling). A page neither rung can fetch is an
   honest `unfetchable` disposition.

Additionally: **point the existing durable crawl capability** (Postgres frontier + ledger +
fenced claiming — accepted C0–C10, currently stage-0-scoped) **at tier-1 account sites**. New
composition, zero new machinery: rosters, pricing pages, per-office fax lines — the things
one-shot search partially missed in every run — come from a bounded site sweep with Scrapling as
the fetcher.

### 4b. The source-class expansion (seed manifests, honoring Aryan's source_profile design)
New registered source classes — data rows, not code: **reviews** (G2/Capterra/Trustpilot/app
stores/BBB — public pages, quoted per page, APIs are partner-gated and we say so), **community**
(Reddit, HN, vertical forums), **podcast/video** (episode pages + YouTube transcripts — free;
audio transcription deferred until a concrete gap demands it), **job boards** (Ashby/Greenhouse/
Lever public JSON APIs — free and authoritative, proven in run 3), **news/PR**, **social posts**.
Each class gets a manifest with an identity-binding prior and the pack source_profiles weight
them per vertical. The **reputation charter** (one extra ~$0.03 deep call on tier-1 accounts,
explicitly hunting criticism and churn stories) is the retrieval discipline that fills
`account.resonance.*` — including the negatives, which models omit unless ordered to find them.

### 4c. The evidence corpus — where the Google embedding model actually lives
The embedding model is not a fetcher; it is **the memory over everything fetched.** Every
artifact the platform captures (pages, reviews, transcripts, reports) gets normalized → chunked →
embedded (`gemini-embedding-001`, $0.15/1M tokens ≈ $0.001 per account) → stored in **pgvector,
which the workspace databases already provision** (.conductor/settings.toml; confirm the prod DB
image before relying on it). That buys, in order of value: a `search_evidence` tool ("what do we
already know about X across everything we ever collected?"), semantic claim dedup, and
client-specific lookalike discovery (embed won accounts, nearest-neighbor the candidate pool).
This is the one place a genuinely new table (+ `CREATE EXTENSION` if absent) is justified — a
deliberate, single, deferred migration, Phase 2 of the awareness layer, not on the build's
critical path.

### 4d. The confirmed production stack and sequence
| Order | Tool | Job |
|---|---|---|
| 1 | **Exa search** (+ Websets for bulk/monitors) | discover accounts; semantic + signal-first pathways |
| 2 | **AI Ark** | the database: rosters, identities, LinkedIn anchors, emails (SMTP-vs-catch-all recorded), phones; company filter/lookalike search |
| 3 | **Exa `/contents` → Scrapling** ladder (+ durable crawl on tier-1) | fetch: own site, reviews, job boards, communities |
| 4 | **Exa deep research** | one call per subject: account, each committee member, + the reputation charter |
| 5 | **Free registries & job-board APIs** (NPI/CMS/SEC; Ashby/Greenhouse/Lever) | deterministic anchors + hiring truth |
| 6 | gpt-5-mini (structuring) → **gemini-embedding** (corpus) → Luna (display) | claims → memory → human-readable |
| — | Apollo | fallback only |

## 5. Frontend placement — the complete map

Already renders with zero work: everything in the Core rail, the Custom section (generic
fieldKey), Contacts. Needs the already-proposed slots (each a small backend+Zod PR, founder
parity sign-off per the house rule): prose slots (summary/about paragraphs), the fit-bullets
block (headline + support + ✓/✗ state), the Insights feed ordering (priority + date + source
domain), the contact research surface (career/education/hooks/openers/email-with-status), and
`evidenceId` so display copy references sources without re-typing URLs. The screenshot's page is,
almost region for region, the Probook report §Layer-2 rendered into the design — which is the
strongest possible sign the architecture and the design already agree.

## 6. Open decisions (founders)
1. Bless the custom-variable mechanism (§2) incl. the agent propose→approve loop and the
   description-quality rule.
2. Commission the healthcare pack fill-out (the dossier-derived field list) as the first real pack.
3. Ratify the fetch ladder + Firecrawl-out-of-research ruling + durable-crawl-on-accounts
   composition.
4. Approve the source-class seed set + reputation charter as tier-1 standard.
5. Phase-2 go/no-go on the evidence corpus (the one new table/extension).
6. The frontend slot PRs, one sign-off each.
