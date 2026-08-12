# 2026-08-12 — FI-2 Slice 7 Account Artifact truthfulness

Branch: `platform/fi2-accounts-cutover` in the Monterrey worktree.

## Contract and implementation

- Confirmed there is no live Account-artifact read endpoint or repository. The Account-workspace
  model was an explicit empty adapter after Slice 1, but the route still rendered fixture-era
  search, sorting, grid/list, cards, preview and image machinery around that empty array.
- The authenticated Artifacts route now reads only Account detail, preserving Account-not-found and
  cross-workspace behavior, then renders `capability_unavailable`. It makes no guessed Artifact
  request and cannot show fake cards or empty-result copy.
- Added typed copy for `capability_unavailable`, future authoritative `empty`, and future
  `service_unavailable` states. The states stay semantically distinct so a later backend outage
  cannot masquerade as a zero-Artifact Account.
- Removed the fixture-only Artifact model, client controller, card/preview/search/sort/view UI and
  three dedicated public thumbnails. There is no Account Artifact content image left to prioritize;
  the former `/artifacts/insight-report.png` LCP request is eliminated at its source.
- Updated `apps/frontend/docs/api-contracts/accounts.md`; closed LF-ARTIFACT-001 and LF-PERF-001 in
  `.context/defect-log.md`.

## Verification

- Frontend suite: 169 passed. ESLint and design-system token generation passed.
- `next build --webpack` compiled, type-checked and generated all routes. The existing warning about
  Next inferring `/Users/aryankeshri` from multiple lockfiles remains LF-BUILD-001 territory.
- Repository static gates: mypy passed across 634 source files; all 25 import contracts passed;
  `git diff --check` passed.
- React/Next review: the route remains a Server Component and performs its one authenticated Account
  read; the non-interactive Artifact state adds no client hook, event handler, image or serialized
  Artifact collection.

## Authenticated browser acceptance

- On `localhost:3077`, Account `fda8f410-015b-45e6-a5cc-4d9b6a9dc027` rendered a named
  `Account artifacts are not connected yet` region and its capability-specific explanation.
- The Account content has no search input, fixture card, preview, `Last viewed`, grid or list
  control. The only remaining main buttons are the existing accessible Account-header actions.
- The state was identical across direct reload. Unknown Account
  `00000000-0000-4000-8000-000000000000` retained the domain 404 behavior.
- At 1280×720, the complete state region occupied y=165..251 and was above the fold. Resource timing
  contained no former `/artifacts/*.png` or `/_next/image` request; the region contains zero images.
  A clean fresh tab reported no browser errors.

## Operational notes

- The previous browser tab binding had been cleaned up; the existing signed-in browser session was
  retained and a fresh tab was opened. No new sign-in was required.
- `apply_patch` cannot decode binary PNG files. After confirming the three files were regular,
  tracked, dedicated Account fixture thumbnails with no remaining code references, they were
  removed by exact path.

No remote push was performed.
