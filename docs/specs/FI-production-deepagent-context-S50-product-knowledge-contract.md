# S5.0 Product-Knowledge Consumption Contract

**Status:** RATIFIED and contract-frozen 2026-08-15

**Parent:** [Production Deepagent Context Composition](./FI-production-deepagent-context-composition.md)

**Executable fixture:**
`tests/fixtures/production_context/s50_product_knowledge_decision.json`

**Executable constants/state invariants:** `clue_api.product_knowledge_decision`

## 1. Outcome and boundary

S5.0 resolves the product-knowledge decisions that were deliberately left open after S3.1. It is
a contract gate, not a claim-extraction, synchronization, migration, card-runtime, tool-runtime,
or production-cutover slice.

The binding outcome is:

```text
Account-wide context
└── ClientKnowledgeCard@2
    └── bounded product catalog only

Selected-product context, only after human confirmation
├── ProductProfileCard@1
└── ProductKnowledgeCard@1

Active-project context
├── ProjectConversationCard@2
└── Stage0ProjectStateCard@1
```

Selected-product knowledge uses **both** the bounded `ProductKnowledgeCard@1` and the governed
`list_product_knowledge@1` / `inspect_product_claim@1` tools. The company tools remain separate.
The model can filter or follow a reference; it can never author a workspace, client, product, or
knowledge-version coordinate.

S5.0 itself does not claim that these new runtime surfaces exist. Until the S5 production cutover,
current turns continue to use `ClientKnowledgeCard@1`, company-only S4 tools, and
`company-account-wide-v1` scope receipts.

## 2. Why company and product knowledge are separate

The customer account and each product have different truth lifecycles.

Company/account-wide knowledge includes company overview, portfolio-level positioning, target
market, founders, reputation, company competitors, and portfolio/customer context. These claims
use the Client-KB scope where `claim.product_id IS NULL`.

Detailed product knowledge includes capabilities, use cases, differentiators, pricing,
integrations, product competitors, product-specific positioning, and customer evidence. These
claims use the independently versioned Client-KB scope where `claim.product_id` equals one exact
spine `product.product_id`.

The shared claim store remains the substrate. “Product Knowledge Base” does not create a second
fact system: it names the product-scoped version sequence already supported by
`current_kb_version` and `read_client_kb_claims`. Company and product readers differ by a trusted
scope selector, never by model-authored text.

## 3. Ratified decisions

### S50-D1 — Company facts remain account-wide

- The company Client-KB uses `product_id IS NULL`.
- Every project under the canonical workspace client can reuse it.
- Company S4 tools continue to reject product-scoped claim membership.
- `ClientKnowledgeCard@2` is the company opening index; detailed product facts are forbidden from
  its catalog block.

### S50-D2 — Product facts are independently versioned

- Product knowledge uses the same canonical `client_entity_id` plus one trusted `product_id`.
- Each product has its own integer version sequence. Product A v3 and Product B v3 are unrelated
  pins; neither supersedes the other or the company v3.
- Product claims never enter another product's card merely because both products share a client,
  workspace, or brand.
- A selected product may honestly have no published product-KB version. In that state its identity
  profile is available, while the product-knowledge card and product tools are unavailable.

### S50-D3 — Selected-product consumption uses a card and tools

`ProductKnowledgeCard@1` provides a bounded navigation index: topic and field descriptions, short
previews, claim references, open gaps, coverage, and an omission cursor. It does not contain raw
page bodies or an unbounded claim set.

`list_product_knowledge@1` discovers additional exact-version product refs.
`inspect_product_claim@1` resolves one such ref to its bounded value and provenance. Replaying
either tool is zero-write and zero-provider-spend.

The card is not a substitute for exact inspection, and the tools are not a reason to flood opening
context. Both are required.

### S50-D4 — Product authority is platform-derived

The model-visible product-tool fields are:

```text
list_product_knowledge@1: topic, field_key, cursor, limit
inspect_product_claim@1: claim_id
```

The platform injects:

