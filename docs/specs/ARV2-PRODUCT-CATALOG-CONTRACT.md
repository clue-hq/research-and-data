# ARV2 product-catalog contract — research shape, artifact, gate, and the multi-product ruling

**Status:** RATIFIED by Aryan 2026-09-07 (rulings P1–P4 below). Shashank's column in the master
plan §12 is open. Version 1.0.

**Parent:** `ARV2-MASTER-PLAN.md` (Track O — onboarding as a research pipeline). This document is
the product-catalog child of that plan the way `ARV2-DATA-SOURCE-MAP.md` is its data-source child.

**Supersedes, for new projects only:** the one-product-per-project assumption in
`FI-production-deepagent-context-S50-product-knowledge-contract.md` §5–§6 and in the combined
human-gate amendment of `apps/frontend/docs/api-contracts/projects.md` (2026-08-15). Historical
rows, gates, pins, and receipts written under those contracts stay immutable and replayable.

## 1. What this document fixes

Onboarding must find every product a client sells, show them to the user, and let the user say
which of them a project is about. Four things are fixed here:

1. the shape the Exa search request asks for (the provider shape);
2. the platform artifact the onboarding research agent writes (the platform shape);
3. how that artifact becomes a claim, product rows, and a human gate;
4. **the ruling that a project targets a set of products, not one** (P1), with its two
   sub-rulings (P2, P3), and that a project has exactly one ICP which targets the whole set (P4).

Nothing here touches the accounts screens or contract v1 (master plan §6).

## 2. The chain, end to end

```
onboarding research agent
  └─ Exa /search, type deep-reasoning, outputSchema = §3        (provider shape)
       └─ Exa client maps output.content + output.grounding
            └─ ProductCatalogResearch@1 artifact (markdown + front matter)   (platform shape, §4)
                 └─ one account-wide claim: client.product_catalog            (§5)
                      └─ ProductCatalogSynchronizer → product rows + lineage  (§5)
                           └─ product_set_selection gate (snapshot = catalog)  (§6, §7)
                                └─ human answers selected_option_refs[]
                                     └─ project_product rows, selection_version n (§6)
                                          └─ ICP artifact + research runs pin the version
```

The model never mints a `product_id`. Ids are minted by the synchronizer, carried by the gate
snapshot, and chosen by a human. That rule is unchanged from S5.0.

## 3. The Exa request shape (provider shape) — FINAL

Exa's `/search` reference (28 Aug 2026) limits `outputSchema` to nesting depth 2 and 10 total
properties, documents only `type`, `properties`, `required`, `items`, and `description`, and
returns per-field citations automatically in `output.grounding`. Citation fields must not appear
in the schema. The finalized schema has nine properties and two levels:

```json
{
  "type": "object",
  "required": ["products"],
  "properties": {
    "coverage_note": {
      "type": "string",
      "description": "What was searched and what may still be missing."
    },
    "products": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "short_description", "offering_kind"],
        "properties": {
          "name": {
            "type": "string",
            "description": "Official product name exactly as the company writes it."
          },
          "short_description": {
            "type": "string",
            "description": "One or two sentences at portfolio level. No pricing, capability lists, integrations, competitors or customer names."
          },
          "offering_kind": {
            "type": "string",
            "enum": ["product", "platform", "integration", "partner_program", "service"],
            "description": "product = standalone offering; platform = layer over several products; integration = an existing product delivered inside a third-party system; partner_program = white-label or embed program; service = human-delivered offering."
          },
          "family": {
            "type": "string",
            "description": "Umbrella brand or product family, when the company groups offerings that way. Omit if none."
          },
          "lifecycle": {
            "type": "string",
            "enum": ["active", "beta", "sunset", "unknown"]
          },
          "official_url": {
            "type": "string",
            "description": "Canonical page for this offering on the company's own domain. Omit if none exists."
          }
        }
      }
    }
  }
}
```

Request discipline (behaviour lives in `systemPrompt`, shape lives in `outputSchema`):

- `type: "deep-reasoning"`; `numResults` raised above the default 10 (cap 100) — an exhaustive
  list needs the headroom; `additionalQueries` seeded with the company's product vocabulary once
  a first pass has revealed it.
- `systemPrompt`: prefer pages on the company's own domain; list every distinct product page;
  keep integrations and partner programs separate from standalone products; never invent an
  offering; when unsure of a field, omit it.
