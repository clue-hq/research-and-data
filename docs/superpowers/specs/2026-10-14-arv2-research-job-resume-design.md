# ARV2 research: resume a stopped job

Status: draft for founder review, 2026-10-14. Founder rulings so far (2026-10-14): the resume tool
has a script and admin endpoints, including a list of stuck jobs; an admin may top up a job's
allowance when resuming it; when the agent's instructions changed since the first attempt, the job
restarts fresh inside the same job instead of being refused; the six frozen 2026-10-03 jobs are left
alone; spec before code. Builds on PR #115 (the deadlock fix and the one-shot lock-conflict retry).

## 1. Why

A research job that stops partway can never be continued. The only ways forward today are hand
surgery in the database or a fresh launch, which redoes and re-pays the work.

**Production, as of 2026-10-14.** Seven jobs sit in `needs_review`, every one stopped deep into its
work. About $38.66 of research that can be redone but not finished:

| Date | Jobs | Failure | Rounds | Spent |
|---|---|---|---|---|
| 2026-10-03 | 1 account, 5 people | `workspace_conflict` | 39–74 | $32.29 |
| 2026-10-06 | 1 account | `page_writer_failed` | 59 | $5.37 |

The Reuben Doetsch job (2026-10-13, deadlock) was re-claimed by hand and refused. It was closed out
manually after a fresh person launch replaced it. It is the only job production has ever
re-claimed.

**How it breaks.** A research job's execution id is derived from its job id, and its turn id from
the execution id (`quality_research_wiring.py`), so every attempt reuses the same turn. Each claim
starts that turn from the beginning:

1. It assembles a fresh opening context and records a receipt keyed by the turn. If an earlier
   attempt's receipt exists and differs, the receipt store refuses with "turn already has a
   different opening context receipt" (`agent_turn_wiring.py`). The refused context was never
   stored, so which layer differed for Doetsch is unproven.
2. Even with a matching receipt, the runtime starts the conversation over. It feeds the opening
   messages into a thread that already holds the saved conversation. The "continue the existing
   turn without re-adding history" branch exists only for continuation turns
   (`clue_agents/runtime.py`), and research turns are always first turns.

The turn journal already intends resume. `load_committed_outcome` deliberately returns nothing for
an unfinished failed turn "so an explicit retry can resume their durable model checkpoint". The
chat path's continuation spec (2026-09-29, §3.3) promises the same for chat: "the retry finds the
turn's own half-run state and continues it without re-adding history". Research never got that
path, and no test covers re-claiming an interrupted research job.

**Two situations reach this path:**

- **Failed jobs.** Anything that lands `needs_review`. Nothing in the product moves a job out of
  that state. The "Needs attention" card lingers for 24 hours.
- **Interrupted jobs.** A deploy restart, a crash, or a lost lease. The driver suspends the job and
  requeues it, and the next worker re-claims it down the same path. This has never been exercised
  in production. It is the larger exposure, because every deploy restarts the workers.

## 2. Goals and non-goals

**Goals**

1. A re-claimed research turn continues its saved conversation instead of starting over. This
   covers account jobs, person jobs, and specialists. Interrupted jobs continue automatically.
2. One resume operation takes a stopped job back into the queue. It writes an audit record, and an
   admin may add an explicit top-up to the job's allowance.
3. A developer script lists stuck jobs and resumes one, in any environment, dry run by default.
4. Admin endpoints list a workspace's stuck jobs and resume one, for workspace owners and admins.
5. When the agent's instructions changed between attempts, the job restarts fresh inside the same
   job, keeping what it already paid for.
6. Every outcome of a resume is a continued job, a fresh restart, or a named refusal. Nothing fails
   silently.

**Non-goals**

- Re-running completed jobs. A completed turn is never re-executed. That rule is unchanged.
- Resetting allowances or counters. A top-up adds to the limit; it never zeroes what was spent.
- The in-product Retry button's look and placement. The endpoint is its contract. The button waits
  for a design ruling, because the designed frontend is the presentation truth.
- A cross-workspace staff console. The script covers operator needs across workspaces.

## 3. Design

### 3.1 Resume inside the runner

The research runner decides how to start a turn **before** it assembles anything. This mirrors the
chat path's rule that a turn has exactly one opening-context receipt.

1. **Committed outcome:** replay it. This is unchanged.
2. **No receipt yet:** a first attempt. Assemble, record the receipt and run, as today.
3. **Receipt exists:** this is a resume. Do not assemble again.
   - Read the recorded receipt back. The replay reader already rebuilds its manifest from the
     stored rows.
   - Check that the profile reference and resource-manifest digest on the turn's constitution
     still match what this deployment resolves. If a deploy changed the prompt, skills or tool
     surface since the first attempt, **restart fresh** (§3.2). The saved conversation has the old
     instructions baked in, so it is never continued under new ones.
   - **A saved checkpoint exists on the execution's thread:** invoke the graph with no new input.
     LangGraph runs the pending step, the one that was interrupted, and carries on. The round
     count continues from the checkpoint.
   - **No checkpoint yet** (the worker stopped between recording the receipt and the first step):
     rebuild the opening messages from the receipt's content-addressed references, checking each
     digest, and start the graph with them. The model sees exactly what the receipt says it saw.
