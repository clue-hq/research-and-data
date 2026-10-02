# ARV2 onboarding O5 — the brand-context Knowledge read surface (close-out)

Date: 2026-09-08. Branch `onboarding/o5-knowledge-read-surface`, worktree `semarang-o5`,
base `d751c3749` (the O5 plan commit). Local commits only; nothing pushed.
Plan: `docs/superpowers/plans/2026-09-08-arv2-onboarding-o5-knowledge-read-surface.md`.
Executed via SDD in six tasks; the task briefs and reports live in
`.superpowers/sdd/2026-09-08-arv2-onboarding-o5-knowledge-read-surface/`.

Goal: the brand-context page's Knowledge section lists the **real** onboarding documents
(`company/`, `product/`, `audience/`, `proof/`) out of `brand_knowledge_document`, renders each as
markdown with no edit control, and fills in as an O3 run publishes documents.

## Commits (5, in order)

| SHA | What |
| --- | --- |
| `bef32b210` | The three backend reads + `tests/api/test_frontend_read_brand_knowledge.py` |
| `1d368a0bd` | Router path inventory, `frontend_read` exports, the contract-doc resolution, the arv2 README paragraph, the unreadable-document log line |
| `ec4bf381a` | Frontend wire model + knowledge repository (`toKnowledgeFolders`, bodies in parallel, never rejects) |
| `50ab0117d` | The page merge (platform folders before the kit's Design) + the Preview/Edit control removed page-wide |
| `5f05a8ead` | Progressive fill: poll the onboarding status while a run is live, `router.refresh()` when a step lands |

Diff over the lane: 24 files, +1571 / −258.

## What landed

### Backend — `platform/api/clue_api/frontend_read/brand_knowledge.py` (new, 432 lines)

Three workspace-scoped read-only routes on the existing flag-gated `/frontend/v1` router (auth,
tenant scoping, FI-1 error envelope and CORS come for free from
`frontend_read_workspace_resolver`). **The plan's §7 wrote `/api/v1/...`; the REAL paths are:**

- `GET /frontend/v1/brand-context/knowledge?brandId=…` → `KnowledgeTreeWire`
- `GET /frontend/v1/brand-context/knowledge/documents/{document_id}` → `KnowledgeDocumentDetailWire`
- `GET /frontend/v1/brand-context/onboarding/current` → `OnboardingStatusWire`

Readers (all `async`, first arg `conn: AsyncConnection`): `resolve_knowledge_brand`,
`read_knowledge_tree`, `read_knowledge_document`, `read_onboarding_status`, plus
`register_brand_knowledge_routes`. Wire models are `WireModel` subclasses (frozen, `extra="forbid"`,
camelCase alias generator) reused from `accounts_list`, so the JSON convention matches every other
slice-1 payload. All seven names are exported from `clue_api.frontend_read` (`__all__` is now 30).
The reads touch only `brand_knowledge_document`, `brand`, `onboarding_run`/`onboarding_step`,
`artifact` — nothing else.

### Frontend

- `src/features/brand-context/model/brand-knowledge.ts` — the three wire schemas + `KnowledgeSource`,
  `onboardingRunIsLive`, and the pure `toKnowledgeFolders(tree, bodies)` mapping onto the dummy's
  lifted `BrandKnowledgeFolderSchema` shape.
- `src/features/brand-context/data/brand-knowledge.repository.ts` — `readBrandKnowledgeFolders`
  (one tree read, then every document body **in parallel**) and `readOnboardingStatus`. Neither
  ever rejects.
- `data/brand-context.repository.ts` — `httpBrandContextRepository({ clueFetch, designFetch })`
  merges the platform folders in front of the brand kit's Design folder. **Merged folder order is
  `company, product, audience, proof, design`** — Design keeps riding the brand-kit read
  (`brand_kit_json.brief`), and the platform read never serves `design`. Memories stays absent.
- `src/app/(protected)/brand-context/page.tsx` — one `authenticatedBackendContext()` feeds both
  `clueFetch` and `designFetch`; the `mode` query field is gone.
- **The Preview/Edit control is removed page-wide**: the header's whole `Document mode` block, the
  `documentMode === "edit"` branch in `knowledge-panel.tsx`, all `documentMode`/`documentBody`
  plumbing in `use-brand-context-controller.ts`, `BrandDocumentModeSchema`/`BrandDocumentMode` in
  `model/brand-context.ts`, `components/markdown-source-editor.tsx` (deleted), and the orphaned
  `.documentModeControl*` / `.markdownEditorShell` / `.markdownCodeEditor*` CSS.
- `hooks/use-knowledge-refresh.ts` — the refresh hook. Arms a 5s `window.setInterval` only while
  `onboardingRunIsLive(initial)`; `shouldRefresh(previous, next)` calls `router.refresh()` when the
  finished-step count grows and once more on the live→terminal transition so the last documents
  land; stops on terminal and after 3 consecutive refused reads; cleans up on unmount.

## Founder rulings (2026-09-08)

1. **No status chip → servable documents only.** The tree lists documents whose status is `ready`,
   `proposed` or `confirmed`, highest such version per path. `running` / `empty` / `failed` /
   `superseded` never appear in the tree and 404 on the detail route — with no chip in the dummy
   there is nothing honest to render for them.
2. **The edit control is removed from the whole page, `Design.md` included.** Read-only surface; the
   contract doc's proposed `POST`/`PUT` stay proposals.

## The plan's own rulings (as implemented)

- **Brand resolution order** (`resolve_knowledge_brand`): explicit `brandId` **when the workspace
  owns it** (a foreign id resolves to `None`, never leaking another tenant's tree) → the brand of
  the workspace's newest `onboarding_run` by `requested_at DESC` → the workspace's **only** brand →
  `None`. Several brands and no run is `None`, never a guess.
- **Title** = the markdown's first `# ` heading, else the file name without `.md`. `product_id` /
  `icp_key` come from front matter.
- **Sources** are flattened from O2's front-matter shape
  (`sources: {field: {citations: [{url, title}], confidence}}`) into a flat
  `[{section, url, title, confidence}]`, sections sorted, citations without a string `url` skipped.
- **Body reads:** the **tree** reads bodies **sequentially server-side** (a few dozen documents);
  the **page** reads the document bodies **in parallel** from the browser-side repository.
- **Refusals become honest empties, never a 500.** A refused platform tree read leaves the four
  folders out and the kit's Design folder still lists; a refused body lists the document with an
  empty body; a design-store outage still lists the onboarding documents (the two stores are
  independent). `readBrandKnowledgeFolders` / `readOnboardingStatus` never reject.
- **No storage backend in the process:** the tree still serves (file-name titles, `None` ids); the
  detail route refuses loudly with **`503 KNOWLEDGE_STORAGE_UNAVAILABLE`** rather than pretending.
- **404 uniformity:** missing, non-servable, wrong-workspace and `design`-folder all return the same
  `404 KNOWLEDGE_DOCUMENT_NOT_FOUND`, so a probe cannot distinguish "not yours" from "not there".
- **`updatedLabel`** rides the wire and is never rendered (dummy is presentation truth; anything
  with no designed slot — status, kind, version, sources, dates — stays invisible).

## Implementer deviations (all deliberate, all recorded in the task reports)

1. **`WorkspaceDep` is imported at module scope, not lazily inside the register function** (Task 1).
   The brief's lazy import **does not work**: the module has `from __future__ import annotations`,
   so FastAPI resolves handler annotations with `get_type_hints` against *module* globals; a
   function-local `WorkspaceDep` is invisible there and FastAPI degraded it into a required **query
   parameter** — every request 422'd with `query.workspace_id: Field required`. The brief's stated
   circular-import reason is also wrong: `app.py` imports the endpoint modules lazily *inside*
   `build_frontend_read_router`, and every sibling (`account_detail`, `contacts`, `bulk_actions`,
   `account_activity`) already imports `WorkspaceDep` at module scope.
   Also Task 1: row helpers are typed `RowMapping`, not `Mapping[str, Any]` (mypy; `RowMapping` is
   not assignable to `Mapping[str, Any]`) — annotation-only.
2. **The platform read runs concurrent with, and independent of, the design read** (Task 4). The
   plan's snippet awaited the platform read before `designFetch()`, serializing two round trips; the
   shipped version starts the promise in `getWorkspace` and awaits it at the end. Because the
   promise is started there, the **outer catch also serves the platform folders**, so a design-store
   outage no longer blanks onboarding documents we actually hold.
3. **Lazy session memoization on the page** (Task 4): `let pending = null; const sharedContext = ()
   => (pending ??= authenticatedBackendContext())`. The plan's eager resolve left a floating promise
   on the fixture path (where neither fetch is ever called) — an unhandled rejection risk the old
   lazy `designFetch()` did not have. Same single proof per render, still lazy.
4. **The refresh hook has an exhaustive dependency list, no `eslint-disable`** (Task 5). Liveness is
   derived outside the effect (`const isLive = onboardingRunIsLive(initial)`) so the effect never
   references `initial`. This is also better than keying on `runId`/`status`: `router.refresh()`
   hands the client a new `initial` object on every landed step, and re-arming on each would restart
   the poll under its own success. The `last` ref survives those re-renders, so a landed step is
   never counted twice.
5. **The page's status read is a guarded async thunk** (Task 5), not a bare expression in the
   `Promise.all`. `readOnboardingStatus` catches its own transport/parse failures, but proving the
   session (`await clueFetch()`) happens outside that catch — a session-proof failure would have
   500'd a page whose whole design is fail-soft. Also gated on
   `Boolean(process.env.CLUE_API_BASE_URL?.trim())`, so the fixture path opens no transport at all.
6. **Two small additive edits the briefs did not name:** `dateLabel` exported from
   `brand-context-mapping.ts`, and `export type BrandKnowledgeFolder` added to
   `model/brand-context.ts` (the schema was exported, the type alias was simply missing; without it
   the new files fail `tsc` with TS2724). Plus a `log.warning("brand_knowledge.document_unreadable",
   …)` in the tree's `except Exception` arm, so half-broken storage is no longer silent.

## Deferred minors (none blocking)

- **The unreadable-blob log arm is untested.** Nothing seeds a document whose `artifact_key` points
  at nothing; that `except` branch was uncovered when it shipped and the log line did not change
  that. Worth a fixture later (assert the tree still lists it by file name).
- **`codemirror` + five deps are now unused in `src`.** Deleting `markdown-source-editor.tsx`
  removed the only importer of `codemirror`, `@codemirror/lang-markdown`, `@codemirror/language`,
  `@codemirror/state`, `@codemirror/view` and `@lezer/highlight`. `package.json` and the lockfile
  were deliberately not touched (the design editor may want them back) — real dead weight in the
  bundle graph, needs a deliberate decision.
- **`.passthrough()` is deprecated in Zod 4** (this repo is on zod 4.4.3). Works at runtime,
  type-checks, eslint silent; `z.looseObject(...)` is the Zod-4 spelling for a future pass.
- **The `last` ref is seeded from the first render's `initial` only.** If a *different* run started
  while the page stayed mounted and live, the first comparison would be against the previous run's
  finished-step count — at worst one missed refresh on the next tick. Not a path this surface
  exposes.
- `resolve_knowledge_brand` has no tie-break on `requested_at` (`, run_id DESC` would cost nothing).
- The tree re-derives titles and `product_id`/`icp_key` from bytes on every request; they are not
  projected onto `brand_knowledge_document`. Projecting them at publish time would remove the
  per-document fan-out and the no-storage degradation entirely. Design observation, not a defect.
- No test drives the page Server Component or the hook's timer wiring (only the pure
  `shouldRefresh`); the 5s interval and the 3-refusal budget are the plan's numbers, not tuned
  against a real run.
- The contract doc describes the merged folder list (four platform + the kit's Design), while the
  **endpoint** serves only the four — a reader of the doc alone might expect five from the wire.

## Tests and gate results

Test files: `tests/api/test_frontend_read_brand_knowledge.py` (new, 5 tests);
`tests/api/test_frontend_read_app.py` (modified — the three new paths added to the router inventory);
`apps/frontend/src/features/brand-context/model/brand-knowledge.test.ts` (new),
`data/brand-knowledge.repository.test.ts` (new), `hooks/use-knowledge-refresh.test.ts` (new),
`data/brand-context.repository.test.ts` (modified — +4 merge/refusal tests).

- **Backend** (throwaway DB `clue_o4_agent` @ `localhost:55040`, head `9f81e5692fea`):
  `uv run pytest tests/api/test_frontend_read_brand_knowledge.py tests/api/test_frontend_read_app.py
  tests/arv2 --ignore-glob='*_live.py' -q` → **483 collected, 481 passed, 2 failed**. Both failures
  are **pre-existing and outside this lane**:
  `tests/arv2/test_settings.py::test_env_example_documents_each_setting_with_its_default` and
  `tests/arv2/test_onboarding_settings.py::test_every_onboarding_env_name_is_documented_with_its_default`
  — the env-parity tests compare `.env.example` raw text against the shipped default, and base
  commit `33ab4fed1` ("quote the display pitch example so .env stays shell-sourceable", an ancestor
  of the lane base `d751c3749`) added shell quotes the parser does not strip.
  **The lane touched neither `.env.example` nor anything under `tests/arv2/`** (`git diff
  --name-only d751c3749..HEAD` confirms). Reported, not fixed — the fix belongs to whoever owns the
  quoting change (either strip quotes in the test's comparison or unquote the example).
  Both O5 backend test files passed (29/29).
  `uv run ruff check platform/api/clue_api/frontend_read` → **All checks passed!**
  `uv run mypy platform/api/clue_api/frontend_read/brand_knowledge.py` → **Success: no issues found**.
  No `make check`, no broad pytest (live tests spend money).
- **Frontend** (`apps/frontend`): `npm run design-system:build && npm run lint && npm run build &&
  npm test` → **exit 0**. Lint: 0 errors, **2 pre-existing warnings** (`snapPosition`/`snapExtent`
  unused in `src/features/design-editor/engine/scene/canvasOperations.ts:728,760` — outside
  brand-context, present before the lane). Build: compiled successfully, 20 routes,
  `/brand-context` emitted as `ƒ` (dynamic, as its `force-dynamic` boundary requires). Tests:
  **2071 pass / 0 fail / 113 suites**.
- **Standing rule (catalog contract §10 / `_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`):**
  `grep -rn "client_kb_version\|readiness_decision\|project_run_stage0_pins\|evaluate_stage0_readiness"
  platform/api/clue_api/frontend_read/brand_knowledge.py apps/frontend/src/features/brand-context`
  → **zero hits**. No Client-KB version, readiness decision or Stage-0 pin on any O5 path.

## Acceptance

**NOT run — Task 7 is founder-triggered** (the frontend on its own port against the semarang API,
walked by the founder against a real onboarding run). Nothing on this branch has been exercised
against live data; the O5 gates above are offline plus the throwaway DB only.

## Addendum — live acceptance walk (2026-09-08, founder-triggered)
Stack from this checkout: platform API `uvicorn clue_api.projections_main:app` on **127.0.0.1:8070**
(`CLUE_FRONTEND_READ_ENABLED=true`; `http://localhost:3040` added to `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES`),
frontend `npm run dev -- -p 3040` with `apps/frontend/.env.local` → `CLUE_API_BASE_URL=http://127.0.0.1:8070`,
`CLUE_APP_ORIGIN=http://localhost:3040`, `LUMEN_API_BASE_URL` pointed at a dead port (no design API:
the Design folder is honestly absent). Logs `/private/tmp/semarang-{api,frontend}.log`. Both left running.
- **Sign-in:** the Clerk dev user (`aryan+clerk_test_design@example.com`) has no row in `clue_semarang`;
  the old `/auth/v1/provision` path answered 404, so the Clerk subject (`user_3IKQ…`) was linked to the
  seeded owner `usr_aryan_onboarding` of `ws-insight-health-o3` via `link_auth_identity(provider_key="clerk")`.
  `/select-workspace` then offered that workspace.
- **Read surface (exit gate 1):** `/brand-context?section=knowledge` rendered Company / Product /
  Audience / Proof from the real store — 1 + 28 + 6 + 1 documents, ICPs `proposed`, personas `ready`,
  markdown rendered, **no Edit control anywhere**. Evidence: `.context/arv2-onboarding-o5-acceptance/`
  (screenshots, served tree JSON before/after, API log excerpt, 971 lines).
- **Progressive fill (exit gate 2):** run 4 `54246e39…` started from the page's own session
  (`POST /api/clue/onboarding` → 202), page reloaded once so the server render saw a live run; the hook
  then made **220 status polls** and the page **re-read the tree 30 times** — once per landed step plus the
  terminal refresh — over the 17-minute run (`completed`, $2.57, synthesis completed). Every path went to
  its next version (audience v2), counts level because the paths already existed.
- **Findings for other owners:** (1) the sidebar's Projects list shows the O4 system project
  "Onboarding · Insight Health brand" — the O4 ruling said O5/O6 keep it out of the sidebar; that list is
  the projects surface (O6/project-list owner), not this lane's. (2) the document title is the body's
  first H1, so the page shows the heading twice (title bar + article) — cosmetic; switch `title` to the
  file name if it grates. (3) the refresh hook arms only when the server render sees a live run: a tab
  opened before a run starts does not start polling until reloaded (by design; note for O6's "start
  onboarding" affordance to navigate/refresh after POST).