- Two passes, compared: one with `includeDomains` restricted to the client's domain, one open.
  The open pass catches offerings announced only through partners or press.
- Every raw response is saved before parsing (master plan Appendix A); the cost ledger records
  the call.
- `enum` is not on Exa's documented keyword list. If a request is rejected, the allowed values
  move into `description` and the enum is enforced platform-side at mapping time. The schema
  above stays the contract either way.

This shape is seen by exactly one module: the Exa client under `platform/api/clue_api/arv2/`.
Nothing else in the platform reads or stores it.

## 4. The platform artifact — `ProductCatalogResearch@1`

One markdown document per research run, written by the onboarding research agent into the
deepagent workspace and the durable artifact store, following the ICP artifact pattern (master
plan §5.2): front matter is the structured contract, the body is the human-readable prose.

Front matter (`kind: product-catalog`):

| Key | Type | Source | Notes |
|---|---|---|---|
| `kind` | `"product-catalog"` | constant | |
| `as_of` | date | run timestamp | never from the model |
| `company_domain` | string | onboarding input | the domain the run was scoped to |
| `coverage_note` | string \| null | Exa `coverage_note` | coverage confidence, never a completeness claim |
| `products[]` | list | Exa `products[]` | one entry per offering, in the order returned |
| `products[].name` | string | Exa | required |
| `products[].short_description` | string | Exa | required; portfolio level only (S50-D1) |
| `products[].offering_kind` | enum | Exa | required; the five values of §3 |
| `products[].family` | string \| null | Exa | |
| `products[].lifecycle` | enum \| null | Exa | `active` / `beta` / `sunset` / `unknown` |
| `products[].official_url` | string \| null | Exa | |
| `products[].aliases[]` | list | empty on this path | kept optional so a later source can fill it; the 2026-09-07 schema deliberately dropped it from the Exa request |
| `products[].sources[]` | list of `{url, title}` | Exa `output.grounding` | every grounding row whose `field` starts with `products[i]` |
| `products[].grounding_confidence` | enum \| null | Exa `output.grounding` | the lowest confidence among that entry's grounding rows; a label, never a gate |

Mapping rules:

- `sources[]` is the only place per-product provenance lives. The Exa schema carries none.
- An entry with no `name` or no `short_description` is dropped and listed in the artifact body
  under "Dropped by the mapper"; the run is never refused (lenient mode, master plan §4).
- Detailed product facts (capabilities, pricing, integrations, competitors, customer evidence) do
  not belong here. They are product-scoped research, one artifact per selected product, produced
  after selection (§6).

## 5. Claim and synchronization deltas

- The artifact's `products[]` becomes the value of one account-wide claim, field key
  `client.product_catalog` (`product_id IS NULL`), `extraction_method = llm_synthesis`,
  `source_url` = the client's domain, run lineage stamped. This is the same field the old
  official-site path wrote; the registered value schema in
  `subsystems/research/clue_research/stage0/fields.py` is extended, not replaced: `offering_kind`,
  `family`, `lifecycle`, `official_url`, `sources`, `grounding_confidence` are added as optional
  members; `name` + `short_description` stay the only required ones.
- `platform/api/clue_api/product_catalog_sync.py::CatalogEntry` currently forbids extra keys. It
  accepts the new optional members. Matching stays conservative: normalized name, then alias.
  With `aliases` empty on this path the match is effectively name-only; a product is created
  once, and renames stay a human act (S5.0 §7 unchanged).
- Every entry becomes a `product` row regardless of `offering_kind`. Kind is a grouping label,
  not a filter: a partner program is a legitimate ABM motion.
- `lifecycle` is recorded on the claim and shown as a label. The spine `product.status`
  (`active` / `archived`) is human-controlled and is never set from research.
- `official_url` is threaded into `OfficialSiteProductTarget` so the later per-product research
  never searches for a page it already knows (Appendix A law).

## 6. The multi-product ruling (P1) and what it changes

### 6.1 Rulings

| # | Ruling | Aryan |
|---|---|---|
| **P1** | **A project targets a set of products, not one.** | ✓ 2026-09-07 — "a very important ruling" |
| **P2** | The set can change at any time, as a new version. Runs keep the version they pinned; nothing is re-researched automatically. | ✓ 2026-09-07 |
| **P3** | A project has exactly one ICP. | ✓ 2026-09-07 |
| **P4** | That ICP targets the whole project product set; there is no per-ICP product subset. | ✓ 2026-09-07 (follows from P3) |

