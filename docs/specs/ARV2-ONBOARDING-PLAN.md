# ARV2 ONBOARDING PLAN — Track O: onboarding as a research pipeline, the synthesis agent, and the Head-of-ABM integration

**Status:** PROPOSED for Aryan's rulings (decision boxes O-D1–O-D6 in §12). Version 1.0,
2026-09-07. Once initialed, this is the authoritative plan for Track O; the master plan's Track O
paragraph points here.

**Parent:** `ARV2-MASTER-PLAN.md` (Track O). **Children already written:**
`ARV2-PRODUCT-CATALOG-CONTRACT.md` (lineup + product-set gate + rulings P1–P4),
`ARV2-COMPANY-OVERVIEW-CONTRACT.md` (overview, live-validated). The three remaining research
contracts (reviews, per-product, evidence tool) and the synthesis-agent contract are sections of
this document (§4–§6) rather than separate files, until a founder rules otherwise (O-D6).

**Standing rule** (`ARV2-PRODUCT-CATALOG-CONTRACT.md` §10;
`_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`): nothing on any path in this plan may
demand a Client-KB version, a readiness decision, or a Stage-0 run pin. The seven-item checklist is
run at O1, O4, O6 and O7.

---

## 1. Outcome, and what is already settled

**Outcome.** A client types a domain. Within minutes the brand-context page fills, read-only, with
the company overview, the product lineup, the customer reviews, two to three ICP proposals and one
audience-persona document per ICP, each appearing as it lands; per-product research keeps arriving
in the background. The Head-of-ABM reads those files itself before the first Stage-0 exchange,
proposes from the ICP files, and the human confirms an ICP and a product set through the two
existing human gates. Nothing is scraped as a primary source; nothing is stored as a company claim.

**Settled (Aryan, 2026-09-07), restated so this document stands alone:**

| # | Ruling |
|---|---|
| S1 | No scrapers as primary source. Exa Agent runs (deep research) and Exa search (deep-reasoning + `outputSchema`) replace the fast/background recon scrapers. The brand-kit ingestion stays as it is. |
| S2 | Fast recon = company overview ∥ product lineup ∥ customer reviews (O-D3) → ICP synthesis → one persona document per ICP. Background = one Exa Agent run per discovered product, in parallel, capped. |
| S3 | Seller-company knowledge is markdown artifacts in the brand-context Knowledge folders, rendered read-only; never Client-KB claims. |
| S4 | The Head-of-ABM reads the files itself (`read_file`, `grep`) before conversing. Nothing from them enters the opening context verbatim; only an L2 index card (path, version, status per file). |
| S5 | ICPs live at **brand** level: 2–3 per company, each naming the products it applies to. A project picks exactly one (P3). The project's product set defaults from the ICP's products and is edited at the product-set gate (P1/P2). |
| S6 | Personas: one document per ICP, one section per role in that ICP's `persona_map`; no fictional names; no invented numbers; bullet counts are maximums. The optional evidence pass (one deep-reasoning search per role) is on, and thin evidence is acceptable. |
| S7 | The persona/ICP prompts are prompts for **our** synthesis agent, not for Exa. The agent calls Exa through a governed tool whose request template is fixed inside the tool. |
| S8 | Rulings P1–P4 and D14–D17 (multi-product per project, versioned set, one ICP per project, the catalog schema) stand. |

---

## 2. Architecture

```
POST /onboarding (domain, brand)  ──►  onboarding_run row; driven on the FLEET (never the web loop)
   │
   ├─ brand-kit ingestion                 unchanged; first-time-only; independent job
   │
   ├─ FAST RECON  (steps run in parallel where no arrow joins them)
   │    ├─ overview   Exa Agent, effort high      → company/overview.md          (§4.2)
   │    ├─ lineup     Exa search, deep-reasoning  → product/catalog.md            (§4.1)
   │    │                └─ ProductCatalogSynchronizer → product rows + lineage
   │    ├─ reviews    Exa Agent, effort medium    → proof/customer-reviews.md     (§4.3)   [O-D3]
   │    └─ synthesis  agent turn (reads the three files above)
   │            ├─ audience/icp-<key>.md   ×2–3      status: proposed            (§5, §6.1)
   │            └─ audience/persona-<key>.md  per ICP                            (§5, §6.2)
   │                  └─ evidence tool: exa_search_evidence@1, one call per role  (§4.5)
   │
   └─ BACKGROUND
        └─ per-product  Exa Agent, effort O-D2, one run per catalog entry, concurrency-capped
                                                → product/<slug>.md                (§4.4)

brand_knowledge_document rows: (workspace, brand, folder, path, kind, version, status, artifact ref, step ref)
   ├─ brand-context page: GET tree + GET document, read-only markdown, status per document (§7)
   └─ Head-of-ABM turn: L2 index card + every document materialized read-only under
      brand/knowledge/**; the agent reads them itself (§8)
```

