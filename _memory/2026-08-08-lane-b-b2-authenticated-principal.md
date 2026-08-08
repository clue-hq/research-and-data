# Lane B B2 — authenticated principal service

Date: 2026-08-08
Branch: `platform/platformlane-b-auth`

## Shipped

- Added the closed provider-neutral flow: `AuthenticationRequest` -> `ExternalSession` ->
  `InternalIdentity` -> `RequestPrincipal`.
- Added a Clerk-only RS256/JWKS adapter with issuer, optional audience, authorized-party, required
  time/session claims, pending-session, algorithm/token-type, signature, unknown-key, bounded-cache,
  and refresh-throttling checks. Provider claims stop at the adapter.
- Added Postgres identity resolution and active workspace-membership/permission authorization over
  B1's internal ids.
- Added explicit local-fixture authentication that still requires a real `auth_identity` row and
  is rejected when `auth_environment=production`.
- Added `/auth/v1/session` and `/auth/v1/principal` wiring behind default-off `auth_enabled`; API
  responses expose only Clue user/membership/workspace/role/permission values.
- Added one registration call to the projections composition root. `frontend_read/**`, CORS,
  accounts/projects feature code, and Lane D action references were not touched.

## Verification

- `tests/auth` + `tests/test_config_settings.py` + `tests/api/test_projections_app.py`: 52 passed on
  the Honiara-only Postgres container.
- Credential-free Clerk adversarial matrix: issuer, audience, `azp`, expiry, `nbf`, pending status,
  unknown key, and tampered signature all fail closed.
- Whole-repo mypy: 589 source files, no issues.
- Import-linter: 25 contracts kept, 0 broken.
- Targeted Ruff check/format and `git diff --check`: green.

## Limits / follow-up

- No Clerk keys are present in this worktree, so no live-provider acceptance was attempted or
  claimed. B3 supplies the browser session/BFF and B4 supplies the principal-to-tool context seam.
- B5 remains separate: existing production trusted-header routes are not removed by this slice.
- The requested Fable plan review was attempted twice; both local CLI calls remained silent for
  several minutes and were stopped, so they produced no recommendation or design change.