### 6.2 Durable shape

New table `project_product`:

```
project_product (
  workspace_id        text  NOT NULL,
  project_id          text  NOT NULL,
  product_id          text  NOT NULL,
  brand_id            text  NOT NULL,
  selection_version   int   NOT NULL CHECK (selection_version >= 1),
  gate_id             uuid  NOT NULL,          -- the answered product_set_selection gate
  confirmed_by        text  NOT NULL,          -- the human addressee who answered
  confirmed_at        timestamptz NOT NULL,
  PRIMARY KEY (project_id, selection_version, product_id),
  FOREIGN KEY (product_id, workspace_id, brand_id) REFERENCES product (product_id, workspace_id, brand_id),
  FOREIGN KEY (project_id, workspace_id, brand_id) REFERENCES project (project_id, workspace_id, brand_id)
)
```

- Each confirmation writes the **full** set as a new `selection_version` (append-only; the
  0004-style append-only trigger applies). The current set is the highest version.
- Same-workspace, same-brand pinning is structural, exactly as `project.product_id` had it.
- `project.product_id` stays as a frozen legacy column. New projects never write it. The
  `confirm_project_product@1` tool and `clue_spine.confirm_project_product` are replay-only for
  historical projects.
- A `selection_version` is minted by the answer route, never by the model.

### 6.3 The gate

New gate kind `product_set_selection` on the existing `agent_gate` substrate. The old
`product_selection` kind stays for replay of historical gates; no new gate of that kind is opened.

| Gate kind and decision | Required auxiliary value | Forbidden value |
|---|---|---|
| `product_set_selection + approved` | `decision_payload.selected_option_refs[]`, ≥ 1 entries, each proved to be a `products[].product_id` in the immutable snapshot, no duplicates | `selected_option_ref` |
| `product_set_selection + rejected/revised` | none | `selected_option_ref` and every `decision_payload` member |

- The candidate-membership check is the same database-trigger pattern the single-product kind
  uses (`064ad0f43519`), applied per array element.
- Subject ref: `client-product-catalog:{client_entity_id}:v{company_client_kb_version}`;
  subject snapshot: §7.1. Digest, addressee, permitted decisions, privacy bindings: unchanged
  from the combined human-gate amendment.
- The tool that opens it is the existing `open_product_selection_gate@1` re-pointed at the new
  kind (a new tool version). It derives every candidate from the synchronized catalog; the model
  supplies only the trusted turn ref. A gate may be opened again on a project that already has a
  set (P2); "already confirmed" is no longer a refusal.
- The answer route validates membership, inserts the immutable receipt, then writes
  `project_product` rows at `max(selection_version) + 1` in the same transaction.

### 6.4 The research lane

- A claim still carries one `product_id` or none. A fact is about one product.
- ARV2 runs pin `(project_id, selection_version)`, never a single product. The launch contract
  (master plan §5.1) gains `product_selection_version` on the run, stamped by the launcher from
  the project's current set at launch time. Later versions do not touch a running or finished run
  (P2).
- The ICP artifact (master plan §5.2) records `product_selection_version` in its front matter as
  provenance — the set it was written against. It carries no product subset (P4). A new product
  set does not invalidate the ICP; the agent may propose an ICP revision in conversation, and a
  human confirms it as a new ICP version.
- Product-scoped research after selection: one `product-research` artifact per product in the
  current set, materialized into the deepagent workspace. Products added in a later version get
  theirs on the next onboarding turn; nothing runs automatically (P2).
- Value narratives, when they return, key on `(account, persona, product)` and iterate the set.
  Not in v1.

### 6.5 The old lane (quarantine-bound; no rewrite)

Every reader below sees a NULL `project.product_id` for a new project and falls into the "no
product selected" state that S5.0 §5 already defines. None of them is rewritten for the set:

- `agent_turn_scope_pin` (`company-and-selected-product-required-v3`): pins `product_id = NULL`,
  `product_kb_version = NULL`.
- `ProductProfileCard@1`, `ProductKnowledgeCard@1`, `list_product_knowledge@1`,
  `inspect_product_claim@1`: absent / not admitted.
- `project_run.product_id` and `project_run_stage0_pins_complete`: old-lane Stage-0 runs only;
  ARV2 runs do not use those pins.