**The artifact tree** (the same paths on the page and in the agent workspace):

| Path | Kind | Producer | Versioning |
|---|---|---|---|
| `company/overview.md` | `company-overview` | overview step | per run |
| `product/catalog.md` | `product-catalog` | lineup step | per run; product rows keyed by lineage |
| `product/<slug>.md` | `product-research` | background step, one per product row | per run |
| `proof/customer-reviews.md` | `customer-reviews` | reviews step | per run |
| `audience/icp-<key>.md` | `icp-definition` | synthesis agent | proposed per run; a human confirmation mints a confirmed version (existing ICP gate) |
| `audience/persona-<key>.md` | `audience-persona` | synthesis agent | per ICP version |
| `design/Design.md` | (existing) | brand-kit ingestion | unchanged |

`memory/` stays absent (`CLUE_MEMORY_ENABLED=false`). Every document is markdown with YAML front
matter; front matter is the machine contract, the body is the human-readable render.

---

## 3. The onboarding run — state contract

**Tables (one migration, O1):**

```
onboarding_run (
  run_id, workspace_id, brand_id, client_entity_id, company_domain,
  requested_by, requested_at, status ∈ {queued, running, completed, completed_with_gaps, failed},
  lane_version text,                -- 'onboarding-v2'
  cost_usd numeric, finished_at
)
onboarding_step (
  step_id, run_id, kind ∈ {overview, lineup, catalog_sync, reviews, synthesis, product_research},
  subject_ref text NULL,            -- product_id for product_research; icp_key for per-ICP work
  phase ∈ {fast, background},
  status ∈ {queued, running, completed, empty, failed},
  provider_run_id text NULL, raw_artifact_ref, output_document_ref NULL,
  cost_usd, searches int, started_at, finished_at, failure_code text NULL, failure_message text NULL
)
brand_knowledge_document (
  document_id, workspace_id, brand_id, folder, path, kind, version int,
  status ∈ {running, ready, empty, failed, proposed, confirmed, superseded},
  artifact_ref (+sha256), produced_by_step_id NULL, produced_by_turn_id NULL,
  supersedes_document_id NULL, created_at
)
```

**Rules**

- **Failure law (master plan §9 R2, applied here):** every provider error, timeout, schema
  rejection or empty result is a *recoverable refusal* recorded on the step (`failed` or `empty`
  with a code); the run continues; the document row shows the status; nothing raises out of the
  driver. `completed_with_gaps` is the honest terminal when any step is `failed`/`empty`.
- **Fast/background is a scheduling label, not a gate.** The synthesis step starts when overview and
  lineup are `completed` (reviews if O-D3 = fast). Background steps never block anything.
- **Progressive visibility.** A document row is created `running` when its step starts, so the
  page shows the tree immediately with statuses, and flips to `ready`/`empty`/`failed` per step.
- **Re-run mints new versions.** A second onboarding run for the same brand creates new document
  versions and marks the old ones `superseded`; agent turns keep the versions they materialized.
- **Concurrency.** Background fan-out is capped by `CLUE_ONBOARDING_MAX_PARALLEL_RUNS` (default 6)
  with exponential backoff on Exa 429; cost per step is recorded from `costDollars`, never estimated.
- **Money.** Onboarding is budget-unconstrained (ruling 2026-08-13): record, surface, never cap.
- **Idempotency.** `(run_id, kind, subject_ref)` is unique; a retried step reuses its provider run
  id when Exa returns one, otherwise re-issues and records both.
- **Web loop.** `POST /onboarding` enqueues and returns 202; the driver is a fleet job (the
  `stage0_setup._drive_recon` on-loop path is not reused). R1's `ProviderCaller.call` is
  synchronous and blocking (Exa deep reasoning up to 1200 s), so every step calls it through
  `asyncio.to_thread`, with **one `ProviderCaller` per worker task** (its totals and halt latch are
  unlocked mutable state) — the R2 composition constraints in `platform/api/clue_api/arv2/README.md`
  bind this driver too. `reset_halt` ownership for the onboarding lane: the operator, via the
  same surface R2 chooses; recorded here so the two lanes do not diverge.