4. **Workspace:** the same execution re-acquires its own workspace lease. Its materialized
   resources are verified against the recorded seed files, not re-derived.

**Why re-running the pending step is safe.** Every step a resumed graph can repeat is idempotent on
a stable key:

- Allowance reserves replay by activity id or delegation id. PR #115 keeps them under one retry.
- Provider acquisitions begin their ledger entry before dispatch. A dispatch whose outcome was
  never recorded comes back as `dispatch_outcome_unknown` and is never repurchased. That path
  exists today.
- Claim proposals and corrections replay by their proposal key.
- Finalization refuses before it freezes outputs (fix `9f0d8b51e`).

### 3.2 Restart fresh inside the same job

A restart gives the job a new conversation and keeps everything the job owns.

- **Identity.** The job gets a restart counter, a new `restart_count` column defaulting to 0. One
  shared function derives the execution id from the job id and that counter. At 0 it returns
  today's id, so existing jobs and their saved state keep their ids. The three places that derive
  the id today (the runner twice, account reconciliation once) all call it. A new execution means
  a new turn, a new receipt and a new checkpoint thread. Nothing collides with the old attempt.
- **What carries over.** These are owned by the job, not by the conversation:
  - Purchases. The provider ledger keys an operation by job and exact request, so any repeated
    call with the same arguments comes back from the ledger without buying again.
  - Claims already written for the job.
  - The job's acquired evidence. The new execution receives a fresh evidence grant over the
    job's sources, the same way a first attempt does.
  - The shared allowance and everything already counted against it. A restart may need a top-up,
    because the fresh agent spends more of it.
- **What does not carry over.** The old conversation and the old workspace notes. Both were
  produced under the old instructions.
- **When it happens:**
  - Automatically, at claim time, when §3.1 finds the instructions changed. This is recorded with
    the actor `system:profile_changed`.
  - Explicitly, when an admin resumes with `restart_fresh`, for example because a conversation went
    wrong. This is recorded with the admin as the actor.
- Account reconciliation reads the job's current execution, so its pages build on the latest
  attempt.

### 3.3 Specialists

A child turn is keyed by its delegation id. A completed child is already replayed
from its result. A child that was mid-flight resumes through the same three steps. When a resumed
parent re-runs its pending delegation, the child's own resume or replay decides the result.

### 3.4 Job states

| Job state | Interrupted (lease lost, deploy, crash) | Failed (`needs_review`) |
|---|---|---|
| How it re-enters | Automatic, as today. The driver requeues it. | Only through the resume operation. |
| What the runner does | §3.1 resume, or §3.2 restart | §3.1 resume, or §3.2 restart |
| Attempt counter | +1 on claim, as today | +1 on claim, as today |

The account generation must treat a resumed job as in flight again. Its pages wait for the job and
are rewritten when it settles, through the same signal the Doetsch link used by hand. A resumed
person job reports its result to its account's current generation, as a fresh launch would.

### 3.5 The resume operation

One function, used by the script and the endpoint:

`resume_research_job(conn, *, workspace_id, job_id, actor, reason, top_up, restart_fresh=False)
-> ResumeResult`

