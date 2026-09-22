# ARV2 product-catalog contract — research shape, artifact, gate, and the multi-product ruling

**Amendment, Aryan 2026-09-21 — automatic approval:** Brand kits and ICP/product
targeting no longer require approve/reject actions. For current project turns,
`configure_project_targeting@1` replaces the product-selection and ICP-confirmation
gates described below. It selects only active catalog product ids belonging to
the project's brand, preserves an existing override for the same ICP, and records
the exact ICP artifact and versioned product set. Explicit product ids take
precedence; otherwise the first application uses ICP products, an existing set,
or all active brand products, in that order. The user can revise the set in chat.

P1–P4's multi-product set, versioning and one-ICP-per-project invariants remain.
Automatic selections store `confirmation_turn_id` instead of `gate_id`, with an
exclusive-source database constraint. Historical human receipts are immutable;
no synthetic gate answer is created. The current profile grants the automatic
tool and withholds both old gate tools. The original gate-specific requirements
below are retained as historical contracts and are superseded by this amendment.

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
3. how that artifact becomes product rows and a human gate (no company claim — §5);
4. **the ruling that a project targets a set of products, not one** (P1), with its two
   sub-rulings (P2, P3), and that a project has exactly one ICP which targets the whole set (P4).

Nothing here touches the accounts screens or contract v1 (master plan §6).

## 2. The chain, end to end

```
onboarding research agent
  └─ Exa /search, type deep-reasoning, outputSchema = §3        (provider shape)
       └─ Exa client maps output.content + output.grounding
            └─ ProductCatalogResearch@1 artifact (markdown + front matter)   (platform shape, §4)
                 └─ ProductCatalogSynchronizer (input = the artifact ref) → product rows + lineage  (§5)
                           └─ product_set_selection gate (snapshot = catalog)  (§6, §7)
                                └─ human answers selected_option_refs[]
                                     └─ project_product rows, selection_version n (§6)
                                          └─ ICP artifact + research runs pin the version
```

The model never mints a `product_id`. Ids are minted by the synchronizer, carried by the gate
snapshot, and chosen by a human. That rule is unchanged from S5.0. What changed (2026-09-07 amendment):
no Client-KB claim or version sits anywhere on this chain — see §5 and §10.

## 3. The Exa request shape (provider shape) — FINAL

Exa's `/search` reference (28 Aug 2026) limits `outputSchema` to nesting depth 2 and 10 total
properties, documents only `type`, `properties`, `required`, `items`, and `description`, and
returns per-field citations automatically in `output.grounding`. Citation fields must not appear
in the schema. The finalized schema has eight properties (two top-level, six on each product item; the R1 Exa client copies this JSON verbatim and Exa accepted it, `enum` included, on 2026-09-07) and two levels:

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
            "description": "The offering's name exactly as its official_url page writes it, keeping that page's spelling, spacing and capitalisation."
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
            "description": "The page on the company's own domain where this offering is presented; a page may present several offerings. Not the homepage, a pricing page or a blog post. Omit only if no such page exists."
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
  offering; when unsure of a field, omit it. **Amended 2026-09-09** (validated in the Exa
  playground, 2026-09-08), because §5.1's ladder reads the answer as identity evidence: for each
  offering give `official_url` as the page on the company's own domain where that offering is
  presented (a page may present several offerings), and give `name` exactly as that page writes it
  for the offering, keeping the page's own spelling, spacing and capitalisation; if an offering has
  no page of its own on the company's domain, omit `official_url` rather than citing the homepage
  or a listing page. The two `description`s above carry the same two rules on the schema side.
  A shared page is *evidence*, never a rule that two offerings on one page must be one product —
  and a homepage repeated across every entry is worse than an absent page, because it reads as
  "all one offering".
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

## 5. Synchronization deltas — the artifact is the input; no company claim is written

**Amended 2026-09-07 (Aryan, same day):** the new onboarding lane stores seller-company knowledge as
markdown artifacts, never as Client-KB claims. The synchronizer therefore takes the
`ProductCatalogResearch@1` artifact (its ref + digest) as input and records lineage against that
artifact ref, not against a `client.product_catalog` claim or a Client-KB version. The registered
`client.product_catalog` field and its old official-site writer stay as replay-only history.

- `platform/api/clue_api/product_catalog_sync.py::CatalogEntry` currently forbids extra keys. It
  accepts the new optional members (`offering_kind`, `family`, `lifecycle`, `official_url`,
  `sources`, `grounding_confidence`); `name` + `short_description` stay the only required ones.
  `CatalogLineage` gains `catalog_artifact_ref` (+ sha256) and drops the `company_client_kb_version`
  / `catalog_claim_id` requirement for new-lane runs. Matching stays conservative: normalized name,
  then alias.
  With `aliases` empty on this path the match is effectively name-only; a product is created
  once, and renames stay a human act (S5.0 §7 unchanged).
- Every entry becomes a `product` row regardless of `offering_kind`. Kind is a grouping label,
  not a filter: a partner program is a legitimate ABM motion.
