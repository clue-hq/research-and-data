---
schema_version: "1"
kind: skill
name: manual-accounts-research
version: v9
summary: "Manual: accounts, contacts and their research. How an account joins a project, what each status means, the stages a job walks, and what settles."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
<!-- sources: research/2026-09-13-head-of-abm-manual/C-domain-model.md §3 (entities, membership, status derivation, display pages) and §4 (runs, jobs, settled, launch preconditions, the committee flow); research/2026-09-13-head-of-abm-manual/E-runtime-and-sibling-agents.md §3.1-3.2 and "What the agent is never told" rows 22-25 -->
# Accounts, contacts, and what their research means

## The entities

An account belongs to exactly one workspace. There is no global account identity and no cross
tenant reuse, so an account from another workspace is not found, never empty. A contact always
hangs under exactly one account. Both carry a status of `candidate`, `active` or `merged`, and
both can be a merge loser, in which case `merged_into` names the survivor and every read drops
the loser silently.

## How an account joins a project

Membership carries `added_via`, one of `discovered`, `imported`, `manual` or `directive`. The
**first add wins**: a later add through another channel changes nothing. Read `manual`
carefully: it does not mean a person typed the name, because a launch stamps `manual` too.
`discovered` is stamped by a discovery run at the moment the company is verified.

## What "researched" means, exactly

The research status you read is the status of the account's **latest account job**, served
verbatim:

| Value | What it means |
| --- | --- |
| `not_started` | a job exists and has not begun |
| `in_progress` | the job is running |
| `needs_review` | the job **failed and is waiting for a human**. This is the failure state |
| `completed` | the job finished |
| `suspended` | the job is **paused, not failed**. Every worker restart suspends whatever was in flight |

"Not started" in the sense of never asked for is different: an account with no job at all has no
status row. `refreshing` is a separate flag: a non terminal job exists that is newer than a
completed one for the same account. Person jobs never light the account's flag: a committee
member still being researched is not the account being researched again.

Research status is project independent on purpose: an account researched under one project is
not unresearched when you read it under another.

## Reading accounts and their claims

The account list is ordered newest first, the same order the human sees on the accounts screen,
so "the first ten accounts" means the same ten to both of you. It is capped: at most 200
accounts, at most 120 claims, and a capped read says `truncated` rather than dropping the tail
in silence.

A claims read pages under a byte budget: it returns an `offset` and a `next_offset`, and you
continue from `next_offset` until there is none. It also carries `prefixes`, the claim families
this account actually holds, with a count each. Narrow with one of those, never with a guess. An
honest precondition refusal from one of these effect free reads does not spend your repair
budget, so being refused for a bad prefix and correcting it is cheap. The tools themselves,
with every refusal code, are `.deepagent/skills/manual-tools/v9/SKILL.md`.

One thing you cannot read: the ICP fit verdicts your own launch produced. They are born
outreach unsafe, so the read holds them back and they reach you only as a number in the
excluded counts. Say that plainly rather than guessing at a verdict. Why the read holds them
back is `.deepagent/skills/manual-claims/v9/SKILL.md`.

## The run and the job

A run is the **authorization record**: the exact account set, the confirmed ICP artifact and
its digest, the product selection version, the effort, the committee cap, the human's own
`directive_text`, and the agent profile digest. If any of those bytes move, the job refuses and
asks to be relaunched, because moved bytes are a different thing to have approved.

The run id is the digest of the request, so relaunching the same signed off request returns the
same run, adds no second job and buys no second task. A launch result of `replayed` means
exactly that.

One job is one subject. `subject_type` is `account` or `person`. Runs and jobs share the same
five statuses listed above. A job can finish on `completed` or `needs_review` only; `suspended`
is a pause, not a finish.

`effort` is `full`, `reduced` or `cheap-pass`, and `committee_cap` is how many committee
members the account agent may seat. The account agent implements full mode only today, so a
cheaper effort does not currently buy a cheaper run.

## Stages

An account job walks `deep_research`, then `synthesis`, then `committee`, then
`member_research`. A person job stamps only the first two. The stage is how far along a job is,
which the status alone does not tell you.

**The run read does not carry the stage, and it cannot tell a person job from an account job**:
its rows are job id, account entity id, status and failure code, and a committee person job
appears as an extra row sharing the account's id. The stage and the person job count exist only
in `project/status.md`, which prints one line per account as
`<name>: <status> (<stage>), <n> person jobs`. So use the run read for "did it finish", and
`status.md` for "how far along is it", remembering that `status.md` is frozen for your turn
(`.deepagent/skills/manual-turn/v9/SKILL.md`).

## "Settled"

A job settles in its terminal transaction: the row is finished, and for an account job the
committee step runs inside that same transaction. Committee members and their person jobs are
written first and offered to the queue only after that transaction commits. So "once the
account job settles" means "once its committee has been written", not merely "once it stopped".

## What a launch needs before it will run

The checks run cheapest first and nothing is written until all of them pass. The refusals you
can receive name exactly what is missing: the lane being off, the project not found, an account
not found or not in this workspace, no pinned ICP for the project, the ICP artifact not found,
not confirmed, not matching its digest, or not this project's pin, and an unknown product
selection version. The person launch adds no contacts, contact not found, contact merged,
contact without an account, and the product set not being confirmed.

The person launch **never creates a person**. It researches contacts that already exist,
because inventing one would mean researching someone who does not exist. It also seats each
contact with a persona, defaulting to `user`, so the person is not invisible on their own
account's screen afterwards.

## The buying committee

The account agent names committee candidates as claims on the account. That is a finding about
the account, not yet a person. The committee step then turns each confirmed candidate into a
contact, three claims keyed to that contact (persona, role on the committee, current title),
and one person job. Skips are named rather than silent: a vacant seat is not a person, and a
name with no confirming url is not admitted.

The five personas are `champion`, `economic_buyer`, `technical_evaluator`, `blocker` and
`user`. The order they are displayed in is different from that list: economic buyer, champion,
technical evaluator, user, blocker. Recite the committee in display order so your words match
the screen.

## The three pages a human reads

`overview` and `insights` are about an account; `contact` is about a person. Their sections are
fixed: overview holds What they do, Why they fit, Why now, Buying committee, How to approach
and Watch-outs; insights holds Buying signals, Money and momentum, Tools they already use, How
they sell and who they win, Contact insights and Context only; a contact page holds Why this
person, Their problem right now, Openers, Angles and Do not mention. Watch-outs, Context only
and Do not mention are the **restricted** sections: they exist to show the operator facts they
must not use.

A page is written lazily, when a human first opens that screen, and a section with no claims is
not written at all rather than written empty. Your own read does not generate it: asking for
the overview when none exists is refused `overview_not_written`, and the honest move is to read
the claims instead, or tell the human to open the account in the app.
