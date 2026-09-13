# Separate local brand review instances

## Request and diagnosis

The founder requested four different localhost instances because separate tabs on
3020 shared the workspace-selection cookie. Brand Context could therefore show the
last-selected brand in every tab. Different ports alone would not fix that cookie:
browser cookies are scoped by host/path, not port.

## Implemented

- Four real Next development processes: Clue 3021, AWS 3022, Google Cloud 3023,
  Conduit 3024. Existing workspace IDs live only in the ignored local manifest
  `.local-setup/brand-instances/instances.json`.
- Optional server-owned workspace pin in the central session loader; existing
  active membership and matching backend principal are mandatory. No fallback to
  another workspace, and browser-supplied workspace headers cannot override it.
- Port-specific HttpOnly workspace cookies across SSR, BFFs, session establishment,
  selection and clearing. Explicit cross-workspace selection and both provisioning
  endpoints refuse while pinned; provisioning replay could otherwise modify the
  original self-serve workspace.
- Separate Next caches, compiler configs, logs and process groups; generic launcher
  supports run/status/stop and refuses occupied ports. Brand and port are visible in
  sidebar and brand-first browser titles. Compiler output is excluded from ESLint.
- Flags are empty by default in both env examples; local origins are documented and
  added to the existing private backend/Clerk allowlist. Production, unconfigured,
  unauthenticated or non-loopback pinned configurations are refused.

These are four frontend instances in the same checkout, using the existing shared
authenticated backend, database, workers and asset store behind workspace tenancy.
They are not four database copies or independently deployed agent implementations.
Clerk identity/sign-out remain shared across localhost ports. Existing creative
quality and AWS's limited source-asset coverage are not resolved by session isolation.

## Verification and failures

- Red/green domain regression: two new tests initially failed, then passed.
- 45 focused auth/session/BFF/provisioning tests pass, including actual bundled
  route/session modules with external Next/Clerk/backend boundaries stubbed.
- Browser checks on all four ports: Projects -> Brand Context -> Assets, reload,
  and interleaved visits retain the correct brand. Verified distinct logos/assets
  and palettes, with visible brand/port labels. Four different listening PIDs.
- Frontend design-system build passes. Final lint passes with two existing unused
  snap-helper warnings; final production rebuild passes after the cache/config/title
  fixes (compile, TypeScript, route generation and build traces).
- First parallel startup put tsconfig inside distDir: Turbopack could not resolve
  it despite the file existing. Fixed to ignored tsconfig.local-PORT.json files at
  frontend root. An initial lint run traversed the new caches; explicit generated
  cache ignores fixed it. Raw standalone tsc retains existing fixture errors.
- No generation/provider work, database migrations, pushes or production changes.

## Resume

The ordinary local backend stack must be running first (`bash .local-setup/run-stack.sh`).
From the repository root, run the manager in a persistent terminal:

```sh
node apps/frontend/scripts/local-workspace-instances.mjs run .local-setup/brand-instances/instances.json
```

Use `status` or `stop` with the same manifest path. Private logs and PID state are
beside the manifest. Full local operational instructions are in `.local-setup/README.md`.
Preserve the unrelated September 8 memory edits already present in the checkout.

## Closing state

Four authenticated brand tabs are open and marked as deliverables in Codex at
their individual ports. Browser asset previews, navigation and reload checks pass;
the base backend and all four frontend listeners are running. The session-isolation
change is ready for a scoped local commit. No creative-quality acceptance is implied.
