# 2026-08-05 — M8C P1 authority remediation

## Scope completed

- C7 now validates exact workspace, project, product, project-run, and account scope before reading
  account-run committee references. Wrong-scope empty/cancelled-selection requests expose no contact
  identifiers.
- C4 Exa contact operations and C5 channel operations now carry exact selection lineage and share
  append-only stop authority for selection cancellation, objection, and erasure.
- Pre-dispatch stops cancel without provider traffic. Post-dispatch stops retain only settlement
  receipts, charge once, and cannot persist, materialize, validate, reuse, or serve contact data.
- Contact-research selections now require database-backed approval. Initial selections derive from
  the durable directive-confirmation receipt; successors require the human-only
  `approve_contact_research_selection@1` tool and form one linear current head.
- One confirmed project directive can approve initial selections for multiple accounts; approval
  operation uniqueness is account-scoped.
- Production composition binds the real Exa Websets channel transport, workspace use gate,
  pre-spend gate, storage, and an explicitly injected independent validator. Enabling C5 without
  that validator fails startup. C7 is exposed as a provider-free, reference-only tool for content
  drafting and review agents.
- Compliance depends only on a privacy-stop protocol; the API root binds it to durable operation
  control, preserving subsystem dependency rules.

## Migrations

- `91c664b17911_unify_contact_research_operation_stops.py`
- `d338ba5a8f7e_database_backed_contact_selection_.py`
- Single head: `d338ba5a8f7e`.
- Owned isolated database completed full downgrade-to-base / upgrade-to-head, plus a final
  `d338ba5a8f7e -> 91c664b17911 -> d338ba5a8f7e` correction cycle.

## Verification

- Complete contact-research, DSAR, tool-authority, agent-catalog, and composition suite: green.
- Focused C4-C7/DSAR/production-composition suite: green.
- Strict mypy: 540 source files, green.
- Ruff lint: libs/subsystems/platform/tests/alembic, green.
- Ruff format: 1,105 files green with the two pre-existing known exclusions.
- Import contracts: 24 kept, 0 broken.
- Broad account/deep/provider regression run reached 100% with two failures in
  `tests/durable/test_account_run_db.py`; both are pre-existing order-dependent field-registry
  contamination (`account.strategic_moves` production definition versus incompatible test-local
  definition). Both tests pass on the same database after a clean schema rebuild.

## Remaining deployment boundary

- No concrete independently accepted channel validator ships in this branch. C5 is wired but
  deliberately fail-closed until deployment injects that validator. No paid provider call was
  made during this remediation session.
