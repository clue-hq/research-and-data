# 2026-08-08 — Lane B B1 internal identity substrate complete

## Scope

Implemented B1 from `docs/specs/FI-lane-B-authenticated-principal-contract.md`. No Clerk SDK,
external credential, FastAPI auth dependency, frontend session work, Lane-D thread/action-ref code,
FI-2 account surface, provider call, or production database was touched.

## What landed

- New hash Alembic revision `9398ae4467e3` chained from branch-time head `870fe4f2af87`.
  It creates `platform_user`, `auth_identity`, `workspace_membership`, and
  `workspace_invitation` with named lifecycle/role checks, internal-only FKs, composite inviter
  locality, token-digest-only invitation storage, and the indexes required for identity and
  membership resolution.
- New `clue-auth` package at `platform/auth/clue_auth` with opaque `usr_`/`aid_`/`wsm_`/`wsi_`
  ids; frozen row models; provider-neutral CRUD; user/identity/membership/invitation lifecycle;
  immutable version-1 internal permission policy; invitation and self-serve-owner provisioning;
  provider-swap continuity; and an identity DSAR path that tombstones provider/profile values while
  preserving internal audit ids.
- The role floor is least-privilege: viewers read; operators can write/gate/estimate/launch; only
  admins/owners can approve spend or manage members; an administrator cannot grant a role above
  their own.
- Root tooling now discovers/types/checks `clue_auth`, and import-linter enforces that the auth
  substrate cannot depend on subsystem or capability-plane packages.
- The no-provider-FK static gate scans migration DDL and rejects provider subjects, Clerk/session
  ids, or email values in primary/foreign/reference keys. DB tests cover provider replacement,
  one-user/two-workspace isolation, address-bound single-use invitation acceptance, replay,
  cross-workspace inviter rejection, revocation non-resurrection, and DSAR erasure.

## Verification

- Dedicated Honiara Postgres only: `make db-smoke` passed (upgrade head → downgrade base → upgrade
  head); `alembic heads` reports only `9398ae4467e3`.
- `tests/auth`: 10 passed.
- Root mypy: 583 source files, no issues.
- Import-linter: 25 contracts kept, 0 broken.
- `ruff check .`: passed.
- Root `make check` still stops at the pre-existing formatting baseline (21 unrelated files).
- Full root pytest on the isolated DB: 3,846 passed, 25 skipped, 30 failed. The failures match the
  existing branch baseline classes: stale C6 v9 test after the v10 profile re-pin, clue-design
  logging guard scope, and shared-session DB pollution/migration-order fallout. No `tests/auth`
  node failed. The standalone migration smoke and auth DB suite pass from a fresh isolated schema.

## Handoff / ordering

B1 is ready to merge into `platform/frontend-integration` and then be cherry-picked into Lane D's
Damascus branch so D0 can create real `thread.created_by` and membership FKs. Do not hand-renumber
this revision if FI-2 minted another parallel migration; integrate with `alembic merge` to restore
one head. B2 is next: provider-neutral `Authenticator`/`IdentityResolver`/`Authorizer`, the initial
Clerk adapter, FastAPI dependency, and production refusal of local-header authority.