---

## 4. The research calls

### 4.1 Product lineup — `ARV2-PRODUCT-CATALOG-CONTRACT.md` (final)

Exa `/search`, `type: deep-reasoning`, the 8-property schema (two top-level, six per item; R1's Exa client sends it verbatim and Exa accepted it, `enum` included), two passes (own-domain and open),
artifact `ProductCatalogResearch@1`, synchronizer input = the artifact, product rows + lineage.

**Amendment carried by this plan (S5):** the ICP artifact gains `product_ids[]`; §6.4 of the
catalog contract changes from "product research runs after selection for selected products" to
"one background run per discovered product"; the project product set defaults from the chosen
ICP's `product_ids[]` at the product-set gate.

### 4.2 Company overview — `ARV2-COMPANY-OVERVIEW-CONTRACT.md` (final, live-validated)

Exa Agent, effort `high`, the nine-section query, the facts/sections/competitors/customers/not_found
schema, artifact `CompanyOverviewResearch@1` with fixed H2 rendering; sample run 67 s, $0.50.

### 4.3 Customer reviews — `CustomerReviewsResearch@1` (draft, to validate live like 4.2)

Exa Agent, effort `medium` ($0.10). Query: *"Find what customers say about [COMPANY NAME]
([DOMAIN]) as a vendor: reviews on G2, Capterra, Trustpilot, app marketplaces, EHR/partner
marketplaces, Reddit and professional communities, plus the company's own case studies and
testimonials. Separate praise from complaints. Quote verbatim."*

```json
{
  "type": "object", "additionalProperties": false,
  "required": ["summary", "themes_positive", "themes_negative", "reviews", "case_studies", "not_found"],
  "properties": {
    "summary": { "type": "string", "description": "Markdown, 1–2 paragraphs: overall sentiment, volume and where reviews live. Say plainly when the corpus is thin." },
    "themes_positive": { "type": "array", "maxItems": 8, "items": { "type": "string" } },
    "themes_negative": { "type": "array", "maxItems": 8, "items": { "type": "string" } },
    "reviews": {
      "type": "array", "maxItems": 40,
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["platform", "quote", "sentiment", "source_url"],
        "properties": {
          "platform": { "type": "string" },
          "source_url": { "type": "string", "format": "uri" },
          "quote": { "type": "string", "description": "verbatim, 40 words max" },
          "sentiment": { "type": "string", "enum": ["positive", "mixed", "negative"] },
          "rating": { "type": ["number", "null"] },
          "date": { "type": ["string", "null"] },
          "reviewer_role": { "type": ["string", "null"] },
          "reviewer_org_type": { "type": ["string", "null"], "description": "e.g. multi-specialty group, 20 clinicians. Never the reviewer's name." },
          "product_mentioned": { "type": ["string", "null"] }
        }
      }
    },
    "case_studies": {
      "type": "array", "maxItems": 15,
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["customer", "source_url"],
        "properties": {
          "customer": { "type": "string" },
          "source_url": { "type": "string", "format": "uri" },
          "outcome_claim": { "type": ["string", "null"], "description": "the stated result, verbatim, e.g. '38% fewer no-shows'" },
          "named_person": { "type": ["string", "null"], "description": "only if the seller's own case study names them, with title" }
        }
      }
    },
    "not_found": { "type": "array", "maxItems": 10, "items": { "type": "string" } }
  }
}
```

Personal-data rule: reviewer names are never requested or stored; a person is named only when the
seller's own case study names them. Artifact: front matter = themes, reviews, case studies,
not_found, sources; body = `# Customer reviews` → `## Summary` → `## What customers praise` →
`## What customers complain about` → `## Case studies` → `## Not established` → `## Sources`.
Rendered under *Proof*.

### 4.4 Per-product research — `ProductResearch@1` (draft, background)

Exa Agent, effort **O-D2**. One run per product row; the query names the product, the company, the
`official_url` from the catalog (a known URL is fetched, never searched for — Appendix A law), and
the sibling product names so the model does not conflate them.

```json
{
  "type": "object", "additionalProperties": false,
  "required": ["overview", "capabilities", "use_cases", "integrations", "pricing", "differentiators", "competitors", "customer_evidence", "not_found"],
  "properties": {
    "overview": { "type": "string", "description": "Markdown, 1–2 paragraphs, this product only." },
    "capabilities": { "type": "array", "maxItems": 15, "items": { "type": "string", "description": "one explicitly stated capability, in the company's words" } },
    "use_cases": { "type": "array", "maxItems": 10, "items": { "type": "string" } },
    "integrations": { "type": "array", "maxItems": 20, "items": { "type": "string" } },
    "pricing": { "type": ["string", "null"], "description": "published prices and packaging for this product only; null if not published" },
    "differentiators": { "type": "array", "maxItems": 8, "items": { "type": "string" } },
    "competitors": { "type": "array", "maxItems": 8, "items": { "type": "object", "additionalProperties": false, "required": ["name"], "properties": { "name": { "type": "string" }, "website": { "type": ["string", "null"], "format": "uri" }, "how_they_compare": { "type": ["string", "null"] } } } },
    "customer_evidence": { "type": "array", "maxItems": 10, "items": { "type": "object", "additionalProperties": false, "required": ["customer", "source_url"], "properties": { "customer": { "type": "string" }, "source_url": { "type": "string", "format": "uri" }, "outcome_claim": { "type": ["string", "null"] } } } },
    "who_it_is_for": { "type": ["string", "null"], "description": "buyer and user roles, organisation types, in the company's words" },
    "not_found": { "type": "array", "maxItems": 10, "items": { "type": "string" } }
  }
}
```

These nine topics are the old lane's `client.product_*` fields, kept as the topic vocabulary
without the claim substrate. Artifact body: `# <Product name>` → `## Overview` → `## Capabilities`
→ `## Use cases` → `## Who it is for` → `## Integrations` → `## Pricing` → `## Differentiators` →
`## Competitors` → `## Customer evidence` → `## Not established` → `## Sources`. Rendered under
*Product*. Front matter carries `product_id` (spine) so the ICP synthesizer can join.

### 4.5 The evidence tool — `exa_search_evidence@1` (governed toolbelt tool)

**Model-visible input** (all else is platform-fixed):

```text
query: str (≤ 400 chars)            — what the agent wants evidence of
include_domains: list[str] ≤ 5      — optional
num_results: int 1–10 (default 6)
```

**Fixed inside the tool:** `type: deep-reasoning`; `systemPrompt`: *"Prefer first-person accounts
by people in the named role: forum posts, interviews, reviews, talks, job postings. Never
paraphrase a quote; return it verbatim with its URL. Return nothing rather than a weak match."*;
`outputSchema` (within the /search limits):

```json
{
  "type": "object", "required": ["passages"],
  "properties": {
    "passages": { "type": "array", "items": { "type": "object", "required": ["quote", "speaker_role"],
      "properties": {
        "quote": { "type": "string", "description": "verbatim, 60 words max" },
        "speaker_role": { "type": "string", "description": "the speaker's role/title as stated or evident" },
        "org_type": { "type": "string" },
        "topic": { "type": "string", "description": "pain | language | tooling | trigger | objection" }
      } } }
  }
}
```

The tool maps `output.grounding` onto each passage as `url` + `title` (the schema carries no
citation field, per Exa's rule), saves the raw response, records cost (`~$0.015`), and returns a
bounded list, possibly empty. Effect class SPEND; replay policy journaled; no writes. Behind
`CLUE_ONBOARDING_PERSONA_EVIDENCE_ENABLED` (default `true`).

---

## 5. The synthesis agent — `onboarding-synthesis@v1`

**What it is.** A catalog profile (`platform/agents/catalog/profiles/onboarding-synthesis/v1/`),
run once per onboarding as one agent turn on the fleet, in an isolated workspace with the three
fast-recon documents materialized read-only. It is not the Head-of-ABM (which reads ICPs; it does
not author first drafts) and not Exa (which searches; it does not reason about a client's
go-to-market).

**Profile**

```yaml
role: onboarding_synthesis
model_id: <O-D1>                 # overridable by ONBOARDING_SYNTHESIS_AGENT_MODEL (.env.example)
prompt: onboarding-synthesis v1
skills: [icp-synthesis v1, audience-persona v1]
tools: [exa_search_evidence@1]   # + framework tools ls/read_file/write_file/edit_file/glob/grep
```

**Workspace inputs (materialized, read-only):** `brand/knowledge/company/overview.md`,
`brand/knowledge/product/catalog.md`, `brand/knowledge/proof/customer-reviews.md` (if present),
every `brand/knowledge/product/<slug>.md` already `ready`, and the platform's persona vocabulary.

**Outputs:** files under `outputs/audience/icp-<key>.md` and `outputs/audience/persona-<key>.md`.
The existing finalization snapshot turns `outputs/**` into artifacts; the onboarding driver
registers each as a `brand_knowledge_document` (`status: proposed` for ICPs, `ready` for personas).
No new promote tool.

**Failure law:** an unreadable input is reported in the turn's final message and the run continues
with what exists; a missing reviews document is normal; an evidence-tool refusal or empty result
means the section is written as inference and says so.

### 5.1 Prompt — `onboarding-synthesis` v1 (system)

```text
You are the onboarding synthesis agent for a B2B account-based marketing platform. Your client is
the company described in brand/knowledge/company/overview.md. Your job, in two steps, is to write
the client's ideal customer profiles and then one audience-persona document per profile, from the
documents in your workspace and nothing else, unless the evidence tool returns a cited passage.

Read, before writing anything: company/overview.md; product/catalog.md; proof/customer-reviews.md
if it exists; every file under product/. Do not state a fact about the client that these files do
not contain. Cite the file path in parentheses after any specific fact. When a file lists
something under "Not established", you may not assert it.

Write plainly. No em-dashes. No platitudes. Prefer fewer, sourced bullets over a filled quota.
When you are inferring, say "inference".
```

### 5.2 Skill — `icp-synthesis` v1

```text
Produce two to three ideal customer profiles for the client. Each profile is one markdown file
outputs/audience/icp-<key>.md in the ICP artifact format (front matter + body, see the format
block below). Decide the number of profiles from the product lineup and the customer segments in
the overview: one profile per distinct buyer motion, not one per product. Each profile names the
product_ids it sells, from product/catalog.md.

For each profile:
- hard_gates: pass/fail rules with a test a researcher can run (industry, size band, geography,
  stack or system in use, hiring, regulatory status). Write the rule and its test.
- exclusions: who is explicitly out, and why.
- persona_map: which of economic_buyer, champion, user, technical_evaluator, blocker exist at
  this account type, each with the titles that hold it.
- qualifier_fields: the client-specific facts research must find per account, each as
  {field_key, description}; the description is the research instruction. Reuse an existing key
  when one fits; otherwise name a new one under account.*.
- body: the human-readable definition in priority order; TAM/list-math estimate and whether to
  widen, tier or shrink; disqualifiers and red flags; the client's own phrasing of who they sell
  to, quoted from the overview or reviews; the qualification-floor verdict.

Every gate must trace to something in the files: a customer segment, a named customer, a
regulatory posture, an integration, a review theme. If you cannot trace it, drop it. Set
status: proposed. Never write a project id, a version number or a product id you were not given.
```

### 5.3 Skill — `audience-persona` v1 (the revised prompt, final text)

```text
You are a customer research strategist writing for a B2B account-based marketing team. For each
ICP file you wrote, write outputs/audience/persona-<key>.md with one section per role in that
ICP's persona_map, in this order: economic_buyer, champion, user, technical_evaluator, blocker.
Skip a role only if the ICP omits it.

Before writing a role, call exa_search_evidence once with a query built from the ICP's industry
and the role's titles, asking how people in that role describe this problem in their own words.
Use returned passages, with their URLs, in sections 3, 6 and 10. If nothing useful returns, write
those sections as inference and say so.

For each role, write:
1. Role and snapshot (3–4 sentences). Who holds this role at an account that passes the hard
   gates, what they own, why this problem is theirs. No fictional names. Firmographic ranges come
   from the ICP, not from you.
2. Titles that hold this role (up to 8). Exact title strings and common variants as they appear
   on LinkedIn and org pages. These are search keys.
3. Daily reality (up to 6 bullets, one sentence each). Responsibilities, tools, where friction
   shows up. Name a tool or a number only if a source or a product file supports it; otherwise
   mark it inference.
4. Core fears (up to 5 bullets, 15 words or fewer each).
5. Deep motivations (up to 4 bullets). Practical and aspirational.
6. Critical pain points (up to 6 bullets). Industry-specific, phrased as the pain.
7. Buying triggers (up to 6 bullets). Observable events on the account that mean this person is
   in motion: a job posting, a regulation date, a system migration, a leadership change, a
   complaint pattern. Each must be something a researcher could find.
8. Trust builders (up to 5 bullets), customer-first: "Show me...", "Prove you...".
9. Trust killers (up to 5 bullets), blunt.
10. Language and channels (up to 5 bullets). Words and phrases they use for the problem, and
    where they read or ask: communities, publications, events.
11. How the products serve them (1 paragraph). Only capabilities the product files state, cited
    by file. Tie each capability to a fear or pain above.

Rules. Cite the source of any specific fact in parentheses: a file path, or a URL. Mark inference
as inference. Prefer fewer sourced bullets over the maximum count. No platitudes. No em-dashes.
300–450 words per role. Put titles (2) and buying triggers (7) in the front matter as well as the
body.
```

---

## 6. Artifact formats owned by this plan

### 6.1 ICP artifact — master plan §5.2, with the brand-level additions

Front matter: `kind: icp-definition`, `icp_key`, `version`, `brand_id`, **`status:
proposed | confirmed`**, **`product_ids[]`** (spine ids from the catalog), `hard_gates[] {key, rule,
test}`, `exclusions[]`, `persona_map {role: {titles[]}}`, `qualifier_fields[] {field_key,
description, display: rail | section:<key>}`, and on confirmation only: `confirmed_by`,
`confirmed_at`, `confirmed_for_project_id`, `product_selection_version`. Body as §5.2.

Confirmation is the existing ICP gate over an artifact ref: the Stage-0 interview picks one
proposed ICP for the project; approval mints a `confirmed` version (a new document row,
`supersedes` the proposed one for that project), registers the `qualifier_fields` (seam-freeze
box 2b, automatic), and pre-checks `product_ids[]` at the product-set gate. A project has one
ICP (P3); the brand keeps all proposals for other projects.

### 6.2 Persona artifact

Front matter: `kind: audience-persona`, `icp_key`, `icp_version`, `brand_id`, `personas[] {role,
titles[], buying_triggers[], evidence_urls[]}`. Body: the eleven sections per role. The research
lane reads `titles[]` for committee resolution and `buying_triggers[]` as signal instructions; the
frontend reads `personas[].role` to label committee members.

### 6.3 The L2 brand-knowledge index card — `BrandKnowledgeIndexCard@1`

Bounded (≤ 2k tokens by the byte counter): one line per `brand_knowledge_document` in the current
version set: `path`, `kind`, `version`, `status`, `as_of`, a ≤ 160-char summary (the first
paragraph of the body, truncated), and for ICPs the `product_ids[]` and status. Compiled
deterministically; replaces `ClientKnowledgeCard@2` on new-lane workspaces.

---

## 7. Brand-context Knowledge read contract (backend serves; frontend re-lifts the dummy)

Read-only in v1; the proposed write endpoints in `apps/frontend/docs/api-contracts/brand-context.md`
stay unimplemented (S3: no direct editing).

```
GET /api/v1/brand-context/knowledge
  → { folders: [ { key: "company"|"product"|"audience"|"proof"|"design", label,
                   documents: [ { id, path, title, kind, version, status, updatedAt,
                                  productId?: string, icpKey?: string } ] } ] }
GET /api/v1/brand-context/knowledge/documents/:id
  → { id, path, title, kind, version, status, markdown, frontMatter: {...}, updatedAt,
      sources: [ { section, url, title, confidence } ] }
GET /api/v1/brand-context/onboarding/current
  → { runId, status, steps: [ { kind, subjectRef, phase, status, startedAt, finishedAt,
                               costUsd, failureCode } ], costUsd }
```

Rendering rules: markdown render only, `Edit` disabled; status chip per document (running / ready /
empty / failed / proposed / confirmed); `not_found`/"Not established" sections render as written;
dates on the wire but not rendered (R1); the design brief keeps its existing slot. The dummy's
Knowledge section is re-lifted, not patched (principle 7); anything the dummy has no slot for
(e.g. per-section confidence) stays unserved.

---

## 8. Head-of-ABM integration

- **Profile vN+1 (from v43):** drop `evaluate_stage0_readiness`, `inspect_readiness_history`,
  `list_client_knowledge`, `inspect_client_claim`, `list_product_knowledge`,
  `inspect_product_claim`, `start_confirmed_project_run`, `open_product_selection_gate@1`; add
  `open_product_set_selection_gate@1`, `open_icp_confirmation_gate@2` (artifact-ref subject).
  Keep the launch tools, directive tools, design leg, `record_interview_answer`.
- **Context:** L2 = brand card + `BrandKnowledgeIndexCard@1`; the constitution materializes every
  `ready`/`proposed`/`confirmed` document under `brand/knowledge/**` read-only, pinned by ref +
  digest (composition D4 applied to files). No Client-KB card, no Stage-0 state card, no product
  cards. L4 memory stays off.
- **Stage-0 skill v21 (rewrite):** read `audience/icp-*.md` and `company/overview.md` before the
  first reply; propose from the ICP files and talk them through; when the user picks one, open the
  ICP gate on that artifact ref; then open the product-set gate (pre-checked from the ICP's
  products); "record in project context" replaces every "route to memory"; readiness and recon
  language removed; never state a product fact a product file does not contain; re-read a file when
  a detail is needed rather than recall it.
- **Launch:** `launch_account_research` carries `icp_artifact_ref` + `product_selection_version`.

---

## 9. Phases, exit gates, ownership, timeline

| # | Phase | Builds | Exit gate | Owner |
|---|---|---|---|---|
| O0 | Contracts freeze | This document initialed; §4.3–4.5 validated live once each (as 4.2 was); catalog contract §6.4 + master plan §5.2 reworded for S5; the §7 read contract copied into `apps/frontend/docs/api-contracts/brand-context.md` | Both founders initial §12 | Aryan (docs), Shashank (contract doc copy) |
| O1 | Substrate | Migration: §3 tables, `project_product`, `product_set_selection` kind + per-element answer trigger; flags (§10) in `.env.example`; `ONBOARDING_SYNTHESIS_AGENT_MODEL` in the agent-model block | One alembic head; `make db-smoke` green; parity test green; checklist items 3, 7 | agent-built, Aryan merges |
| O2 | Exa Agent surface (leaf) — **re-based on R1 (merged 2026-09-07, PR #45)** | R1 already ships `platform/api/clue_api/arv2/exa_client.py` (search, contents, `deep_reasoning_body` with a caller-supplied `outputSchema`, `product_catalog_output_schema()` = the catalog contract §3 verbatim) behind the `ProviderCaller` wrapper (estimate row → raw record → retry/halt → result row; `sinks.py` file/memory sinks; `provider_call_ledger` spec in master plan §4). O2 therefore adds only: the Exa **Agent** surface (`/agent/runs` create + poll + stream, `output.text`/`structured`/`grounding`, `costDollars`) through the same `ProviderCaller`; the four remaining request templates (overview §4.2, reviews §4.3, per-product §4.4, evidence §4.5) as builder functions next to `product_catalog_output_schema`; the artifact mappers (§4 of each contract). Tests follow R1's founder ruling: **live against Exa, skipping with the env-var name when the key is unset; no replay fixtures.** | Live test on Insight Health reproduces the overview run's shape (`schema_satisfied`, 8 grounding rows, facts non-null) and the catalog run's 12 entries; ledger rows carry `costDollars.total` | agent-built from a charter; Aryan reviews |
| O3 | Research steps on the fleet | `arv2/onboarding_driver.py` (fleet job), `POST /onboarding` 202, step graph, catalog sync re-pointed at the artifact, background fan-out + cap, document rows with statuses | One unseeded Insight Health run: every document present or honestly failed; ledger complete; nothing on the web loop | agent-built, Aryan composes |
| O4 | Synthesis agent | Profile/prompt/two skills (§5), `exa_search_evidence@1`, materialization of inputs, outputs→documents registration | 2–3 ICPs + personas for Insight Health; no fictional names; every specific fact cited; per-role evidence when found; matches Shashank's answer keys; checklist item 1 | content Shashank, wiring agent-built, Aryan promotes |
| O5 | Brand-context read surface | §7 endpoints; frontend Knowledge section re-lifted from the dummy on the real endpoints; status chips; progressive fill | With `CLUE_API_BASE_URL` set the page renders the real tree and fills as steps land; frontend gates green | agent-built from Shashank's charter; Aryan merges |
| O6 | Head-of-ABM integration | §8: profile, index card source, materialization, Stage-0 skill v21, product-set gate tool, ICP gate on artifact refs, launch fields | New project on Insight Health: interview → ICP pick → product set → ICP confirmation → launch; old lane off; checklist 7/7 | Aryan (integration point) |
| O7 | Acceptance | Unseeded onboarding on Clue (cluehq.ai) and one more seller; cost/latency table per step; defect list; evidence under `.context/` | Founders sign; old Stage-0 recon stays flag-off until Phase 6 | both |

**Coordination with D1 (running in parallel on the display lane; recorded 2026-09-07 from the D1
lane's own analysis).** O1 and D1 meet in exactly three places and one rule:

1. **Alembic.** Both cut off the same head. Whichever lands second runs `alembic merge` and adds
   the join revision; neither hand-renumbers (repo convention). `alembic heads` = one before merge.
2. **`libs/clue-config/clue_config/settings.py` and `.env.example`.** Both add rows; trivial hand
   merges; the parity test is the gate after the merge.
3. **`libs/clue-core/clue_core/enums.py::Persona`.** **D1 owns it** (it adds `user`, ruling D8).
   O1 never touches the enum, the DB enum, or the parity test for it. The onboarding lane consumes
   the persona vocabulary as strings from the ICP artifact's `persona_map` and validates them
   against `Persona` at read time only after D1 lands.

Everything else in O1 is disjoint from D1.

**Ordering.** O1 ∥ O2 the day O0 is initialed (separate worktrees). O3 needs O1 + O2. O4 needs O1
and the evidence tool from O2; runs alongside O3. O5 starts on fixtures after O1, flips to live
after O3. O6 needs O3 + O4. O7 last. **Timeline:** ~3 weeks with parallel worktrees; 4 if the
synthesis prompts need a second pass against the answer keys.

**What this plan does not build:** editing of knowledge documents; a product-set display on the
accounts screens; claim extraction from any artifact; deletion of the old recon (Phase 6).

---

## 10. Flags (all in `.env.example` in the commit that introduces them)

| Flag | Default | Meaning |
|---|---|---|
| `CLUE_ONBOARDING_V2_ENABLED` | `false` until O7 | routes `POST /onboarding` to the new driver; `CLUE_SELF_SERVE_PROVISIONING_ENABLED` stays `false` |
| `CLUE_ONBOARDING_OVERVIEW_EFFORT` | `high` | Exa Agent effort for 4.2 |
| `CLUE_ONBOARDING_REVIEWS_EFFORT` | `medium` | 4.3 |
| `CLUE_ONBOARDING_PRODUCT_EFFORT` | O-D2 | 4.4 |
| `CLUE_ONBOARDING_REVIEWS_PHASE` | O-D3 (`fast`/`background`) | when 4.3 runs |
| `CLUE_ONBOARDING_MAX_PARALLEL_RUNS` | `6` | background fan-out cap |
| `CLUE_ONBOARDING_PERSONA_EVIDENCE_ENABLED` | `true` | the evidence tool |
| `ONBOARDING_SYNTHESIS_AGENT_MODEL` / `_EFFORT` | O-D1 / blank | agent-model block |

`CLUE_EXA_API_KEY` already exists and is reused.

---

## 11. Standing rule (repeated so it is never missed)

Nothing in §2–§9 demands a Client-KB version, a readiness decision, or a Stage-0 run pin. The
product-set gate reads product rows. The scope pin records artifact refs. The synthesis and
Head-of-ABM profiles carry no readiness/Client-KB/Product-KB tools. Checklist:
`_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`, run at O1, O4, O6, O7 and reported in
each close-out.

---

## 12. Decisions (initial each line)

| # | Decision | Recommendation | Aryan | Shashank |
|---|---|---|---|---|
| O-D1 | Synthesis agent model (`ONBOARDING_SYNTHESIS_AGENT_MODEL`) | `x-ai/grok-4.6`, same as every other deepagent on this branch; change it in env, never by a new profile version | ☐ | ☐ |
| O-D2 | Per-product Exa Agent effort | `medium` ($0.10; ~$1.20 for a 12-product company); raise to `high` per deployment if the product files read thin | ☐ | ☐ |
| O-D3 | Customer-reviews run in fast recon or background | **fast** — the synthesis agent's ICP gates and persona pains are better with review themes, and `medium` effort keeps it under two minutes | ☐ | ☐ |
| O-D4 | O0 form: this single plan with §4–§7 as sections, or separate contract docs per call | this document; split a section out only when it changes independently | ☐ | ☐ |
| O-D5 | One ICP-confirmation gate kind over artifact refs (`@2`) replaces the `icp_spec`-row kind for new projects; `synthesize_icps` retired on the new profile | Yes | ☐ | ☐ |
| O-D6 | Evidence tool default on (`CLUE_ONBOARDING_PERSONA_EVIDENCE_ENABLED=true`) | Yes; per-deployment off switch exists | ☐ | ☐ |

Open from elsewhere, unchanged: D9 (Series A equivalence), Shashank's initials on D14–D17.