```text
workspace_id
client_entity_id
product_id
product_kb_version
```

Those values must come from the immutable turn constitution/scope receipt. Supplying any of them
in model-authored arguments is impossible in the public schema and rejected at any compatibility
boundary. Unknown, foreign, cross-product, wrong-version, superseded-out-of-version, expired, or
erased claims share a non-oracular refusal.

The existing company tools do not gain a `product_id` parameter. Separate tool addresses make the
authority boundary mechanically visible and prevent a model from turning a company read into a
product read.

### S50-D5 — `ClientKnowledgeCard@2` owns the bounded product catalog

`ClientKnowledgeCard@1` is immutable and remains replayable under its historical media type and
policy. S5 introduces `ClientKnowledgeCard@2`; it does not rewrite V1 bytes.

V2 adds a bounded, typed company product catalog. Each included entry carries at least:

```json
{
  "product_id": "prd_123",
  "name": "Insight Health AI Phone Agents",
  "short_description": "AI agents for healthcare calls and scheduling",
  "aliases": ["Insight Voice"],
  "status": "active",
  "catalog_claim_id": "claim_uuid",
  "product_knowledge_available": true
}
```

The catalog answers “what products does this company offer?” It may describe the portfolio but
must not carry detailed capabilities, pricing, integrations, product competitors, or product
customer evidence. Over-cap catalogs expose an omitted count and opaque cursor.

`product_knowledge_available` is descriptive, not read authority. S5 must derive it as of the
durable turn pin/synchronized snapshot so a retry cannot change it because a product marker was
published after the turn began. Exact product-tool authority still requires the trusted selected
product and exact `product_kb_version`.

## 4. One owner per product-context field

`ClientKnowledgeCard@2` owns catalog navigation across the company portfolio.

`ProductProfileCard@1` owns durable selected-product identity:

- `product_id`;
- brand binding;
- name and aliases;
- lifecycle status.

`ProductKnowledgeCard@1` owns selected-product research state:

- exact `product_kb_version`;
- bounded topics/fields and descriptions;
- brief previews and claim refs;
- gaps, coverage, and omissions;
- compiler/source lineage.

The Product-KB card body does not repeat product-profile identity. Its workspace/product binding
and typed constitution domain ref are engine-side authority. The compiler validates those pins
against the profile and scope receipt before persisting bytes.

The catalog's repeated product ID/name is an intentional navigation join across several products,
not a second selected-product authority. The selected `ProductProfileCard` remains authoritative
for the active turn.

## 5. Context state machine

| State | Company card | Catalog | Product profile | Product-KB card/tools |
|---|---|---|---|---|
| Post-recon, no selection | V2 | available/bounded | absent | absent |
| Product selected, no product KB | same V2 | available/bounded | selected product | absent |
| Product selected with product KB | same V2 | available/bounded | selected product | exact pinned version |
| Different project selects another product | same company V2 | same catalog | other product | only other product's exact version |

Before selection the Head-of-ABM may present catalog entries and ask which product the project is
about. It may not confirm one. `confirm_project_product@1` remains the sole human-authorized,
idempotent project-product write. The product tools are not admitted to the model-visible surface
until a selected product and product-KB version are both trusted.

## 6. Durable version pair and retry semantics

S5 extends new-turn scope policy to `company-and-selected-product-v2`. The logical receipt is:

```text
workspace_id
client_entity_id
company_client_kb_version
confirmed_product_id | null
product_kb_version | null
knowledge_scope_policy_version = company-and-selected-product-v2
pinned_at
```

The existing physical `client_kb_version` column remains the company version for compatibility;
S5 adds the optional product version rather than renaming historical columns or rows.

The worker resolves the company version, confirmed project product, and optional product version
inside one database snapshot before any card, model, or tool execution. A coherent pair does not
mean equal integers. It means both were current in the same trusted snapshot for their independent
scopes.

If recon publishes company vN+1 or product vM+1 after the pin:

