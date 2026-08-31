# Railway deployment

The platform frontend is built from the repository root because its prebuild
vendors a small, explicit contract from `subsystems/clue-design/`: four Inter
TTFs, the source-stamped browser engine, and the engine sources used to verify
that stamp. Do not configure `/apps/frontend` as Railway's Root Directory; an
isolated root omits that contract.

## Service source and build

- GitHub repository: `clue-hq/research-and-data`
- Branch: `integration/frontend-design-part-iv-v4`
- Root Directory: unset (repository root `/`)
- Build Command: unset (the Dockerfile owns it)
- Start Command: unset (the Dockerfile owns it)
- Service variable: `RAILWAY_DOCKERFILE_PATH=/apps/frontend/Dockerfile.railway`

Recommended watch paths:

```text
/apps/frontend/**
/subsystems/clue-design/fonts/**
/subsystems/clue-design/crates/lumen-core/**
/subsystems/clue-design/crates/lumen-wasm/**
/subsystems/clue-design/apps/editor/public/wasm/**
/subsystems/clue-design/scripts/preflight_editor_wasm.mjs
/subsystems/clue-design/scripts/build_wasm_core.sh
```

## Service variables

```dotenv
RAILWAY_DOCKERFILE_PATH=/apps/frontend/Dockerfile.railway

CLUE_API_BASE_URL=https://<platform-api-tunnel>
LUMEN_API_BASE_URL=https://<design-api-tunnel>
CLUE_PROJECTS_API_BASE_URL=/api/clue

CLUE_APP_ORIGIN=https://app.cluehq.ai
CLUE_AUTH_ENABLED=true
CLUE_AUTH_CLERK_AUTHORIZED_PARTIES=https://app.cluehq.ai

NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=<Clerk publishable key>
CLERK_SECRET_KEY=<Clerk secret key>
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/onboarding/sign-up
NEXT_PUBLIC_CLERK_SIGN_IN_FALLBACK_REDIRECT_URL=/session/establish
NEXT_PUBLIC_CLERK_SIGN_UP_FALLBACK_REDIRECT_URL=/session/establish
```

`CLUE_API_BASE_URL` and `LUMEN_API_BASE_URL` are server-only. Do not give them a
`NEXT_PUBLIC_` prefix. The Clerk publishable key and route variables are build
arguments because Next compiles them into the browser bundle; the secret key is
runtime-only and must never be declared as a Docker build argument.

The frontend uses Clerk's default session token. Do not configure the retired
`CLUE_CLERK_JWT_TEMPLATE` variable.

## Browser-engine release gate

The two files under `subsystems/clue-design/apps/editor/public/wasm/` are tracked
deployment artifacts. Whenever `subsystems/clue-design/crates/lumen-core/`
changes, rebuild and verify them before committing:

```bash
bash subsystems/clue-design/scripts/build_wasm_core.sh
node subsystems/clue-design/scripts/verify_handshake.mjs
```

The handshake must print `HANDSHAKE OK`. A clean Railway build then runs the
same source-stamp preflight before copying the artifacts into
`apps/frontend/public/vendor/wasm/`.

## Domain and external runtime

After a successful deploy, add `app.cluehq.ai` under the service's Public
Networking settings and create both DNS records Railway displays (CNAME and
TXT). Add the same HTTPS origin to Clerk and to the local platform API's
authorized-party list. Both ngrok tunnels and the local platform/design APIs
must remain running for the hosted frontend to function.
