# ARV2 ONBOARDING PLAN — Track O: onboarding as a research pipeline, the synthesis agent, and the Head-of-ABM integration

**Amendment, Aryan 2026-09-21 — automatic approval:** Successful brand-kit
ingestion publishes an approved kit after validation. Current Head-of-ABM turns
apply the selected ICP and products through `configure_project_targeting@1`,
without an approve/reject step. This supersedes the two human-gate requirements
in the outcome, S5 and O6 below. Onboarding still produces brand-level proposals;
applying one to a project creates its confirmed artifact and exact project pin.
Automatic provenance identifies the initiating turn rather than a human answer.
See `ARV2-PRODUCT-CATALOG-CONTRACT.md`'s 2026-09-21 amendment for selection rules.
Other authority, spending and evidence boundaries keep their existing behavior.

**Status:** RATIFIED by Aryan 2026-09-07 — all six decision boxes O-D1–O-D6 ruled as recommended
(O-D1 with the addition: reasoning effort stays at the model default). Version 1.1. This is the
authoritative plan for Track O; the master plan's Track O paragraph points here. Shashank's column
in §12 is open.

**Parent:** `ARV2-MASTER-PLAN.md` (Track O). **Children already written:**
`ARV2-PRODUCT-CATALOG-CONTRACT.md` (lineup + product-set gate + rulings P1–P4),
`ARV2-COMPANY-OVERVIEW-CONTRACT.md` (overview, live-validated). The three remaining research
contracts (reviews, per-product, evidence tool) and the synthesis-agent contract are sections of
this document (§4–§6) rather than separate files (O-D4, ruled).

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
   │    ├─ reviews    Exa Agent, effort medium    → proof/customer-reviews.md     (§4.3)   fast (O-D3)
   │    └─ synthesis  agent turn (reads the three files above)
   │            ├─ audience/icp-<key>.md   ×2–3      status: proposed            (§5, §6.1)
   │            └─ audience/persona-<key>.md  per ICP                            (§5, §6.2)
   │                  └─ evidence tool: exa_search_evidence@1, one call per role  (§4.5)
   │
   └─ BACKGROUND
        └─ per-product  Exa Agent, effort medium (O-D2), one run per catalog entry, concurrency-capped
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
  step_id, run_id, kind ∈ {overview, lineup, catalog_sync, reviews, synthesis, product_research,
                           persona},   -- 'persona' added 2026-09-08 by the synthesis split (§5)
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

Exa Agent, effort **`medium`** (O-D2; per-deployment switch to `high`). One run per product row; the query names the product, the company, the
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

**Addendum 2026-09-08 — the synthesis split (`onboarding-synthesis@v2`).** Everything below stays
the contract for *what* the agent writes; what changed is that it no longer writes it in one turn.
Design: `docs/superpowers/specs/2026-09-08-arv2-onboarding-o4-synthesis-split-design.md` (founder-
approved 2026-09-08); measured on the two successful Insight Health runs, where the ICPs were
finished about four minutes in but reached the Knowledge page eight to ten minutes later, behind
three personas queued inside the same turn.

- **One run is now `1 + N` turns**, same recipe (`onboarding-synthesis-unit@1`), same per-brand
  system project, same per-turn budget envelope: **one ICP turn**, then **one persona turn per ICP
  it registered**. Identity is the turn's key, not the run's:
  `identity_key = f"{run_id}:icp"` and `f"{run_id}:persona:{icp_key}"`, with the execution id
  `operation_id_from_key(identity_key, "onboarding-synthesis-unit@1")` and the turn id
  `uuid5(TURN_NAMESPACE, identity_key)`. Old single-turn runs are dev data and are not migrated.
- **The ICP turn runs on a declared surface, `onboarding_icp` (`ONBOARDING_ICP_SURFACE`), which
  withholds `exa_search_evidence`** — the ICP skill's "from the files and nothing else" becomes a
  tool that is not installed rather than a sentence. That role's whole spendable surface is that
  one tool, so the ICP turn is structurally unable to spend. Consequence, deliberate: the effective
  skill set on that surface drops `audience-persona` (the skill requires the withheld tool), so the
  ICP turn is not handed a procedure it cannot run. Persona turns resolve the unnarrowed role.
- **Inputs are chosen per turn and ride the opening context.** The ICP turn gets the core three
  (company overview, product catalog, customer reviews) **plus every ICP already on file** — that
  is what makes a re-run refine a profile instead of renaming it — and every product-research file
  on disk. A persona turn gets the core three, **the one ICP it was given** (exact version), and
  only the product-research files whose `product_id` that ICP names (a file whose own product id
  cannot be read is kept; omission is the costly error). `audience-persona` documents are never an
  input to either turn. The core documents are passed as exact-version `focus_refs` and become
  messages in the opening context — `DbCompiledContextCardReader` serves the object type
  `brand_knowledge_document` from the verified artifact body — and are *also* seeded read-only
  under `inputs/brand/knowledge/` so citations keep their paths. The L5 focus budget rises to
  262 144 bytes (`utf8-bytes-v1`); v1's 8 KiB could not hold a company overview, so every input
  arrived as a path only.
