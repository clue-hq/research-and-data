# Design clarification cards: a document's questions reach the user, and the answer reaches the document

**Date:** 2026-09-20 · **Branch:** `project-home` · **Status:** founder-approved shape (chat, 2026-09-20; the Claude.ai clarification card as the visual reference, "always a Something else block", house design tokens)

## 1. What exists and what is missing

The design runtime already asks. Its `request_clarification` tool (opening move only — before any
authoring, rendering or finalize spend; withheld on the turn after it was used) ends the run with
outcome `clarification_requested` and a payload of one to four questions, each
`{id, question, why_it_matters, options[], default, allow_freeform}`. The design API stores it on
the run as `result_json.status = "clarification_requested"` with `result_json.clarification.questions`
and a rendered `summary`; the run row's own status is `succeeded` (a real outcome with nothing to
commit).

None of it reaches the platform user:

- `_assistant_summary` has no branch for the outcome, so the leg's message would read
  "Design turn clarification_requested: clarification_requested" and the questions are dropped.
- Nothing on the platform side renders questions; the frontend never sends the
  `previous_turn_outcome` echo, so the runtime's one-round guard cannot work.
- On a multi-document leg the exit judge routes the reply with no knowledge that one document
  has an open question.
- No run in the lane database has ever ended in a clarification: the path is unexercised.

Founder rulings (2026-09-20): a question card appears ONLY for an opening-move clarification,
before any design spend on that document; the runtime does not ask mid-design and that stays. On
a batch where one document asks and the others finished, the finished ones show their summary
lines as today and only the asking one gets a card; nothing waits on the answer.

## 2. Design

### 2.1 The durable carrier: a `clarification` part

A new transcript part kind, `clarification`, emitted by the leg runner on the leg turn's stream
after the batch is terminal — one part per addressed document whose terminal run result has
`status == "clarification_requested"`, in position order, AFTER the `rehydrate` (stream.reset)
frame and before `turn_finished` — the client's reset handler clears a turn's parts, so a part
emitted ahead of it is dropped (found live 2026-09-20, fixed the same night).

Payload (`ClarificationPart`, `platform/api/clue_api/chat/turn_parts.py`; `PartKind.CLARIFICATION`;
the `agent_turn_event_stream_part_kind` CHECK gains `'clarification'` by migration):

| field | value |
| --- | --- |
| `part_id` | `clarification:<document_id>` |
| `document_id`, `document_title`, `doc_kind` | the leg document (title = the leg's stored title, "Untitled design" fallback) |
| `account_name` | the document's stamped account name, or `null` |
| `run_id` | the run that asked |
| `questions[]` | `{id, question, why_it_matters, options[], default, allow_freeform}` verbatim from the run result |

Why a part: it is the shape the transcript already renders live and replays on reload (a thread
visit re-attaches each recent turn's backlog from its first frame, which is how gate and plan
cards come back). Older turns fall back to the summary text (§2.2), which is the durable record.

### 2.2 Honest text for history and for the agents

`_assistant_summary` gains the branch: a result with `status == "clarification_requested"` renders
"Asked you N question(s) before designing: <q1 text>; <q2 text>." (engine-rendered, deterministic;
the question texts verbatim). `batch_summary` uses the same sentence on that document's line
("<title>: asked you 2 questions before designing: …"). This is what the leg's later history, the
exit judge's history, and the Head-of-ABM exit summary see.

### 2.3 "This document has an open question" is derived, never stored

A document has an open question when its latest terminal design run's result status is
`clarification_requested`. One DAL read, `latest_terminal_run_for_document(conn, workspace_id=,
document_id=)`, serves both consumers below. No new column.

### 2.4 The reply reaches the document that asked (point 4)

Routing stays the exit judge's judgement (founder ruling 2026-09-19). Two inputs improve it:

1. **The judge sees the open question.** `_exit_judge_artifact_lines` appends
   ` [asked: "<q1>" | "<q2>"]` to the line of every document with an open question. The judge
   prompt (exit judgment v3 → v4 text only) gains one sentence under "How to reason about it":
   "An artifact marked [asked: …] is waiting for an answer; a message that answers one of those
   questions is work on THAT artifact, even when it names nothing."
2. **The card binds the reply to the document.** A message composed from the card carries a
   `design_document` context ref for each document it answers (the composer's existing
   `contextRefs`; the judge already reads tagged designs as a strong signal and the dispatch
   already accepts focus refs).

The one-round guard becomes **per document and server-derived**: when the leg runner builds each
addressed document's run request, `previous_turn_outcome` is `"clarification_requested"` if that
document has an open question (§2.3), else the submission's own value (kept for the wire's sake;
`None` in practice). The client never has to echo anything.

### 2.5 The card (point 3)

