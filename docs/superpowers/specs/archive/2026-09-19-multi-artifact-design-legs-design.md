# Multi-artifact design legs: one message, many documents, parallel design runs

**Status:** IMPLEMENTED 2026-09-19 on branch `project-home` (plan
`docs/superpowers/plans/2026-09-19-multi-artifact-design-legs.md`, tasks 1–11; ledger
`.superpowers/sdd/2026-09-19-multi-artifact-design-legs/progress.md`). The six live proofs of §7
are OWED, founder-triggered.
**Depends on:** design session continuity (`2026-09-18-design-session-continuity-design.md`,
shipped), the exit judge v2 (free reasoning, artifact line and tag lines; commit `4834e9083`),
and the seller/target-account context for the design agent
(`2026-09-19-design-agent-account-and-seller-context-design.md`, shipped as PR #67).
**Amends:** ruling 3 of the 2026-09-19 account-context note (see §3.6).

## 1. The rulings this note implements

Founder, 2026-09-19:

1. **One message may ask for many design artifacts, and they are made in parallel.** Twenty
   tagged accounts and "a 1:1 ad for each" means twenty ads; "five variants of this LinkedIn
   ad" means five ads. Each artifact is its own design document, opens in its own tab, and
   iterates in its own design session.
2. **The shape is one open leg per thread holding a SET of documents**, executed as parallel
   queued design runs that the chat turn joins. The one-open-leg-per-thread rule, the
   per-thread single-flight rule, the one-document-one-session rule, and the design runtime's
   one-scene-per-run substrate all stay.
3. **Follow-up messages are routed by judgement, not mechanically.** The exit judge, the one
   model call already in the routing path, decides which of the leg's documents a message
   addresses: a tagged document, a document named in words, all of them for a general
   statement, a subset when the sentence says so. When it genuinely cannot tell, it asks the
   user instead of guessing, and nothing is dispatched.
4. **A scene ad born for a tagged account carries that account**, so the artifacts page and the
   gallery can show the link.
5. **No confirmation before spend, at any batch size.** Stop on the chat cancels every design
   run of the batch that has not finished.

## 2. What is true today (why this note exists)

Verified on `research-streaming` at `21e3ef1e9` (PR #67 merged):

- **One turn, one leg, one document.** `open_design_leg@4` derives the leg id from the
  presenting turn and the born document id from the leg id, so a second call in the same
  Head-of-ABM turn replays the first (`platform/api/clue_api/design_leg_tools.py`,
  `derive_design_leg_id` / `derive_leg_document_id`). The input takes one `title` and one
  `doc_kind`.
- **One open leg per thread** is the partial unique index `design_leg_one_open_per_thread`
  (migration `549de68ae3b9`) and Part III ruling D4 ("concurrent design sessions per user are
  across threads").
- **One turn at a time per thread** is the fleet's single-flight invariant
  (`agent_turn_submission.py`, `thread_work_id`).
- **A leg turn runs one design run inline on the chat worker's slot** and holds the slot for
  the whole run (`design_fleet.InlineDesignLaneDriver`; `design_leg_wiring._dispatch`). The run
  id is derived from the turn id (`design_leg_run_id`).
- **The exit judge already refuses multi-account asks the right way.** Its v2 prompt says a
  request naming two or more accounts closes the session and hands the message to Head-of-ABM,
  which can then open one leg for the first account. The others are dropped. Nothing queues
  them.
- **The parallel machinery exists one layer down.** The fleet kind `design_job` is drained by
  every design-capable worker slot (`lumen_api.fleet_handler.DesignJobWorkHandler`, registered
  in `fleet_main`), the design API's editor route already offers independent runs onto it
  (`lumen_api/main.py` `/agent/turns`), each run row is a frozen envelope with a claim CAS and
  a lease-generation fence (`clue_design.runs.claim_run_for_execution`), and the reaper
  re-offers a stranded run's own envelope (`lumen_api/fleet_reaper.py`). This lane runs four
  worker processes with three slots each.
- **The design runtime is already the right unit to parallelize.** One run is one document:
  `LumenDesignTools` holds one scene, a leg turn persists to one document under a compare-and-set
  (`_LegSceneCommitter`), the agent has no tool to create a document, and since session
  continuity each document has its own LangGraph thread and workspace folder. Since PR #67 it
  reads the target account by name through the three governed reads. None of this changes.
- **The frontend opens ONE tab per feed refresh.** `chat-shell/model/artifact-auto-open.ts`
  picks the single newest artifact from this thread. The tab list has no limit.
- **The gallery and the artifacts page derive a document's project from its leg**
  (`design_leg_wiring.project_design_documents` / `workspace_design_documents` join
  `design_leg.document_id`). The artifacts page already renders an account on a document
  through `design_document.account_id → design_account` (`frontend_read/artifacts.py`,
  `ArtifactAccountV1`); the gallery card wire (`DesignArtifactListItemWire`) carries none.
- **Composer tag validation assumes one leg document.** `validated_context_refs` takes
  `design_leg_document_id`; node targets must name exactly that document.

## 3. Target model

### 3.1 Delegation: `open_design_leg@5` takes a list of artifacts

The tool input gains `artifacts`, a list of items, each `{title, note, account_id?}`:

- `title` — the name the user would recognise; distinct per item (the engine appends a
  position suffix only if two items collide, so a document is always addressable by name).
- `note` — this item's own words: the account it is for, the variant's emphasis, anything that
  distinguishes it from its siblings. Free text, bounded at 2,000 characters.
- `account_id` — optional; the research account (`account_entity`) this artifact is for. See
  §3.6.

`brief` stays the shared brief for the whole batch, `doc_kind` stays one per leg (a batch is all
ads or all pages; mixed batches are two legs on two messages), and `title` at the top level is
retired in favour of the per-item title. **A single-artifact ask is a list of one**, and every
existing single-document path is that case. `document_id` (work on an existing artifact) and
`reopen_leg_id` are unchanged and exclusive with `artifacts`.

Identity, replay and the transaction are the existing disciplines, widened:

- Leg id from the presenting turn, unchanged.
- Document id per item: `derive_leg_document_id(leg_id, position)`; position 0 keeps today's
  derivation byte-for-byte, so a retried delegation converges on the same N rows and a
  single-item leg mints the id it always has.
- All N births and the leg insert in ONE transaction; brand identity decided by
  `create_document`'s creation contract at each birth and read back, exactly as today. The leg
  carries one brand pin (all documents of a leg are born from one kit).
- The bundle records the item list. The size cap becomes `24,000 + 1,500 × (N − 1)` bytes so
  the shared half of the L3 layer is preserved for a single ad and a large batch is not refused
  for being large. The item list's schema bound is 200 (the existing list bound on this tool),
  which is a schema sanity bound, not a product cap (ruling 5).

**Head-of-ABM's guidance (prompt v10, `manual-tools` regenerated).** Head-of-ABM decides by
reasoning how many items there are and what each note says. Twenty tagged accounts asked for
1:1 ads are twenty items, each note naming its account in words and carrying its `account_id`
from the tagged ref. "Five variants" are five items whose notes give each a distinct emphasis
(angle, proof point, visual direction) so the sessions do not converge on the same ad. One
account per item; a generic variant carries no account. It still puts the user's own words in
the shared brief and never chooses dimensions. This is prompt text, not code.

### 3.2 Storage: the leg's documents

A new table `design_leg_document` (Alembic hash id, chained off the current head):

```
leg_id, workspace_id     → design_leg (id, workspace_id)
document_id, workspace_id → design_document (id, workspace_id)
position   int  NOT NULL          -- 0..N-1, the birth order and the run-id seed
note       text NOT NULL DEFAULT ''
UNIQUE (leg_id, position); UNIQUE (leg_id, document_id)
```

`design_leg.document_id` and `document_version_guard` stay and mean **position 0**, so every
reader that needs "the leg's document" for a single-document leg keeps working unchanged
(`design_memory_runtime`, the exit journal, the finish tool's `document_version`). The
migration backfills one child row per existing leg with a document. The readers that need the
SET move to the child table: the gallery and artifacts-page derivations (§3.8), the leg runner
(§3.3), the judge's inputs (§3.5), the composer's tag validation (§3.7), and the finish tool's
close summary (it records every document's version).

### 3.3 Execution: fan out, drive, join

The leg runner (`DesignLegTurnRunner.run_leg_turn`) dispatches the addressed documents of the
leg (§3.5 decides which; the first turn addresses all) as a batch:

1. **Envelopes.** One `DesignTurnEnvelope` per document, built by the existing `_envelope`
   with the document's own row, its own session thread (`design_session_id(workspace,
   document)`), the shared bundle, and the item's note rendered into the DELEGATION BRIEF
   block after the shared brief ("This artifact: <title>. <note>"). The run id is
   `design_leg_run_id(turn_id, position)`; position 0 keeps today's derivation, so a
   single-document leg's runs, receipts and replays are byte-identical to before.
2. **Rows and tasks, one transaction.** N run rows `queued` (leg id and execution id stamped
   as today) and N `design_job` tasks enqueued on the fleet queue via the design store's
   existing offer path. The leg is marked `running` once. From this moment every free slot on
   every design-capable worker can claim a sibling.
3. **Drive and join** — `InlineDesignLaneDriver.drive_batch(envelopes)`, the existing
   single-run loop applied across siblings with its rule unchanged: for each non-terminal run,
   try to acquire its work lease; **if acquired, drive it inline** (handler on a worker thread,
   supervised heartbeat, event tail) and on return move to the next non-terminal sibling; **if a
   live foreign lease holds it, skip it**; when every non-terminal sibling is held elsewhere,
   wait and poll as the single-run loop does today; when a foreign lease lapses with no
   terminal row, acquire and drive. Return when every run is terminal. The join window is
   **progress-based** rather than fixed: the single-run `join_timeout_s` is measured from the
   last moment the batch made progress (a run reached terminal, or a lease of one of its runs
   was renewed), so a large batch on a busy fleet is never failed for being large, and a batch
   nobody is driving still fails within the same window a single run does. On a deadline the
   turn fails loudly and the reaper owns what is left, as today.
4. **Per-document progress.** `_DesignEventForwarder` tails the batch: one poller over the
   run ids, each frame carrying the run's own `document_id` (it already does; the forwarder's
   identity resolution keys on run id). The canvas of each open tab reloads on its own
   `design.checkpoint` frames.
5. **Same-document wait.** `_wait_for_document` runs per document, before that document's run
   is created, so a sibling leg on another thread driving one of the documents delays only that
   one.
6. **One hand-back.** Receipts recorded for every run against the platform turn
   (`_record_design_receipts` over the batch); one assistant message listing each document by
   title with its outcome (saved at version v / failed: reason / cancelled / conflicted); one
   `AgentFinalizeEnvelope` naming every run in `domain_refs`; the leg back to
   `open_awaiting_user` once; one `leg.awaiting_user` frame.

**Why parallelism equals free slots.** Nothing decides how many runs go at once. An idle fleet
runs up to its slot count together; a busy one runs fewer and the chat turn's slot works through
more of them itself. There is no new setting, and `CLUE_FLEET_WORKER_CONCURRENCY` stays the only
knob (ruling 2026-09-10).

**Why it cannot deadlock.** The single-slot hazard the inline driver was built for is still
covered: if no other slot ever frees, the chat turn's slot acquires every lease itself and drives
all N sequentially. The waiting branch is entered only against a live foreign lease, which is
proof that a real slot is executing that job.

**Failure model** (each case is the single-run behaviour applied per run):

- *A sibling's worker dies.* Its lease lapses; the batch loop or the reaper re-drives it; the
  claim CAS lets the newer generation take over; the dead thread's writes are fenced; the
  document's session resumes from its last checkpoint.
- *The chat turn's worker dies.* The turn is re-offered; the retried turn derives the same N
  run ids, finds the rows, and re-joins (the existing re-join branch of `_dispatch`, per run).
  Finished runs stay finished; in-flight runs keep going; unheld runs get driven.
- *One run fails.* It is terminal; the batch continues; the summary names it and why; the leg
  hands back; the user's next message can address that document alone. The whole turn is
  `AWAITING_INPUT` if at least one run succeeded, `design_leg_turn_failed` only if all did.
- *Stop.* §3.9.

### 3.4 Sessions and history on a multi-document leg

Each document keeps its own session (thread, folder, drift note) exactly as shipped. The leg
history block (`load_design_leg_history`) is the leg's user↔design exchanges and is sent only to
a thread that does not already hold state, as today; on a batch's first turn every session is
fresh and receives the brief, its item note, and no history. A follow-up addressed to a subset
continues those sessions; the others are untouched and their threads carry nothing about the
message, which is correct: the message was not for them.

### 3.5 Follow-up routing: the exit judge addresses documents

The exit judgment moves to **v3**. Inputs: instead of one `CURRENT_ARTIFACT` line, a numbered
`ARTIFACTS` block, one line per leg document — `1. "<title>" (scene ad | web page)
[account: <name>]` — in position order; `TAGS` lines mark a tagged design that is one of the
leg's documents with its number ("(artifact 3)"). Output gains two answers:

```
{
  "close_this_session": ...,
  "hand_message_to_strategy_agent": ...,
  "current_artifact_accepted": ...,
  "addressed_artifacts": [3, 7] | "all",
  "clarifying_question": null | "one question, in the user's terms",
  "reasoning": "..."
}
```

- `addressed_artifacts` — which documents this message is work on, by the numbers in the
  block. Numbers are addresses, not a vocabulary of intent: the judge still reasons in prose
  about what the message means, then names where it lands. Meaningful only on a stay.
- `clarifying_question` — set when the judge cannot tell which documents are meant. The turn
  ends `AWAITING_INPUT` with that question as the assistant message; no run is created, no
  design spend. The leg stays open; the user's answer is the next message.

Prompt guidance (scenarios, not buckets): a tagged document is the strongest address, but a
tag can be a reference for work on others ("match @Apollo's colours on the rest"); a document
named in words is matched against the list, including by its account ("the Apollo one", "the
two hospital ones", "the third variant"); a general statement that plausibly applies to every
artifact addresses all; a general statement with a qualifier addresses the subset the list
identifies; when a message could be for one or for all and nothing in it says which, ask. When
a leg has one document, `addressed_artifacts` is that document and the question is never
needed, so single-document legs behave exactly as v2.

Engine mapping (`decide_exit`): close decisions are unchanged and apply to the whole leg
(acceptance locks the leg; the finish tool records every document's version). On a stay: a
non-blank `clarifying_question` yields the ask outcome above; otherwise `addressed_artifacts`
selects the dispatch set; `"all"` or an empty selection on a single-document leg selects it.
**Fail-safe on a multi-document leg:** an absent or malformed judgment, or an address that
names no document of the leg, does NOT dispatch — the engine asks the user which of the N
designs the message is for (an engine sentence, no model authorship). This is a deliberate
divergence from the single-document fail-safe (continue): "continue" there costs one run; here
it would cost N.

The judge's reasoning and the addressed set are logged (`design_leg.exit_judgment`) and the
addressed titles are named in the turn's assistant summary.

### 3.6 The account on a born document (amendment)

`design_document.account_id` references `design_account`, the design plane's account row,
which joins to the research spine through `design_account.account_entity_id`
(`clue_design.joins`). A born scene ad for a tagged account is stamped as follows: the tool
validates the item's `account_id` as an `account_entity` of this workspace that is on this
project (the same containment the composer's tag validation applies), resolves-or-creates the
`design_account` for it (name, domain, `account_entity_id`; a new
`clue_design.accounts.ensure_web_account_for_entity`, the inverse direction of
`joins.resolve_account_entity_id`, called from the platform side, which is the direction
Part III sanctioned), and passes it to `create_document(account_id=…)`. A web page born for an
account gets the same stamp, which also makes the existing G2 account-card resolution work for
chat-born 1:1 pages.

**Amendment to ruling 3 of the 2026-09-19 account-context note** ("no account ids are passed"):
the id exists on the delegation for the durable link and the gallery, never as the design
agent's input. The agent still reaches the account by tools and by the words in the item note;
nothing in the runtime reads the stamp. A generic variant has no account and no stamp.

### 3.7 Composer tags while a multi-document leg is open

`validated_context_refs` takes the leg's document SET. Node targets must name one document of
the set (all targets on one document per message, as the runtimes edit one document at a
time); reference images are accepted when the leg is scene-kind and ride every addressed run.
The judge sees a tagged leg document with its number (§3.5). A tagged design that is NOT on the
leg is a reference, exactly as ruled 2026-09-17.

### 3.8 Frontend: a tab per born document, the account on the card wire

- `artifactToAutoOpen` returns every new or updated artifact from this thread (not the newest
  one); the surface opens each and activates the first in feed order. The `leg.opened` frame
  already refetches the feed, so the N tabs open at delegation time, before generation, each on
  an empty document that the pageless-birth banner already explains; checkpoints fill them in.
- The gallery feed wire (`DesignArtifactListItemWire`) gains `account` in the artifacts page's
  `ArtifactAccountV1` shape. The artifacts page renders it today. **The gallery card's designed
  component has no account slot**, so on the gallery the field stays invisible until the
  co-founder designs one (dummy-frontend rule); no invented chrome.
- The editor's run lock is per thread (`agent-run-lock.ts`) and therefore covers every document
  of the thread while a leg turn runs. That is correct for a batch (any of them may be written)
  and unchanged.
- The transcript's leg notices are unchanged; the wait sentence already says generation takes
  minutes.

### 3.9 Stop cancels the batch

`request_stop_for_turn` requests cancellation on every non-terminal run of the batch
(`design_runs.request_run_cancellation` per run id derived from the turn); `await_stopped_turn`
drives the batch to terminal through the same batch driver. A run in flight on another slot
stops at its next model-call boundary and finalizes cancelled with its checkpoints kept (the
existing A3 path); a still-queued run is cancelled before any slot pays a model call (the
cancel probe runs before the graph is entered). The turn's summary lists which documents
finished and which were cancelled, each with the version it stands at.

## 4. What stays as it is

One open leg per thread; one turn at a time per thread; the routing read; one document = one
session; the design runtime, its substrate, its tools and skills; the `design_job` handler, the
claim CAS, the lease and fence, the reaper; the brand pin at birth; the exit judge's place in
the path and its fail-safe stance on a single-document leg; the finish tool's exit vocabulary;
the G1/G2 gates per document; erasure (each session folder goes with its document).

## 5. Cost and behaviour

- A batch of N is N design runs at the same time, each in the tens of model calls; the fleet's
  slots also serve research and onboarding, so a large batch occupies the fleet for a while.
  Ruling 5: it launches without confirmation.
- A follow-up costs one judge call plus one run per addressed document. A clarifying question
  costs one judge call and nothing else.
- Receipts and Langfuse traces: one `design-leg.turn` trace per run, all nested under the
  platform turn; the cost read sums them per turn as today.

## 6. Open points for the plan

- The exact prompt text of exit judgment v3 and of Head-of-ABM prompt v10 / the design skills'
  mention of sibling artifacts (skill text is founder-reviewed before landing, standing rule).
- Whether the batch's assistant summary is engine-rendered only (recommended, like the exit
  summaries) or lets each run's own summary sentence through.
- The forwarder's page limit under N concurrent runs (one poll of 500 rows may need to become
  per-run pages).
- Title collision suffixing versus refusing duplicate titles at the tool.

## 7. Acceptance (live, spends money)

1. Twenty tagged accounts, "a 1:1 LinkedIn ad for each": one leg, twenty documents born in one
   transaction, twenty tabs open at delegation, runs distributed across more than one worker
   process (log lines `design_job.started` from several worker ids plus
   `design_leg.lane_drive_finished` from the chat slot), one assistant summary naming all
   twenty with versions, every document stamped with its account and shown on the artifacts
   page.
2. "Five variants of this ad": five documents with distinct emphases, no account stamp.
3. Follow-ups on the twenty: "@Apollo ad: bigger logo" runs one; "the two hospital ones need a
   softer palette" runs two; "make all the headlines shorter" runs twenty; "the logo is too
   small" gets a clarifying question and no run.
4. Stop pressed mid-batch: every queued run cancelled with no model call, in-flight runs
   finalize cancelled at their next boundary, summary lists both sets.
5. A worker killed mid-batch: its runs are re-driven, the batch completes, no duplicate run rows.
6. A single-artifact ask on the same build: leg, document id, run id, prompt and receipts
   byte-identical to the pre-change path.
