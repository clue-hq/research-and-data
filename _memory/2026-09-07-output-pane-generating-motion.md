# 2026-09-07 — website "agent is generating" motion (cofounder handoff ad4f30bb)

Source: orphan branch `handoff/output-pane-generating-motion` on clue-hq/research-and-data, commit
ad4f30bb (Shashank, approved 2026-09-04). Founder scope: WEBSITE veil + edge glow only; the ad lock is
NOT integrated ("don't add the ad lock at all for now").

Landed (design/website): f69ae9386 (integration) + 52b30bcf8 (host moved up). Files under
`apps/frontend/src/features/design-editor/components/generating/` are byte-identical to the delivery
(the cofounder's dummy is presentation truth); only `index.ts` differs (no ad-lock export).

Wiring: `chat-surface.tsx` passes `generating={chat.threadBusy && chat.designLegOpen}` to
`ArtifactStage`; the stage hosts `clue-gen-host` + veil + glow on the "Web output canvas" wrapper (so
the motion exists with or without a document and inherits the pinned Tablet/Mobile 2px radius);
`WebArtifactCanvas` reports its render kind up via `onRenderKindChange`. Hold rule (pure, 12 tests,
`adapter/generating-veil.ts`): active from generating-start; on generating-end lift immediately if
neither the reload token nor the document changed, else stay until the render is no longer loading —
"the blur never lifts onto a stale page". `editor-surface.tsx` passes nothing (no turn stream).

Verified by the controller: at rest in the live pane the veil is mounted, inactive, pointer-events
none; forced active (DOM toggle) it renders "Building your landing page" over the blurred page.
NOT verified: a real design turn (the founder's walk — handover "done when" #1 and reduce-motion).

Parked: before a FIRST landing page's document is born the pane is on the Gallery surface, so no
motion until the born document auto-opens (F2(b)); blurring the Gallery is a presentation call.
Dev-env finding fixed on the way: Slice 2's migration 4cbfa56e52a8 was never applied to
`clue_istanbul_dev` (thread pages 500'd on `turns?include=submission_bodies`); applied with the
stack's DSN. `.env`'s CLUE_DATABASE_URL names `clue`, not the stack's DB — mind that for migrations.
