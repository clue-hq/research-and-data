# Account brief after person research: design

Status: draft for founder review, 2026-11-05. Nothing here is built. Trial lane only; taking it to
production is a separate decision.

## Why

Today the account agent writes its verdict and page brief before any person research exists. The
account pages are rewritten once people finish, but with the same brief, and the writer's guide tells
it not to change the brief's messages.

Recipe 39 showed the cost. Drew Herpich's profile lists strategic-advisor roles at Vooma and Drumkit.
Person research found this, yet Vooma and Drumkit appear nowhere on NTG's account pages, and NTG's
verdict could not use them. Contact pages have a related gap: they are written against the account's
first story, before the rewrite.

## Goals

- One brief per account in the normal case, written with the person findings in hand.
- The verdict stays with the account agent, which keeps its memory of the research.
- Every account ends with pages or a clear `needs_review`. Never a silent stall.
- Nothing that waits holds a job slot.

## Not in this work

- Refreshing contact pages already written when a later review changes the story.
- Screen changes beyond what `pending` sections already show.
- Changing queue priorities.
- Page-writer guide changes (roadmap stage 4). Taking this to production.

## Founder rulings

| Ruling | Effect |
|---|---|
| Option D | The brief is written after person research, not before and again after. |
| Reps do not need account pages before person research finishes | No first account pages. |
| Stop waiting after 30 minutes without progress on a started person | The job is not killed. |
| Crash retries get a limit | Proposed: 3 attempts in a row without progress. |
| Someone has left: nominate a replacement | The agent is told who left and why, then waits for that research. |
| A late finisher triggers a newer brief, then a page rewrite | See "Late finisher". |
| No deadlocks | See "Why this cannot deadlock". |

## The main finding: no paused state is needed

Tracing the code changed the design. The flow already has what D needs:

- An account job can finish (`completed`) while its people are still running. Its generation stays
  `provisional`, and the job's slot is released.
- `pending_continuations` offers a continuation for the account only when no person is still
  unsettled (`quality_generation.py`). Suspended and privacy-stopped people do not hold it.
- A person finishing signals a new input revision through `record_child_result`.
- The continuation is its own queued task, with its own work id and lease.
- Before page writing moved out (recipe 25), that continuation resumed the account agent on its saved
  conversation (`continue_account` in `_focused_reconciliation`). Today `writes_pages_separately`
  sends it to the page writer instead.
- `_final_page_step` already writes account pages first, then deferred contact pages, so contact pages
  get the new story.

So "the agent pauses" means **the account job finishes its first turn, and the generation waits**.
This avoids the trap I raised earlier: `ready_person_jobs` will not release people whose parent is
`suspended`, so reusing that status would have blocked them forever. We do not use it.

## The flow (new recipe)

1. **First turn.** The account agent researches, imports its dossier and nominates people, as today.
   It records a provisional verdict in its report and does not write the brief. `_write_pages` defers
   `overview` and `insights` (`coverage` already accepts deferred pages). The job finishes and frees
   its slot.
2. **People.** Person jobs run as today and can read the imported account dossier. Each contact page
   is always deferred, not only when the parent has not imported.
3. **Review turn.** When no person is unsettled, or the wait rule ends the wait, the continuation
   resumes the account agent on its saved conversation. It reads a new `/work/review/input.json`: each
   person's status, findings, gaps and any "has left" report. It may check a specific lead and
   nominate a replacement. It writes `/outputs/page-brief.md` and its final verdict.
4. **Pages.** If nobody new was nominated, `_final_page_step` writes the account pages from that brief,
   then the deferred contact pages. If someone was nominated, the turn ends and the flow returns to
   step 2 for that person.

With no nominations at all, nothing is unsettled, so step 3 follows at once.

The review turn needs more tools than the old continuation, which kept only `finalize_turn`: reading
evidence, `search_web`, `fetch_page`, and the nomination tools.

## Draft instruction for the review turn (for founder review)

> Your people's research is finished, or as finished as it will get. Read /work/review/input.json. It
> tells you, for each person, what was found, what could not be reached, and whether they are still
> running or failed. Decide what this changes about your verdict and your approach, then write
> /outputs/page-brief.md as your only brief. Treat a failed or unfinished person as a gap, not as
> nothing to find.
>
> If someone has left the company, look for whoever holds that responsibility now, check where they
> work today, and nominate them, saying who left and why. If you find no suitable person, name the seat
> as a gap. Check a lead only if it could change your verdict or approach; do not repeat your research.
> If your research was blocked, say so plainly instead of writing a confident verdict.

The first-turn prompt loses its "write /outputs/page-brief.md" section and asks for a provisional
verdict instead. This recipe also carries two approved changes: the free-slot committee wording and
credentials under the career rule.

## Waiting rule

`pending_continuations` treats a person as unsettled unless they completed, failed or landed
`needs_review`. The new rule also treats a person as settled for waiting purposes when they have
**started and shown no progress for 30 minutes** (`CLUE_ARV2_PERSON_STALL_WAIT_S`, default 1800, added
to `.env.example`).

- Progress means their latest row in `arv2_quality_activity`. To confirm while building: that its
  timestamp moves often enough, given that one deep call or page-writer call takes minutes.
- A person who has not started is never skipped, because a queue can be long without anything being
  wrong.
- The job is not killed, and the agent is told the person is still running.
- This runs in the existing sweep, which takes no job slot.

## Retry limit

