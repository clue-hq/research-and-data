# 2026-08-22 — AD4.E: action menu + multi-select closure (Lane E, ndjamena worktree)

Branch `integration/frontend-design-part-iv-v7`, commits `c9850b79` + `e2191d2f` on the attested
AD4.R base `c22f3ef9` (base attestation held: HEAD + marker files + 1754/1754 — the initial 1738
was exactly the 16 wasm-artifact-gated tests; fixed by vendoring the built `lumen_wasm` artifacts
from the colombo worktree into `subsystems/clue-design/apps/editor/public/wasm/`). Regime: Opus
implementer → Opus task review → controller verification + write-free browser proof. Ledger (now
the record here): `.superpowers/sdd/2026-08-20-ad-editor-integration-execution-plan/progress.md`
during the session. Suite 1754 → **1763** (+9), lint 0 errors, build clean. Nothing pushed.

## What AD4.E turned out to be

A **closure task** — every §1.12/§1.7/§1.8 requirement was already correctly wired by AD3.3 /
AD2.6-2.7 / the kind-agnostic shell. The deliverables were verification citations + covering
tests. The ONLY production change: the `clue:artifact-action-request` listener's decision extracted
to pure `adActionRequest(detail): "undo"|"redo"|null` (use-scene-inspector-writes.ts, behavior-
identical, spot-checked by controller). New tests: 4 (pure decision: kind guard, §7 actions
refused, malformed detail), 3 (Versions inert guard pair in artifact-actions.test.ts: repo-walk
proves `clue:artifact-version-select` has NO listener anywhere + presence pin on the four rows +
single-click-behaviour pin), 2 (layers additive-modifier + whole-set-highlight source pins,
merged-panel negative — scene-session.test.ts).

## Key rulings (full list with costs in the session close-out message)

- **R2:** "provable-inert" = document-inert per contract §3; the version rows KEEP their lifted
  onClick/local radio (dummy parity). The plan's "no event listener attached" is satisfied
  precisely: the dispatched event has zero listeners repo-wide, guard-pinned. The fast-follow that
  binds real history will TRIP this guard deliberately — rewrite it consciously, it is not a flake.
- **R3:** artifact-rename persistence is OUT of scope — the tab-rename seam is client reducer
  state (`use-editor-shell-controller.ts` rename-artifact case); a reload restores the server
  title. §7 platform-semantics family. **Founder-visible residual.**
- **R5:** "Arrange consumes the set" is Lane B's (AD4.B step 4). AD4.E verified the surface Lane B
  consumes: `selectedIds` additive, `[0]`-primary. ArrangeControls still dispatches the dead
  `clue:inspector-action` with no node ids.
- **R9:** lane-level final review = the task review (identical 2-commit range); AD5.1 + the
  lanes-merge review are the phase-level nets.

## Browser proof (write-free by design — parallel lanes B/C/D own the seeded docs' mutations)

Own dev server on **:3030** from THIS worktree (3035 failed: backend `CLUE_AUTH_CLERK_
AUTHORIZED_PARTIES` allows only 3020/3030/3033 — azp mismatch → session_expired loop; 3030 is in
the allowlist). Login: the recorded Clerk test user + 424242, then /session/establish →
select-workspace. Chats route, seeded `doc_ad22linkedinsquare00000000001`: §1.12 menu rows exact;
Redo [disabled] at redo-depth 0 while Undo enabled at 138 (live depth wiring); Versions click →
ZERO network calls, document byte-identical v162/138/0; Rename → header+tab update, reload
restores server title; multi-select: accumulate keeps FIRST-selected schema, primary-removal
promotes next (image schema appeared). Zero editor-era console errors. Server stopped after.

## For the lanes-merge / AD5.1

- Deferred minors (7, all guard-robustness polish) live in the session close-out + were triaged
  none-blocking: versions-slice end anchor implicit; dispatcher exempted by basename; walk root
  `src/` only; bare-"Mixed" scan false-fail-prone; opaque index arithmetic in the layers pin;
  LayersControls slice lacks both-anchor assert; cross-feature disk read.
- Reviewer ⚠️ worth knowing: §1.8 first-selected derivation (`use-scene-editing-session.ts`
  `primaryNodeId = selectedIds[0]`) is deliberately UNPINNED (would false-fail lanes actively
  editing that file); it is the most-likely-to-silently-regress spot — Lane B's Arrange tests and
  AD5.1's walk are the nets.
- `use-scene-editing-session.ts` is source-text-PINNED by scene-image-ai.test.ts:581 — lanes
  editing it must run the guard-pin grep first (AD4.R protocol).
- Duplicate/Archive/Delete still dispatch into the void (§7, unchanged, by contract).
