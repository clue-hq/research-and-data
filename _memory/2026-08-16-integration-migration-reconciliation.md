# Integration migration reconciliation — unified human-gate enforcement

Date: 2026-08-16
Branch/worktree: `platform/integration-onboarding-pilot` in `singapore`

## Scope completed

- Reconciled the two Alembic heads without rewriting either branch's immutable migration history:
  - pilot head `0974f1d29e79`;
  - onboarding/product head `2500c418396f`.
- Generated the normal random-hash merge revision `fea2a60cffc0` with both heads as parents.
- Generated child revision `f85ca69b93ba`, now the single Alembic head, to install the explicit
  union rather than relying on branch-application order.

## Combined database contract

- `agent_gate_kind` admits `directive_confirmation`, `icp_confirmation`, `product_selection`,
  and the substrate's retained `plan_approval` / `budget_approval` kinds.
- The existing nullable amount/currency pair and durable `permitted_decisions` constraints remain.
- One `agent_gate_answer_validate()` function now enforces:
  - snapshot availability / erasure;
  - offered-decision membership;
  - exact reviewed digest;
  - exact addressee;
  - answering-turn project, thread, and submitter authority;
  - trimmed 1–4,000-character ICP `revision_request` shape;
  - empty ICP approve/reject payloads and no ICP selection;
  - required product choice for approval;
  - exact membership of that choice in the immutable snapshot candidate array;
  - no product payload, no selected option on product rejection/revision, and no answer carrying
    both a revision payload and a selection.
- The row-local `agent_gate_answer_selection_valid` check also forbids non-approved, blank, or
  payload-bearing selections. The existing snapshot-erasure trigger remains defense in depth.
- Downgrade restores the effective product-branch merge-parent constraint/function shape and
  refuses if durable ICP gates already exist, because those receipts cannot honestly fit that
  historical parent vocabulary.

## Tests and evidence

- Added `tests/db/test_unified_agent_gate_migration.py` for the exact graph, single head, installed
  constraint union, trigger set, and validator invariants.
- Extended `tests/api/test_product_selection_s5f_db.py` with direct-SQL adversarial cases for
  missing/foreign choices, selection+payload smuggling, stale digest, wrong addressee, wrong turn,
  and erased snapshots. This suite remains blocked from execution until the surrounding runtime
  merge conflicts are resolved in a later slice.
- `ruff check` passed for both migrations and both touched tests; `git diff --check` passed for the
  migration slice.
- Default no-DB focused run: `1 passed, 1 skipped`.
- Fresh isolated database `clue_gate_merge_20260816_c1`:
  - clean base → `f85ca69b93ba` upgrade passed;
  - targeted `f85ca69b93ba` → `fea2a60cffc0` → `f85ca69b93ba` passed;
  - full head → base → head passed;
  - focused installed-schema suite passed `2 passed` at the final head;
  - a transaction-rolled-back direct-SQL probe refused missing/foreign product choices, mixed
    payload+selection, cross-thread authority, and untrimmed ICP revision text, then accepted one
    valid product answer and one valid ICP revision answer.
- The disposable database had zero active connections, was dropped, and its absence was verified.
  The pilot/target database was not migrated or modified.

## Integration state

- The new migration/test files can be staged, but a checkpoint commit remains impossible while the
  broader branch merge still contains unresolved runtime/frontend conflicts. Resolve those in the
  later contract/runtime slices, run the extended API gate suites, then commit the coherent merge.
