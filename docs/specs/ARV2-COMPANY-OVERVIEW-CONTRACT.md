# ARV2 company-overview contract — the Exa Agent request, the `CompanyOverviewResearch@1` artifact, and its rendering

**Status:** Schema and request VALIDATED on a live run by Aryan 2026-09-07 (Insight Health,
`agent_run_11b83e1af2bd44f399badec0d8c77ebd`; see §6). Version 1.0. Sibling of
`ARV2-PRODUCT-CATALOG-CONTRACT.md`; parent `ARV2-MASTER-PLAN.md` Track O.

**What it fixes.** The second of the fast-recon research calls (master plan Track O; the
onboarding lane replaces scrapers with Exa): one **Exa Agent** run per client that produces the
company overview the brand-context page renders under *Company* and the Head-of-ABM reads from its
workspace before the Stage-0 interview. The product lineup (`ARV2-PRODUCT-CATALOG-CONTRACT.md`) and
the customer-reviews run (to be specified) are separate calls; this document tells the model so.

Standing rule §10 of the catalog contract applies unchanged: this artifact is **never** a Client-KB
claim, and nothing on this path may demand a Client-KB version, readiness decision, or Stage-0 pin.

## 1. Provider surface

`POST https://api.exa.ai/agent/runs` (SDK: `exa.agent.runs.create(...)` then
`poll_until_finished`). Async; poll or stream. Verified facts about the surface (Exa Agent guide,
read 2026-09-07):

- `outputSchema` supports the full JSON Schema specification (nullable unions, `format`,
  `maxItems`, `additionalProperties: false`). The `/search` limits (depth 2, 10 properties) do
  **not** apply here.
- Response: `output.text` (short natural-language answer), `output.structured` (validated JSON),
  `output.grounding[]` (`{field, citations[{url,title}], confidence}`), `usage`
  (`agentComputeUnits`, `searches`), `costDollars`, `stopReason` (`schema_satisfied` on success).
- Effort: fixed prices — `minimal` $0.012, `low` $0.025, `medium` $0.10, **`high` $0.50**,
  `xhigh` $1.00; `auto` metered to a $5 cap. **This contract uses `high`** (Aryan's choice; the
  sample run cost exactly $0.50).
- `previousRunId` exists for follow-ups; not used here.

## 2. The request — FINAL

### 2.1 Query (as run; `[COMPANY NAME]` is substituted with the client's domain/name)

```text
Research [COMPANY NAME] and create a comprehensive report covering these areas:

**==The Origin Story==**
- How did this company start? What problem were they solving?
- Who are the founders? What's their background and previous experience?
- Early funding, initial customers, and first product iterations

**==The Business Reality==**
- How does this company make money? What's their revenue model?
- Are they profitable? What's their financial trajectory?
- Who funds them? Latest valuation and investor expectations

**==What They Actually Do==**
- Current products and services – skip the marketing fluff
- How their technology works under the hood
- Key features that matter to users
- Product evolution and major pivots

**==The Market Position==**
- Who are their main competitors? How do they stack up?
- What's their competitive advantage? Is it defensible?
- Market size, share, and growth potential
- Target customers and use cases

**==The Customer Reality==**
- Who actually uses this? Customer segments and personas
- Positive reviews and success stories
- Complaints, negative feedback, and common problems
- Customer retention and satisfaction data

**==The People==**
- Current leadership team and key employees
- Company culture and employee reviews
- Team size, hiring patterns, and organizational structure

**==The Problems==**
- What criticism do they face? Industry controversies
- Failed products or initiatives
- Operational challenges and technical debt

**==The Future==**
- Product roadmap and strategic direction
- Market trends that help or hurt them
- Partnerships, acquisitions, and expansion plans
- Regulatory risks and opportunities

**==Recent Context==**
- Latest news, announcements, and developments
- Industry changes affecting the company
- Geopolitical pressures and international strategy

company name is [COMPANY NAME]
```

The query deliberately asks for more than the schema keeps. The schema is the filter: sections the
schema does not name (employee reviews, culture, technical debt, geopolitics) are not returned, and
the model's search is wider for it. The sample run confirmed the model respects the schema's
"do not enumerate products / do not reproduce reviews" instructions.

### 2.2 System prompt (recommended; the sample run used none — add it in production)

```text
Prefer the company's own domain first, then press and case studies, then third-party sources.
Every section states where each fact came from. Quote the company's own phrasing for its value
proposition and any customer count. Do not enumerate individual products; another document owns
the catalog. Do not reproduce customer reviews; another document owns them. If a fact cannot be
established, leave the field null and add it to not_found. Never estimate silently; label any
estimate as an estimate inside the text.
```

