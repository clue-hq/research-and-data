# 2026-08-11 — Onboarding screens imported from clue-frontend (selective, path-restricted)

## What happened
Imported the co-founder's dummy onboarding screens into `apps/frontend/` on
`platform/onboarding-integration`, commit `e143e68a`. **Not** a `git subtree pull`
(that would merge everything on the tracked branch into already-integrated files);
instead a path-restricted patch applied under the prefix:

- Source: local remote `clue-frontend` (`/Users/aryankeshri/Documents/clue-hq/clue-frontend`),
  branch ref `refs/remotes/origin/onboarding-flow` (note: only a remote-tracking
  ref there, so fetch it by full refname — plain `git fetch clue-frontend onboarding-flow` fails).
- The onboarding work is a single commit `ab25e436` based exactly on `fa192b1f`
  (the commit the original `apps/frontend` subtree import squashed from), purely
  additive: 18 new files under `src/app/onboarding/`, `src/features/onboarding/`,
  `docs/api-contracts/onboarding.md`, `docs/figma/onboarding-flow.md`.
- Method: `git diff fa192b1f..ab25e436 -- <those paths> | git apply --directory=apps/frontend`
  (dry-run with `--check` first).
- `docs/README.md` hunk hand-applied (monorepo copy had drifted — session.md entry):
  added the two index lines for imported docs; **dropped** the line referencing
  `figma/design-system-source.md` — that file does not exist on the onboarding
  branch either (dangling ref, probably from his `codex/main-sidebar` branch).

## Sync point for future deltas
`ab25e43662ea6ddb86dcec71252f47ac9ed3603c`. When the co-founder pushes more
onboarding commits: fetch the ref, then
`git diff ab25e436..<new tip> -- <same paths> | git apply --directory=apps/frontend --3way`.
Once integration edits touch these files, any further pull is a reviewed merge,
not a blind apply.

## Verification
`npm run design-system:build` + `eslint` clean, `next build` green with
`/onboarding` and `/onboarding/[step]` in the route table, `npm test` 146/146
(includes his onboarding.repository + onboarding-navigation tests).
(`npm install` was needed in this worktree — node_modules was incomplete; lockfile unchanged.)

## Next (not started)
Contract-gap review of `apps/frontend/docs/api-contracts/onboarding.md` (frontend-authored
proposal) against the real backend Stage-0/onboarding-input + session surfaces, founder
sign-off, then replace `onboarding.fixture.ts` via the repository seam (fixture → HTTP
adapter, `CLUE_API_BASE_URL` flip). Screens still render fixture data today.
