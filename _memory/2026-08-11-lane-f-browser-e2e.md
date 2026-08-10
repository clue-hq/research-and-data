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
  request headers restored authenticated operation. This still needs a dedicated regression test.

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