- the running/reclaimed turn continues on `(company vN, product vM|null)`;
- card and tool retries reuse that exact pair;
- no old-company/new-product or new-company/old-product recomputation occurs;
- a newly submitted turn may receive the newer independently current pair.

Historical `company-account-wide-v1` receipts remain replayable. The S5 worker must support both
policy meanings and never reinterpret a V1 row as V2.

## 7. Catalog synchronization contract

The source is one registered tenant-private, account-wide field: `client.product_catalog`.
Official-site extraction grounds it in exact snapshots and evidence like every other promoted
claim.

Synchronization runs after the catalog claim is committed and:

1. reads one exact company Client-KB version and catalog claim;
2. conservatively normalizes each entry;
3. creates or reuses a product under the recon brand;
4. records immutable claim/version/catalog-entry-to-product lineage;
5. returns the same product/lineage rows on replay;
6. refuses cross-workspace or cross-brand candidates;
7. never automatically renames, merges, archives, or deletes a product.

Name normalization alone is not merge authority. Exact existing product identity or a governed
alias match may reuse a row; ambiguous matches remain unresolved rather than collapsing products.
The catalog claim owns what recon observed. The product spine owns stable application identity.
Lineage connects them without making either overwrite the other.

## 8. Privacy, injection, and provenance requirements

- Catalog descriptions, aliases, labels, claim values, evidence, sources, URLs, and page text are
  untrusted evidence. They cannot select tools, author scope, confirm products, delegate, or
  override policy.
- Product cards and tool-result artifacts bind the client, selected product, and every exact claim
  body they copy. Catalog lineage is reachable by client/product/claim DSAR.
- Source URLs follow S4-E bounded redaction/digest rules. Tokens, credentials, raw bodies, and
  unrestricted URLs never enter cards, tool outputs, logs, checkpoints, or streams.
- Replay after erasure cannot restore product/card/tool bodies from checkpoints or earlier
  receipts. Body-free version/hash/cost/ref receipts may remain for audit.
- Privacy-safe logs contain only operational IDs, policy/card/tool versions, hashes, counts,
  availability, and refusal/outcome codes.

## 9. S5 implementation checkpoints unlocked by this decision

S5 should be delivered as the following ordered checkpoints:

1. **S5-A — Product field/catalog contracts:** register/freeze `client.product_catalog`, product
   topic taxonomy, `ClientKnowledgeCard@2`, `ProductProfileCard@1`, `ProductKnowledgeCard@1`,
   cursors, caps, refusals, and provider/DB-free fixtures.
2. **S5-B — Grounded catalog extraction and synchronization:** materialize the official-site
   catalog, add reversible claim-to-product lineage, conservative matching, idempotency, and DSAR.
3. **S5-C — Product-scoped readers and card compilers:** exact-version product membership,
   deterministic bounded cards, catalog omission traversal, cross-product refusal.
4. **S5-D — Governed product tools:** implement/register `@1` list/inspect tools with trusted-only
   product scope, privacy bindings, zero-spend replay, profile/recipe/skill pins.
5. **S5-E — Durable pair pin and production composition:** migrate the scope receipt additively,
   compile V2 company + optional product artifacts through the real fleet/assembler, and preserve
   V1 replay.
6. **S5-F — Human selection and refresh acceptance:** present catalog candidates, retain
   `confirm_project_product@1` as the only write, and prove next-turn product context for Projects
   A/B with crash/background-refresh isolation.

No checkpoint may silently combine these surfaces or add product scope to the company tools.

## 10. S5.0 exit evidence

S5.0 passes when:

- all five decisions above are ratified in the parent and this child contract;
- the executable fixture and state validators pass without DB, network, storage, or provider
  access;
- static guards prove future product tool schemas contain no model-authored scope fields;
- existing `ClientKnowledgeCard@1` and S4 `@2` inputs remain unchanged;
- each future runtime/migration responsibility has one explicit S5 checkpoint owner;
- documentation says clearly that S5.0 is contract-complete but runtime behavior is not live.