`fleet_task.attempts` is counted but I found nothing that acts on it for research jobs. After 3
attempts in a row without progress (`CLUE_ARV2_JOB_MAX_ATTEMPTS_NO_PROGRESS`), the job lands
`needs_review` with `retries_exhausted`, which counts as settled. A normal stop or deploy requeues
without counting, as `_REQUEUE_SQL`'s `uncount` allows.

## Replacement

- The person agent reports that someone has left, as it does today.
- The agent gets it in the review input and nominates a replacement, within this rule.
- Re-nominating the same person reuses the existing job, so the same person cannot loop.
- **One replacement per seat.** If the replacement has also left, the seat is named as a gap. This is
  my addition: your reasoning stops the same person repeating, but a second candidate can also be stale.
- To confirm while building: the nomination tool accepts a parent job that has finished, and the
  committee cap does not count someone who left.

## Late finisher

A person who finishes after the wait ended already signals a new revision. That offers another
continuation: a review turn, then account pages from the newer brief, plus that person's contact page.
Contact pages already written are not refreshed. People who finish during a review are covered by the
next one, because each account runs one continuation at a time (`only_if_work_idle`).

## Why this cannot deadlock

**The rule: no task holding a job slot ever waits for another job.** The first turn, each person job,
each review and each page step runs and ends. Waiting exists only as a condition the sweep reads.

| Scenario | Why it cannot block |
|---|---|
| Agent waits while a person needs a slot | The agent's job has finished and released its slot. |
| Every slot full | Tasks run to completion and free slots. None depends on another. |
| Person waits on the account | They do not. They read the imported dossier when listed, or work from their own findings. |
| Parent looks paused | The parent is `completed` or `needs_review`, and release only refuses `suspended` or `not_started`. |
| Wait check needs a slot | It runs in the sweep. |
| Review bumps its own revision, forever | See below. |
| Replacement chain | One replacement per seat. |
| No workers | Nothing runs and no timer fires for people not started. Everything continues on restart. |

**Revision loop.** Importing or correcting claims can signal a new revision through
`signal_subject_change`. If a review corrects its dossier, that causes one more review, which should
change nothing and end. Page writes are also skipped when the request is identical. A test must show
that one review with no new input causes no further review.

**Queue order, a correction.** I worried that new accounts could starve people. All these tasks share
one priority and run first-in, first-out (`ORDER BY priority, enqueue_seq`), so nothing starves. On a
large launch, people run after the accounts queued before them, so results arrive later but all arrive.

## Failure cases

| Case | What happens |
|---|---|
| 3 of 5 seats found | The review uses those three, and the brief names the open seats. |
| Nobody nominated | The review runs at once and says why. |
| A person fails | Settled. The agent sees the failure and treats it as a gap. |
| A person hangs or loops | The wait rule or the retry limit ends the wait. |
| Agent cannot resume | Up to 3 attempts. Then pages are written from the job's verdict summary, which `page_brief` already falls back to, and the account lands `needs_review`. |
| Account never imported | The final step already handles this: contact pages are written, and the account lands `needs_review`. |
| Exa or another provider refused | The agent says research was blocked. Fix first: `ResearchUnitReport` rejects `status` and `next_actions`, so an honest blocked report crashes the job (recipe 38). |
| Agent nominates with no research | Seen on Nav in recipe 38. The prompt tells it not to; to be re-checked in the outage test. |
| Page writer fails | `needs_review`. No earlier pages exist any more, so the existing retry path must be proven. |
| Long wait loses raw reads | Raw reads expire 48 hours after last activity, working files after 7 days. The agent gets a receipt saying what expired. It relies on its notes and dossier, which are the parts that matter here. |

## What the rep sees

Sections with no pages show the existing `pending` state. "Waiting on 2 of 5 people" would be better,
but that is a new screen element and needs your ruling, so it is left out of this first version.

To confirm while building: `_offer_display_page` and the first-open offer in the read path must not
write account pages before the review. In the trial lane there are no screens, so this first matters at
production time.

## Proof before relying on it

Forced on trial accounts, each ending in pages or a clear `needs_review`:

1. Normal run: one brief, one account page write, contact pages after it.
2. Kill a person job partway: another worker takes over.
3. Hang a person job: the wait ends after the set time, and the agent reports them as still running.
4. Let that person finish late: a new brief and a page rewrite.
5. Crash a job repeatedly: it stops at the retry limit.
6. Make the review fail: pages from the fallback, `needs_review`.
7. Refuse Exa: an honest blocked result, with no crash.
8. Limit to one job slot: the whole run still finishes. This is the direct deadlock test.
9. A person who has left: a replacement is nominated, researched and reviewed. A second one who has
   left becomes a gap.
10. A review with no new input: no further review.

Then rerun NTG and Nav and compare with recipe 39: does Drew's Vooma role reach the verdict and pages?

## Cost and time

Removes one account page write and any second brief. Adds one review turn per account. That turn's
price is unknown: it re-reads about 75,000 tokens of context, likely without the cache after a long wait.
We measure this on the first run. On recipe 39's NTG, pages would have arrived about 33 minutes after
the first turn.

## Questions for the founder

1. **Late finisher:** I read your replies as a newer brief, then a page rewrite. Correct?
2. **One replacement per seat:** agreed?
3. **Three attempts:** is that the right starting number?

## Left to the builder

- Names of the new setting, constant and input file.
- Exact fields in the review input.
- How `arv2_quality_activity` is read for progress.