- **The known-ICPs rule** (ruling 2, shaped like the lineup's known-products rule) is in
  `skills/icp-synthesis/v2` *and* in the ICP turn's user message, which names each key on file with
  its path and version: reuse a key when the buyer motion is the same, propose a new key only when
  it is genuinely different, never carry a key forward to fill a slot. Ruling 3: the skill reads
  the product file for each product a profile names, not "every file under `product/`".
- **Resources:** `prompts/onboarding-synthesis/v2/SYSTEM.md`, `skills/icp-synthesis/v2`,
  `skills/audience-persona/v2`, `profiles/onboarding-synthesis/v2` (v1 retired). Registry digest
  `676ef758e01e667ee9ad18f2a25203bbd71d86ffe0d32c04f2a95e9a9a8286da`. Model, timeouts and round
  cap are unchanged from v1.
- **Steps and failure law:** the `synthesis` step keeps its kind and its fast phase and now covers
  the ICP turn only; each persona turn is a `kind='persona'` step, `phase='background'`,
  `subject_ref=<icp_key>`, opened the moment the ICP turn returns and sharing the one
  `onboarding_max_parallel_runs` semaphore with the product fan-out. An ICP turn that ends anything
  but `completed` opens no persona step. One persona failing takes only its own step. Migration
  `ae4a5dfb3943` (down `a3602967bb73`) widens the §3 kind CHECK to admit `persona`; its downgrade
  RAISEs if a persona step exists.
- **Containment:** each launcher call is wrapped in `asyncio.wait_for(...,
  SYNTHESIS_TURN_HARD_TIMEOUT_S)` (1800 s) and a trip lands that one step `failed` with
  `turn_hung`. This is not an agent cap (the profile already has a 1200 s turn timeout) — it exists
  because `RecipeExecutor.execute` can spin forever when a recipe gate is opened and its dynamic
  child never completes (a refused governed tool call is still a tool result), and a launcher call
  that never returns would strand the run on `running`. That executor hazard is the execution
  substrate's to fix; the guard only contains it.

**What it is.** A catalog profile (`platform/agents/catalog/profiles/onboarding-synthesis/v1/`),
run once per onboarding as one agent turn on the fleet, in an isolated workspace with the three
fast-recon documents materialized read-only. It is not the Head-of-ABM (which reads ICPs; it does
not author first drafts) and not Exa (which searches; it does not reason about a client's
go-to-market).

**Profile**

```yaml
role: onboarding_synthesis
model_id: x-ai/grok-4.6          # O-D1; overridable by ONBOARDING_SYNTHESIS_AGENT_MODEL; effort blank = model default
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

**Addendum 2026-09-08 (the synthesis split, §5).** One persona document is now written by its own
turn, for the one ICP that turn was given, so `icp_version` is **the registered ICP document row's
version** — the version named in the persona turn's user message alongside the ICP's input path —
never a literal `1`. `skills/audience-persona/v2` says so; the front-matter shape is unchanged.

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

### Addendum 2026-09-09 — O6 as built

Built on branch `onboarding/o6-head-of-abm` (commits `8720f3509`..`83817317e`, base `3ceb81f36`)
from `docs/superpowers/plans/2026-09-09-arv2-onboarding-o6-head-of-abm.md`. The §8 text above is
the specification and is unchanged; this addendum records the decisions the plan took and the shape
that actually landed. The **live** exit gate in §9 is still owed (founder-triggered).

**Decisions D1–D12 (from the plan's decision table):**

- **D1 — profile v44 tool set.** Drop the eight tools §8 names *plus* `synthesize_icps@3`,
  `start_recon@1`, `submit_onboarding_input@1` and `open_discovery_configuration_gate@1`; keep the
  directive, launch, read, propose, ingestion, design-leg and `record_interview_answer@1` pins; add
  `open_product_set_selection_gate@1`, `open_icp_confirmation_gate@2`,
  `launch_arv2_account_research@1`, `read_arv2_account_research_run@1`.
- **D2 — the launch is R2's tool.** §8's "`launch_account_research` carries `icp_artifact_ref` +
  `product_selection_version`" is satisfied by `launch_arv2_account_research@1`; the old directive
  chain stays granted, and `account-deep-steering@v8` is *not* rewritten in O6.
- **D3 — gate order.** Pick the ICP in conversation → the **product-set** gate pre-checked from that
  ICP's `product_ids[]` → then the **ICP confirmation** gate, whose approval stamps
  `product_selection_version`. The other order is tolerated (the stamp is then absent and the launch
  pins the set version itself).
- **D4 — `revised` on the ICP gate is recorded, not authored.** The agent records the requested
  changes in project context and says a revised ICP needs a new onboarding synthesis. O6 adds no
  ICP-authoring tool.
- **D5 — the four old cards leave the production conversation for every workspace**, not behind a
  flag: no Client-KB v2 card, no Stage-0 project-state card, no product-profile or product-knowledge
  card. `_compose_project_context` compiles the brand-knowledge index card and (when account refs
  are attached) the account-deep-steering context, and nothing else.
- **D6 — knowledge documents are pinned per turn** in `agent_turn_knowledge_pin` (migration
  `a3fc75e248e0`): one insert-once row of document refs + digests, written before composition and
  read again by every retry.
- **D7 — recipe v22 = v19 + the four new addresses + `draft_account_research_directive@5` in place
  of `@3`.** Old addresses stay in the slot; the slot is a ceiling, the profile is the grant.
- **D8 — the exact-quote rule stays in skill v21**, because `record_interview_answer@1` refuses a
  paraphrased quote. The master plan's "quote rule removed" line waits for a
  `record_interview_answer@2` — recorded as a follow-up, not built.
- **D9 — `pin_requirements = ("project",)`** on the two R2 tools and both new gate tools; the
  Stage-0 pin provider resolves `project` from the execution row or from the presenting turn.
- **D10 — product-set gate subject** is `brand-product-catalog:{brand_id}:{catalog_document_id or
  'none'}` at the catalog document's own version, with the contract §7.1 snapshot plus
  `suggested_product_ids[]` and per-candidate `resolution_state` / `reconcile_confidence` /
  `reconcile_reason`. The catalog contract's `client-product-catalog:{client_entity_id}:v{kb}` form
  is superseded — it named a Client-KB version.
- **D11 — the projects sidebar lists `status = 'active'` projects only**, which keeps O4's
  onboarding system project out of it.
- **D12 — `qualifier_fields` registration (seam-freeze 2b) is not built anywhere in the tree.** The
  confirmed ICP document keeps them in its front matter; registration into the field catalog belongs
  to the R lane at launch. Recorded, not built.

**Two amendments taken during execution:**

1. **Recipe v22 re-pins `open_icp_confirmation_gate` at `@2` and drops `@1`** from its allowlists and
   requirements. The compatibility loader resolves one version per tool key, so carrying both is a
   `conflicting_requirement` and the seeder refuses to promote the recipe (the v16 fresh-boot wedge).
   `@1` stays in `RECIPE_0_TOOL_ADDRESSES` for replay, and v19 remains the exact replay input for
   turns that ran on `@1`. Consequence: profile v44 must pin `@2`, and does.
2. **A confirmation never retires another project's confirmed row.** `confirm_icp_document` retires
   the subject row only when it is `proposed`, or `confirmed` for the *same* project; a version
   confirmed for a different project stays confirmed. (Two confirmed versions of one path can then
   coexist and `current_knowledge_documents` serves only the newest, so the displaced project's index
   card loses its confirmation — a known multi-project limitation deferred to O7.)

**The landed shape.**

- **Profile `head-of-abm@v44`** (prompt v8, skills `stage0-interview@v21` + `account-deep-steering@v8`)
  pins eighteen tools: `draft_account_research_directive@5`, `get_research_view@1`,
  `inspect_statement_history@1`, `launch_account_research@1`, `launch_arv2_account_research@1`,
  `launch_selected_account_research@1`, `launch_contact_research@1`, `open_design_leg@4`,
  `open_directive_confirmation_gate@1`, `open_icp_confirmation_gate@2`,
  `open_product_set_selection_gate@1`, `propose_field@2`, `propose_source@1`,
  `read_account_research_run@1`, `read_arv2_account_research_run@1`, `read_contact_research_run@1`,
  `record_interview_answer@1`, `submit_ingestion@1`. Model, effort, timeout and budget are v43's.
- **The knowledge pin.** Every production project-conversation turn writes its
  `agent_turn_knowledge_pin` row before it composes anything, and every retry reads the winner. The
  pinned bytes are seeded read-only under `inputs/brand/knowledge/`, and a reclaimed turn re-verifies
  the frozen tree rather than skipping it.
- **The index card.** L3 carries exactly one compiled artifact from that pinned set —
  `BrandKnowledgeIndexCard@1` (`card_kind = "brand_knowledge_index"`) — a bounded index of the files,
  so the model reads a document by path instead of being handed its body.
- **The two gates.** `open_product_set_selection_gate@1` (set-valued; answered with
  `selected_product_ids`, which writes the project's `project_product` rows and a new selection
  version) and `open_icp_confirmation_gate@2` (subject = a knowledge document pinned by id and
  digest; approval mints a `confirmed` version of the same path stamped
  `confirmed_for_project_id`). Both live at the composition root, outside `clue_api/arv2/`, because
  of the lane's import guard.
- **The launch** is `launch_arv2_account_research@1`, taught by skill v21 with what must be confirmed
  first: a confirmed ICP document version and a confirmed product set.
- **Env posture unchanged; O6 added no flag** (`git diff` on `.env.example` and
  `clue_config/settings.py` against the base is empty).

---

### Addendum 2026-09-12 — the project folder beside the brand folder

Every production turn also seeds `inputs/project/status.md` (compiled from the project's ARV2 rows:
pin, product set, accounts, discovery, research) and `inputs/project/decisions.md` (the project's
current-effective `project_state` statements with their quotes), pinned once per turn in
`agent_turn_project_files` and indexed by a second L3 card `ProjectFilesIndexCard@1`. Spec:
`docs/superpowers/specs/2026-09-12-project-context-and-icp-authoring-design.md` §4.1. Project-scoped
documents (`inputs/project/audience/…`, `inputs/project/plan.md`) follow in the next slices.

---

### Addendum 2026-09-12 — ICP authoring (profile v46, skill v23, recipe v24)

The next slices landed. A marketer who reads the onboarding walk's proposals and says *"none of
these is who we sell to"* is no longer stuck: the Head of ABM can **write the profile down** in the
conversation, and can ask for the **personas** of a profile the human has confirmed. Spec:
`docs/superpowers/specs/2026-09-12-project-context-and-icp-authoring-design.md` §4.2.

- **Knowledge documents carry a scope and a lineage** (migration `b953bf11e2a9`).
  `brand_knowledge_document` gains `project_id` (NULL = the brand's own knowledge; a value scopes the
  row to one project, composite FK to `project` so it cannot cross tenants) and
  `derived_from_document_id`; the path/version UNIQUE becomes the scope-aware unique index
  `brand_knowledge_document_scope_path_version (workspace_id, brand_id, COALESCE(project_id, ''),
  path, version)`, so a project's variant of `audience/icp.md` coexists with the brand's.
  `onboarding_run` gains `kind ('full' | 'personas')`, `project_id` and `persona_icp_document_id`,
  welded by `onboarding_run_persona_shape`.
- **The reader rule, in one sentence:** a brand reader sees brand rows (`project_id IS NULL` — the
  onboarding walk, the Knowledge tree and its PUT); a project reader unions both and lets the project
  win (`current_project_knowledge_refs`; `current_icp_document(project_id=)` orders
  `path, (project_id IS NULL), version DESC`). Confirmation mints the next version *in the subject's
  own scope* and carries the scope and the lineage forward; the pin carries them too. A project
  document materializes under `inputs/project/…` (never `inputs/brand/knowledge/…`), is compiled onto
  the lease by `project_status.current_project_documents`, and is listed in `status.md` off the same
  read.
- **`author_icp_document@1`** (WRITE, free, no flag) writes a **`proposed`** document — authoring
  proposes, the human's confirmation gate still decides — at `brand` or `project` scope, optionally
  naming the brand profile it was derived from. Platform front matter is stripped and re-stamped; the
  document id is turn-derived so a replay never re-renders. Refusals: `icp_key_invalid`,
  `icp_front_matter_invalid`, `icp_key_taken_by_brand`, `icp_key_taken_by_project`,
  `derived_from_not_found`, `icp_document_version_race`.
- **`request_persona_synthesis@1`** (SPEND, behind `onboarding_v2_enabled`) opens a **personas-only
  onboarding run** for the project's *pinned* ICP: `mark_run_running` → one `_persona_step` →
  `finish_run`, in the ICP's own scope. Refusals: `icp_not_pinned_for_project`,
  `persona_run_already_open`, `brand_not_onboarded`, `enqueue_failed`. `read_current_run` and the
  `POST /onboarding` 409 both filter `kind = 'full'`, so a personas run neither shows on the
  setting-up screen nor holds the workspace's one start slot.
- **The grant:** `stage0-interview@v23` (new §5b "Author a profile" and §5c "Personas for a confirmed
  profile"), `head-of-abm@v46`, `recipe0-stage0-v24.json`, `CONVERSATION_RECIPE_VERSION = 24`. Both
  tools are withheld from the Stage-0 trial surface — this is a project-conversation capability.
  v22 / v45 / recipe v23 are byte-untouched.
- **Standing rule re-run at this stage** (`_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`),
  all seven items answered; **env posture unchanged and no new flag**. Engineering detail:
  `platform/api/clue_api/arv2/README.md` § "ICP authoring and project-scoped documents"; close-out:
  `_memory/2026-09-12-icp-authoring.md`.

### Addendum 2026-09-12 — the project plan document (profile v47, skill v24, recipe v25)

The plan itself is now written down. `write_project_document@1` (WRITE, free, no flag) stores the
project's execution plan as `project/plan.md` — a `project-plan` knowledge document with `project_id`
set, materialized as `inputs/project/plan.md` and listed in `status.md` — one immutable version per
save, refused (`project_document_revision_conflict`) when the version the writer read is no longer
current, so a human edit is never silently overwritten; skill `stage0-interview@v24` §6b says when to
write it (after the section-2 questions, a confirmed pinned ICP and a confirmed product set, never on
a first turn) and to re-read and keep the human's edits after a refusal. The human's own edit path is
the project-documents surface on `/frontend/v1` (list, detail, and a `{body, expected_revision}` PUT
that mints the next version with `user_edit` provenance; 404/409/422 refusals), contracted in
`apps/frontend/docs/api-contracts/projects.md` § "Project documents". The grant is
`head-of-abm@v47` / `recipe0-stage0-v25.json` / `CONVERSATION_RECIPE_VERSION = 25`, with the tool
withheld from the Stage-0 trial surface; v46 / v23 / recipe v24 are byte-untouched. Founder ruling
**R12** defers the Plan tab, the editor, the plan card's click-through and the gallery document cards
to `docs/superpowers/plans/2026-09-12-plan-tab-frontend.md`. Standing rule re-run, 7/7; env posture
unchanged, no new flag. Engineering detail: `platform/api/clue_api/arv2/README.md` § "Project plan
document"; close-out: `_memory/2026-09-12-project-plan-document.md` (live walk owed).

### Addendum 2026-09-13 — the three reads (profile v48, skill v25, recipe v26)

The Head of ABM can now look at what it has done instead of remembering it: `read_project_accounts@1`
(the project's accounts, each with its latest account job's research status and a `refreshing` flag),
`read_account_research@1` (one account's written overview in the page's own order, or its claims with
evidence) and `read_discovery_run@1` (the latest or a named run with its asked/found window, its
verified/shown/approved tallies and its candidates) — all three effect-free, registered with **no
flag**, scoped by the ambient `ctx.workspace_id` rather than anything the model supplies, and
answering absence with a typed refusal (`project_not_found`, `account_not_found`,
`overview_not_written`, `account_not_researched`, `no_discovery_run`, `discovery_run_not_found`,
`arv2_reads_not_composed`) so the agent can never read silence as "nothing to report". Ruling **M**:
a read follows no lineage — a merge loser is `account_not_found`, not a quiet redirect to its
survivor, and any lineage a read ever learns to follow must re-check `workspace_id` on the row it
lands on. Skill `stage0-interview@v25` §7c ("Read before you speak about accounts") is the prose that
makes it habitual; the grant is `head-of-abm@v48` / `recipe0-stage0-v26.json` /
`CONVERSATION_RECIPE_VERSION = 26`, pinned through `_execution_project_pin`, with v47 / v24 / recipe
v25 byte-untouched and the trial surface unchanged (a read withholds nothing worth withholding).
Standing rule re-run, 7/7; env posture unchanged, no new flag. Engineering detail:
`platform/api/clue_api/arv2/README.md` § "The three reads"; close-out:
`_memory/2026-09-13-head-of-abm-read-tools.md` (live walk owed).

### Addendum 2026-09-14 — the versioned project root (profile v55, skill v32, recipe v27)

The three document tools above are **ungranted at `head-of-abm@v55`**, and their addresses are not
admitted by `recipe0-stage0-v27.json` (`CONVERSATION_RECIPE_VERSION = 27`, promoted by the workers'
boot seeding). The Head of ABM now writes the project's documents with the file tools it already
has: `project/` is mounted as a **versioned root**, so `write_file` / `edit_file` under that prefix
go through `platform/api/clue_api/project_root_writer.py` to the very same stores
(`arv2/icp_authoring.py`, `arv2/project_documents.py`) — one immutable version per save, the same
revision check the human PUT meets, the row stamped with the writing turn. The expected version is
the `version:` in the file the turn was mounted against, never a model argument, and the library is
re-materialized after every accepted write so the agent reads back what it wrote. Plan:
`docs/superpowers/plans/2026-09-13-versioned-project-root-and-document-skills.md`; spec
`docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md` W6/W7/W8 §4.4/§4.6/§4.7.

- **The document skills replace §5b / §5c / §6b of the Stage-0 skill** (§4.6) — the procedure moves
  out of those sections, which stay in `stage0-interview@v32` as one-line pointers. `icp-authoring@v1`,
  `persona-authoring@v1` and `plan-authoring@v1` are granted beside `stage0-interview@v32`: each
  states what a good document contains, the path to save it to, and the gate after it (an ICP is
  born `proposed` and the human's confirmation gate still decides; a persona and a plan have no
  approval stamp). `head-of-abm@v55` adds `project` to the writable prefixes and re-pins the
  operating manual at `manual-*@v2` (fifteen chapters re-minted because three tools left the
  profile). v54 / v31 / recipe v26 / manual v1 are byte-untouched, for replay.
- **Kinds by folder (ruling P3-a, 2026-09-14 — the platform's existing path convention, amending
  spec §4.1/§4.4's `personas/` folder). [SUPERSEDED the same day by the founder ruling on
  free-flowing documents: the table below describes plan 3 and is kept for the receipts it
  explains.** Any markdown path under `project/` that is not a compiled file is now a versioned
  document; the kind and title are the document's own front matter (`document` when it claims
  none); every document is born `ready`; plan, ICP and personas are **pins** the human agrees to in
  one question — `role: plan` / `role: persona` in the front matter, and the ICP confirmation gate
  for an ICP — never paths or kinds the code checks. The only refusals left are
  `compiled_file_read_only` and `unsupported_document_type` (a path that is not markdown), plus
  `body_empty` and `revision_conflict`.**]**

  | Path under `project/` | Kind | Born | Refusals the model sees |
  | --- | --- | --- | --- |
  | `audience/icp-<key>.md` | `icp-definition` | `proposed` | the ICP writer's own: `icp_key_invalid`, `icp_front_matter_invalid`, `icp_key_taken_by_brand`, `icp_key_taken_by_project`, `derived_from_not_found`, `icp_document_version_race` |
  | `audience/persona-<key>.md` | `persona` | `ready` | `icp_not_pinned` (no pin, or not this key — personas follow the project's **pinned** ICP), `persona_front_matter_invalid`, `revision_conflict` |
  | `plan.md` | `project-plan` | `ready` | `revision_conflict: plan.md is at version 3, you read version 2 — read it again`, `body_empty` |
  | `status.md`, `decisions.md`, `index.json`, `artifacts/**` | compiled | — | `compiled_file_read_only` |
  | anything else | — | — | `unknown_project_path` (the message names the three writable paths) |

  The backend surfaces a refusal as the write tool's `conflict: <code>: <message>` — the code is
  there so the model can tell a stale read from a bad path without parsing prose.
- **The plan card reads rows, not receipts** (ruling P3-6). The turn's finalize merges the documents
  the turn wrote into `domain_refs` with kind-bearing object types — `project_document` (the plan),
  `project_icp_document`, `project_persona_document` — projected as PLAN parts titled "Plan" / "ICP"
  / "Personas" at `v<n>`.
- **Retired, never deleted** (§4.7, standing rule): `author_icp_document@1`,
  `write_project_document@1`, `request_persona_synthesis@1` and the personas-only
  `onboarding_run.kind` entry point stay registered and intact so a receipt pinned to recipe ≤ 26
  replays against its own immutable revision; outside replay they are uncomposed, because no current
  profile grants them.
- **Standing rule re-run at this stage**, 7/7: v55 pins no readiness / Stage-0 / Client-KB /
  Product-KB tool (it *drops* three and adds three skills); the product-set gate source is untouched
  and no card compiler runs for a document write; the pin is the turn's own project pin, with no
  Client-KB pin and no new `AgentTurnScopePinConflict` path; a written document is a version row
  plus a re-materialized library file; `launch_arv2_account_research` / `launch_arv2_discovery`
  gained no precondition; `tests/arv2/test_import_guard.py` green and `lint-imports` 26 kept / 0
  broken; **env posture unchanged, no new flag**. Engineering detail:
  `platform/api/clue_api/arv2/README.md` (the retirement notes on the three tools); close-out:
  `_memory/2026-09-13-live-walk-findings-and-workspace-reorg.md` § "Plan 3 landed (2026-09-14)"
  (live proof owed).

### Addendum 2026-09-14 — catch-up: the workspace libraries and the operating manual (plans 2, 2b)

Written late, because the two plans between the three reads and the versioned root never got an
addendum here and the root above stands on both. **Plan 2 (profile v53, skill v30, prompt v9)** gave
the Head of ABM two read-only libraries in its workspace instead of a context block to remember: the
**brand library** is compiled once per knowledge version and mounted as `brand/`, and the **project
library** is compiled from rows — `status.md`, `decisions.md`, one file per document version, and an
`artifacts/index.json` — and mounted as `project/`. The turn pins the library manifest, so a replay
opens the same bytes the original turn read, while writers and a DSAR erasure re-materialize the
shared copy. **Plan 2b (profile v54, skill v31, prompt v10)** turned the Head of ABM's operating
manual into fifteen catalog skills (`manual-*@v1`, four generated from the registry and drift-tested,
eleven hand-written): the capability map discloses the chapters and the agent opens one with
`read_file` when it needs the detail, which is why the L1 identity budget rose to 40,000 bytes. Both
are proven live; close-out `_memory/2026-09-13-live-walk-findings-and-workspace-reorg.md` §§ "Plan 2
proven" / "Plan 2b proven". Neither added a flag.

### Addendum 2026-09-14 — paged and spilled reads, free-flowing documents (profile v56, skill v33, recipe 28, manual v3)

The reads above could answer a small question and die on a big one: a 72-claim account read overflowed
the governed receipt's 16 KiB bound *after* the tool had already run, and the agent was told it could
not read the account at all. This addendum is the fix, plus the founder's two rulings of the same day.
Plan: `docs/superpowers/plans/2026-09-13-paged-and-spilled-reads.md`; spec
`docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md` (W4 read side, W9, §4.5);
close-out `_memory/2026-09-13-live-walk-findings-and-workspace-reorg.md` § "Plan 4 landed (2026-09-14)"
(live proof owed).

- **Version ladder.** `head-of-abm@v56` pins `stage0-interview@v33`, the document skills at
  `icp-authoring@v2` / `persona-authoring@v2` / `plan-authoring@v2` and the manual at `manual-*@v3`
  ×15; `recipe0-stage0-v28.json` with `CONVERSATION_RECIPE_VERSION = 28`, promoted by the workers'
  boot seeding. The prompt stays v10. v55 / v32 / recipe 27 / manual v2 are byte-untouched, for
  replay.
- **Four reads, all paged.** `read_discovery_run@2` and `read_account_research@2` replace
  `candidate_limit` / the fixed 120-claim cut with `offset`/`limit` and answer `next_offset`; their
  `@1`s stay frozen (a paging change is an input-schema change, and the profile's schema digest pin
  exists to catch exactly that). `read_claims@1` is the general claims query — any account **or**
  contact by `entity_id`, narrowed by `field_prefix`, `tier`, `verification_status` and `since`
  (against `collected_at`), through the account pages' own display gate, so `excluded` still
  separates `sensitive` / `unverified` / `outreach_unsafe`; refusals `entity_not_found`,
  `since_invalid`, `offset_past_end`. `read_artifact@1` opens one gallery artifact by id —
  membership through the rail's own leg join, `summary` (the card) or `content` (the page JSON as
  text, cut at 12 KiB with `body_truncated`), and `artifact_not_found` for both a missing row and
  another project's document. Both new tools are effect-free, ambient-scoped and flagless, like the
  three before them. A slot resolves one version per `(kind, key)`, so recipe 28 **re-pins** the two
  paged reads rather than admitting `@1` and `@2` side by side.
- **Spilling, so a bound is never a refusal.** A governed result whose references exceed 12 KiB is
  written as canonical bytes to `reads/<operation_id>.json` in the thread's workspace, and the
  receipt carries a pointer — `spilled_to`, `count`, a `summary` sliver, the producing tool — which
  the model opens with `read_file`. `reads/` is readable by the model and writable by nobody; the
  write is trusted, quota-counted and idempotent per operation. Both places a receipt is built apply
  the rule (the live one and the rebuilt, hydrated one the model is actually handed), and the full
  result is still the journaled `result_ref` artifact. Where there is no thread lease — the research
  and onboarding-synthesis surfaces — there is no sink and the old refusal stands.
- **Free-flowing documents (founder ruling).** The harness is not made deterministic with a type or
  branch per narrow case: any markdown under `project/` that is not a compiled file is a versioned
  document at that path, its kind and title read from its own front matter, born `ready`, stamped by
  the platform only with `version`, `status`, `project_id`, `brand_id`, `authored_by`,
  `authored_at`. Migration `639d081ad799` (reversible) drops the `kind` and `folder` CHECK
  vocabularies. The plan, the personas and the ICP are **pins the human agrees to in one question** —
  `role: plan` / `role: persona` in front matter, and the existing confirmation gate for an ICP,
  which now finds the document by the `icp_key` its front matter claims at any path. The only
  refusals left are `compiled_file_read_only`, `unsupported_document_type`, `body_empty` and
  `revision_conflict`; cards collapse to one `project_document` object type titled from the
  document. (This supersedes the kinds-by-folder table above, which is kept for the receipts it
  explains.)
- **Budgets are observability (founder ruling).** No hard context budget may fail or trim a turn:
  the deterministic assembler no longer raises on a required layer that does not fit and no longer
  excludes an optional candidate, and L6 keeps every message in order. `agent_context_layer` already
  persists `token_budget` and `token_count`, so "over budget" is a number on the receipt and one
  warning in the log. The four context policies that share the assembler move to
  `project-conversation-context-v3`, `stage0-trial-context-v3`, `onboarding-synthesis-context-v3`
  and `account-research-context-v3`.
- **Standing rule** (`_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`): v56 pins no
  readiness / Stage-0 / Client-KB / Product-KB tool (it adds two reads and re-pins two); the
  product-set gate source is untouched and no card compiler runs for a read or a document write; the
  pin is the turn's own project pin, with no Client-KB pin and no new `AgentTurnScopePinConflict`
  path; a read compiles nothing onto the lease and a spill is a workspace file, not lease state;
  `launch_arv2_account_research` / `launch_arv2_discovery` gained no precondition; `lint-imports` was
  re-run at Task 3, 26 kept / 0 broken; **env posture unchanged — no `.env.example` line moved and no
  new flag**. The checklist is re-run in full at the live proof. Engineering detail:
  `platform/api/clue_api/arv2/README.md` § "The four reads".

---

## 9. Phases, exit gates, ownership, timeline

| # | Phase | Builds | Exit gate | Owner |
|---|---|---|---|---|
| O0 | Contracts freeze | This document initialed; §4.3–4.5 validated live once each (as 4.2 was); catalog contract §6.4 + master plan §5.2 reworded for S5; the §7 read contract copied into `apps/frontend/docs/api-contracts/brand-context.md` | Both founders initial §12 | Aryan (docs), Shashank (contract doc copy) |
| O1 | Substrate | Migration: §3 tables, `project_product`, `product_set_selection` kind + per-element answer trigger; flags (§10) in `.env.example`; `ONBOARDING_SYNTHESIS_AGENT_MODEL` in the agent-model block | One alembic head; `make db-smoke` green; parity test green; checklist items 3, 7 | agent-built, Aryan merges |
| O2 | Exa Agent surface (leaf) — **re-based on R1 (merged 2026-09-07, PR #45)** | R1 already ships `platform/api/clue_api/arv2/exa_client.py` (search, contents, `deep_reasoning_body` with a caller-supplied `outputSchema`, `product_catalog_output_schema()` = the catalog contract §3 verbatim) behind the `ProviderCaller` wrapper (estimate row → raw record → retry/halt → result row; `sinks.py` file/memory sinks; `provider_call_ledger` spec in master plan §4). O2 therefore adds only: the Exa **Agent** surface (`/agent/runs` create + poll + stream, `output.text`/`structured`/`grounding`, `costDollars`) through the same `ProviderCaller`; the four remaining request templates (overview §4.2, reviews §4.3, per-product §4.4, evidence §4.5) as builder functions next to `product_catalog_output_schema`; the artifact mappers (§4 of each contract). Tests follow R1's founder ruling: **live against Exa, skipping with the env-var name when the key is unset; no replay fixtures.** | Live test on Insight Health reproduces the overview run's shape (`schema_satisfied`, 8 grounding rows, facts non-null) and the catalog run's 12 entries; ledger rows carry `costDollars.total` | agent-built from a charter; Aryan reviews |
| O3 | Research steps on the fleet | `arv2/onboarding_driver.py` (fleet job), `POST /onboarding` 202, step graph, catalog sync re-pointed at the artifact, background fan-out + cap, document rows with statuses | One unseeded Insight Health run: every document present or honestly failed; ledger complete; nothing on the web loop | agent-built, Aryan composes |
| O4 | Synthesis agent | Profile/prompt/two skills (§5), `exa_search_evidence@1`, materialization of inputs, outputs→documents registration. **+ 2026-09-08 — the synthesis split** (§5 addendum; branch `onboarding/o4-synthesis-split`, spec `docs/superpowers/specs/2026-09-08-arv2-onboarding-o4-synthesis-split-design.md`): `onboarding-synthesis@v2`, one ICP turn + one persona turn per ICP, the `onboarding_icp` surface, per-turn input selection into the opening context, migration `ae4a5dfb3943` | 2–3 ICPs + personas for Insight Health; no fictional names; every specific fact cited; per-role evidence when found; matches Shashank's answer keys; checklist item 1. **Split gate (2026-09-08, owed — founder-triggered):** one unseeded Insight Health re-run where the three ICP documents are servable within ~6 minutes while `persona` steps still run, three `persona` steps run concurrently and the run settles `completed`, the ICP keys on file are reused, each persona's `icp_version` equals its ICP row's version, fifteen `exa_search_evidence@1` invocations, none of them attributed to the ICP turn | content Shashank, wiring agent-built, Aryan promotes |
| O5 | Brand-context read surface | §7 endpoints; frontend Knowledge section re-lifted from the dummy on the real endpoints; status chips; progressive fill | With `CLUE_API_BASE_URL` set the page renders the real tree and fills as steps land; frontend gates green | agent-built from Shashank's charter; Aryan merges |
| O6 | Head-of-ABM integration | §8: profile, index card source, materialization, Stage-0 skill v21, product-set gate tool, ICP gate on artifact refs, launch fields | New project on Insight Health: interview → ICP pick → product set → ICP confirmation → launch; old lane off; checklist 7/7. **Built 2026-09-09 on `onboarding/o6-head-of-abm`; live exit gate owed (founder-triggered)** — see the §8 addendum | Aryan (integration point) |
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
| `CLUE_ONBOARDING_PRODUCT_EFFORT` | `medium` (O-D2) | 4.4; raise to `high` per deployment if product files read thin |
| `CLUE_ONBOARDING_REVIEWS_PHASE` | `fast` (O-D3) | when 4.3 runs (`fast`/`background`) |
| `CLUE_ONBOARDING_MAX_PARALLEL_RUNS` | `6` | background fan-out cap |
| `CLUE_ONBOARDING_PERSONA_EVIDENCE_ENABLED` | `true` | the evidence tool |
| `ONBOARDING_SYNTHESIS_AGENT_MODEL` / `_EFFORT` | `x-ai/grok-4.6` / blank (O-D1: default reasoning) | agent-model block |

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
| O-D1 | Synthesis agent model (`ONBOARDING_SYNTHESIS_AGENT_MODEL`) | `x-ai/grok-4.6`, same as every other deepagent on this branch; change it in env, never by a new profile version | ✓ (2026-09-07) — **and `ONBOARDING_SYNTHESIS_AGENT_MODEL_EFFORT` stays blank: model-default reasoning only** | ☐ |
| O-D2 | Per-product Exa Agent effort | `medium` ($0.10; ~$1.20 for a 12-product company); raise to `high` per deployment if the product files read thin | ✓ (2026-09-07) | ☐ |
| O-D3 | Customer-reviews run in fast recon or background | **fast** — the synthesis agent's ICP gates and persona pains are better with review themes, and `medium` effort keeps it under two minutes | ✓ (2026-09-07) | ☐ |
| O-D4 | O0 form: this single plan with §4–§7 as sections, or separate contract docs per call | this document; split a section out only when it changes independently | ✓ (2026-09-07) | ☐ |
| O-D5 | One ICP-confirmation gate kind over artifact refs (`@2`) replaces the `icp_spec`-row kind for new projects; `synthesize_icps` retired on the new profile | Yes | ✓ (2026-09-07) | ☐ |
| O-D6 | Evidence tool default on (`CLUE_ONBOARDING_PERSONA_EVIDENCE_ENABLED=true`) | Yes; per-deployment off switch exists | ✓ (2026-09-07) | ☐ |

Open from elsewhere, unchanged: D9 (Series A equivalence), Shashank's initials on D14–D17.
