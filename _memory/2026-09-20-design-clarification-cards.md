# 2026-09-20 — Design clarification cards (points 3 + 4; SDD on `project-home`)

Spec `docs/superpowers/specs/2026-09-20-design-clarification-cards-design.md`; plan
`docs/superpowers/plans/2026-09-20-design-clarification-cards.md`; ledger
`.superpowers/sdd/2026-09-20-design-clarification-cards/progress.md`. Opus implementers; every
review the controller's own. Founder rulings: opening-move only (the runtime never asks
mid-design); on a batch only the asking document gets a card, finished siblings show their summary
lines, nothing waits; "Something else" always present; house `--clue-ds-*` tokens only.

## What shipped (commits after 3c4633210)
- `d96439cb6` T1 — `PartKind.CLARIFICATION`, `ClarificationQuestion`/`ClarificationPart`
  (`clarification:<document_id>`), `TurnStreamEmitter.emit_clarification_part`, migration
  `fc9580642b71` (the `agent_turn_event_stream_part_kind` CHECK admits `clarification`; downgrade
  is dev-only-reversible and says so).
- `94b56cbc8` T2 — `clarification_sentence(result)` → "Asked you N question(s) before designing:
  q1; q2." (before the design branches of `_assistant_summary`; batch lines use it);
  `design_runs.latest_terminal_run_for_document` (the derived "open question").
- `bd6b011ab` + `be93cfb47` T3 — the leg runner emits one part per asking document BEFORE the
  rehydrate frame, each under its own guard (`design_leg.clarification_emit_failed`), the card's
  account name resolved from the document's `account_id` for scene ads; the one-round guard
  (`previous_turn_outcome`) is derived PER DOCUMENT on the scene request from the latest terminal
  run — the client echoes nothing; the exit judge's artifact line gains `[asked: "…" | "…"]` and
  the prompt (v3 → v4) says an answer to an asked question is work on THAT artifact.
- `6be5b026c` T4 — client: the part parsed (`account_name` absent → null), `openClarification`
  (last transcript message = settled assistant with clarification parts), `composeClarificationReply`
  (exact text format; unanswered questions and answerless documents omitted; one
  `design_document` ref per answered document).
- `a613395f4` + `638d3498c` T5 — `ClarificationCard` above the composer (header `<title> ·
  <account>`, pager, why-line, numbered options with ↑↓/digits/Enter/Esc, Something-else row,
  `Skip — use <default>`, collapse chip, strip for >1 documents, hint line; the last answer sends
  one message through `chat.submitMessage(text, {contextRefs})`); `ClarificationHistoryCard`
  inline for older turns; the asking turn's inline record is suppressed while the card is up
  (`ChatPartActions.openClarificationTurnId`). Stylesheet: 16 `--clue-ds-*` tokens, no hex,
  tokens test green.

## Verified first-hand
Every task's diff read; per-task tests re-run by the controller (T1 36, T2 53, T3 90, T4 70,
T5 9 + eslint + tsc filter); full frontend `npm test` 3219/3220 (1 pre-existing skip); migration
applied/downgraded/re-applied (head fc9580642b71); platform APIs + fleet workers restarted on
638d3498c, stack all UP, worker logs clean.

## Owed — founder-triggered live proof
A deliberately under-specified ad brief → the run stops to ask → the transcript shows "Asked you
N questions before designing: …" and the card appears above the composer; answering sends the
composed message with the document ref; the next run designs from the answers (its request
carries `previous_turn_outcome=clarification_requested`); on a batch only the asking document
gets a card. Reload while the card is up → the card returns.

## Residuals / deferred minors
- Web documents: `WebTurnRequest` has no `previous_turn_outcome`, so a web run that asked could
  ask again next turn (the web runtime has no clarification today).
- A FAILED answering run becomes the latest terminal run and disarms the guard (one more ask
  possible; the runtime's own one-round-per-turn rule still bounds it).
- The per-document reads on `payload->>'document_id'` are unindexed (batches ≤ 24); an index if
  legs ever grow.
- No DOM test covers the card's keyboard flow / pager / collapse — live walk owed.
- The card's collapse is component-local (a reload reopens it).
- Other lanes: `alembic upgrade head` (c937a6b69e8a, fc9580642b71) before running this branch.
