# Local frontend preview parity

- Branch `feat/direct-mail-infrastructure-ui`; user wants the editable real
  frontend source on localhost:5000 with complete UI and isolated demo data.
- Verified deployed UI has the profile/Settings menu and composer controls.
  Latest successful GitHub deployment record points to the branch base
  `ab10fd287`; active Railway service revision could not be independently read
  because the CLI account lacks project access. No production writes made.
- Root causes: auth-disabled shell never supplied a profile; project fixture
  disabled all composer capabilities; Gallery document reads required auth.
- Implementing an explicit development-only preview adapter at existing data
  seams. It refuses production/auth/live backend configuration, retains only
  process-local synthetic state, and never forwards unsupported operations.
- Initial regression run: missing preview module and mismatched composer
  capabilities failed as expected. Implementation and verification in progress.
- Direct Mail flow design remains proposed; no Direct Mail screens added yet.

## Closing verification

- Implemented the full-shell preview under `CLUE_FRONTEND_PREVIEW_MODE`, default
  false in both examples and the ignored local envs. Reproducible launcher:
  `cd apps/frontend && npm run dev:preview` (5000 by default; only 5xxx accepted).
- Profile/Settings, composer attachment/context/model controls, project Gallery
  documents and background project reads use the real UI with explicit fixtures.
  Settings administrative actions remain read-only; unsupported backend actions
  return an explicit preview error. Existing scripted chat is still demo behavior.
- Browser checked: profile menu → Settings, profile update + reload, Pages,
  account context selection, model picker, Gallery document open/edit/save.
  Attachment picker opens; the synthetic multipart file was verified against the
  actual local API (200, parsed metadata). Native app picker automation was not
  available, so no claim of a full browser file-upload walk.
- Actual API smoke: discovery/research-progress return 200 with no live jobs;
  cross-origin profile mutation returns 403. Preview never connected to production.
- Fixed an HMR issue found during verification: retain state globally, not the
  request-handler closure, so adapter code changes take effect immediately.
  Also aligned fixture workspace titles with the existing directory/sidebar.
- Final focused run: 24 tests passed (preview, workspace repository, authenticated
  read, document repository and BFF). Required design-system build, lint and
  production build passed. Lint: 0 errors, 11 existing warnings in site-kit,
  site-editor host globals, scene canvas operations and site-selection tests.
  Initial missing-module/capability and background-read failures were resolved.
- Reinitialized the dev server after QA to reset demo edits. No backend services
  started, no remote mutations/pushes. Handoff guide:
  `apps/frontend/docs/architecture/local-preview.md`.