- `lifecycle` is recorded on the artifact entry and shown as a label. The spine `product.status`
  (`active` / `archived`) is human-controlled and is never set from research.
- `official_url` is threaded into `OfficialSiteProductTarget` so the later per-product research
  never searches for a page it already knows (Appendix A law).

### 5.1 The catalog identity ladder (added 2026-09-09)

Four live re-runs on one workspace grew that brand's product rows from 19 to 28: the lineup asks
the same question every run and spells the same offering differently each time ("AI Front Desk",
then "AI FrontDesk Agent"). The onboarding synchronizer
(`platform/api/clue_api/arv2/onboarding_lineage.py::synchronize_catalog`) resolves each entry down
four rungs, in order, and stops at the first that answers:

1. **the same lineage row** — a row already written for this `(document, ordinal)` is mirrored
   verbatim, so re-driving one document is a no-op;
2. **a prior lineage binding of the same entry fingerprint** → `lineage_reused`, whichever rung
   originally made that binding (a durable decision is replayed, never re-derived — including one a
   model made);
3. **the entry's spelling key** (`normalize_identity`: `™®©℠` stripped before NFKC, case folded,
   whitespace and punctuation dropped, **no word ever dropped**) against the names *and aliases* on
   file — exactly one hit is `alias_reused`, several hits is `unresolved_ambiguous`;
4. **one batched model reconciliation** after the loop, over everything left over, with each
   entry's `official_url` and description as evidence.

What merges automatically is deliberately narrow: rungs 1–3 (deterministic) and, on rung 4, only a
`high`-confidence match → `model_reused`. Anything the model answers with less confidence **mints a
new product row** and is recorded `model_unsure` with the model's own confidence and reason, for a
human to look at. Minting a duplicate is recoverable; a wrong merge silently retargets a campaign.

Every match on rung 3 or rung 4 writes the *observed* spelling back as an alias
(`add_product_aliases`), so the next run's rung 3 resolves deterministically what rung 4 had to
reason about. Nothing on this path ever renames, merges or archives a product row — the only spine
writes are `INSERT product` and appending aliases — and there is **no stoplist of "generic" tokens
anywhere** (founder ruling 2026-09-08: a one-company heuristic would silently merge distinct
products at another company).

The model stage is composed per run behind `CLUE_ONBOARDING_CATALOG_RECONCILE_ENABLED` (model:
`CLUE_ONBOARDING_RECONCILE_MODEL`). It never raises and never decides alone: a worker without an
OpenRouter credential composes the lane anyway, logs `onboarding.reconciler_not_composed` once, and
runs rungs 1–3 only; a failed or malformed call degrades to "every leftover is a new product at
`low` confidence", which is what the ladder did before the stage existed.

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

**`onboarding_product_lineage` — the two model states (migration `be9f4984729a`, 2026-09-09).**
The table carried the S5 resolution vocabulary verbatim (`created` / `alias_reused` /
`lineage_reused` / `unresolved_ambiguous`); §5.1's fourth rung adds two more, and both, like every
resolved state, carry a product:

| `resolution_state` | Meaning |
|---|---|
| `model_reused` | the reconciler matched the entry onto an existing product row, at `high` confidence |
| `model_unsure` | the reconciler minted a row, but said so at less than `high` confidence — flagged for the human gate |

`unresolved_ambiguous` stays the **only** product-less state, so "did this entry get a product?"
remains one structural question. Two nullable columns record the reconciler's own account of
itself: `reconcile_confidence` (`high` / `medium` / `low`, CHECKed) and free-text
`reconcile_reason`. Both are NULL for every deterministically-resolved row — a NULL says "no model
decided this", which is the honest reading — and both are mirrored onto the `ProductLink` the
synchronizer returns.

### 6.3 The gate

New gate kind `product_set_selection` on the existing `agent_gate` substrate. The old
`product_selection` kind stays for replay of historical gates; no new gate of that kind is opened.

| Gate kind and decision | Required auxiliary value | Forbidden value |
|---|---|---|
| `product_set_selection + approved` | `decision_payload.selected_option_refs[]`, ≥ 1 entries, each proved to be a `products[].product_id` in the immutable snapshot, no duplicates | `selected_option_ref` |
| `product_set_selection + rejected/revised` | none | `selected_option_ref` and every `decision_payload` member |

- The candidate-membership check is the same database-trigger pattern the single-product kind
  uses (`064ad0f43519`), applied per array element.
- Subject ref (ruling D10, 2026-09-09): `brand-product-catalog:{brand_id}:{catalog_document_id}`,
  where a brand with no catalog document yet names that absence literally —
  `brand-product-catalog:{brand_id}:none`. The subject revision is the catalog document's own
  version, or `1` when there is no document (the frontend refuses a revision below 1, and a brand
  whose product rows exist without a catalog document is still a legitimate subject). The gate is
  therefore anchored on the brand's catalog as it currently stands, never on a Client-KB version.
  Subject snapshot: §7.1. Digest, addressee, permitted decisions, privacy bindings: unchanged
  from the combined human-gate amendment.