**Allowed from:** `needs_review`; `suspended`; or `in_progress` with no open fleet task (stranded,
the existing requeue script's definition).

**Refused with a named code:**

| Code | When |
|---|---|
| `job_completed` | The job completed. Nothing to resume. |
| `job_already_queued` | An open task already exists. A second resume is a no-op that returns the first. |
| `run_cancelled` | The run was cancelled. |
| `privacy_stopped` | The job or its generation was stopped for privacy. |
| `outputs_frozen` | The workspace's outputs were frozen by the pre-fix finalize bug (the six 2026-10-03 jobs). |
| `reason_required` | No reason was given. |

**What it writes, in one transaction:**

- The job moves to `suspended`, and its failure code, failure message and finish time are cleared.
  The table's existing checks hold.
- The job's own fleet task is re-opened under the same dedup key, exactly as the launch and the
  stranded-job requeue script offer it.
- The run's derived status is refreshed.
- **Top-up, if given:** explicit increments to the job's allowance limits for model calls, tool
  calls, delegations and runtime minutes. Each increment is a non-negative integer added to the
  limit. Used counters are never touched.
- **Restart, if `restart_fresh`:** the job's restart counter is incremented (§3.2).
- **Audit row** in a new table, `arv2_research_job_resume`: id, workspace, job, attempt before the
  resume, actor, reason, top-up, whether it restarted, and created time. The actor is a user id
  from the endpoint, `operator:<name>` from the script, or `system:profile_changed` for an
  automatic restart.

### 3.6 Script

`scripts/resume_arv2_research_job.py`, in the shape of the stranded-job requeue script.

- **No flags:** lists every stuck job across workspaces: `needs_review`, `suspended`, and
  stranded. For each it shows workspace, account or person, failure code, rounds, spend, and
  whether it can be resumed, with the refusal code if not. It writes nothing.
- **`--job <id> --reason "<text>" [--top-up-runtime-minutes N] [--top-up-model-calls N]
  [--top-up-tool-calls N] [--top-up-delegations N] [--restart-fresh]`:** prints the plan.
- **Add `--apply`:** performs it.
- In production it runs from a worker container, the way the 2026-10-13 repairs ran.

### 3.7 Endpoints

Both take the workspace from the `X-Workspace-Id` header, like every other `/frontend/v1` route, and
both require `research.approve_spend`.

**List stuck jobs:** `GET /frontend/v1/research/jobs/stuck`

- Returns the workspace's `needs_review`, `suspended` and stranded jobs, newest first. Each one
  carries: job id, run id, account (id and name), person (id and name) for a person job, state
  (`failed` or `stalled`), failure code and message, rounds, tool calls, spend, when it stopped,
  and `resumable` with the refusal code when it is false.
- This is the same reading the script prints, from one shared query.
- It is meant for a "research needing attention" screen. That screen's design is still owed.

**Resume one job:** `POST /frontend/v1/research/jobs/{job_id}/resume`

- **Permission:** `research.approve_spend`, which only workspace owners and admins hold. A top-up
  approves more spend, so this is the existing permission for exactly that decision.
- **Body:** `{ "reason": string, "restart_fresh"?: boolean, "top_up": { "runtime_minutes"?,
  "model_calls"?, "tool_calls"?, "delegations"? } }`
- **200:** `{ job_id, status: "suspended", attempt, restarted, top_up_applied }`
- **403:** viewer or operator.
- **404:** the job is not in this workspace. Cross-workspace ids look the same as missing ones.
- **409:** a refusal from §3.5, with its code.
- Both contracts are recorded in `apps/frontend/docs/api-contracts/` when the screens are
  designed.

### 3.8 Settings

None. The operation has no flag. Its permission gates it, and every action is audited.

## 4. Tests

These are scenario tests through the real runner, database and storage, run on a throwaway
database with no provider keys. A scripted model stands in for the LLM.

1. **Interrupted mid-tool:** a job runs N rounds, the worker is cancelled mid-step, and another
   worker re-claims it. It completes. There is exactly one opening-context receipt. The saved
   conversation holds the opening messages once. Rounds continue from N. The replayed provider step
   is not charged twice.
2. **Interrupted before the first step:** a receipt exists with no checkpoint. The turn starts
   from the recorded context, and its aggregate digest equals the receipt's.
3. **Specialist in flight:** a parent is interrupted while a child runs. The child resumes, the
   parent receives its result, and the delegation is reserved once.
4. **Failed, then resumed:** a job lands `needs_review` from an injected failure. The resume
   operation queues it, it completes, the audit row exists, counters are kept, the top-up is
   applied, and the account pages are rewritten.
5. **Instructions changed between attempts:** the claim restarts the job under a new execution.
   The old receipt and checkpoint are untouched. A repeated purchase with the same arguments comes
   back from the ledger without a second charge. Claims already written survive. The audit row
   names `system:profile_changed`.
6. **Explicit restart:** `restart_fresh` behaves the same way, with the admin as the actor.
7. **Existing ids are stable:** a job with restart count 0 derives exactly today's execution id.
8. **Refusals:** completed, already queued, run cancelled, privacy stopped, outputs frozen, no
   reason.
9. **Endpoints:** viewer and operator get 403, admin and owner get 200, another workspace's job
   gets 404, a second resume is a no-op, and the list shows exactly the stuck jobs with the right
   `resumable` flags.
10. **Script:** a dry run writes nothing, and `--apply` matches the endpoint's effect.
11. **Live proof, founder-triggered, spends money:** on the lane, restart the workers in the middle
   of a real person job. It continues and completes.

## 5. Risks and open questions

- **Profile changed between attempts. Founder ruling 2026-10-14: restart fresh** (§3.2). It
  should be rare, because each job pins its recipe version at launch. It only happens when a pinned
  recipe's own files change in place or are retired, or a shared tool changes shape.
- **The six 2026-10-03 jobs. Founder ruling 2026-10-14: leave them.** They are refused as
  `outputs_frozen`, and no one-off repair unfreezes them. Their research is superseded by later
  runs.
- **A step that dies inside a provider call.** The ledger records the dispatch first, so the step
  comes back as outcome unknown and is not repurchased. The agent sees a gap, not a duplicate
  charge. This is intended.
- **Listing in the API. Founder ruling 2026-10-14: include it** (§3.7).
- **Screens.** The Retry button and the "research needing attention" screen are not in this build.
  They need a design ruling first. The endpoints are their contracts.
