# FI — Stage-0 confirmed discovery-run contract

**Status:** RATIFIED 2026-08-16 (founder); checkpoint 1 contract freeze

**Supersedes for the active flow:** the model-authored run-entry input in
[`PC-C0-step4-contract-freeze.md`](./PC-C0-step4-contract-freeze.md) and the corresponding
`start_confirmed_project_run@1` behavior in
[`PC-C4-stage0-recipe0.md`](./PC-C4-stage0-recipe0.md). Historical `@1` resources and receipts
remain immutable and replayable.

## Outcome

Approving a substantively complete ICP is enough to proceed toward discovery. Stage 0 already has
the knowledge required for the run:

- the exact company Client-KB version;
- the human-selected product and its selection receipt;
- the selected product profile;
- the exact Product-KB version;
- the exact approved ICP version.

The platform must not research, synthesize, or ask the user to confirm a second product context.
`product_context_version` is only the immutable replay/audit receipt that binds those existing
inputs before paid discovery execution.

## 1. Product-context receipt

The backend derives an ordered manifest containing exactly these five reference classes:

1. `client_kb`;
2. `selected_product`;
3. `product_profile`;
4. `product_kb`;
5. `approved_icp`.

Each entry carries its native durable subject reference, revision coordinate, and canonical
SHA-256. The receipt also carries workspace, project, client-entity, and product scope plus a
canonical manifest SHA-256. The resulting identity is insert-or-reuse idempotent for the same
exact inputs and changes whenever any referenced revision or digest changes.

The receipt:

- contains references, not copied prose or newly generated claims;
- performs no provider call, research, LLM call, or user interaction;
- cannot silently select a newer "current" KB, product, or ICP after the turn scope is pinned;
- cannot mix workspace, project, client, product, or ICP lineages;
- is derived by trusted backend code; neither the model nor the frontend supplies its id;
- may be returned as a reference for replay and audit after the backend has created or reused it.

## 2. Confirmed-run entry

The active successor is `start_confirmed_project_run@2`. Its model-authored input is the empty
object:

```json
{}
```

The trusted execution/turn scope supplies the project. The backend resolves the approved ICP and
the five receipt inputs, derives or reuses the receipt, evaluates the internal discovery boundary,
creates or reuses the confirmed project run, and attaches the discovery recipe.

The model and frontend must never author:

- workspace, project, client, product, Client-KB, Product-KB, product-context, ICP, or readiness
  identifiers or versions;
- context claim/artifact/memory lists;
- `budget_cap_cents` or an estimated-cost echo.

The historical `start_confirmed_project_run@1` schema remains unchanged for exact replay but must
not remain in the active profile/skill/recipe after `@2` is implemented and promoted.

## 3. Budget-controls-off behavior

`Settings.budget_controls_enabled` remains the deployment switch. For the pilot it is `false`.
The discovery boundary is still evaluated and recorded internally so execution has an auditable
decision reference, but the exact off-mode result is:

```text
enforcement_mode = record_only
execution_allowed = true
human_gate_required = false
```

Therefore no `discovery_spend` card, amount, approval, override, or blocking state is presented to
the user. The decision is internal authority/audit state, not a human decision. Spend recording,
provider-console limits, tenancy, exact lineage, idempotency, and non-economic safety gates remain
enforced.

This amendment is specific to the Stage-0-to-discovery transition. It does not silently change the
separate deep-account directive/selection contracts.

## 4. Discovery configuration is a separate contract

Provider-neutral discovery configuration may contain the approved ICP reference, entity type,
requested account count, search intent, must-have criteria, and exclusions. It contains no
product-context receipt id, readiness id, cost field, or budget authority.

When those values follow deterministically from the approved ICP plus versioned policy, the run
may proceed without another user interruption. If a material value is genuinely absent or
ambiguous, the Deep Agent may explain a bounded proposal (for example, start with 10 accounts) and
use the existing directive-confirmation substrate so the user can revise it. That interaction
confirms discovery scope only; it never generates product knowledge or grants budget authority.

The provider adapter compiles only a validated provider-neutral configuration into Exa-specific
request fields. Exa-specific requirements do not leak into the receipt or run-entry tool.

## 5. Checkpoint-1 executable freeze

`clue_api.stage0_project_contracts` freezes, without registering runtime behavior:

- `ProductContextReceiptContract` and its exact five inputs;
- canonical receipt digest validation;
- the budget-controls-off non-interactive invariant;
- the separate provider-neutral discovery configuration;
- empty `StartConfirmedProjectRunV2Input` and reference-only output.

Later checkpoints implement receipt persistence/derivation, the internal readiness transition,
the versioned tool/profile/skill/recipe promotion, discovery compilation, and browser acceptance.