### 2.3 `outputSchema` — FINAL (verbatim as run)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["facts", "sections", "competitors", "named_customers", "not_found"],
  "properties": {
    "facts": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "legal_name": { "type": ["string", "null"] },
        "website": { "type": ["string", "null"], "format": "uri" },
        "founded_year": { "type": ["integer", "null"] },
        "headquarters": { "type": ["string", "null"] },
        "employee_range": { "type": ["string", "null"], "description": "e.g. 51-200, as publicly stated or estimated; say which" },
        "funding_total_usd": { "type": ["number", "null"] },
        "latest_round": { "type": ["string", "null"], "description": "round name, amount, date, lead investor" },
        "investors": { "type": "array", "maxItems": 15, "items": { "type": "string" } },
        "revenue_model": { "type": ["string", "null"], "description": "how they charge: per seat, per encounter, platform fee, services" },
        "pricing_posture": { "type": ["string", "null"], "description": "published prices, quote-only, freemium, enterprise-only" },
        "industries_served": { "type": "array", "maxItems": 10, "items": { "type": "string" } },
        "geographies": { "type": "array", "maxItems": 10, "items": { "type": "string" } },
        "customer_count_claim": { "type": ["string", "null"], "description": "the company's own stated number, verbatim, with where it was stated" },
        "regulatory_posture": { "type": ["string", "null"], "description": "certifications and compliance claims relevant to buyers, e.g. HIPAA, SOC 2, BAA availability" }
      }
    },
    "sections": {
      "type": "object",
      "additionalProperties": false,
      "required": ["origin_story", "business_model", "positioning", "market_position", "customer_segments", "leadership", "recent_context"],
      "properties": {
        "origin_story": { "type": "string", "description": "Markdown. Founding problem, founders and their prior experience, first customers and early product." },
        "business_model": { "type": "string", "description": "Markdown. How they make money, pricing posture, funding trajectory. No valuation speculation." },
        "positioning": { "type": "string", "description": "Markdown. Value proposition in the company's own words, the differentiators they claim, and the portfolio described in one paragraph. Do NOT list individual products; another document owns the catalog." },
        "market_position": { "type": "string", "description": "Markdown. Main competitors and how the company stacks up, defensibility, market size and growth where sourced." },
        "customer_segments": { "type": "string", "description": "Markdown. Who buys and who uses it: segments, roles, organisation types and sizes, use cases. Cite case studies. Do not reproduce reviews; a separate document owns them." },
        "leadership": { "type": "string", "description": "Markdown. Current leadership team with titles. No employee reviews or culture commentary." },
        "recent_context": { "type": "string", "description": "Markdown. Announcements, partnerships, expansion, hiring signals from the last 12 months, each dated." }
      }
    },
    "competitors": {
      "type": "array",
      "maxItems": 12,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["name", "how_they_compare"],
        "properties": {
          "name": { "type": "string" },
          "website": { "type": ["string", "null"], "format": "uri" },
          "how_they_compare": { "type": "string", "description": "one or two sentences, sourced" }
        }
      }
    },
    "named_customers": {
      "type": "array",
      "maxItems": 30,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["name"],
        "properties": {
          "name": { "type": "string" },
          "segment": { "type": ["string", "null"] },
          "evidence_kind": { "type": "string", "enum": ["case_study", "logo_wall", "press", "review", "other"] }
        }
      }
    },
    "not_found": {
      "type": "array",
      "maxItems": 20,
      "items": { "type": "string", "description": "an item that was searched for and could not be established, stated plainly" }
    }
  }
}
```

Request parameters: `effort: "high"`; no `dataSources`; no contact enrichment fields (they are
billed separately and are not wanted here). The raw response is saved before parsing and the
`costDollars` / `usage` block goes on the cost ledger (master plan Appendix A).

## 3. The platform artifact — `CompanyOverviewResearch@1`

One markdown document per run, `kind: company-overview`, written to the durable artifact store and
materialized read-only into the deepagent workspace at `brand/knowledge/company/overview.md`.
Rendered read-only in the brand-context page under *Company*.

### 3.1 Front matter

| Key | Source | Notes |
|---|---|---|
| `kind` | constant `company-overview` | |
| `as_of` | run timestamp | never from the model |
| `company_domain` | onboarding input | |
| `provider_run_id` | Exa `id` | audit join to the raw response |
| `facts` | `output.structured.facts` | verbatim; nulls kept as nulls |
| `competitors[]` | `output.structured.competitors` | verbatim |
| `named_customers[]` | `output.structured.named_customers` | verbatim |
| `not_found[]` | `output.structured.not_found` | verbatim — **rendered**, never hidden (see §4) |
| `sources` | `output.grounding` | map `field → {citations[], confidence}`; keys are the grounding field paths (`structured.facts`, `structured.sections.<name>`) |
| `cost_usd`, `searches` | `costDollars.total`, `usage.searches` | ledger copy |

### 3.2 Body — fixed headings, fixed order (product vocabulary, never model-written)

```
# Company overview                       ← facts block rendered as the bullet list
## Origin story                          ← sections.origin_story
## Business model                        ← sections.business_model
## Positioning                           ← sections.positioning
## Market position                       ← sections.market_position
## Competitors                           ← competitors[] as a table: name · website · how they compare
## Customer segments                     ← sections.customer_segments
## Named customers                       ← named_customers[] as a table: name · segment · evidence kind
## Leadership                            ← sections.leadership
## Recent context                        ← sections.recent_context
## Not established                       ← not_found[] as a list
## Sources                               ← per-section citations from grounding, with confidence
```

The model writes its own `##` inside a section string (the sample did: "## Leadership and
organization"). The renderer **demotes** any heading inside a section body by one level so the
fixed headings stay the only H2s. Inline bracketed labels the model writes ("[Company About]",
"[Business Wire]") are left as text; they are not links.

