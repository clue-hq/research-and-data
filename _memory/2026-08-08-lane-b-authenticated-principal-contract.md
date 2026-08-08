# 2026-08-08 — Lane B authenticated-principal contract

## Scope

Documentation-only contract freeze after founder discussion. No runtime, migration, frontend, API,
provider, or database implementation changed.

## Founder rulings

- Lane D approvals use a real authenticated Clue user principal, not a trusted workspace-header
  identity.
- Clerk is the initial authentication/session adapter only.
- Clue Postgres owns canonical users, workspaces, workspace memberships, roles/permissions, and
  durable audit identities.
- No Clerk/provider value may be a primary key, foreign key, tenancy key, domain id, or
  authorization decision key. `auth_identity.provider_subject` is an opaque unique lookup attribute
  only; every relationship uses Clue-owned ids.
- Lane B and Lane D may develop in parallel after the B0 contract, using an injected deterministic
  `RequestPrincipal` in Lane D until production auth joins.

## Contract written

- Added `docs/specs/FI-lane-B-authenticated-principal-contract.md`.
- Frozen internal table shapes for `platform_user`, `auth_identity`, `workspace_membership`, and
  internal invitations/provisioning.
- Frozen provider-neutral `Authenticator` → `IdentityResolver` → `Authorizer` → `RequestPrincipal`
  seams, token/BFF boundary, error semantics, durable actor/service-principal split, file ownership,
  B0–B5 slices, Lane-D join gates, and adversarial acceptance matrix.
- Kept provider organization/role claims outside workspace authority; workspaces remain the existing
  Clue spine rows.

## Companion amendments

- Lane D §6-D4 is now ratified and P1/P2/P3/D0/D1 ordering consumes internal user/membership ids
  only.
- The lane-demarcation registry expands Lane B from the former thin actor seam into the authenticated
  principal foundation while retaining L3/L4 and preserving all FI-2 exclusions.
- FI-1 §9 records the founder ruling.

## Verification

- `git diff --check` passed.
- Stale Lane-D D4-open wording was removed; D1/D3/D5/D6 remain pending.
- The unrelated in-progress `account_entity_research.py` changes and `.playwright-mcp/` directory
  were left untouched.
