# 2026-08-19 — Chat-flow editor integration, Slice 6: close-out. PLAN COMPLETE.

Branch: `integration/frontend-design-part-iv-v2` (istanbul). Plan:
`docs/superpowers/plans/2026-08-19-chat-flow-editor-integration.md` — **all six slices
done** (S1 `f7540b63`, S2 `f6d63cdc`, S3 `3957166a`, S4 `3ba169be`, S5 `95922696`,
S6 this commit). S1–S2 implemented in a Cursor session; S3–S5 via SDD (Opus implemented,
controller reviewed inline per the binding founder rule); S6 controller-inline
(doc recording is controller work). SDD ledger deleted at finish per the skill — the
rulings live here and in the per-slice notes.

## S6 deliverables

- **Phase-C plan R6 bullet** (`2026-08-17-phase-c-chat-chrome-adoption.md`): dated
  composer-stays clarification appended (dock replaces the TRANSCRIPT only; composer is
  structurally a sibling of `.chatBody`), plus the R6-went-LIVE record (slices 4–5).
- **Contract notes** (`apps/frontend/docs/api-contracts/projects.md`, new dated
  "Chat-flow editor integration — as built" section): the chats-route feed props
  (feed rides props, never the workspace schema), the pane-state write-back rules
  (resting = bare URL; `?surface=chat` inbound alias; `edit`/`selection` domains;
  `?artifact=` never emitted), the deep-link limitation + the OPEN founder decision on
  an artifact-identity param. Also superseded (dated strike) the stale "Artifact
  integration is not yet available → empty Gallery" line.
- **`.gitignore`**: `.artifacts/` (design-API runtime byproduct from live editor
  browser sessions) — the slice-4 deferred minor.
- **Plan doc**: STATUS COMPLETE header added.
- **Final review pass over S1–S2** (the Cursor-implemented diffs the controller had
  never reviewed): clean — proper server-only/testable split in the feed helpers,
  load-bearing tests (map direction pinned, both refusal postures), the hook extraction
  faithful with carried caveat comments; S3–S5 then exercised the hook hard on both
  mounts, the strongest validation of the refactor.

## Gates at close

- Frontend (all re-run this session): design-system:build ✓, **test 772/772**, lint ✓,
  production build ✓.
- **`make check`: 5 backend failures — pre-existing/environmental, NOT this plan's**
  (proven: `git diff 44a24088..HEAD` excluding apps/frontend//_memory/docs/.gitignore is
  EMPTY). Failure modes: 3× `tests/api/test_pilot_budget_controls.py` on
  `FieldRedefinitionError: field_key 'core.industry' already registered with a different
  definition` (shared dev-DB field-registry drift vs test seeds — the pilot-budget lane
  owns these; this workspace's Conductor target branch is
  `origin/platform/pilot-budget-controls`), 1× `tests/db/test_unified_agent_gate_migration.py`
  head assertion, 1× `tests/agents/test_o3_account_deep_behavior.py`. Code `alembic heads`
  shows a single head (`a1c5b9842f0e`). Whoever owns those lanes should triage against a
  CLEAN per-branch DB per the migration conventions.

## Rulings made across the plan (the exhaustive list; per-slice notes hold detail)

1. (S3) Rich-text canvas props ride slice 3 with `richTextEnabled` gated per-mount on
   the chat route's dock condition (W4.8a law).
2. (S4) Dock guard stays `editorVisible && kind==="web"` — narrowing to the
   document-aware gate would blank `.chatBody` for a document-less web tab.
3. (S4) Params/controller tests implemented via the pure-decisions idiom
   (`model/chat-dock.ts`) — the runner has no DOM harness.
4. (S4, adjudicated) Dismiss call sits BEFORE the accepted-status early return, guarded
   by the pure predicate over the full status union — semantically identical, keeps the
   tested decision load-bearing.
5. (S5) Resting state serializes to NO pane params; `?surface=chat` is the accepted
   inbound alias, canonicalized to the bare URL.
6. (S5) Only the chats route writes back; the artifact route's URL is its path.
7. (S5, adjudicated+confirmed) `?selection=` serializes the EFFECTIVE inspector schema
   (`session…schema.selection ?? shell.inspectorSelection`) — the brief's literal source
   is inert on real documents.
8. (S5, parked → founder) Deep links restore pane state, not the open artifact —
   R2-inherent (no artifact identity in the vocabulary; `?artifact=` forbidden).
   **OPEN founder decision** recorded in the contract doc.

## Deferred minors carried out of the plan (all recorded at their sites)

- Edit toggles +1 history entry WITH a canvas mounted — pre-existing srcdoc-iframe
  navigation (reproduces on the artifact route); candidate fix lives in canvas iframe
  mounting.
- One mount-time canonicalizing replace if inbound param order differs — harmless.
- `chat-dock.ts` type-only import from `features/projects/hooks` (drift-proof; invert if
  a boundary rule lands). `setEditing(false)` on every accepted send (one extra render).
- `chat-surface.tsx` predates-this-plan `prettier --check` failure (lint gate is
  eslint-only).
- R6's known cost (recorded in the Phase-C plan): a running turn's gate/Stop banner is
  invisible while the dock is open — founder owns revisiting.
- Ops: FOUR dead-server incidents on this branch's sessions (8030 thrice, 8010 once
  historically) — port-check-before-launch is mandatory and in every brief; servers
  left running at close (3030/8030/8010).

## Founder walkthrough (the acceptance choreography — run it yourself)

URL: `http://localhost:3030/projects/prj_79aa603b3c3853898045e3cfa414e136/chats/thr_4ef1f65aee39574e8290f60cf3b32a40`
(login: onboarding+clerk_test_20260814@example.com / pass@123 / code 424242).

1. Real conversation + composer at bottom; URL is bare.
2. Open artifact panel → Gallery (URL `?surface=gallery`) → click "Insight Health
   homepage" → live canvas in the rail (`?surface=web`).
3. **Edit** → the transcript is replaced by the real inspector (real layers, real theme
   swatches); the composer is still at the bottom, usable (`?surface=web&edit=1`).
4. Click the subheadline → text schema with real values (`&selection=text`); change
   Alignment → the canvas updates and the write persists (reload to confirm).
5. Type a message and send → **the dock dismisses, the conversation returns, your
   message posts** (URL drops `edit`/`selection`); Edit brings the dock back.
6. Empty message → Send is disabled; the dock stays (only an ACCEPTED send dismisses).
7. Copy an editing URL into a new tab → lands rail-open on the Gallery (pane state
   restored; the open artifact is NOT — the recorded limitation awaiting your ruling).
8. Browser Back leaves the page (pane toggles never grow history).

## Next (the queue after this plan)

W4.10 keyboard node-op audit (trunk, audit-only) → W4 exit gate (§1 live / §3 inert /
§2 absent) → W5 acceptance audit + founder sign-off. Independent: the brand-kit
worktree (`feature/brandkit-onboarding-integration`) and the founder decisions queue
(artifact-identity param; §8 register).
