# 2026-08-19 — genweb slice 3: the visible loop (frontend, B5)

Branch `integration/frontend-design-part-iv-v2`, worked directly. Plan:
`docs/superpowers/plans/2026-08-19-chat-driven-website-generation.md` §"Slice 3" (the
founder's binding 8-point acceptance list). Brief + report:
`.superpowers/sdd/2026-08-19-chat-driven-website-generation/slice3-{brief,report}.md`.

Commit (local only): `67d2b191` —
`feat(genweb): the chat surface shows the design leg — frames, feed refresh, canvas reload (B5)`.
Frontend-only; zero backend paths touched. Gates: `npm test` 857/857 (835 baseline + 22 new),
lint clean, `design-system:build` + `build` ✓.

## What the slice added (all under `apps/frontend/src/features/`)

- `projects/model/design-leg.ts` (**new, pure — the only home of the copy**): the four leg
  lifecycle lines, the close-reason table, the verbatim wait sentence
  `"Website generation often takes 5–15 minutes."`, the four typed leg-refusal sentences, and
  `designRefreshForEvent(event, {activeThreadId}) -> {refetchFeed, reloadCanvas}`.
- `projects/model/chat-events.ts`: the parser learns `leg.opened` / `leg.awaiting_user` /
  `leg.closed` / `leg.reopened` + `leg_id`. Unknown `leg.*` stays a **non-fatal** drop.
- `projects/model/chat-transcript.ts`: reducer rule 7 — a leg frame becomes ONE system line on
  the turn that transacted it (keyed by `event_id`, so a replayed backlog cannot double it) and
  moves `TranscriptState.designLeg`. `TranscriptMessage` gains `legNotices` + `generatingDesign`.
- `projects/components/chat-transcript.tsx`: renders them in the EXISTING `reasoningStatus`
  status-line pattern; the bare `failureCode` line now goes through `designTurnFailureNotice`.
- `projects/hooks/use-project-chat-controller.ts`: `designRefresh: {feedRevision, canvasRevision}`.
- `chat-shell/components/chat-surface.tsx`: `feedRevision` → `router.refresh()` (the gallery
  feed is a SERVER fetch on the chats page, so a router refresh IS the client's re-fetch);
  `canvasRevision` → `session.onWriteReload()` (the same nonce seam an inspector write uses).

## Facts worth keeping

- **The refresh rule is deliberately narrow.** Only `leg.*` frames refresh anything;
  `turn.completed` refreshes nothing. `leg.awaiting_user` is written in the transaction that
  hands the leg back AFTER the design run committed the document version
  (`design_leg_wiring._leg_back_to_awaiting`), so it is exactly "the committed turn completed".
  Refreshing on `turn.completed` would remount an open canvas after every strategy answer.
- **`leg.awaiting_user` is emitted even when the run FAILED** — `_leg_back_to_awaiting` runs
  before the `run["status"] != "succeeded"` check. So a failed design turn also refreshes; that
  is harmless (both refreshes are idempotent re-reads) but it means the frame is "the leg came
  back", not "a version landed".
- **The first generation is TWO turns.** Message 1 → head-of-abm turn → `open_design_leg` →
  `leg.opened` + the web document is born (slice 2) → the card appears. Message 2 → routed to
  design (`routed_to: "design"` on the 202) → the actual generation. So the transcript shows the
  leg line on turn 1 and the wait line on turn 2.
- **There is no durable "this turn is a design turn" read.** `GET …/turns` (the submissions
  union, `chat/stream.py`) carries no role, and `ThreadWire.speaker` (which does carry the leg
  id/state) is not parsed by the frontend at all — and the founder's no-speaker-chip ruling means
  it should not start being parsed just for a chip. So `generatingDesign` is derived from the
  leg frames in the replayed backlog. Honest degradation: if the opening frame is older than the
  3-turn backlog the surface simply says less.
- **`router.refresh()` preserves client state** and re-runs the chats page's
  `loadGalleryFeed`, handing fresh `artifacts`/`documentIds` props down. Verified live: the
  gallery went 3 → 4 cards with no navigation and no lost transcript.
- Screenshots of the walk: `.playwright-mcp/slice3-*.png` (gitignored).

## Stack recipe used (unchanged from slice 0/1.5, re-confirmed)

`/tmp/slice0-relaunch-8010.sh` (design API 8010), `/tmp/slice3_platform_8030.sh` (platform API
8030 — same command as the slice-0 note), `/tmp/slice15_fleet_worker.sh` (istanbul fleet
worker). Frontend 3030 was already alive. NEVER touch the tunis or missoula workers.
Browser login: `onboarding+clerk_test_20260814@example.com` / `pass@123` / code `424242`.

## The live walk (dev data, left in place)

Thread `thr_a203a052febe5ef993cefdc5ebe5be5e`, leg `d392f701-8901-554b-8564-34ca8fdb1172`,
doc `doc_7b2c6ffe137a5bd9beba32745d77ce35`. Full loop passed: ask → `leg.opened` line + card
appears (gallery 3→4, no navigation, no auto-open) → second message routes to Design → wait
line on the design turn only → navigate away, sidebar shows the running spinner → open the tab
on the empty v0 → **12m07s** later the turn commits v0→v1 and the canvas iframe `srcdoc` goes
8 651 → 20 733 bytes **live** (no navigation) → hand edit via the inspector (v1→v2, R6 dock)
→ send a message (dock dismisses, `?edit=1` drops) → that turn failed honestly
(`design_leg_turn_failed`, nothing saved) and the transcript said so in a sentence → the next
message retried on the same leg/document and succeeded. Forced `design_leg_document_finalized`
refusal proven on `thr_genweb_slice2_ask` (doc SQL-marked finalized, then reverted).
Screenshots `.playwright-mcp/slice3-1..8-*.png`. Zero console errors.

Two presentation fixes came out of the walk and are in the commit: the generic `Response
failed` line is suppressed when a typed failure code is present, and the failure sentence
renders ABOVE the leg lines (a failed design turn still emits `leg.awaiting_user`, so
"Design is ready for your next message." was reading as the headline).

**Design-lane observation (not this slice's):** the iteration turn failed because the agent
said it could not target the hero headline node on a generated page ("the live document
exposes only the hero section container, not its headline node"). That is the founder's own
slice-4 script line ("make the hero darker"), so the design lane's node addressing deserves a
look before the acceptance walk.

**Founder directive received at the end of the session:** pause all browser work and stack
relaunching — `g7` owns the browser/dev servers and is diagnosing `tailwind_runtime_missing`.
The walk had already completed; nothing browser-shaped was done after it. The stack (8010,
8030, istanbul fleet worker) was LEFT RUNNING for g7. Data point for that investigation: in
this walk the committed page **did** render with layout in the EDITOR canvas (which loads
`/vendor/tailwind-browser.js`, W1.4) — the missing-runtime reports come from the fleet-side
preview renders, a different renderer, as slice 2 also recorded.
