# 2026-08-11 — Lane F authenticated browser E2E

Branch: `platform/pilot-budget-controls` at Lane F head `642064e6`.

## Scope and runtime

- Real in-app browser journey for signed-in Clerk subject
  `user_3HgQQdIm1N5dv8mASeo6TGUIcAX` (Aakash Shrivastava), acting as Insight Health GTM lead.
- Isolated DB: `postgresql+asyncpg://clue:clue@127.0.0.1:55040/clue_singapore_lane_f_e2e`,
  migrated to `5d7ab295742b`; artifacts under `.context/lane-f-e2e/artifacts`.
- Frontend `127.0.0.1:3000`, API `127.0.0.1:8001`, fleet active against the isolated DB.
- Project `prj_90d73b617fd951aabcbe08c955494bec`, thread
  `thr_58d30cd99e1f5c71b0adaf106d0db0ee`.

## Changes and decisions

- Do not change `record_interview_answer@1` wiring before proving the database preconditions. Added
  client identity/project binding first. The unchanged tool moved from missing `client_entity_id`,
  through an unseeded `client` field-class refusal, to successful durable writes after the standard
  packs/source manifests were loaded.
- Added a replay-safe authenticated Insight Health browser fixture tied to the exact Clerk subject.
  Base state is user/membership/workspace/brand/product. Project-bound state adds append-only client
  and website onboarding receipts, four recorded official-page artifacts, and seven evidence-backed
  product-scoped Client-KB claims through `reverse_profile`. It creates no ICP or research run.
- Reused the existing Insight Health official-page fixture compiler rather than duplicating claim
  definitions. Focused DB tests pass (`4 passed`) for browser and discovery fixtures.
- Frontend auth required a compatibility wrapper around Clerk middleware: local Clerk/Next returned a
  same-URL middleware rewrite that recursively hung. Removing only that rewrite while retaining Clerk
  request headers restored authenticated operation. The final seam preserves the auth-disabled mode,
  normalizes only an exact self-rewrite, and has pure regression coverage for auth-header retention and
  real-rewrite preservation. Frontend unit suite: 142 passed; lint passed; live project/API reloads
  continue to return 200 through `proxy.ts`.

## Browser evidence

- Stage-0 interview now records target segment, exclusions, buying roles, priority thresholds, and
  practice-type boundary through completed `record_interview_answer@1` calls.
- Before Client KB: readiness decision `7359460c-1b21-561c-8297-0b83d002f2a4` was `not_ready`.
- After the project-bound onboarding result: readiness decision
  `cf1629c4-146f-5870-b150-44c084aa4f9c` is `ready` and product context
  `761430ac-5289-4727-b4a0-3ea6ae8c4a6d` exists.
- No `icp_spec` row exists. The agent misleadingly called readiness policy `spec_version=1` a
  “synthesized spec version”; the surface says it has no ICP confirmation tool.
- ICP/readiness cards are not durable gates: the thread has zero `agent_gate` rows. The stream has
  two thin gate parts with no digest/subject/permitted decisions; one uses object id `human_only`.
  The frontend correctly disables decision controls without a digest. The present structured
  gate-response route supports account-research directive confirmation, not these Stage-0 refs.

## UX/visual findings

- Composer does not clear after submission; replacement attempts splice new copy into stale text,
  creating contradictory persisted turns. User screenshots capture `they arAdd...` and
  `lock result.e independent...` corruption.
- Long composer text overlaps mention/model/send controls; chat develops a horizontal scrollbar;
  sticky header clips message content; empty Gallery consumes half the width; raw fixture workspace
  id is shown; project remains Untitled.
- Ongoing authoritative ledger: `.context/lane-f-e2e/defect-log.md`.

## Current blocker and next work

- Real browser ICP synthesis/lock is blocked by a contract gap, not fixture data. Do not make disabled
  buttons clickable by inventing a digest. Need founder sign-off on the proper Stage-0 durable gate
  presenter/answer action (including revise semantics) before integrating, per branch charter.
- Continue non-browser Lane F acceptance and account-flow inspection while the gate decision is open;
  then resume discovery/deep research browser flow only after a real active ICP exists.

## Backend acceptance and Account-screen join

- Lane-F/R11 composition and bridge tests pass (55 cases across acceptance, committee bridge, deep
  fleet wake/phase bridge, and verification resolver). The account-research API/fleet selection
  suite passes (43 cases). The contact-research C0-C7 and V0 manifest suite passes (63 cases), all
  against the isolated database.
- The authenticated `/accounts` screen initially rendered 14 unrelated frontend fixtures
  (Anthropic, OpenAI, Cohere, etc.) because `CLUE_ACCOUNTS_API_BASE_URL` was unset. This is not Lane-F
  evidence and is logged as `LF-ACCOUNT-001`.
- Enabling the documented Account HTTP adapter exposed a real auth cutover gap: its transport still
  sends legacy `X-Workspace-Id` directly to FastAPI with no provider proof. The ratified principal
  resolver requires `Authorization` plus `X-Clue-Workspace-Id`, so `/frontend/v1/accounts` returns
  `403 WORKSPACE_FORBIDDEN: a workspace selection is required`. Project chat already uses the
  centralized same-origin BFF; Accounts does not. Logged as `LF-ACCOUNT-002`; do not weaken auth to
  make it pass.
- The Account page turns that deterministic 403 into a generic page crash/reload loop (and a Next
  runtime overlay in development), logged as `LF-ACCOUNT-003`.
- Isolation is now explicit: 111 frontend-read list/detail/contact contract tests and the 4-case real
  Lane-B/D principal join suite pass. The missing piece is the Account repository's auth cutover,
  not either substrate in isolation.

## Fixture-only authored Account/Contact journeys

- Walked every authored route because the live join is blocked: list, preview, overview, contacts,
  one valid contact profile, governed withheld/unnamed contact routes, Insights, Artifacts, Activity.
  These observations are presentation coverage only, never live research evidence.
- Five of six contact rows are guaranteed 404s in fixture mode: the list offers six links but the
  detail fixture repository serves Denise Dresser only. The “Look up” email action is a 700-ms
  client timer that claims “Email found” without a backend call or value. Account “New account” is
  likewise a random local React row that disappears on reload and links to an unknown id.
- Account Insights display exact-looking post/article paths but link to site/company/profile roots;
  contact Evidence is non-link provider/date chips with no span or claim mapping. Raw backend tokens
  (`1b_plus`, `product_led`, `c_level`, etc.) leak into results, and neither identity-binding nor
  allowed-use governance is reviewable.
- Activity contradicts the other fixture tabs (14 contacts versus six; summary updated versus summary
  not composed). Artifact sort/grid/list controls are inert and the latter two are unlabeled.
- Root-caused the project composer corruption: the parent clears `prompt`, but the focused Slate
  editor ignores prop replacement; blur then writes its stale prompt back. The layout overlap is
  structural too: the whole workspace composer is fixed at 126 px while the editor alone may grow to
  120 px plus padding/footer, with overflow visible.
