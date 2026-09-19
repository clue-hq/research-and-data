# Research progress card — one pinned live card per project, above the composer

**Status:** design approved in chat by the founder, 2026-09-12. Branch `research-streaming`.
**Rulings (founder, 2026-09-12):** pinned above the composer (not a transcript part); one card per
project summing every live run; four equal stage quarters per account with member research
fractional by person jobs; the mockup is the only state, no chevron; a finished card lingers as
"Completed" for 60 s then disappears; the real stage order is used: deep research → synthesis →
committee → member research → done. Pill states: Running, Completed, Needs attention.

## 1. Stage on the job row

Migration adds `arv2_research_job.stage text NULL` with a CHECK over
`deep_research | synthesis | committee | member_research`. The account driver stamps it:

| Moment (`account_research_driver.py`) | stage |
|---|---|
| `begin_job` claims the row | `deep_research` |
| the agent's `finalize_research` tool call lands | `synthesis` |
| `_fan_out_committee` starts (inside `_settle`) | `committee` |
| `_offer_committee` enqueues person jobs | `member_research` |

A person job stamps `deep_research` on claim and `synthesis` on `finalize_person_research`.
Terminal rows keep their last stage. No other mid-run writes; `updated_at` moves with each stamp.

## 2. One project-level read

`GET /frontend/v1/projects/{project_id}/research/progress` (new
`frontend_read/research_progress.py`, registered in `frontend_read/app.py`), BFF mirror
`GET /api/projects/[projectId]/research-progress`. It folds every run in the project whose jobs
are not all terminal, plus runs whose last job finished within 60 s, into:

```
{ requested_accounts, queued, running, finished,
  progress_pct, pill: "running" | "completed" | "needs_attention",
  last_finished_at, agents: [{ account_name, stage, subject: "account" | "person" }],
  attention: [{ account_name, reason }] }
```

`queued` = account jobs `not_started`; `running` = jobs `in_progress` (account and person);
`agents` lists the running jobs in `started_at` order. Reads ARV2 tables only. `{ card: null }`
when nothing qualifies.

## 3. Progress math (pure, tested)

Per requested account: four equal quarters. `deep_research` done at `synthesis`; `synthesis` done
at `committee`; `committee` done at `member_research` or at a terminal account job with no person
jobs; `member_research` = person jobs terminal ÷ person jobs created (0 when none created yet, the
full quarter once the account job is terminal with zero committee). Overall = mean over all
requested accounts across the folded runs. 100 only when every job is terminal.

## 4. The card

`features/projects/components/research-progress-card.tsx` renders the mockup exactly: telescope
glyph, "Account research", "N account research agents running, M accounts queued", the queued row
("M Accounts" / "Queued"), the bar at `progress_pct`, the status line. No chevron. Mounted in
`chat-surface.tsx` inside the composer dock above `ProjectComposer`, the slot the edit-targets bar
uses. Controller `use-research-progress-controller.ts` polls the BFF route every 5 s while the
read returns a card, starts polling on mount and on a completed `launch_account_research` tool
part, and stops when the read returns `null`.

## 5. The status line

`model/research-progress-line.ts`, pure: given the agents list and a tick counter, one sentence,
round-robin every 4 s:
`deep_research` → "<Account> agent doing deep research";
`synthesis` → "Synthesising our findings for <Account>";
`committee` → "Finding the buying committee for <Account>";
`member_research` or any person job → "Diving deeper into each committee member of <Account>".
Completed → "Research complete for N accounts". Needs attention → "<Account>: <reason>".

## 6. Lifecycle and failures

Completed: pill "Completed", line as above, card removed 60 s after `last_finished_at` (the read
stops returning it). Needs attention: any job `needs_review`/`suspended` or run `suspended` flips
the pill and lists the account; the card stays until the run resumes or the job leaves that
state. A failed status read keeps the last card and retries next tick.

## 7. Tests

Driver: each stamp lands at its moment (fakes + DB test). Read: DB test over a run with mixed
statuses. Math and line: pure tests including no-committee and zero-person cases. Frontend:
controller tests for poll start/stop; source-contract test that the dock mounts the card.

## 8. Out of scope

Worker capacity (not exposed by the fleet); per-account detail; dismiss controls.
