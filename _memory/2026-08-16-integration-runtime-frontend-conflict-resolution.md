# Runtime and frontend merge conflict resolution

## Outcome

Step 5 of the onboarding/pilot integration is complete. The merged runtime and frontend now use
one authoritative human-gate contract for directive confirmation, ICP confirmation, and product
selection. No conflict was resolved with a blanket `ours` or `theirs` choice.

## Resolutions

- Preserved the Next build roots and removed the obsolete API rewrite.
- Unified gate storage, projections, schemas, response routing, and tool registration around the
  exact subject digest, addressee, permitted decisions, nullable cost, bounded ICP revision
  payload, and dedicated selected-product reference.
- Kept strict JSON output validation in the tool runner and added company/product subject
  bindings without weakening durable turn-scope pins.
- Corrected Stage-0 lineage resolution: `client_kb_version` remains the account-wide company KB
  version while the selected `product_id` remains a separate trusted project/ICP pin. ICP
  readiness still uses the ratified nine-field denominator.
- Promoted the combined Head-of-ABM v29, Stage-0 skill v16, and Recipe #0 v10 resources.
- Implemented the frontend decision discriminated union for ordinary decisions, ICP revision,
  and product approval. Withheld costs remain null, erased/stale/foreign gates fail closed, and a
  product receipt renders its snapshotted product name rather than raw transport data.
- Reconciled the derived backend/frontend tests only after the source contracts and runtime were
  resolved.

## Verification

- Critical unified migration/gate/ICP/product/budget DB suite: 73 passed.
- Client context, product context, agent-turn wiring, and durable scope-pin DB suite: 10 passed.
- Focused backend static/toolbelt/routing suite: passed (DB-dependent cases skipped in the
  non-DB invocation as designed).
- Frontend: 301 passed; ESLint passed; design-system token build passed; Next production build
  passed.
- Focused Ruff check passed.
- The unified Alembic lineage had already passed clean upgrade, downgrade, and re-upgrade against
  the isolated `clue_singapore_merge_20260816` database.

## Follow-up

No conflict remains in this merge slice. The isolated database is intentionally retained until
the merge commit is reviewed; it contains test-only data and is not a shared database.