## 4. Rules

- **`not_found` is rendered.** An empty, named gap is a correct output (repo principle). The brand
  page shows "Not established" as a section; the Head-of-ABM must not state anything listed there.
- **No products, no reviews.** The overview describes the portfolio in a paragraph; the catalog and
  the reviews document own the details. If a run enumerates products anyway, the renderer does not
  strip them; the prompt is fixed instead.
- **Provenance granularity is per section, not per fact, on this surface.** The sample run returned
  8 grounding rows: one for `facts` and one per section; `competitors`, `named_customers`, and
  `not_found` carried **no** grounding rows. Consequence: a competitor or customer row has no URL
  unless the model filled `website`. Open item (§7): add `evidence_url` to those two item shapes in
  a v1.1 schema if the founders want row-level provenance; not changed here because the v1.0 schema
  is the one validated live.
- **Personal data.** Leadership names and titles are public professional data from the company's
  own site and press; stored as-is. No employee-review or culture text is requested or kept.
- **Money.** `high` is a fixed $0.50 per run; onboarding is budget-unconstrained (ruling
  2026-08-13). Record, never cap.
- **Freshness.** The artifact is versioned per run; re-running onboarding mints a new version; a
  turn pins the version it materialized (context-composition D4 applied to artifacts).

## 5. Where it is read

- **Brand-context page → Knowledge → Company → `overview.md`**, read-only markdown render.
- **Head-of-ABM workspace** at `brand/knowledge/company/overview.md`, read by the agent itself
  (`read_file`) before the Stage-0 interview; listed in the L2 brand-knowledge index card with
  version and status. Nothing from it enters the opening context verbatim (Aryan, 2026-09-07).
- **ICP synthesis** reads `facts`, `positioning`, `market_position`, `customer_segments`,
  `named_customers` and `competitors` as its company-side inputs (next contract).

## 6. Sample run (Insight Health, 2026-09-07) — the acceptance reference

| Metric | Value |
|---|---|
| Run id | `agent_run_11b83e1af2bd44f399badec0d8c77ebd` |
| Effort / stop reason | `high` / `schema_satisfied` |
| Wall time | 67 s (12:26:41 → 12:27:48 UTC) |
| Cost | $0.50 (agent compute $0.20, search $0.30); 2 ACU, 60 searches |
| Grounding rows | 8 (facts + 7 sections); 7 `high`, 1 `medium` (market_position) |
| Sections | 1.1–1.7k chars each |
| Competitors | 5 (Tennr, HealOS, Documo, PracticeEHR, Sully.ai) |
| Named customers | 8, all press/review/other evidence kinds |
| `not_found` | 7 items: audited financials/ARR, confirmed valuation, market share/TAM, retention/NPS, attributable negative-review corpus, dated roadmap, FDA clearance |

Quality notes from the read: facts were specific and dated (Series A $11M led by Standard Capital,
April 2026; published Aura pricing; SOC 2 Type II + HIPAA + BAA on paid tiers); the model kept
products to a portfolio paragraph as instructed; `employee_range` honestly reported the
13-vs-20 discrepancy between company releases and LinkedIn. The raw JSON is kept in
`.context/attachments/MB8vCz/` for this session and must be copied into the ARV2 evidence folder
when the onboarding lane's acceptance set is assembled.

## 7. Open items

- **v1.1 schema:** `evidence_url` on `competitors[]` and `named_customers[]` items (row-level
  provenance), and `source_url` on `customer_count_claim`. Founders' call; schema change only.
- **The customer-reviews run** (separate Agent run, effort `medium`) — its contract is not yet
  written.
- **Per-product research** (one Agent run per catalog entry, background) — contract not yet
  written; the catalog contract §6.4 already says it runs for every discovered product.
- **The ICP and audience-persona synthesis** that consumes this document — next.
