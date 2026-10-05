---
schema_version: "1"
kind: skill
name: manual-siblings
version: v18
summary: "Manual: the work you start but never perform. Account and person research, discovery, design legs, and where to read each outcome."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
<!-- sources: research/2026-09-13-head-of-abm-manual/E-runtime-and-sibling-agents.md §3.0 (the shape of every sibling), §3.1 (account research), §3.2 (person research), §3.3 (discovery), §3.4 (onboarding synthesis), §3.5 (the design leg), §3.6 (legacy tools still granted); docs/superpowers/specs/2026-09-13-head-of-abm-operating-manual-design.md §1 (the ingestion tool has no engine at any composition root) -->
# Siblings: what you start, and what you never do yourself

**You never run research.** Every sibling below is a fleet job: your tool call writes durable
rows, offers a task to the work queue, and returns. A successful result means queued or
replayed, never finished. Say it is running; never say it is done.

| Sibling | You start it with | Ends on | Where you read the outcome |
| --- | --- | --- | --- |
| account research | `launch_arv2_account_research` | `completed` or `needs_review`; `suspended` is a pause | the run read, the accounts read, `project/status.md`, the account research read |
| person research | `launch_arv2_person_research`, or it is spawned by an account job's committee | the same | the same run read, with the caveat below |
| discovery | `launch_arv2_discovery` | the same | the discovery run read, and `status.md` |
| a design leg | `open_design_leg` | closed by Design, not by you | the leg's closing summary re-entering the thread |

## Account research

One job is one account, with its own lease and its own failure. Before a single model call, the
job re-checks the ICP artifact digest and the agent profile digest from the launch; moved bytes
mean a relaunch, not a resume.

The account agent holds twelve tools of its own and works to a constitution: a target lock
against same name contamination, an evidence law where every assertion carries a verbatim quote
and its url and "not found" is a correct answer, free sources before paid ones, and finalize
once. The ICP is a charter for what to look for, and it never vetoes research.

The job's model rounds, tool calls per round, wall clock and jobs per worker are deployment
settings. Near its round limit, the research agent is told to wrap up. It then finalizes as
blocked with what it saved, and the job shows as needing review. There is no total call cap and
no zero yield cap, by ruling. A real account job has been observed at 12 rounds and 113
claims for about a dollar; expect minutes, not seconds.

It produces claims, a finalization receipt (reason, summary, fit verdicts, gaps), the ICP fit
verdict claims, link audit annotations, the committee's contacts and their person jobs, and one
activity event. The run's status is recomputed from its jobs.

The account's overview page is a separate thing: it is written lazily, when a human first opens
that screen. Your own read does not write it.

## Person research

Most person jobs are automatic: the account job's committee step creates one per confirmed
member, inside its settling transaction. You can also launch people explicitly, but only the
ones the human's current message names, and only for contacts that already exist. The launch
never creates a person.

The person agent has eleven tools, is locked to the subject by that person's verified
employment history, and never synthesises an email. A deterministic compliance pass runs over
everything it wrote before any of it is readable: minors are redacted, sensitive categories are
redacted with the category named, rows with no quote or url are marked unevidenced, and a claim
carrying a phone number, personal email or home address is dropped whole. It produces no fit
verdicts and no committee candidates; those are the account job's.

Same three caps as the account agent. Observed wall time per person: six to thirteen minutes.

**The caveat.** A committee person job lives in the same run as its account job, and the run
read's rows carry no subject type, so person jobs appear as extra rows sharing the account's
id. The count of person jobs is visible only in `status.md`. See `.deepagent/skills/manual-accounts-research/v18/SKILL.md`.

## Discovery

Composed only where the lane is enabled and a provider key is configured; otherwise the tool
refuses and nothing runs. One run per request digest, so asking the same thing twice is one run
and one bill. Wall clock 1,800 seconds. How a run works, what the verdicts and dispositions
mean, and how to read the tallies, is `.deepagent/skills/manual-discovery/v18/SKILL.md`.

## Persona synthesis

Personas are not a sibling's work here: they are yours to write, at
`project/audience/persona-<key>.md`, for the key this project pinned. The procedure is the
`persona-authoring` skill. Onboarding synthesis still writes the brand's personas from the
onboarding flow, but it no longer serves this surface, so there is nothing here to start and
nothing to wait for.

The Personas section of `status.md` is still where a persona document shows up once it lands,
and the document itself appears as a file in the audience folder.

## The design leg

Opening a leg starts the design work at once. In the same step that opens the leg, the platform
queues the leg's first design turn from the human's own message on this turn, so the human does
not need to send anything else to begin, and you should not ask them to. The tool itself makes no
provider call; the queued design turn is what spends. The leg row's existence **is** the routing
rule: while the leg is open, every message the human sends on this thread goes to Design.

Three things follow, and all three matter:

- **You do not run while a leg is open.** You cannot check in, and you will not see the thread
  again until the leg closes. Tell the human the design session is open and what is being made,
  and end your turn so the design can run. Queued is not finished: never say the design is done.
- **You cannot close a leg.** Only Design can. A closing summary is what you resume with, and
  you never see the design transcript, only that summary.
- **A leg you open may never hand the thread back.** The exit judge is built with a timeout the
  gateway refuses, so it always fails and the fail safe treats every exit intent as continue.
  Saying "lock it in" does not close the leg today. Do not promise the human that it will.

A gate cannot be answered while a leg is open, so do not leave an approval pending and then
open one.

Design owns dimensions, formats, units and page sizes. Design sees the brief, not this
conversation, so the brief carries the human's own ask and everything Design needs from you.

### How to write the brief for a page

Your brief gives Design the direction. Design writes all the words on the page itself, so describe
what the page should achieve and what it can draw on. Do not write the page's copy. Split the brief
into two parts under these headings.

**For the page**
- What the page is for, who will read it, and the one action you want them to take.
- The angle: why this account, why now, and the argument the page should make.
- A suggested structure: the sections in order, and what each one should get across.
- The facts Design can draw on, each with where it came from (a claim, a research section, or a
  seller file). These are material for Design to work with, not wording to copy.
- Customer stories that fit: who the customer is, the person and their role, and the result as
  theirs.

**Notes for Design, never shown on the page**
- What must not be claimed, and why.
- Limits of the evidence, for example a number a company published about itself.
- Who is on the buying committee and what each person cares about. Use this to shape the page, but
  do not name these people on an account page.
- Anything else Design should know that the visitor should not read.

In neither part describe the prospect's own product negatively.

### When the account has not been researched

If the human asks for a page for one account and that account has no research, tell them the page
can only talk about the seller, say what research would add, and offer to run it first. If they
want to go ahead without it, open the design leg. This is a recommendation, never a requirement.

## Tools you hold that lead nowhere

- `propose_field` and `propose_source` are live, but the research lane registers an unknown
  field itself when it writes a claim, so a proposal made here is a conversation artefact
  rather than how fields are actually born.
- `submit_ingestion` is a material capture path into the claim store, unrelated to account
  research, and its ingestion engine is not composed at any production entry point, so treat it
  as unavailable here.

Each of these, with its exact inputs and refusals, is in `.deepagent/skills/manual-tools/v18/SKILL.md`.
