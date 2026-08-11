# Onboarding API contract

Status: frontend shell implemented with a fixture-backed repository. Backend
authentication, persistence, and setup execution are not connected.

Figma source: production Clue file, `onboarding-flow` page (`1634:16661`),
limited to the seven frames marked Ready for dev.

## Ownership boundary

`OnboardingRepository` owns backend data acquisition. Visual components receive
validated props and do not import fixtures or fetch data. When
`CLUE_API_BASE_URL` is present, the repository reads HTTP; otherwise the local
fixture supplies deterministic mock content.

## Read flow configuration

`GET /api/v1/onboarding`

Returns authentication labels, profile defaults and role options, plus the
workspace-setup checklist. The response must satisfy `OnboardingFlowSchema` in
`src/features/onboarding/model/onboarding.ts`.

## Authentication endpoints

The following endpoints are reserved for Aaryan's integration and are not
called by the frontend shell yet.

### Google authentication

`POST /api/v1/auth/google`

```json
{ "intent": "sign-in" }
```

`intent` is either `sign-in` or `sign-up`. The backend should return an OAuth
redirect URL or initiate the redirect directly.

### Email sign in

`POST /api/v1/auth/sign-in`

```json
{
  "email": "name@company.com",
  "password": "user-supplied-password"
}
```

### Email sign up

`POST /api/v1/auth/sign-up`

```json
{
  "email": "name@company.com",
  "password": "user-supplied-password"
}
```

Passwords must never be placed in the onboarding read payload, logs, or client
fixtures in production.

## Profile endpoint

`PUT /api/v1/onboarding/profile`

```json
{
  "firstName": "Aakash",
  "lastName": "Shrivastava",
  "role": "Founder",
  "companyName": "Company",
  "companyWebsite": "www.company.com"
}
```

Return the persisted profile plus a stable workspace identifier.

## Workspace setup endpoints

### Start setup

`POST /api/v1/onboarding/setup`

```json
{ "workspaceId": "workspace-id" }
```

Expected production response: `202 Accepted` with a durable `runId`.

### Read setup progress

`GET /api/v1/onboarding/setup/{runId}`

```json
{
  "runId": "run-id",
  "status": "running",
  "items": [
    {
      "id": "brand-kit",
      "label": "Creating brand kit",
      "detail": "Colors, typography, tone & voice",
      "status": "running"
    }
  ]
}
```

`status` is `queued`, `running`, `complete`, or `failed`. Item status is
`complete`, `running`, or `queued` to match the approved frontend shell.

## Integration notes for Aaryan

- Replace the fixture adapter by setting `CLUE_API_BASE_URL`.
- Keep server payloads compatible with `OnboardingFlowSchema`, or update the
  schema and this contract together.
- Persist profile data before starting workspace setup.
- Setup progress must be resumable; the current client timer is for presentation
  only and is not a production execution mechanism.
- Authentication errors should map to field-level messages without changing
  the approved card geometry.
