# Phase 4c — agent edits on human-owned geometry (+ 4c-B toggle batch)

Session: 2026-07-05 (second half; 4c-A shipped earlier as 1fe3622).
User ack for this batch: "proceed with the 4c-B+ batch — the per-document
handoff toggle, plus the pinned-p() page-space semantics flip and the
best-draft-wins loop fix."

## Commits (this batch)

| Commit | What |
|---|---|
| 641e4d9 | chore: leftovers from previous session (4c re-scope plan note, export fmt churn, stale root screenshots) |
| ca9ae71 | feat(engine): p() on pinned targets is page-space |
| 96c3207 | fix(agent): budget exhaustion proposes the least-severe draft |
| 698b5ec | feat(editor+api): per-document layout-managed-editing toggle (4c-B) |
| 33373a3 | fix(assets): pre-existing providers_contract compile break (Slice-0 fields) |

## 1. Pinned p() page-space flip (ca9ae71)

4c-A lowered `p()/s()` on pinned targets to `absolute_box`, translating
parent-relative → page-space via `pinned_origin()`. run_8e7b9f64 falsified
the frame choice immediately: the model wrote artboard coordinates on both
attempts (p(80,872)-style), matching what the brief/inspector display
(`absolute_box` is page-space) — parent-relative lowering put the badge
88pt off, then off-canvas.

- `dsl.rs`: `DslProperty::Position` on a pinned target now writes
  `absolute_box.x/y` verbatim. `pinned_origin()` deleted; **LUMD0918 no
  longer exists** (page-space reads nothing from the parent, so pinned
  moves compile even with no solved parent geometry — that test flipped
  from asserting the error to asserting success). LUMD0919 (fixed sizes
  only) unchanged. s() unchanged (sizes are frame-independent).
- Frame rule (now stated in the agent brief, prompts.py FREEHAND/PINNED
  block): **p() speaks the frame the brief shows that node's geometry
  in** — page space for pinned `absolute_box` nodes, parent-local for
  everything else, including NEW children inserted into Free containers
  (they get transforms, container-relative). Frozen children keep
  container-relative transforms (only human-dragged nodes are pinned), so
  the asymmetry is exactly the one the model already sees in its brief.
- Brief reword also landed: "leave pinned where the human put it, move
  ONLY when the user asks; p()/s() work when they do."
- Tests: dsl_compiler 84/84; the two coordinate tests updated to
  page-space expectations; page-parent test unchanged (was already
  page-space by construction).

## 2. Best-draft-wins (96c3207)

Finding B of the retest, but the mechanism was subtler than
"last-draft-wins": `_consider_best` already ranked drafts — the rank tuple
`(preflight_clean, accepted, -issue_count, confidence)` tie-broke on RAW
critic confidence. From the actual run_8e7b9f64 trace: iter1 (badge
visible) rejected with [error(overflow), warning(spacing)] conf 0.86;
iter2 (badge off-canvas) rejected with [blocker(clipping),
error(request_satisfaction)] conf 0.90. Both preflight-clean, both
rejected, both 2 issues → confidence decided → the loop proposed the
draft the critic was MORE certain was bad.

Fix (loop.py):
- `_ISSUE_SEVERITY_PENALTY`: blocker 10 / error 3 / warning 1 / info 0 —
  severity-weighted penalty replaces raw count.
- Confidence is verdict-signed: `confidence if accepted else -confidence`.
- Either change alone fixes the run; both are principled (penalty = how
  bad, confidence = how sure; certainty-of-badness must rank DOWN).
- Regression test `test_budget_exhaustion_returns_least_severe_draft_not_
  the_last` replays the exact shape. TRAP FOUND WRITING IT: the first
  version passed on the OLD code too — the iter-2 repair block referenced
  a node absent from the fake scene, the layout-cluster gate zero-applied
  it, iteration 2 never reached the critic, and exhaustion trivially
  returned iter 1. The committed test targets the in-scene node and
  asserts `len(reviewer.calls) == 2` to guard the vacuous pass. Verified
  red-on-old / green-on-new via stash round-trip.
- Runtime suite 129 → 130. (Suite needs `PYTHONPATH=$PWD:$PWD/../api`
  from apps/agent_runtime with the repo-root .venv.)

## 3. 4c-B per-document layout-managed-editing toggle (698b5ec)

Design decided with user: handoff-absolute stays the DEFAULT; the opt-out
is per-document, advanced, and the rollout safety valve.

- Persistence: `documents.layout_managed_editing INTEGER` via
  ensure_column + `PUT /documents/{id}/layout-managed-editing`
  `{"enabled": bool}`, mirroring agent_instructions; GET returns the flag
  (NULL→false for legacy rows). NOT in the scene schema — editor policy,
  invisible to engine + agent runtime.
- Both freeze seams gated on the flag:
  - Accept seam: `useAgentTurn.acceptAgentPreview` skips the freeze +
    merge entirely (turn ops commit verbatim, Stack containers stay live).
  - Gesture seam: `CanvasKitCanvas` pointer-down skips the
    `isNodeFreezableOnGesture` freeze.
- One-way: enabling never un-freezes already-Free containers; disabling
  re-freezes at the next seam. No undo integration (document setting,
  outside the ops stream).
- UI: checkbox in DocumentPageSection Document section (`toggle-field`
  idiom from SlotInspector) + muted hint. New `useLayoutManagedEditing`
  hook: immediate persist per change; on a fresh canvas the value stays
  local and auto-persists when the first Accept mints the document id
  (same contract as standing instructions).
- Editor suite 535 → 544, API suite 79 → 80, zero new failures.

## Verification

- All 58 cargo workspace suites green (after fixing the PRE-EXISTING
  lumen-assets providers_contract compile break, 33373a3 — Slice-0 added
  constraint fields without updating the explicit test initializer).
- Stack realigned at 33373a3 through dev-setup.sh (prepare + backend —
  the env-loading path; LUMEN_AGENT_API_KEY verified in process env,
  handshake + served-WASM-bytes verified identical). NOTE: a test-only
  commit still shifts engine_commit — helper reports git HEAD — so ANY
  commit needs a prepare+restart to keep the handshake clean.
- Browser e2e (opus agent): badge replay on the real doc (page-space
  proof: DSL p(x,y) must equal landing coordinates) + fresh-doc toggle
  scenario (accept-seam skip with live Stack containers, first-gesture
  freeze after toggling back off). Verdict recorded in
  .context/phase4c/e2e/ when it lands.

## Process notes

- The 4c-B subagent's first run delegated to a background child of its
  own and idled; the child kept working the same brief in parallel after
  I resumed the parent. Both converged on the same files; the child
  deduplicated the overlapping test additions before commit. Lesson: when
  resuming a completed/stalled agent, check whether it left live children
  on the same working tree.

## Open next (needs user's word)

- 4c-C managed gestures in advanced mode: strict reorder-within-container
  v1; pull-out-to-detach as fast-follow.
- Recorded riders: stale "Layout-managed" inspector copy post-freeze;
  preflight only warns on fully-off-artboard nodes; LUMD0918/0919 not in
  the agent diagnostics doc (0918 now deleted).