- `account_research_turn_wiring` (run product must equal project product), the C7 pinned read
  (`request.product_id` vs `project_run.product_id`), `stage0_trial`: unchanged, historical.

All of the above are in the R0 quarantine ledger. Their deletion rides Phase 6.

## 7. The wire contract to the frontend

### 7.1 Gate snapshot (`product_set_selection`)

```json
{
  "client_entity_id": "…",
  "company_client_kb_version": 3,
  "products": [
    {
      "product_id": "prd_…",
      "name": "Aura AI Scribe",
      "short_description": "Ambient clinical documentation with automated coding suggestions.",
      "aliases": [],
      "status": "active",
      "offering_kind": "product",
      "family": "Aura",
      "lifecycle": "active",
      "official_url": "https://www.insighthealth.ai/ambient"
    }
  ],
  "omitted_count": 0,
  "current_selection": { "selection_version": 1, "product_ids": ["prd_…"] }
}
```

`current_selection` is null on a project with no set yet; on a re-selection it pre-checks the
current members. `offering_kind`, `family`, `lifecycle`, `official_url` are optional; a reader
treats a missing member as absent. Ids are server-minted.

### 7.2 Gate answer (`gate_response`)

```jsonc
{
  "gate_id": "<durable-gate-uuid>",
  "decision": "approved|rejected|revised",
  "expected_subject_sha256": "<64-lowercase-hex>",
  "expected_estimated_cost_cents": null,
  "selected_product_ids": ["prd_…", "prd_…"]   // only for product_set_selection + approved; ≥ 1
}
```

`selected_product_ids` is a browser transport name. The server validates membership and persists
`decision_payload.selected_option_refs`. `revision_request` and `selected_product_ids` remain
mutually exclusive.

### 7.3 Rendering rules

- Checkboxes, grouped by `offering_kind` in the fixed order product → platform → integration →
  partner_program → service; each group has a plain-language heading.
- `family` as a secondary label; `lifecycle` as a small label when not `active`; `official_url`
  as a source chip resolved server-side with no dates (ruling R1).
- Primary action "Use these products", disabled until ≥ 1 is checked. The receipt lists every
  chosen product's retained display name from the immutable snapshot; never a technical id.
- A snapshot with zero candidates renders the existing recovery notice.
- `archived` products are shown unchecked and not selectable.

The Zod model gains `offeringKind`, `family`, `lifecycle`, `officialUrl` as optional members of
`ProductSelectionOption`, a `currentSelection` member, and a set-valued decision variant. The
single-product variant stays for historical gate replay.

## 8. Non-goals and open items

- No product-level budget, no product-level research caps. Onboarding is budget-unconstrained
  (founder ruling 2026-08-13).
- No automatic archive/merge/rename of products from research (S5.0 §7).
- No per-ICP product subset (P4). If a client needs two ICPs for two product lines, that is two
  projects.
- Open, not blocking: the display of the product set on the accounts screens (contract v1 has no
  slot for it; per the dummy-frontend rule it stays invisible until a slot is designed).
- Open, Shashank's column: initials on P1–P4 in the master plan §12.

## 9. Files this contract touches when implemented (for the charter, not done here)

| Area | Change |
|---|---|
| `subsystems/research/clue_research/stage0/fields.py` | extend `_PRODUCT_CATALOG` value schema with the optional members (§5) |
| `platform/api/clue_api/product_catalog_sync.py` | `CatalogEntry` accepts the optional members; `official_url` → `OfficialSiteProductTarget` |
| `alembic/` | `project_product` table + append-only trigger; `product_set_selection` in the gate-kind vocabulary; the answer trigger's per-element membership check |
| `platform/api/clue_api/agent_gate.py`, `chat/schemas.py`, `chat/router.py` | new kind, `selected_option_refs[]` invariants, the write of `project_product` rows |
| `platform/api/clue_api/product_selection_gate_tools.py` | re-point at the new kind; drop the "already confirmed" refusal; `current_selection` in the snapshot |
| `platform/api/clue_api/arv2/exa_client.py` | the §3 request and the §4 mapping (leaf code, fixture-tested) |
| `apps/frontend/src/features/projects/model/chat-gate.ts` + `components/chat-gate-card.tsx` | set-valued option list and decision (§7.3) |
| `apps/frontend/docs/api-contracts/projects.md` | the amendment pointer (added 2026-09-07) |
| `.env.example` | any new flag the Exa client introduces, at introduction (parity rule) |
