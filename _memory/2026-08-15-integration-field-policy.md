# 2026-08-15 — Integration: Stage-0 field-policy split

## Scope

Second bounded merge slice on `platform/integration-onboarding-pilot`: reconcile the target's
nine-field ICP readiness policy with Denver's company product catalog and product-scoped fields.
No gate/backend-resource/migration conflict outside this policy was resolved.

## Ratified policy

- `CLIENT_ICP_SYNTHESIS_FIELDS`: the stable nine-field ICP-readiness denominator. Workspace
  required-field policy may extend it explicitly.
- `CLIENT_ONBOARDING_FIELDS`: the founder-ratified original eleven-field onboarding checklist and
  fast legacy release walk (nine plus competitor/buyer enrichment).
- `CLIENT_COMPANY_KNOWLEDGE_FIELDS`: the broader 12-field account-wide set (the eleven onboarding
  fields plus `client.product_catalog`). `CLIENT_BASELINE_FIELDS` remains its compatibility name.
- `PRODUCT_KNOWLEDGE_FIELDS`: a disjoint nine-field detailed product set. Every claim requires one
  exact `product_id`; all company fields, including the catalog, forbid `product_id`.
- `client.product_catalog` is bounded company portfolio navigation. It is neither an ICP
  denominator member nor an onboarding checklist/release prerequisite.

## Implementation

- Resolved `subsystems/research/clue_research/stage0/fields.py` by retaining both branches' field
  contracts and naming the three distinct company policies explicitly.
- `reverse_profile` now accepts a validated ordered company-field subset. The fast `start_recon`
  composition passes `CLIENT_ONBOARDING_FIELDS`; background/default company work retains all 12.
- `/stage0/setup/current` filters and orders field events by `CLIENT_ONBOARDING_FIELDS`, so catalog
  or future company navigation does not silently become a checklist row.
- ICP readiness callers explicitly pass the nine-field set. Discovery/deep callers explicitly pass
  the broader company set. The shared metric math remains one implementation.
- Frontend fixtures/constants now use onboarding terminology and prove the catalog is absent from
  the four-group checklist.
- Canonical onboarding and product-context docs record the 9/11/12/product-scoped split and clarify
  that opportunistic fast-corpus catalog extraction is not a release predicate.

## Verification

- Scoped Ruff check passes across all changed Python files.
- Provider-free backend field-policy suite: `tests/stage0/test_stage0_static.py` — 14 passed.
- Focused frontend onboarding tests — 44 passed; scoped ESLint passed.
- Worktree diff check and merge-marker scan pass for the slice files before staging.
- API/product-contract test collection is currently blocked by the unrelated unresolved marker in
  `platform/api/clue_api/agent_execution_wiring.py:1835`. Database acceptance is deferred until
  the migration/schema and API conflicts are resolved; no shared database was touched.

## Failed attempts

- The first `uv run ruff format` used a fresh sandbox cache and could not resolve
  `opentelemetry-proto`; the approved network-enabled rerun completed and formatted the scoped
  files.
- The first frontend test command could not create tsx's sandboxed IPC socket and ESLint was run
  from the wrong directory. The approved IPC rerun passed, and ESLint passed from `apps/frontend`.

## Next boundary

Proceed to the unified gate schema/migration/backend-authority slice. In particular, reconcile the
two `agent_gate_kind` CHECK rewrites explicitly rather than creating an empty Alembic head merge.
