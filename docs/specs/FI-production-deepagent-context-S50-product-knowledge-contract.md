# S5.0 Product-Knowledge Consumption Contract

**Status:** RATIFIED; S5-A through S5-F implemented and verified 2026-08-15

**Parent:** [Production Deepagent Context Composition](./FI-production-deepagent-context-composition.md)

**Executable fixture:**
`tests/fixtures/production_context/s50_product_knowledge_decision.json`

**Executable constants/state invariants:** `clue_api.product_knowledge_decision`

> **Founder supersession — 2026-08-19:** `selected_without_product_knowledge` remains in the S5.0
> fixture only as a frozen historical V2 state. It is not valid for a newly selected product or a
> newly created turn pin. `confirm_project_product@1` now atomically creates an idempotent empty
> Product-KB v1 when no product-scoped marker exists; that marker carries 0/N coverage, no claims,
> and every registered product field as an open gap. New turns use
> `company-and-selected-product-required-v3`, whose database and runtime invariant is
> `confirmed_product_id != null => product_kb_version != null`. A new-turn repair creates the same
> honest baseline for legacy selected projects before inserting their immutable V3 pin. Historical
> V1/V2 pins remain unchanged and readable.

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

S5.0 was the no-runtime decision gate. S5-A through S5-F now implement the cutover for newly
submitted production turns: Head-of-ABM profile `v27`, Stage-0 skill `v14`, and Recipe #0 `v9`
compose `ClientKnowledgeCard@2`, the optional selected-product cards/tools, and
`company-and-selected-product-v2` receipts. Historical V1 cards, policies, profiles, skills, and
recipes remain immutable and replayable.

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

Field-policy placement is explicit. `client.product_catalog` belongs to the broader, account-wide
`CLIENT_COMPANY_KNOWLEDGE_FIELDS`; it is not one of the nine
`CLIENT_ICP_SYNTHESIS_FIELDS` or eleven `CLIENT_ONBOARDING_FIELDS`. Its absence therefore cannot
block ICP readiness or the legacy fast onboarding release, and it is not rendered as a fifth
technical checklist concept. Detailed `PRODUCT_KNOWLEDGE_FIELDS` remain disjoint and every claim
requires the exact selected `product_id`.

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

S5 was delivered through the following ordered checkpoints:

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

### S5-A — complete: product field, card, and tool contracts

- Registered tenant-private `client.product_catalog` plus the product-scoped overview,
  capability, use-case, differentiation, pricing, integration, competitor, customer-evidence, and
  positioning fields.
- Froze V2 company-catalog, product-profile, Product-KB card, cursor, cap, topic, and refusal
  contracts without changing V1 bytes.
- Provider/DB-free fixtures prove duplicate IDs, count drift, authority fields, and cross-card
  ownership fail closed.

**Gate:** `tests/api/test_product_knowledge_contracts_s5a.py` and
`tests/api/test_product_knowledge_decision_s50.py`.

### S5-B — complete: grounded extraction, synchronization, and lineage

- The official-site materializer commits the account-wide product catalog in the fast corpus and
  fans detailed per-product extraction over the same immutable background corpus, without a page
  refetch. The fast corpus may opportunistically contain the catalog, but catalog absence is not
  the onboarding release predicate; the legacy release walk is explicitly constrained to the
  eleven onboarding fields.
- Company fields remain `product_id IS NULL` even if an older/project recon already carries a
  product. Product claims are written only for an exact synchronized spine product.
- Catalog synchronization is append-only and conservative: exact prior lineage or one alias may
  reuse a product; name equality alone never merges. Replays reuse provider responses, product
  rows, lineage, markers, and claims.
- `client.product_competitor` is registered but deliberately not synthesized from an official
  site alone: a company's own comparison page is not an exhaustive competitor source. It remains
  an honest gap until a separately governed source fills it.

**Gate:** `tests/official_site/test_materialization_c7_db.py` proves concurrent grounded writes,
fast/background separation, exact product targeting, same-name ambiguity, alias reuse, prior
lineage reuse, DSAR reach, replay with zero added model/provider work, and account-wide scope under
a pre-existing recon product.

### S5-C — complete: exact readers and deterministic cards

- Added exact-version product membership reads and deterministic compilers for
  `ClientKnowledgeCard@2`, `ProductProfileCard@1`, and `ProductKnowledgeCard@1`.
