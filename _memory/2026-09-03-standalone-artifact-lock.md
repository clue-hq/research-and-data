# 2026-09-03 — Standalone artifact route honours the editor lock

Closes the finding in `_memory/2026-09-03-agent-working-chip.md`: `/projects/{p}/artifacts/{id}`
rendered `ArtifactStage` via `editor-surface.tsx` with no lock at all (live Edit pill, no chip,
only the server's 409s during a run). Founder: "treat it as the missing half of the
no-mid-run-editing rule" → done. Plan: `docs/superpowers/plans/2026-09-03-standalone-artifact-lock.md`.

## What shipped
- Design API `GET /documents/{document_id}/agent-run` (commit b1dc94481) →
  `{schema_version, document_id, active, run_id, current_version}`, built on
  `repo.active_design_run_for_document` — the SAME predicate the manual-write 409 uses — plus
  the document's version. 404 for an unknown document. Live: `{"active":false,…,"current_version":131}`.
- Frontend (commits 45ffcb705 + 4edf07a74): `data/document-agent-run.ts` (zod read),
  `hooks/document-agent-run.logic.ts` (pure reducer: reload nonce bumps iff `current_version`
  moved since the previous read; first read is a baseline), `hooks/use-document-agent-run.ts`
  (4 s poll while enabled + tab visible; first poll immediately; failed poll keeps the last
  answer; state stamped per document and DERIVED against the current one — the repo's idiom,
  because `react-hooks/set-state-in-effect` fails the gate on a `setState` reset in an effect).
  `editor-surface.tsx` now passes `agentRunLocked`, `inspectorDisabled`, `sceneGestureDisabled`,
  `onSceneLockedEdit`, `editDisabled`/`editDisabledReason`, and adds the poll's nonce to
  `canvasReloadToken`; the three "deliberately NOT passed" comments were replaced.

## Rulings
- R1 source of truth = the run row (backend enforcement boundary), not the platform thread's leg
  state; the seconds between turn-accepted and run-claimed stay unlocked here (a write in that
  window is read by the run when it starts, not lost). R2 poll (4 s, visible tab), not SSE.
  R3 version moves bump the reload token — the standalone page gets checkpoint refreshes too.
- Fix round 1: `onSceneLockedEdit` (a refused gesture speaks the lock's sentence) was missing
  from my plan; wired for parity with the chat route.

## Verified
- API: 4/4 new + write-lock 9/9 first-hand. Frontend: 5/5 new; chat-shell + design-editor 2190
  pass; gate green.
- LIVE: design turn on the Apollo thread; the artifact URL opened DIRECTLY during the run →
  Edit `[disabled]` with title = the ratified lock sentence, `[status] Designing. Please wait to
  edit.`, agent-run polled; after the run succeeded → Edit enabled, chip gone, version 131→132,
  the page refetched the document itself and shows the run's change (smaller headline).

## Hygiene incident (again)
This session's API suites left 19 `ws_test_*` design jobs in the shared fleet queue; colombo's
worker was executing them (real model calls on runs whose rows were gone) and my real turn sat
"Queued". Failed those tasks/runs and restarted the worker. The disposable-test-DSN ruling is
still the founder's open item; until then, never run the design API suites while a real turn
is wanted on the same DSN.
