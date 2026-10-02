# 2026-09-04 — Scene-ad agent-working motion ported from the co-founder's handoff

Plan: `docs/superpowers/plans/2026-09-04-scene-ad-generating-motion.md`. Source: branch
`handoff/output-pane-generating-motion` (orphan; `HANDOVER.md`, approved by Shashank 2026-09-04),
fetched as `origin/handoff/output-pane-generating-motion`. Commit `dfffcd4c4` (one Opus task, reviewed
and re-run first-hand by the controller). Founder's instruction: port ONLY the scene-ad pieces — the
lock + chip (Clue-mark spinner, shimmering copy) and the edge glow — and retire the top-left
"Designing. Please wait to edit." chip. The website veil is NOT ported.

## What changed
- New `apps/frontend/src/features/design-editor/components/generating/`: `clue-mark.tsx`,
  `generating-glow.tsx`, `ad-designing-lock.tsx` (byte-identical to the handoff), `generating.css`
  (handoff minus the veil section; z-index raised to glow 42 / lock 43 so both clear the scene
  canvas's banners (40) and caret textarea (41); the shared `clue-gen-shimmer` keyframe moved next to
  its only remaining consumer), `index.ts`, `scene-agent-motion.ts` (`sceneAgentMotionActive` — the
  old chip's rule: only while the lock holds AND over a real scene), `generating.test.ts` (4).
- `artifact-stage.tsx`: imports the global stylesheet, mounts `<AdDesigningLock>` + `<GeneratingGlow>`
  as siblings after `SceneArtifactCanvas` inside `.sceneStage` (now also `clue-gen-host`), driven by a
  new `agentWorking?: boolean` prop. `chat-surface.tsx` passes `agentWorking={sceneLocked}` — the
  CANVAS lock, not the Edit pill's `editDisabled` (which is false while already editing). The
  standalone artifact route (`editor-surface.tsx`) has no turn stream and passes nothing, same as the
  old chip never showed there.
- Deleted: `agent-working-chip.tsx`, `.logic.ts`, `.test.ts` and the `agentWorking*` CSS block.
- Copy: the handoff's approved "Agent is designing. Please wait." supersedes the founder's 2026-09-03
  chip wording (the `label` prop can change it in one place).
- Behaviour accepted from the handoff: while active the lock shields ALL canvas pointer input (a click
  selects nothing, wheel zoom/pan is swallowed) with `cursor: progress`; the canvas's own
  `onLockedEdit` notice therefore no longer fires during a run — the chip is the explanation.

## Gates
- `generating.test.ts` 4/4; `npm run lint` 0 errors (2 pre-existing warnings); `npm test` 2699 pass,
  1 pre-existing skip; `npm run design-system:build` + `npm run build` green (the global CSS import
  from a component file is fine under Next 16; `clue-gen-lock` present in the built CSS).

## Live proof (colombo, Apollo thread `thr_fccf1ba1…`, doc `doc_cf05190c…`, 16:31 IST)
- Sent "Change the CTA label to: Read Ramp's story" in the project chat; the design turn ran; the
  Apollo ad open in the artifact panel showed the chip top-left (spinner + shimmer) and the edge glow
  (`motion-02-lock-and-glow.png`); `.clue-gen-lock` z-index 43 on top; `elementFromPoint` mid-canvas
  = the lock, cursor `progress`; a synthetic click there selected nothing; the Edit pill was disabled;
  no trace of the old chip class.
- Reduced motion (CDP `prefers-reduced-motion: reduce`): spinner, glow and shimmer animations `none`,
  lock still `data-active="true"` (`motion-03-reduced-motion.png`).
- Release on the terminal frame: the run succeeded at 16:37:36 IST (turn `awaiting_input` at
  11:07:24 UTC); within seconds `.clue-gen-lock`/`.clue-gen-glow` read `data-active="false"`, the lock's
  computed opacity was 0, the Edit pill re-enabled, and the ad showed the new CTA "Read Ramp's story"
  (`motion-04-after-turn.png`). The turn cost ~6 minutes.

## Notes
- The gallery's "Open …" buttons did not open the artifact from the browse tool's click; `button.click()`
  from page context did. Sessions expire (Clerk dev): re-login flow = Sign in again → Continue with
  email → OTP 424242 → workspace.
- `--clue-gen-muted` / `--clue-gen-teal-light` in `:root` are unreferenced after the trim (kept verbatim).