- Catalog and Product-KB omissions carry scope-bound cursors. Cross-product, cross-workspace,
  wrong-version, and unavailable-product states fail closed; a selected product with no Product-KB
  remains an honest profile-only state.

**Gate:** `tests/api/test_product_context_s5c_db.py`.

### S5-D — complete: governed product reads

- Registered separate `list_product_knowledge@1` and `inspect_product_claim@1` tools. The model
  sees only filters/cursor/claim ID; the execution seam injects client, selected product, and exact
  Product-KB version from the immutable turn constitution.
- Profile `v27`, Recipe #0 `v9`, and skill `v14` pin the tools. They are installed only when the
  exact `product_knowledge` artifact exists; company and product tools cannot cross scopes.
- Exact-value copies bind client, product, and claim subjects; streams expose references only.
  Reads are effect-free and replay with zero writes or provider spend.

**Gate:** `tests/api/test_product_knowledge_tools_s5d.py`,
`tests/api/test_product_knowledge_tools_s5d_db.py`, catalog/profile/recipe audits, and the S4-E
privacy regression.

### S5-E — complete: durable pair pin and real production composition

- Alembic revision `1043a61823f1` additively stores `product_kb_version`, product extraction
  lineage, and the reviewed selection-gate schema while preserving V1 receipt meaning.
- New turns resolve company and optional selected-product markers in one PostgreSQL statement and
  reuse the immutable pair through retry, checkpoint, finalization, and replay.
- The real `AGENT_TURN` fleet composes V2 company, active-project Stage-0, optional product profile,
  and optional Product-KB artifacts through the seven-layer assembler. Product/card/tool copies
  are product-subject-bound for DSAR.

**Gate:** `tests/api/test_production_context_s31_scope_pin_db.py` and
`tests/api/test_production_context_s31_fleet_db.py` prove exact original pins, profile-only state,
real tool execution, LangGraph checkpoint/finalization replay, and product/client DSAR reach.

### S5-F — complete: human selection and next-turn refresh

- The model-callable `open_product_selection_gate@1` has no model-visible arguments. It derives the
  exact pinned catalog, project, addressee, digest, and candidates and writes only an idempotent,
  non-spend question whose amount/currency are null. A human-visible surface must never substitute
  zero for that absent amount.
- The production chat route validates the human's structured choice against that immutable
  snapshot and invokes existing human-only `confirm_project_product@1` in the same transaction.
  The browser's `selected_product_id` is persisted as the answer's dedicated
  `selected_option_ref` only after candidate validation. `decision_payload` remains reserved for
  bounded auxiliary input such as an ICP revision request. A request or receipt cannot contain
  both fields; product rejection/revision cannot smuggle either one. The route and database enforce
  the same invariant.
- The frontend parses the additive gate shape, renders the durable catalog options, submits the
  exact product ID through a product-selection branch of a discriminated decision union, and
  retains the selected name in history. It never overloads a generic revision string or renders
  raw answer JSON/technical IDs as the receipt. The trial surface cannot open a gate it cannot
  compose, while the shared Stage-0 procedure remains readable.
- This specialization is governed by the shared exact-subject contract in parent decision D9 and
  the canonical frontend invariant table in `apps/frontend/docs/api-contracts/projects.md`.

**Gate:** `tests/api/test_product_selection_s5f.py` and
`tests/api/test_product_selection_s5f_db.py` prove Projects A/B select different products, next
turn exact pair/profile-only behavior, stale/foreign choice refusal, human-only authority,
immutable no-repoint behavior, cross-brand refusal, request replay, and original-turn pin
stability. The complete frontend test/lint/design-system/build gate also passes.

## 10. S5.0 exit evidence

S5.0 passes when:

- all five decisions above are ratified in the parent and this child contract;
- the executable fixture and state validators pass without DB, network, storage, or provider
  access;
- static guards prove future product tool schemas contain no model-authored scope fields;
- existing `ClientKnowledgeCard@1` and S4 `@2` inputs remain unchanged;
- each future runtime/migration responsibility has one explicit S5 checkpoint owner;
- documentation says clearly that S5.0 is contract-complete but runtime behavior is not live.

That final statement is the historical S5.0 exit condition. It was superseded only after every
S5-A–F gate above passed; it remains useful to explain why no runtime work was admitted during the
decision checkpoint itself.
