# 2026-08-07 — `platform/frontend-integration` branch charter recorded

## What this session did

Recorded the standing charter of the `platform/frontend-integration` branch into the root
`CLAUDE.md` and `AGENTS.md` (new "Current branch charter" section, inserted after the
design-merge paragraph), so every future agent session on this branch inherits it. No code
was changed.

## The charter (summary — the files are authoritative)

- The dummy frontend built by the non-technical co-founder (separate repo) was merged into
  this branch as a squashed subtree at `apps/frontend/` (merge commit `0f9ab466`). This
  branch's purpose is the end-to-end frontend ⇄ backend integration.
- The **functional** design-subsystem integration (Parts II–IV of
  `docs/specs/design-integration-master-plan.md`) happens on a **parallel branch/worktree**,
  not here; this branch has only the Part-I mechanical repo union. That branch merges into
  this one when complete.
- Integration is incremental, one screen/user-flow at a time: **accounts & contacts flow
  first**; **project-level integration second**, only after the design branch merges in.
- The frontend API contracts (`apps/frontend/docs/api-contracts/{accounts,projects}.md`)
  are frontend-authored **proposals** — mismatches with real backend surfaces are expected;
  each gap is reconciled explicitly with founder sign-off before implementation (either new
  backend read endpoints or an amended frontend contract), and the decision is written back
  into the contract doc.
- Integration happens at the frontend's repository seam (Zod schemas in
  `src/features/*/model/`, fixture/HTTP adapters in `src/features/*/data/`,
  `CLUE_API_BASE_URL` flips fixtures→HTTP), never inside presentation components.

## Frontend orientation facts (verified this session)

- `apps/frontend/` is Next.js App Router + TS + Tailwind v4, fixture-backed today; own
  npm toolchain; check gate `npm run design-system:build && npm run lint && npm run build`.
- Accounts contract expects: `GET /api/v1/accounts` (list w/ search/filter/sort/cursor),
  `GET /api/v1/accounts/:id` (detail incl. fit criteria/insights/activity),
  `…/:id/contacts`, `…/:id/contacts/:contactId`, `…/:id/workspace`; planned writes
  (`POST /accounts/query`, create/patch/delete, `POST/GET …/research` job endpoints,
  table-config). Backend candidates to reconcile against: C7 research-view contracts,
  toolbelt/projection/SSE surfaces, B4 run APIs.
- Projects contract expects: `GET /api/v1/projects/sidebar`, `GET /api/v1/home`,
  `GET /api/v1/projects/:id`, plus thread/message/run/artifact writes — deferred until the
  design branch merges.

## Open items / next session entry point

- Next work: the accounts & contacts flow — start with a contract-gap review (frontend
  `accounts.md` shapes vs. actual C7/toolbelt read surfaces) and get founder sign-off
  before wiring any HTTP adapter.
- Nothing was decided about auth/session layer, CORS topology, or `logoPath`→`logoUrl`;
  those are flagged in the frontend contract's integration checklist and remain open.
