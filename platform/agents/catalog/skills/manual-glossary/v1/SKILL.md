---
schema_version: "1"
kind: skill
name: manual-glossary
version: v1
summary: "Manual: every word the platform uses at you, one line each, alphabetical, with the chapter that defines it properly."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
<!-- sources: research/2026-09-13-head-of-abm-manual/C-domain-model.md (the closing list of 22 terms the agent has no word for) plus every term defined by the other chapters of this manual -->
# Glossary

One line per term. The chapter at the end of the line is where it is defined properly. When two
things share a word, both lines are here: read the one that matches where you saw it.

- **added_via** how an account joined a project: `discovered`, `imported`, `manual` or `directive`. A launch stamps `manual` too, so it does not mean a person typed it. manual:accounts-research
- **approved** a human recorded the approval decision on a discovered candidate. It is the only decision the store can hold. manual:discovery
- **assumptions** a field on the finalization. Stored durably, shown to nobody. manual:turn
- **attached refs** the subjects the human attached to this message, in their order. Words like "these" and "them" name exactly those. manual:workspace
- **awaiting_input** an honest terminal status meaning you need a human answer. It ends the turn; the human replies in a new one. manual:turn
- **blocked** an honest terminal status meaning an external gate prevents progress. manual:turn
- **brand library** the `brand/` mount: what the platform researched about this brand, with `brand/index.json` as its manifest. manual:workspace
- **buying committee** the people under an account with a seat: champion, economic buyer, technical evaluator, blocker, user. manual:accounts-research
- **capability map** the generated block appended to your prompt that states what you hold and what is unavailable. It is authoritative. manual:gates-authority
- **claim** one typed fact about one resolved entity, with its provenance attached. manual:claims
- **claim flavor** `field_claim` (a value with a span), `discovery` (admission evidence), or `derived` (an inference over supporting claims). manual:claims
- **committee_cap** how many committee members an account job may seat. manual:accounts-research
- **completed** the honest terminal status for a turn whose outcome is durably complete. manual:turn
- **confirmed** a document version a human approved at a gate. Only the gate mints it. manual:documents-decisions
- **corroborations** how many independent tier 3 or better sources agreed with a claim. manual:claims
- **current value** the merged single answer for a field. It is not what you read here; you read live claims. manual:claims
- **decisions.md** the compiled file of what this human told this project, in their own words. manual:workspace
- **derived_from** the brand profile a project local ICP variant adapts. manual:documents-decisions
- **design leg** a durable row that reroutes this thread's messages to Design until Design closes it. manual:siblings
- **directive_text** the human's own words about what to look for, carried free text on a research run. manual:accounts-research
- **disposition** what a verified discovery candidate is: `pending`, `pass`, `partial`, `unclear`, `duplicate_of_existing`, `not_chosen_before`. There is no `fail`. manual:discovery
- **display gate** the ordered tests that decide which claims a page or a read may show, each exclusion counted. manual:claims
- **effort** a research run's dial: `full`, `reduced` or `cheap-pass`. The agent implements full mode only today. manual:accounts-research
- **evidence span** the verbatim quote a claim's value rests on. manual:claims
- **excluded** the counts a read returns for claims it held back, keyed `sensitive`, `unverified`, `outreach_unsafe`. manual:claims
- **execution id** the identity of one turn's execution, derived from the turn, so every retry reuses it. manual:turn
- **failure_code** the lowercase reason a failed turn or job carries. You never see your own turn's code. manual:turn
- **field key** the registered field a claim asserts. manual:fields
- **finalize_turn** the one tool that ends a turn. Nothing else ends one successfully. manual:turn
- **fit** a discovery candidate's `passes / gates`, an unclear counted as half. Null means unscored. manual:discovery
- **flagged** a claim surfaced for a human rather than silently resolved. manual:claims
- **frozen** compiled once and pinned for the whole turn, so re-reading returns the same bytes. manual:turn
- **gate** the durable question put to a human, append only, answered exactly once. manual:gates-authority
- **gate receipt** the recorded human decision. It is the only authority for a confirmation; prose is not. manual:gates-authority
- **guard** the check that overturns a discovery verdict the evidence does not support, making it unclear. manual:discovery
- **human-only tool** a capability no model surface may hold, disclosed by name in your map. manual:gates-authority
- **icp pin** this project's one confirmed ICP version, named by document id and never moved automatically. manual:documents-decisions
- **identity binding** whether a contact claim is `strong` (it is this person) or `weak` (same name only). manual:claims
- **in_progress** a run or job that is running. manual:accounts-research
- **job** one research subject: one account, or one person. manual:accounts-research
- **lenient write** the claim write gate on this lane: what a strict gate would refuse becomes a durable marker instead of a dropped fact. manual:claims
- **limit_millicents** the ceiling checked against one call's estimate. It is not a running total and not a burn down. manual:gates-authority
- **live claim** a claim that has not been superseded. Reads here serve live claims, several per field included. manual:claims
- **merge loser** an entity found to be the same company or person as another; every read drops it silently. manual:claims
- **needs_review** a run or job that **failed and is waiting for a human**. manual:accounts-research
- **not_chosen_before** a company an earlier run showed and the human did not choose; a later run does not re-surface it. manual:discovery
- **not_started** a job that exists and has not begun. An account with no job at all has no status row. manual:accounts-research
- **onboarding run** a `full` brand walk or a `personas` run for one pinned ICP. manual:documents-decisions
- **outputs** the folder snapshotted to artifacts at finalize, and immutable afterwards. manual:workspace
- **outreach_safe** appropriateness, not accuracy. A false claim reaches only a restricted section and is dropped from the claims read. manual:claims
- **pass** which search produced a discovery candidate: `strict` or `relaxed`. manual:discovery
- **persona** a committee seat: champion, economic buyer, technical evaluator, blocker, user. Display order differs from that list. manual:accounts-research
- **pinned** bound to one exact version by id and digest for the whole turn or the whole run. manual:documents-decisions
- **plan card** what a `domain_refs` entry of an allowed object type renders as in the chat. manual:turn
- **prefixes** the claim families an account actually holds, returned by the read so you can narrow without guessing. manual:accounts-research
- **product selection version** the whole confirmed product set as one version. A change is a new gate and a new version. manual:documents-decisions
- **project library** the `project/` mount, shared by every thread of the project. manual:workspace
- **promotion** a claim leaving `unverified`. Nothing performs it on this deployment. manual:claims
- **proposed** a document version that has been drafted and not confirmed. manual:documents-decisions
- **receipt** the bounded record a successful governed call returns. Substantive output stays behind references. manual:turn
- **refreshing** a non terminal account job newer than a completed one for that account. Person jobs never set it. manual:accounts-research
- **rejected (claim)** a judge or the use gate refused the claim. manual:claims
- **rejected (gate)** the human closed the subject. It confirms nothing. manual:gates-authority
- **relaxed pass** a widened second search, run only when a run came up short and the human or the run allows it. manual:discovery
- **repair budget** three governed refusals per turn, shared across tools, plus two separate finalize repairs. manual:turn
- **replayed** this operation already happened and its stored result was returned; the tool did not run again. manual:turn
- **research directive** a row of the retired lane. Nothing on this lane executes a confirmed directive; the launch takes free text instead. manual:siblings
- **restricted section** a page section that exists to show the operator facts they must not use: Watch-outs, Context only, Do not mention. manual:accounts-research
- **reuse scope** a claim's privacy class, `public_footprint` or `tenant_private`. It is not a sharing grant. manual:claims
- **revised** a gate decision meaning "I want changes". It closes the gate and confirms nothing. manual:gates-authority
- **round** one model call. Every round must call a tool. manual:turn
- **route_key** the short stable label a recorded decision is filed under. manual:documents-decisions
- **run** the authorization record for research or discovery: the exact subjects, pins and digests a human's approval covers. manual:accounts-research
- **scratch** your notebook folder, which persists across the turns of this chat. manual:workspace
- **sensitive** a special category use class. It never enters any display section, restricted ones included. manual:claims
- **servable** a document with bytes that has not been superseded: `ready`, `proposed` or `confirmed`. manual:documents-decisions
- **settled** a job's terminal transaction, including the committee step for an account job. Not merely "it stopped". manual:accounts-research
- **shown** a discovery candidate whose disposition is `pass`, `partial` or `unclear`, meaning the human was shown it. manual:discovery
- **signal_priority** 1 active buying intent, 2 qualifying fact, 3 context. The display sort, never a gate. manual:claims
- **source tier** 1 deterministic API, 2 official scrape, 3 reputable third party, 4 model synthesis. manual:claims
- **stage** how far a job has walked: `deep_research`, `synthesis`, `committee`, `member_research`. Only `status.md` carries it. manual:accounts-research
- **statement** the durable record of something the human said, bound to their exact words by offsets and a digest. manual:documents-decisions
- **status.md** the compiled project state file, frozen for your turn. manual:workspace
- **strict pass** the first discovery search, under the ICP's full criteria. manual:discovery
- **superseded** replaced by a newer row or version, which the older one points at. manual:claims
- **superstep** one step of the turn's graph. The superstep ceiling, not any plan ceiling, is what ends a long turn. manual:limits
- **suspended** a run or job that is **paused, not failed**. Every worker restart suspends what was in flight. manual:accounts-research
- **target_count** how many companies the human asked a discovery run for; `strict_count` is how many the provider is asked for. manual:discovery
- **tier (account scoring)** a mechanism this lane does not run: no account carries a scoring tier and no tier checkpoint is reached. manual:accounts-research
- **unapproved** a discovery candidate nobody chose. It is not rejected; rejection is unrepresentable. manual:discovery
- **unevidenced** a write marker meaning the claim carries no quote, so nobody can check it. manual:claims
- **unmapped** the honest route for a statement that fits no other: it keeps the quote without asserting a fact. manual:documents-decisions
- **unverified** a claim's born state, and the state of essentially every claim here, because verification is off. manual:claims
- **use class** the governance class of personal data: `professional-public`, `personal-public-non-sensitive`, `sensitive`. manual:claims
- **verified (claim)** corroboration or the faithfulness judge promoted it. manual:claims
- **verified (discovery)** at least one gate verdict exists for the candidate, which is to say it was actually judged. manual:discovery
- **withheld tool** a tool this surface does not install, so there is nothing to decline. manual:gates-authority
- **write markers** open notes stamped on a claim by the lenient write gate, such as `source_missing` or `proposed_field`. manual:claims

Two gate kinds exist in the schema that you cannot open at all, `plan_approval` and
`budget_approval`, plus `product_selection`, the single product predecessor. If a human asks
you to open one, say plainly that no tool of yours does. manual:gates-authority
