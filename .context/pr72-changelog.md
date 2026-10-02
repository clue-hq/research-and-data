## Summary

One chat message can now produce many design artifacts at once, a design session starts generating the moment it opens, a design agent's opening questions reach the user as a card above the composer, and a manual edit no longer throws the editor out of edit mode. Thirty-nine code commits on top of `research-streaming`; 129 code files, +14,339/−749 (plus the re-minted manual chapters, the real-ad fixtures and a rebuilt wasm); three migrations (`b9c5e4829868`, `c937a6b69e8a`, `fc9580642b71`); no new env key. Other lanes: `alembic upgrade head` before running this branch.

## Changelog

### Multi-artifact design legs (spec `2026-09-19-multi-artifact-design-legs-design.md`)

- One open leg holds a SET of documents: new table `design_leg_document` (position 0 = `design_leg.document_id`, so every single-document reader is unchanged).
- `open_design_leg@5` takes `artifacts: [{title, note, account_id?}]` and births N documents in one transaction; a born ad for a tagged account is stamped through a resolve-or-create `design_account`. Head-of-ABM `v58`, prompt `v11`, recipe0-stage0 `@29`, manual `v5`.
- The leg turn fans out one design run per addressed document plus N `design_job` fleet tasks, so free slots on every design-capable worker take siblings; `InlineDesignLaneDriver.drive_batch` drives what nobody holds and waits only on a live foreign lease. One hand-back with a per-document summary; Stop cancels every run of the batch.
- Exit judgment `v3`: on a many-document leg the judge answers WHICH documents a message addresses (`addressed_artifacts`) or asks one question (`clarifying_question`); the multi-document fail-safe asks, never fans out. Six new golden fixtures.
- Composer tags validate against the leg's document set; the gallery and library derive from the set; the feed carries the account; the chat surface opens a tab per born document; gallery cards show the account's Brandfetch logo mark.

### Batch hand-back and containment

- A batch's runs number their model-call receipts after one another on the one turn (the first live batch collided on `(turn_id, sequence)` and crashed the hand-back); a one-run turn is byte-identical.
- Crash containment hands a `running` leg back with its `leg.awaiting_user` frame, so a crash past `mark_leg_running` no longer strands the thread.

### Freeze-bake fill parity (design engine)

- Ruling C-9 (freeze-on-grab) stands; the bake now keeps exactly the extents the Stack solve gave a node: a container's own `fill` bakes to `fixed`, a text child's `hug` width bakes, its `hug` height survives. Free-mode `fill` resolves against the padded content box. Pill rows no longer snap to the artboard edge on the first click.
- Pinned by nine new `freehand_ops` cases, `tests/freeze_real_ads.rs` over three real ads (fixtures recovered from their inverse batches by `scripts/design_prefreeze_scene.py`), the same three at the wasm seam, and a canvas-side `[freeze]` console error if a freeze ever moves a node. Vendored wasm rebuilt.

### Derived design turns (spec `2026-09-20-derived-design-turns-design.md`)

- `agent_turn_submission.derivation` / `derived_from_turn_id` mark a submission the server made from the user's own bytes: the leg's out-of-scope redelivery, and the leg's FIRST turn, which `open_design_leg` now queues itself (key `design-leg-first-turn:<leg>:<turn>`) — nobody says "go". The leg runner skips the exit judge for it and addresses every document.
- The turn list carries `derivation`; the transcript renders no user bubble for a derived turn (its durable user row stays — role-scoped history needs it). A closed-and-routed message no longer shows twice.
- Head-of-ABM `v59` / prompt `v12` ("opening a leg starts generation at once"); manual re-minted at `v6`.

### Design clarification cards (spec `2026-09-20-design-clarification-cards-design.md`)

- A run that ends `clarification_requested` (the runtime's opening-move `request_clarification`, never mid-design) rides the leg turn as a `clarification` transcript part per asking document (emitted after the reset frame so the client keeps it), and reads honestly in the summary: "Asked you N questions before designing: …".
- The card above the composer (house `--clue-ds-*` tokens only): document · account header, a pager over the questions, the why-line, numbered options with keyboard navigation, an always-present "Something else…" row, a "Skip" that applies the runtime's default. Several asking documents queue under a "N designs have questions" strip. Answers go out as ONE ordinary message with a `design_document` context ref per document; older turns render read-only.
- The exit judge sees `[asked: …]` on that artifact's line (exit prompt `v4`) and the one-round guard is derived per document from the latest terminal run — the client echoes nothing.

### Chat shell

- A person's own edit never re-opens the active tab or drops edit mode (the feed refresh carrying their own write used to reset the shell and reload the conversation).

### Records

- Specs, plans and SDD ledgers for each slice; `_memory` notes with rulings, owed live proofs and residuals; CLAUDE.md `[design×legs]` / `[design×freeze]` bullets.
