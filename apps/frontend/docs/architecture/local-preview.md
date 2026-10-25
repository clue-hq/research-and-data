# Local frontend preview

Use the real `apps/frontend` application on the feature branch for UI development.
The deployed application is a visual reference; the preview uses isolated demo
data and does not connect to a live workspace.

## Start

```sh
cd apps/frontend
npm ci
npm run design-system:build
npm run dev:preview
```

Open `http://localhost:5000`. Another isolated worktree can use
`npm run dev:preview -- --port 5001`; the command accepts only ports 5000–5999.
It does not edit `.env.local`, start backend services or provision a database.
Stop the process with Ctrl-C. Profile and document edits reset on restart.

## What is available

- Existing Home, Accounts/Contacts, project directory, chat and navigation fixtures.
- Profile menu and the actual Settings screens. Profile name edits work locally;
  workspace, members, Pages and research-field configuration are readable.
  Membership, domain publishing and other connected administrative actions remain
  unavailable. Billing/integrations retain their existing static UI.
- Attachment selection/removal, context selection and the existing demo model
  picker. Attachments are hashed locally and represented as preview metadata;
  their bytes are not stored or sent to a backend/provider.
- Two synthetic Gallery documents per project, using the existing Markdown
  editor and revision-conflict handling. These are not live generated artifacts.
- Existing scripted chat behavior. No model calls, paid research, messages,
  orders or publishing occur. A demo model label is not a live model configuration.

The small “Local preview · Demo data” label identifies this mode on every screen.
This is a UI development environment, not a full backend emulator. Unsupported
API actions return `PREVIEW_ACTION_UNAVAILABLE`, never a fabricated success.

## Data boundary and handoff

`src/features/preview/data/preview-mode.ts` owns the explicit default-off
`CLUE_FRONTEND_PREVIEW_MODE` flag. It requires `NODE_ENV=development`, a loopback
app origin with a port, authentication disabled, Accounts fixtures enabled, no
backend URLs and no workspace pin. The launcher supplies those process overrides.
It refuses mixed/live configurations and cannot be enabled in a production build.

`preview.fixture.ts` contains typed synthetic records. `preview-backend.ts` serves
those records at the existing read, upload and project-document seams, with
process-local state. Presentation components keep using their normal schemas and
repositories. No production read failure falls back to fixtures. Existing
authentication and origin checks still govern the connected mode; mutation-origin
checks also apply to preview requests.

For Aryan: continue feature work on `feat/direct-mail-infrastructure-ui` inside
`apps/frontend`. Direct Mail will have its own typed model, repository and fixture
adapter following the [proposed flow](direct-mail.md). The preview adapter is only
development support; it is not the Direct Mail backend implementation. Switch to
the usual authenticated development command/configuration to test real integration.
Do not copy preview records into a live workspace.

## Baseline and verification

The branch started at `ab10fd287`, also referenced by the successful GitHub
deployment record from 2026-10-22. Production's profile/Settings and composer
controls were inspected in the deployed app. This does not independently prove
the active Railway service revision; CLI access to that project was unavailable.

Focused tests cover preview configuration refusal, real Settings schemas, local
profile edits, versioned/project-scoped documents, attachment metadata and absent
live jobs. Existing request/BFF tests cover authentication, origins and error
propagation. Required gate: `npm run design-system:build && npm run lint && npm run build`.
