---
schema_version: "1"
kind: skill
name: manual-glossary
version: v16
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

- **added_via** how an account joined a project: `discovered`, `imported`, `manual` or `directive`. A launch stamps `manual` too, so it does not mean a person typed it. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **approved** a human recorded the approval decision on a discovered candidate. It is the only decision the store can hold. `.deepagent/skills/manual-discovery/v16/SKILL.md`
- **assumptions** a field on the finalization. Stored durably, shown to nobody. `.deepagent/skills/manual-turn/v16/SKILL.md`
- **attached refs** the subjects the human attached to this message, in their order. Words like "these" and "them" name exactly those. `.deepagent/skills/manual-workspace/v16/SKILL.md`
- **awaiting_input** an honest terminal status meaning you need a human answer. It ends the turn; the human replies in a new one. `.deepagent/skills/manual-turn/v16/SKILL.md`
- **blocked** an honest terminal status meaning an external gate prevents progress. `.deepagent/skills/manual-turn/v16/SKILL.md`
- **brand library** the `brand/` mount: what the platform researched about this brand, with `brand/index.json` as its manifest. `.deepagent/skills/manual-workspace/v16/SKILL.md`
- **buying committee** the people under an account with a seat: champion, economic buyer, technical evaluator, blocker, user. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **capability map** the generated block appended to your prompt that states what you hold and what is unavailable. It is authoritative. `.deepagent/skills/manual-gates-authority/v16/SKILL.md`
- **claim** one typed fact about one resolved entity, with its provenance attached. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **claim flavor** `field_claim` (a value with a span), `discovery` (admission evidence), or `derived` (an inference over supporting claims). `.deepagent/skills/manual-claims/v16/SKILL.md`
- **committee_cap** how many committee members an account job may seat. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **completed** the honest terminal status for a turn whose outcome is durably complete. `.deepagent/skills/manual-turn/v16/SKILL.md`
- **confirmed** a document version a human approved at a gate. Only the gate mints it. `.deepagent/skills/manual-documents-decisions/v16/SKILL.md`
- **corroborations** how many independent tier 3 or better sources agreed with a claim. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **current value** the merged single answer for a field. It is not what you read here; you read live claims. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **decisions.md** the compiled file of what this human told this project, in their own words. `.deepagent/skills/manual-workspace/v16/SKILL.md`
- **derived_from** the brand profile a project local ICP variant adapts. `.deepagent/skills/manual-documents-decisions/v16/SKILL.md`
- **design leg** a durable row that reroutes this thread's messages to Design until Design closes it. `.deepagent/skills/manual-siblings/v16/SKILL.md`
- **directive_text** the human's own words about what to look for, carried free text on a research run. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **disposition** what a verified discovery candidate is: `pending`, `pass`, `partial`, `unclear`, `duplicate_of_existing`, `found_before`. There is no `fail`. `.deepagent/skills/manual-discovery/v16/SKILL.md`
- **display gate** the ordered tests that decide which claims a page or a read may show, each exclusion counted. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **effort** a research run's dial: `full`, `reduced` or `cheap-pass`. The agent implements full mode only today. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **evidence span** the verbatim quote a claim's value rests on. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **excluded** the counts a read returns for claims it held back, keyed `sensitive`, `unverified`, `outreach_unsafe`. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **execution id** the identity of one turn's execution, derived from the turn, so every retry reuses it. `.deepagent/skills/manual-turn/v16/SKILL.md`
- **failure_code** the lowercase reason a failed turn or job carries. You never see your own turn's code. `.deepagent/skills/manual-turn/v16/SKILL.md`
- **field key** the registered field a claim asserts. `.deepagent/skills/manual-fields/v16/SKILL.md`
- **finalize_turn** the one tool that ends a turn. Nothing else ends one successfully. `.deepagent/skills/manual-turn/v16/SKILL.md`
- **fit** a discovery candidate's `passes / gates`, an unclear counted as half. Null means unscored. `.deepagent/skills/manual-discovery/v16/SKILL.md`
- **flagged** a claim surfaced for a human rather than silently resolved. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **found_before** a company an earlier discovery run of this project already found; a later run skips it without asking a gate. `.deepagent/skills/manual-discovery/v16/SKILL.md`
- **frozen** compiled once and pinned for the whole turn, so re-reading returns the same bytes. `.deepagent/skills/manual-turn/v16/SKILL.md`
- **gate** the durable question put to a human, append only, answered exactly once. `.deepagent/skills/manual-gates-authority/v16/SKILL.md`
- **gate receipt** the recorded human decision. It is the only authority for a confirmation; prose is not. `.deepagent/skills/manual-gates-authority/v16/SKILL.md`
- **guard** the check that overturns a discovery verdict the evidence does not support, making it unclear. `.deepagent/skills/manual-discovery/v16/SKILL.md`
- **human-only tool** a capability no model surface may hold, disclosed by name in your map. `.deepagent/skills/manual-gates-authority/v16/SKILL.md`
- **icp pin** this project's one confirmed ICP version, named by document id and never moved automatically. `.deepagent/skills/manual-documents-decisions/v16/SKILL.md`
- **identity binding** whether a contact claim is `strong` (it is this person) or `weak` (same name only). `.deepagent/skills/manual-claims/v16/SKILL.md`
- **in_progress** a run or job that is running. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **job** one research subject: one account, or one person. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **lenient write** the claim write gate on this lane: what a strict gate would refuse becomes a durable marker instead of a dropped fact. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **limit_millicents** the ceiling checked against one call's estimate. It is not a running total and not a burn down. `.deepagent/skills/manual-gates-authority/v16/SKILL.md`
- **live claim** a claim that has not been superseded. Reads here serve live claims, several per field included. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **merge loser** an entity found to be the same company or person as another; every read drops it silently. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **needs_review** a run or job that **failed and is waiting for a human**. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **not_started** a job that exists and has not begun. An account with no job at all has no status row. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **onboarding run** a `full` brand walk or a `personas` run for one pinned ICP. `.deepagent/skills/manual-documents-decisions/v16/SKILL.md`
- **outputs** the folder snapshotted to artifacts at finalize, and immutable afterwards. `.deepagent/skills/manual-workspace/v16/SKILL.md`
- **outreach_safe** appropriateness, not accuracy. A false claim reaches only a restricted section and is dropped from the claims read. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **pass** which search produced a discovery candidate. A run of the search you write records `strict`; `relaxed` appears only on runs from before 2026-09-30. `.deepagent/skills/manual-discovery/v16/SKILL.md`
- **persona** a committee seat: champion, economic buyer, technical evaluator, blocker, user. Display order differs from that list. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **pinned** bound to one exact version by id and digest for the whole turn or the whole run. `.deepagent/skills/manual-documents-decisions/v16/SKILL.md`
- **plan card** what a `domain_refs` entry of an allowed object type renders as in the chat. `.deepagent/skills/manual-turn/v16/SKILL.md`
- **prefixes** the claim families an account actually holds, returned by the read so you can narrow without guessing. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **product selection version** the whole confirmed product set as one version. A change is a new gate and a new version. `.deepagent/skills/manual-documents-decisions/v16/SKILL.md`
- **project library** the `project/` mount, shared by every thread of the project. `.deepagent/skills/manual-workspace/v16/SKILL.md`
- **promotion** a claim leaving `unverified`. Nothing performs it on this deployment. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **proposed** a document version that has been drafted and not confirmed. `.deepagent/skills/manual-documents-decisions/v16/SKILL.md`
- **receipt** the bounded record a successful governed call returns. Substantive output stays behind references. `.deepagent/skills/manual-turn/v16/SKILL.md`
- **refreshing** a non terminal account job newer than a completed one for that account. Person jobs never set it. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **rejected (claim)** a judge or the use gate refused the claim. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **rejected (gate)** the human closed the subject. It confirms nothing. `.deepagent/skills/manual-gates-authority/v16/SKILL.md`
- **relaxed pass** the platform's own loosened search, used only by runs from before 2026-09-30. Runs today never loosen by themselves; loosening is your decision after a run ends. `.deepagent/skills/manual-discovery/v16/SKILL.md`
- **repair budget** three governed refusals per turn, shared across tools, plus two separate finalize repairs. `.deepagent/skills/manual-turn/v16/SKILL.md`
- **replayed** this operation already happened and its stored result was returned; the tool did not run again. `.deepagent/skills/manual-turn/v16/SKILL.md`
- **research directive** a row of the retired lane. Nothing on this lane executes a confirmed directive; the launch takes free text instead. `.deepagent/skills/manual-siblings/v16/SKILL.md`
- **restricted section** a page section that exists to show the operator facts they must not use: Watch-outs, Context only, Do not mention. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **reuse scope** a claim's privacy class, `public_footprint` or `tenant_private`. It is not a sharing grant. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **revised** a gate decision meaning "I want changes". It closes the gate and confirms nothing. `.deepagent/skills/manual-gates-authority/v16/SKILL.md`
- **round** one model call. Every round must call a tool. `.deepagent/skills/manual-turn/v16/SKILL.md`
- **route_key** the short stable label a recorded decision is filed under. `.deepagent/skills/manual-documents-decisions/v16/SKILL.md`
- **run** the authorization record for research or discovery: the exact subjects, pins and digests a human's approval covers. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **scratch** your notebook folder, which persists across the turns of this chat. `.deepagent/skills/manual-workspace/v16/SKILL.md`
- **sensitive** a special category use class. It never enters any display section, restricted ones included. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **servable** a document with bytes that has not been superseded: `ready`, `proposed` or `confirmed`. `.deepagent/skills/manual-documents-decisions/v16/SKILL.md`
- **settled** a job's terminal transaction, including the committee step for an account job. Not merely "it stopped". `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **shown** a discovery candidate whose disposition is `pass`, `partial` or `unclear`, meaning the human was shown it. `.deepagent/skills/manual-discovery/v16/SKILL.md`
- **signal_priority** 1 active buying intent, 2 qualifying fact, 3 context. The display sort, never a gate. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **source tier** 1 deterministic API, 2 official scrape, 3 reputable third party, 4 model synthesis. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **stage** how far a job has walked: `deep_research`, `synthesis`, `committee`, `member_research`. Only `status.md` carries it. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **statement** the durable record of something the human said, bound to their exact words by offsets and a digest. `.deepagent/skills/manual-documents-decisions/v16/SKILL.md`
- **status.md** the compiled project state file, frozen for your turn. `.deepagent/skills/manual-workspace/v16/SKILL.md`
- **strict pass** a discovery search with the full criteria. Every round of a run of the search you write is strict. `.deepagent/skills/manual-discovery/v16/SKILL.md`
- **superseded** replaced by a newer row or version, which the older one points at. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **superstep** one step of the turn's graph. The superstep ceiling, not any plan ceiling, is what ends a long turn. `.deepagent/skills/manual-limits/v16/SKILL.md`
- **suspended** a run or job that is **paused, not failed**. Every worker restart suspends what was in flight. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **target_count** how many companies the human asked a discovery run for. The first search asks the provider for exactly this many. `.deepagent/skills/manual-discovery/v16/SKILL.md`
- **tier (account scoring)** a mechanism this lane does not run: no account carries a scoring tier and no tier checkpoint is reached. `.deepagent/skills/manual-accounts-research/v16/SKILL.md`
- **unapproved** a discovery candidate nobody chose. It is not rejected; rejection is unrepresentable. `.deepagent/skills/manual-discovery/v16/SKILL.md`
- **unevidenced** a write marker meaning the claim carries no quote, so nobody can check it. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **unmapped** the honest route for a statement that fits no other: it keeps the quote without asserting a fact. `.deepagent/skills/manual-documents-decisions/v16/SKILL.md`
- **unverified** a claim's born state, and the state of essentially every claim here, because verification is off. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **use class** the governance class of personal data: `professional-public`, `personal-public-non-sensitive`, `sensitive`. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **verified (claim)** corroboration or the faithfulness judge promoted it. `.deepagent/skills/manual-claims/v16/SKILL.md`
- **verified (discovery)** at least one gate verdict exists for the candidate, which is to say it was actually judged. `.deepagent/skills/manual-discovery/v16/SKILL.md`
- **withheld tool** a tool this surface does not install, so there is nothing to decline. `.deepagent/skills/manual-gates-authority/v16/SKILL.md`
- **write markers** open notes stamped on a claim by the lenient write gate, such as `source_missing` or `proposed_field`. `.deepagent/skills/manual-claims/v16/SKILL.md`

Two gate kinds exist in the schema that you cannot open at all, `plan_approval` and
`budget_approval`, plus `product_selection`, the single product predecessor. If a human asks
you to open one, say plainly that no tool of yours does. `.deepagent/skills/manual-gates-authority/v16/SKILL.md`
