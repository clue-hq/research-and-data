# 2026-07-23 — [B3×research] account/contact workspace-localization (DONE)

Completes the research-lane half of the founder ruling 2026-07-22 (accounts are workspace-local —
no global account identity, no cross-tenant enrichment reuse; grounds: provider licensing + GDPR
controller separation). The memory lane (migration `50b778e4009a`) had added the nullable
`workspace_id`/`brand_id` + `(id, workspace_id)` anchor to `account_entity` but stamped nothing; this
work makes those columns real end to end. Branch `research/b3-account-workspace-localization` off
`platform/b4-toolbelt-v0` (base `e2b2a25`). Executed subagent-driven (Opus implementers, Fable
orchestration + per-slice review), 7 commits.

## What landed, per slice
- **Slice 1 (`5105d16`) — schema + writers.** Migration `7f1868a127aa` (head, off `7f2a9c4b1d8e`):
  `contact_entity.workspace_id` + composite FK `(account_entity_id, workspace_id) → account_entity
  (id, workspace_id)` (a contact's workspace can't disagree with its parent) + `(id, workspace_id)`
  anchor; within-workspace **merge FKs** on both entity tables (MATCH SIMPLE — NULL workspace ⇒
  unenforced ⇒ legacy-safe); strong-key uniqueness (`primary_domain`, DUNS/NPI/CIK/LEI registry ids,
  `linkedin_url`, `verified_email`) re-scoped to `(workspace_id, key)` with **legacy partial indexes**
  keeping global uniqueness for NULL-workspace rows; `account_entity`/`contact_entity` workspace
  lookup indexes. Core **contract-delta**: `AccountEntity.workspace_id`/`brand_id`,
  `ContactEntity.workspace_id` (defaulted None). `insert_account_entity(..., workspace_id=..., brand_id=...)`
  (transitional-optional here); `insert_contact_entity` stamps workspace from the parent atomically in
  the INSERT subquery. `mark_merged` grows an app-level `CrossWorkspaceMergeError` fence (also covers
  the NULL/legacy asymmetry the FK can't).
- **Slice 2 (`9413ad3`) — scoped resolution.** All six candidate arms in `identity/resolve.py`
  (deterministic domain, deterministic registry-id, contact strong-key, ANN join, alias-block,
  trigram) filter by workspace; `workspace_id` transitional-optional on `resolve`/`resolve_many`.
- **Slice 3 (`0206f37`) — threading + flip-to-required.** `workspace_id` threaded through every
  creation/resolution chain: discovery (`admit`←`phases.DiscoveryPhaseHandler` via `ctx.workspace_id`),
  import, seeds, client-KB (`_resolve_client`), review (`disposition`; `resolve_create_new_entity`
  reads `task.workspace_id`, new `ReviewTaskUnscopedError` if NULL), committee (`admit_candidate`
  derives from `account.workspace_id`, fails loud on NULL). Then flipped `insert_account_entity`/
  `resolve`/`resolve_many`/`disposition`/`admit`/`resolve_alias` to **required** `workspace_id` and
  deleted the transitional arms. **Plan-gap caught in review:** `resolve_alias` (client-KB front edge)
  was unscoped → cross-tenant exact-name lookup leak; scoped all four branches + threaded. Also found
  two extra callers by grep: `resolve_crm_seeds`, `capture_downstream`.
- **Slice 4 (`9c999c0` + fix `812c918`) — toolbelt guard.** Replaced the `_warn_unscoped_account`
  placeholder (retired the `toolbelt.unscoped_account_access` warn-and-proceed) with a fail-closed
  `_CapabilityTool._load_account` (analogue of `_load_run`) in the **preconditions** of
  `run_deep_account`/`resolve_committee`/`profile_contact` — a cross-workspace or legacy
  NULL-workspace account collapses to `account_not_found` (no existence leak), refusal logged
  `toolbelt.account_scope_refused`. **Review fix:** `profile_contact` still checked the contact by
  bare existence → a caller could profile a foreign-workspace contact by pairing it with any
  in-workspace account; now the contact must satisfy `contact.account_entity_id == account.id`.
- **Slice 5 (`4dd9026`) — reuse retirement + docs.** Deleted the dead `reusable_public_value`
  amortization hook (zero production callers — the M4 waterfall's reuse was always same-run
  workspace-scoped idempotency, never cross-tenant) + its export + its tests. Kept
  `classify_reuse_scope`/`stamp_reuse`/`dsar_private_claims`/`check_claim_writable` as the privacy
  classification. `content_key(source_key, ref, workspace_id)` — artifact cache keyed by workspace
  (None = public/unscoped partition), threaded `run_pipeline → run_chain → _fetch_and_adapt`. Dated
  supersession blockquotes in 5 docs (research-layer, harness-arch, M02, M04, M12). CLAUDE.md
  `[B3×research]` → DONE; `[B4]` residual (c) → resolved.

## Verification
`make check` **2246 passed, 20 skipped** with the DB up (the important part — a no-DB run skips ~962
and proves nothing). `alembic heads` = single `7f1868a127aa`. `make db-smoke` up→down→up reversible.
mypy/ruff/import-contracts green. Every production caller of the five flipped seams verified by
enumeration (not just mypy) to thread a real workspace_id; no `workspace_id=None` in prod.

## Residuals (documented at their sites; decide before go-live)
- **(a) Legacy NULL-`workspace_id` rows** stay DB-representable (memory-lane fail-closed semantics
  need it) but are invisible to scoped resolution + refused by the toolbelt. Backfill-or-purge is a
  real go-live decision — not forced here.
- **(b) `brand_id`** is plumbed through `insert_account_entity` but never stamped by research (nothing
  in the run lane — `PhaseContext`/`project_run` — carries a brand; V1 is one-brand-per-workspace).
- Final whole-branch review dispatched (Opus) hunting missed-leak/uniqueness/merge/migration holes;
  fold its confirmed findings before merge.

## Process lesson (also worth remembering)
Slice 3's parallel test-threading subagents shared ONE working tree (no worktree isolation); one
subagent's `git stash`+`reset` swept the in-progress set into `stash@{0}`. Recovered fully. **Fan-out
agents that write files must run in per-agent git worktrees (or go single-threaded)** — see
[[opus-subagents-fable-orchestrates]].
