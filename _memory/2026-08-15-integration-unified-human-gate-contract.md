# 2026-08-15 — Integration: unified human-gate contract freeze

## Scope

Docs-only first slice of the in-progress merge of `platform/onboarding-integration` into
`platform/integration-onboarding-pilot`. This slice freezes the combined authority contract before
resolving the schema, backend, profile/skill/recipe, frontend, migration, or test conflicts.

## Ratified decisions

- One durable `agent_gate`/answer substrate supports the current interactive kinds
  `directive_confirmation`, `icp_confirmation`, and `product_selection`.
- Every gate retains exact scope, subject ref/revision/snapshot/digest, permitted decisions,
  addressee, and erasure bindings. Stale, erased, foreign, malformed, unsupported, already-answered,
  or wrong-addressee gates are non-interactive.
- `max_spend_cents` and `currency` are paired nullable values. Non-spend gates store null; a
  withheld amount is never projected or submitted as zero.
- Every answer retains the reviewed digest, empty-or-bounded `decision_payload`, and nullable
  `selected_option_ref` alongside server-derived actor/action/scope.
- `decision_payload.revision_request` is used only by `icp_confirmation + revised`.
  `selected_option_ref` is used only by `product_selection + approved`, after the server validates
  the browser's `selected_product_id` against the immutable candidate snapshot.
- Revision text and product selection are mutually exclusive. Product reject/revise and ICP
  approve/reject carry neither auxiliary value.
- The frontend decision model is a discriminated union for ordinary decisions, ICP revision, and
  product approval. It does not overload a generic string for two meanings.
- Product-selection history renders the retained product name, never raw transport JSON or a
  technical ID. Historical absent optional fields remain absent on replay.

## Source-of-truth updates

- `apps/frontend/docs/api-contracts/projects.md` owns the canonical wire, answer-invariant table,
  frontend union, fail-closed presentation, and receipt rules. Its six profile-version conflict
  blocks were resolved to the target branch's currently implemented `head-of-abm@v25`; promotion
  to a combined profile belongs to the later resource slice.
- `docs/specs/FI-production-deepagent-context-composition.md` decision D9 owns the shared backend
  authority rule.
- `docs/specs/FI-production-deepagent-context-S50-product-knowledge-contract.md` S5-F now
  specializes product selection under D9 and removes the zero-cost courier behavior from the
  target contract.

## Deferred implementation boundaries

- Do not treat this contract freeze as implementation acceptance. Runtime/UI/resource/migration
  and test conflicts remain unresolved.
- The migration slice must reconcile both divergent `agent_gate_kind` CHECK rewrites explicitly;
  an empty Alembic head merge alone would lose one of `icp_confirmation` or `product_selection`.
- The resource slice must mint and promote combined profile/skill/recipe revisions instead of
  rewriting either branch's immutable historical resources.

## Verification

- `git diff --check` passed for the three contract docs and this note.
- All four files are free of merge-marker lines, and the relative contract-link targets exist.
- Only the three contract docs plus this note are staged by this slice; all runtime/UI/resource/
  migration/test conflicts remain open for later slices.