- The tool that opens it is a new version of `open_product_selection_gate` pointed at the new
  kind. **It derives every candidate from the spine `product` rows for the workspace brand plus
  the current catalog artifact ref — never from `ClientKnowledgeCard@2` or a Client-KB version.**
  The `@1` refusals `product_catalog_unavailable` (no Client-KB) and
  `project_product_already_confirmed` do not exist in the new tool; the only refusals are "no
  human addressee" and "no product rows yet". The model supplies only the trusted turn ref. A gate
  may be opened again on a project that already has a set (P2).
- The answer route validates membership, inserts the immutable receipt, then writes
  `project_product` rows at `max(selection_version) + 1` in the same transaction.
- A product whose lineage row is `model_unsure` (§6.2) is a candidate like any other, flagged for
  the gate: the human is the one who decides whether it is really a distinct offering. How the
  flag is surfaced in the snapshot and the card is O6's, not fixed here.

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
  "brand_id": "brd_…",
  "catalog_document_id": "…",
  "catalog_version": 3,
  "products": [
    {
      "product_id": "prd_…",
      "name": "Aura AI Scribe",
      "short_description": "Ambient clinical documentation with automated coding suggestions.",
      "aliases": [],
      "status": "active",
      "resolution_state": "model_reused",
      "reconcile_confidence": "high",
      "reconcile_reason": null,
      "offering_kind": "product",
      "family": "Aura",
      "lifecycle": "active",
      "official_url": "https://www.insighthealth.ai/ambient"
    }
  ],
  "omitted_count": 0,
  "current_selection": { "selection_version": 1, "product_ids": ["prd_…"] },
  "suggested_product_ids": ["prd_…"]
}
```

- `brand_id`, `catalog_document_id` and `catalog_version` identify the subject the digest was
  taken over. `catalog_document_id` is null and `catalog_version` is `1` for a brand whose product
  rows exist without a catalog document yet — the same absence the D10 subject ref names as
  `none`.
- `short_description` is the empty string `""`, never a fabricated sentence, for a product row the
  catalog does not describe.
- `resolution_state`, `reconcile_confidence` and `reconcile_reason` are the catalog lineage flags
  (§6.2), null when the lineage says nothing. A candidate whose `resolution_state` is
  `model_unsure` is the one the card flags as a possible duplicate, with `reconcile_reason` as the
  flag's explanatory text; every other state renders no flag at all.
- `current_selection` is null on a project with no set yet; on a re-selection it pre-checks the
  current members. `suggested_product_ids` is the agent's suggestion and is what the card
  pre-checks **only when there is no `current_selection`** — a saved human selection always wins
  over a suggestion. Both are advisory: neither confines what may be chosen.
- `offering_kind`, `family`, `lifecycle`, `official_url` are optional; a reader treats a missing
  member as absent. Ids are server-minted.

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
  partner_program → service → other; each group has a plain-language heading ("Products",
  "Platforms", "Integrations", "Partner programs", "Services", "Other"). A candidate whose
  `offering_kind` is missing — or is a kind this list does not name — falls into "Other" rather
  than disappearing from the card.
- `family` as a secondary label; `lifecycle` as a small label when not `active`; `official_url`
  as a source chip resolved server-side with no dates (ruling R1).
- Primary action "Use these products", disabled until ≥ 1 is checked. The receipt lists every
  chosen product's retained display name from the immutable snapshot; never a technical id.
- A snapshot with zero candidates renders the existing recovery notice.
- `archived` products are shown unchecked and not selectable.

A candidate flagged `model_unsure` renders a "Possible duplicate" chip carrying
`reconcile_reason` as its title; the human decides whether it is really a distinct offering.

The Zod model gains `offeringKind`, `family`, `lifecycle`, `officialUrl`, `possibleDuplicate` and
`duplicateReason` as members of `ProductSelectionOption`, a `productSet` member on the card model
(options, the pre-checked ids, the current selection version, and the answered ids), and a
set-valued decision variant. The single-product variant stays for historical gate replay.

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

> Note (2026-09-07 amendment): the `fields.py` value-schema row below is no longer needed — the
> artifact, not a claim, is the synchronizer input (§5). Kept in the table for the historical
> replay-only field only.

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

## 10. Standing rule — no old-lane gate may block a new-lane turn (Aryan, 2026-09-07)

Master plan §2 principle 2 is the law here: exactly two gates plus one floor. Human authority
(product-set selection, ICP confirmation, cohort approval, launch, contact selection) and the lenient
claim-write shape gate. Nothing else may refuse a turn. Because the new lane keeps seller-company
knowledge as artifacts, **no mechanism that demands a Client-KB version, a readiness decision, or a
Stage-0 run pin may sit on any new-lane path**: not the gate tool (§6.3), not the scope pin (which
becomes an artifact-ref receipt), not the profile grants (readiness / Client-KB / Product-KB tools
are not granted; the boot-time audit refuses a re-grant), not the launch preconditions. The
per-stage checklist lives in `_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md` and is
run at every charter, review and merge. A failure is a defect against §2, fixed on the path, never
with a bypass flag.
