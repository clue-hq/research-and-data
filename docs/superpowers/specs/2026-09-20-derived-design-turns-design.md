# Derived design turns: no repeated message, no "go"

**Date:** 2026-09-20 · **Branch:** `project-home` · **Status:** founder-approved in chat (2026-09-20)

## 1. The two things that are wrong today

1. **The user's message shows twice when the exit judge closes a leg and routes it on.** The leg
   turn writes the user's message into the transcript as a user row; the judge closes the leg and
   writes a closing summary as that turn's assistant message; the close tool re-submits the same
   message bytes as a fresh turn for Head-of-ABM under the idempotency key
   `design-leg-redelivery:<leg>:<turn>`; the Head-of-ABM runner appends the same user row again.
   The turn list also serves each submission's body as `submission_message`, so even without the
   second history row the client would render the message twice. Verified on thread
   `thr_91f106db…`: turns `96f3e94d…` and `821ea746…` both carry a user row with body sha
   `e6a4abd5c5bd…`, one second apart.
2. **The user has to say "go" after a design session opens.** Head-of-ABM prompt v11 mandates it
   ("Opening a leg starts nothing: the user's next message begins generation"); `open_design_leg@5`
   births the documents, leaves the leg `open_awaiting_user`, and nothing dispatches a design turn.
   The user's next message is routed to the leg runner, passes the exit judge, then fans out.

## 2. Design

### 2.1 One mechanism: the derived turn

A **derived turn** is a submission the server creates from a user's own message bytes. There are
two kinds today, and the machinery does not care which:

| `derivation` | created by | from |
| --- | --- | --- |
| `design_leg_redelivery` | `finish_design_leg` (out-of-scope close) | the leg turn that closed |
| `design_leg_first_turn` | `open_design_leg` (fresh open **and** reopen) | the Head-of-ABM turn that opened |

Two nullable columns on `agent_turn_submission`, written together or not at all:

- `derivation text` — one of the two values above (CHECK-constrained);
- `derived_from_turn_id uuid` — the turn whose message bytes this submission carries.

A column, not idempotency-key sniffing: the key is an identity, the column is a fact readers can
rely on. The append-only trigger on the table is untouched (the columns are set at INSERT).

### 2.2 What a derived turn does NOT do

- **No user bubble.** The turn list (`GET …/turns`) carries `derivation` on each turn; the
  transcript composer renders no user message for a derived turn — not its durable user row, not
  `submission_message`, not an optimistic one — while its assistant message, leg notices and
  lifecycle state render exactly as before.
- **The durable user row STAYS** (ruling 2026-09-20, after Task 2's first cut). Both runners keep
  appending `uuid5(turn_id, "user")` for a derived turn exactly as before. The history loaders
  are role-scoped by turn (`load_head_of_abm_history` excludes design turns; the leg loader
  includes only its own leg's design turns), so the user's message under the leg turn is
  invisible to Head-of-ABM and the message under the Head-of-ABM turn is invisible to the leg.
  Dropping the derived turn's row would leave each role's later history with an answer and no
  question before it. The repetition is a DISPLAY fact, fixed at the display.

### 2.3 The first design turn

`open_design_leg`, in the same transaction that opens (or reopens) the leg and after the
`leg.opened` / `leg.reopened` frame:

1. reads the opening turn's own submission (`get_submission`); a turn with no submission (a
   machine-originated turn) queues nothing, logs `design_leg.first_turn_skipped_no_submission`,
   and the leg stays awaiting the user exactly as today;
2. inserts a derived submission: idempotency key `design-leg-first-turn:<leg_id>:<opening turn_id>`
   (so a replayed open and a reopen from a later turn each converge on ONE submission), the
   opening submission's message artifact key + sha, submitter, membership, onboarding input and
   context refs, `derivation = design_leg_first_turn`, `derived_from_turn_id = <opening turn_id>`;
3. calls `dispatch_next_thread_turn` — a no-op while the opening turn's own task is in flight; the
   worker offers the next turn when that task finishes, exactly as the redelivery does.

The tool's references are UNCHANGED (ruling 2026-09-20: the profile pins the output model's schema digest, so a new reference would force `@6` + recipe 30 + a manual re-mint for a value the agent never reads). The tool logs `design_leg.first_turn_queued` with the derived turn id; the derived id is recomputable from the key.

The leg runner, on a submission whose `derivation == "design_leg_first_turn"`:

- does **not** run the exit judge (there is nothing to judge — no user has spoken on the leg yet)
  and addresses **every** document of the leg;
- everything else is the shipped path: `mark_leg_running`, the batch dispatch (one run per
  document, N fleet tasks when N > 1), receipts, the per-document summary, hand-back, Stop.

The design agent's prompt for that turn is the user's real message rather than "go".

### 2.4 Catalog and copy

- Prompt `head-of-abm` v11 → **v12**: the one sentence "Opening a leg starts nothing: the user's
  next message begins generation, and every artifact generates at the same time, for minutes. Say
  the design session is open, name what will be made, and end your turn." becomes "Opening a leg
  starts generation at once: every artifact generates at the same time, for minutes, and the user
  need not say anything to begin. Say the design session is open and what is being made, and end
  your turn." Nothing else in the prompt moves.
- Profile `head-of-abm` v58 → **v59**: v58's surface exactly, prompt pin v12. No tool address
  moves, so the conversation recipe stays at 29. The manual re-mints at `manual-*@v6` (ruling
  2026-09-20, the v57 precedent): the generated chapters render the profile version into their
  title, so a profile bump cannot leave them at v5 — bodies byte-identical, one header line
  moves. The registry default and every test that pins the active version move to v59.
- Frontend notices: `leg.opened` → "Design session opened — generating now."; `leg.reopened` →
  "Design session reopened — generating now."; `leg.awaiting_user` unchanged.

## 3. Not in scope

- The closing summary stays an assistant bubble; the exit judge's reasoning stays internal (it
  already is).
- Per-document clarification questions and routing a reply to the asking document (points 3 and
  4 of the 2026-09-20 discussion) — a separate spec after this lands.
- Attachments on derived turns: the redelivery never copied them and the leg turn path carries no
  `attachment_refs` (recorded residual); the first turn copies context refs only, like the
  redelivery.

## 4. Acceptance

1. A closed-and-routed message renders ONCE in the transcript, followed by the closing summary and
   Head-of-ABM's answer; `agent_thread_message` still holds a user row per turn (role-scoped
   history), and the derived turn's row is what the transcript hides.
2. Opening a leg with N artifacts starts N design runs with no further message; the transcript
   shows the user's ask once, the leg notice "generating now", then the per-document summary.
3. A replayed open (same turn, same inputs) creates no second first-turn submission.
4. A derived turn can be stopped like any other; a derived turn's failure or crash hands the leg
   back (the containment shipped 2026-09-20).
5. `alembic upgrade head` on every lane DB that runs this branch (san-salvador done as part of
   the plan; others when they pull).
