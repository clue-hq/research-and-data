# Authenticated-principal cutover runbook

Status: Lane B B5 preparation complete; deployment flip intentionally paused for Lane D D5.

This runbook covers the production edge owned by Lane B. Clerk proves a browser session only.
Clue Postgres remains authoritative for users, workspaces, memberships, permissions, and audit
identity. Never copy provider tokens, subjects, or credentials into domain rows, logs, fixtures,
`_memory/`, or this document.

## Before enabling production auth

1. Apply migrations and confirm `alembic heads` reports exactly one head.
2. Provision each intended human as a `platform_user`, active `auth_identity`, and active
   `workspace_membership`. A valid Clerk session without these rows is correctly refused.
3. No Clerk JWT template is used. The frontend forwards Clerk's default session token, which
   carries the session-bound `sid`/`azp` claims the backend requires (template tokens cannot;
   ratified 2026-08-09 — see `apps/frontend/docs/api-contracts/session.md`). Verify
   `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` lists the exact application origins: the `azp` check is
   the origin binding.
4. Set the backend values below through the deployment secret/config store. Do not commit values:

   ```text
   CLUE_AUTH_ENABLED=true
   CLUE_AUTH_ENVIRONMENT=production
   CLUE_AUTH_MODE=clerk
   CLUE_AUTH_CLERK_JWKS_URL=<instance JWKS URL>
   CLUE_AUTH_CLERK_ISSUER=<expected issuer>
   CLUE_AUTH_CLERK_AUTHORIZED_PARTIES=<exact application origins>
   CLUE_PROJECTIONS_AUTH_MODE=authenticated_principal
   ```

5. Set the frontend values through its deployment configuration:

   ```text
   CLUE_AUTH_ENABLED=true
   CLUE_API_BASE_URL=<FastAPI origin>
   NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=<publishable key>
   CLERK_SECRET_KEY=<secret value>
   ```

Production construction fails if trusted-header tenancy is selected or if the authenticated
principal service is absent. `X-Clue-Workspace-Id` remains a selector; changing it never grants
membership. `X-Workspace-Id` and `X-Actor` are not production credentials.

One pre-D1 compatibility exception remains deliberately quarantined: a non-receipt human effect
already declared as a durable C5 execution node may replay while auth is default-off. Free-standing
legacy human contexts and every action-reference-bearing approval are refused. Lane D must replace
that executor context with its persisted turn principal and remove the exception before D5.

## Automated pre-join acceptance

Run against an isolated disposable database:

```text
pytest -q tests/auth tests/test_config_settings.py tests/api/test_projections_app.py
pytest -q tests/api/test_account_research_fleet_r6_db.py tests/fleet/test_entity_research_r2.py tests/fleet/test_entity_research_r2_db.py
```

The first command covers the isolation-safe Lane B matrix:

| Matrix row | Evidence before the Lane D join |
|---|---|
| 1 | Migrated-schema and static no-provider-key inspection |
| 2 | Provider swap preserves internal membership and durable tool actor ids |
| 3, 10 | Cross-workspace tool, launch, and stream selectors return `WORKSPACE_FORBIDDEN` before writes |
| 5 | Membership revocation blocks the next request without a new authority write |
| 6 | A disabled internal user is refused independently of provider-session validity |
| 7 | Issuer, authorized party, session id, time, token shape, signature, JWKS outage, and rotation tests (audience deliberately not verified — session-token-native contract) |
| 8 | Human gates reject legacy-null/service authority; browser/model fields cannot author authority |
| 11 | Frontend session schemas, workspace fallback/repair, BFF header replacement, and recursive tests |

Rows 4, 9, and 12 require Lane D's persisted turn, gate, worker, and `turn-action:<turn_id>` join.
They are not waived and must run before D5. Real-browser row 11 and live JWKS/session behavior also
require the Clerk application and integrated environment; offline tests are not live proof.

## Live smoke and adversarial checks at D5

- Sign in as one provisioned user and verify the shell establishes an HttpOnly workspace cookie.
- Switch between two authorized workspaces; then select an unauthorized workspace and verify a
  `403 WORKSPACE_FORBIDDEN` with no write, enqueue, stream token, or provider spend.
- Revoke the active membership while its provider token remains valid; the next read and mutation
  must fail. Disable the user and verify every linked provider identity fails.
- Rotate the Clerk signing key and verify a token signed by the removed key is rejected after
  refresh. A JWKS outage must return a retryable 503 rather than force sign-out.
- Sign out and confirm both the Clue workspace cookie and provider session are cleared.
- Run Lane D matrix rows 4, 9, and 12, then perform the D5 production flip.

## Rollback

Do not fall back to trusted headers in production. Roll back by disabling the public route or
deployment revision, not by changing `CLUE_PROJECTIONS_AUTH_MODE` to `local_header`. Preserve all
Clue internal users, memberships, turns, approvals, and audit rows; provider configuration is an
adapter concern and rollback must not rewrite canonical identity.

Local/test fixtures may continue to use `auth_environment=local|test`, `auth_mode=local_fixture`,
and `projections_auth_mode=local_header` against seeded internal users and memberships.
