# 2026-07-17 — Phase A3.1: the workspace_id rename (tenant_id + client_id → workspace_id)

Branch `platform/workspace-restructure`. Executed the founder-ruled rename per
`docs/specs/PA-phase-a-restructure-and-spine.md` §A3.1: both `tenant_id` and `client_id` (the same
concept — the tenancy root) became `workspace_id`, in one migration + a full code rename.
NOT committed (per task instruction); working tree also carries unrelated pre-existing
config/settings work.

## Migration
`alembic/versions/b61cd4887129_workspace_id_rename.py` (revision `b61cd4887129`, down_revision
`15b6b816abe4`, single head). Hand-written, fully reversible (up→down→up verified):
- 19 `RENAME COLUMN` (4 × tenant_id: claim, identity_review_task, dsar_tombstone,
  outreach_objected; 15 × client_id: icp_spec, source_profile_override, pre_spend_policy,
  judge_policy, binding_policy, cadence_policy, positioning_policy, client_policy, campaign_run,
  source_yield, account_handoff, handoff_event, disposition, config_revision, review_session).
- **Table `client_policy` renamed to `workspace_policy`** (+ its pkey, 5 named CHECKs, and the
  `client_policy_scope_version` NULLS-NOT-DISTINCT slot index → `workspace_policy_*`).
- Index renames (names carrying old vocab only): icp_spec_client→icp_spec_workspace,
  campaign_run_client→campaign_run_workspace, handoff_event_client→handoff_event_workspace,
  account_handoff_client_run→account_handoff_workspace_run,
  identity_review_task_tenant→identity_review_task_workspace,
  outreach_objected_tenant→outreach_objected_workspace; constraint
  outreach_objected_contact_tenant_unique→outreach_objected_contact_workspace_unique.
  Kept-name indexes (claim_scoped_read, *_scope_version slots, partial WHEREs) follow the column
  rename automatically — verified in pg_indexes.
- CHECK `claim_reuse_scope_tenant` dropped + recreated as `claim_reuse_scope_workspace` over
  workspace_id (enum VALUE `tenant_private` retained — pooling semantics, not the id).
- **Three plpgsql guards recreated** (bodies reference columns by name at run time):
  `claim_reject_immutable_update` (workspace_id kept in the immutable list),
  `icp_spec_reject_immutable_update`, `disposition_reject_value_update`.
- **`labeled_dataset` VIEW dropped + recreated**: Postgres rewrites a view's internal column
  references on RENAME COLUMN, but the *output* aliases stay (`… AS client_id`) — so recreation
  was required. The old `c.tenant_id = d.client_id` join collapsed to workspace_id on both sides.

## Code rename
Mechanical token rename (src/, libs/, scripts/, tests/; alembic/versions untouched) plus
coherence renames: `TenantScope`→`WorkspaceScope` (`for_tenant`→`for_workspace`,
`all_tenants`→`all_workspaces`, `private_for_tenant`→`private_for_workspace`,
`ALL_TENANTS`→`ALL_WORKSPACES`; `_ScopeMode.WORKSPACE`/`PRIVATE_FOR_WORKSPACE`),
`tenant_scope`→`workspace_scope`, `scope_tenant` bind param→`scope_workspace`,
`TenantResolver`/`TenantDep`/`header_tenant_resolver`→Workspace*, HTTP header
`X-Client-Id`→`X-Workspace-Id`, `ATTR_CLIENT_ID`→`ATTR_WORKSPACE_ID` (= "workspace_id"),
`ClientPolicy`/`load_client_policy`/`DEFAULT_CLIENT_POLICY`→Workspace*, `stamp_reuse(...,
workspace_id=...)`, clue-config `Config.workspace_id`/`get_config(workspace_id)`, CLI flags
`--client-id`→`--workspace-id` (scripts + scripts/README.md).

**Collision collapsed:** `profiling/context.py` held the real client_id/tenant_id duality
(`PARAM_CLIENT_ID` + `PARAM_TENANT_ID`, RunContext with both fields, `params_for_run` with both
kwargs and tenant-defaults-to-client logic) — collapsed to a single `workspace_id` /
`PARAM_WORKSPACE_ID`; callers in profiling/account.py, profiling/resonance.py and tests updated.
That was the only true collision; no duplicate dict keys / kwargs elsewhere (AST-verified).

**Retained:** `ReuseScope.TENANT_PRIVATE` + 'tenant_private' string + helpers
(tenant_private_prefixes/fields/methods), `claimstore/tenancy.py` filename, tenant/tenancy prose,
`client_knowledge_ids` (+ its `claim_support_client_ids_is_array` CHECK — client-KB concept, not
the tenancy id), historical migrations byte-identical, `client_entity_id` (Stage-0 client entity).

**Gotcha fixed:** `tests/compliance/test_posture.py` reads the *historical* migration file
`196d37e4a179_m10_4_posture_client_policy_columns.py` by name — the sed renamed the string; the
filename must keep the old name (history never rewritten). Restored with a comment.

## Guard
`tests/test_workspace_rename_guard.py` — greps src/, libs/, scripts/, tests/ (guard file itself
excepted) for the tokens `tenant_id`/`client_id` (lookaround pattern also catches `_client_id` /
`:client_id`; ignores `client_ids`/`client_identity`). **Allowlist is empty.** Plus a
scan-scope-sanity test (>200 files, all four roots present).

## Verification (all green)
1. `uv run ruff check --fix . && uv run ruff format .` — All checks passed / 556 files unchanged.
2. `make check` — exit 0 (lint+mypy 273 files+contracts+tests: 1147 passed, 782 skipped).
3. Fresh schema → full `pytest` with `CLUE_DATABASE_URL` — exit 0 (~1915 passed, ~14 skipped).
4. Fresh schema → `make db-smoke` (up→down→up) — exit 0; `alembic heads` = `b61cd4887129` only.

Note: re-running the DB suite on a **dirty** (already-populated) DB fails 3 pre-existing
state-dependent tests (planner index-choice with stats, field-registry pollution, LangGraph
checkpoint tables surviving downgrade in test_no_domain_tables_at_m0_head) — unrelated to the
rename; the gate is defined over a fresh schema and passes.