A new feature component in `apps/frontend/src/features/chat-shell/components/`:
`clarification-card.tsx` + `clarification-card.module.css`, with its logic in
`apps/frontend/src/features/projects/model/clarification.ts` (pure: card state, answer
composition, which turn's parts are "open").

**Where it lives.** Anchored above the composer (the slot where annotation chips and the queue
controls already sit in `chat-surface.tsx`), when the thread's LATEST turn is a design turn whose
parts include one or more `clarification` parts. One card at a time; several asking documents
queue in position order with a strip above the card: "2 designs have questions".

**What it shows** (the Claude.ai clarification card, in house tokens):

```
┌──────────────────────────────────────────────────────────────┐
│ Capital · LinkedIn 1:1 ad                     ‹  1 of 2  ›  ✕ │
│                                                                │
│ Which proof point should lead the ad?                          │
│ It decides the headline and the hero image.                    │
│                                                                │
│  1  The 40% faster onboarding stat                        →    │
│  2  The Fortune 500 logo wall                                  │
│  3  The customer quote from their CFO                          │
│                                                                │
│  ✎  Something else…                                 [ Skip ]   │
└──────────────────────────────────────────────────────────────┘
   ↑↓ to navigate · Enter to select · Esc to skip
```

- Header: document title, then the account name when present, then the pager over the
  document's questions, then ✕.
- Question text; `why_it_matters` beneath it in the subtle content colour.
- Numbered options (1…k). Keyboard: ↑↓ move, Enter selects, Esc skips, digits jump.
- **"Something else…" is always present** (founder ruling), a single-line text input; Enter
  submits it as the answer. `allow_freeform` from the runtime is ignored.
- **Skip is labelled "Skip"** (founder, 2026-09-21); the default it applies rides the button's
  hover title. The runtime requires a default, so Skip is never blank. Skipping records
  `{skipped: true, default}`.
- ✕ collapses the card into a chip under the design turn's message: "2 questions from Capital —
  answer". Clicking the chip reopens the card at the first unanswered question.
- The last answer of the last document sends. Until then answers are held in component state;
  moving back with ‹ shows the recorded answer selected.

**What it sends.** One ordinary chat message through `chat.submitMessage(text, {contextRefs})`,
composed deterministically (`composeClarificationReply`):

```
For "Capital · LinkedIn 1:1 ad":
- Which proof point should lead the ad? — The 40% faster onboarding stat
- Tone — something else: keep it drier than the Austin one

For "MNGI · LinkedIn 1:1 ad":
- Format — use your default (1:1 square)
```

with one `design_document` context ref per answered document. No hidden payload: the design
runtime reads the user's next message as text, the judge reads text plus tags, and the transcript
shows exactly what was sent.

**What happens if the user ignores the card** and types normally: nothing special. The message
goes to the judge; the run uses the defaults for what was not answered; the card disappears once
a later turn exists.

**Historical rendering.** A `clarification` part on a turn that is NOT the latest renders inline
in the transcript (a `case "clarification"` in the message-part view) as a compact read-only
card: the document, each question, and "answered in your next message" — no controls.

**Tokens.** The card consumes `@clue/design-system` semantic tokens only — the same families
`project-flow.module.css` uses: `--clue-ds-color-bg-page` / `-bg-subtle` / `-bg-neutral-hover` /
`-bg-neutral-pressed`, `--clue-ds-color-border-subtle` / `-border-neutral` /
`-border-brand-default`, `--clue-ds-color-content-neutral` / `-content-subtle` /
`-content-disabled`, `--clue-ds-shadow-card-subtle`, `--clue-ds-product-component-button-sm-radius`
/ `-md-radius`, `--clue-ds-product-motion-duration-fast` / `-easing-standard`, and the
`--clue-ds-typography-*` text tokens. No raw hex, no new variables; `src/design-system-tokens.test.ts`
must stay green. Buttons and the text input reuse the composer's existing classes where they
exist rather than restyling.

### 2.6 What the design agent sees on the next turn

Unchanged in shape: the user's message text (now the composed answers), the brief and the item
note, and `previous_turn_outcome = "clarification_requested"` on THAT document's request (§2.4),
which makes the harness withhold `request_clarification` so the run designs from the answers or
the defaults.

## 3. Not in scope

- Mid-design questions (ruling: opening move only).
- A second chat channel per document; the composer stays the one input.
- Persisting answers structurally (the message text is the record).
- Attachments on the composed reply.
- Anything for the web (`doc_kind == "web"`) path beyond rendering: the web request model has no
  `previous_turn_outcome` field today, so a web document's guard stays as it is (a documented
  residual).

## 4. Acceptance

1. A single-document leg whose run asks two questions: the transcript shows the summary line
   "Asked you 2 questions before designing: …", the card appears above the composer with the
   document's name, both questions, numbered options, a Something-else row and a Skip that names
   the default; answering both sends one message carrying that document's ref; the next run
   request for that document carries `previous_turn_outcome = "clarification_requested"`.
2. A three-document batch where one document asks: two summary lines as today, one card; the
   answer routes to the asking document only (judge decision logged with `addressed` = that
   position); the other two are untouched.
3. Reloading the page while the card is up brings the card back; a later turn turns it into the
   inline read-only card.
4. Typing an unrelated message while the card is up sends it as usual; the card goes away with
   the new turn.
5. Every token the card's stylesheet references resolves (`design-system-tokens.test.ts`); no hex.
