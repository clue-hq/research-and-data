# FI — Stage-0 confirmed discovery-run contract

**Status:** RATIFIED 2026-08-16 (founder); confirmed-run and provider-neutral discovery boundary implemented

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
- remains internal to the durable project-run/replay/audit lineage and is not returned to the
  model or frontend.

## 2. Confirmed-run entry

`start_confirmed_project_run@2` implemented the backend-owned context receipt and remains an
immutable replayable contract. The active provider-neutral successor is
`start_confirmed_project_run@3`; its model-authored input is still the empty object:

```json
{}
```

The trusted execution/turn scope supplies the project. The implementation directly resolves
the approved ICP and five existing receipt inputs, calls the existing content-addressed
`compile_product_context`, evaluates the internal discovery boundary, creates or reuses the
confirmed project run, and attaches the discovery recipe. This explicit confirmed-Stage-0 handoff
is not subject to the older opportunistic Recipe #1 canary: successful run entry must not leave a
durable project run without an execution owner. There is no additional receipt service,
context-compilation wrapper, agent call, or knowledge-generation phase.

The model and frontend must never author:

- workspace, project, client, product, Client-KB, Product-KB, product-context, ICP, or readiness
  identifiers or versions;
- context claim/artifact/memory lists;
- `budget_cap_cents` or an estimated-cost echo.

The historical `@1` and `@2` schemas and behavior remain unchanged for exact replay. Only `@3`
appears in the active profile, skill and Recipe #0 after the discovery-configuration boundary is
promoted.

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

The active `stage0-discovery-planning-policy@1` defaults to 10 accounts and admits at most 50.
When the values follow deterministically from the approved ICP plus that policy, the run proceeds
without another user interruption. If search intent or must-have criteria is genuinely absent,
`start_confirmed_project_run@3` returns the exact missing fields. The Deep Agent explains a
bounded proposal and calls `open_discovery_configuration_gate@1`. The gate reuses kind
`directive_confirmation` but carries `subject_kind=discovery_configuration`, no spend amount and
no product-context authority. The user may approve, reject, or request a revision such as changing
10 accounts to 50.

The final configuration is stored once in append-only
`project_run_discovery_configuration`, keyed by the project run and bound to its workspace,
project, approved ICP, planning-policy version, canonical configuration digest, and optional
approved-gate receipt. The run identity includes the configuration digest, so retries reuse the
same run while a different confirmed scope cannot collide with it.

The Exa adapter reads only this validated run receipt for current runs, compacts all must-have and
exclusion rules into Exa's bounded criterion slots, and enforces the 50-account policy ceiling.
Historical runs without a receipt retain only their already-explicit legacy Exa strategy path.
Exa-specific requirements do not leak into the ICP, product-context receipt, or run-entry tool.

## 5. Executable contract

`clue_api.stage0_project_contracts` freezes:

- `ProductContextReceiptContract` and its exact five inputs;
- canonical receipt digest validation;
- the budget-controls-off non-interactive invariant;
- the separate provider-neutral discovery configuration;
- empty `StartConfirmedProjectRunV2Input` and a minimal output containing only the project-run id
  and `discovery` phase.

Slice 4 adds the schema-identical empty `StartConfirmedProjectRunV3Input`, the versioned planning
policy, the scope-only gate tool, the append-only run receipt, and the Exa compiler boundary.

`start_confirmed_project_run@2` performs the receipt reuse, internal readiness transition and
idempotent run start. A replay after Recipe #1 has advanced the run validates the same immutable
lineage and does not rewind or fail merely because the current phase is later than `discovery`.
Browser acceptance remains a separate follow-on checkpoint.
