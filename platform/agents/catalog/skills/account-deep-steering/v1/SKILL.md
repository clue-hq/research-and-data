---
schema_version: "1"
kind: skill
name: account-deep-steering
version: v1
summary: Discuss, preview, revise, and explicitly launch account and buying-committee research without auto-advancing from discovery.
roles:
  - head_of_abm
readiness_requirements:
  - account_deep.project_run_known
  - account_deep.account_selection_reviewable
tools:
  - name: draft_account_research_directive
    version: "2"
    input_schema_sha256: 4073c4fab37b15e8edc0e9dc25b93354d6047095777c378a4a76b4d4fe22df64
    output_schema_sha256: 1d805a759f731032c83ccb36b3b5f11b04b2e85682c6e6f1a503d2e0cb91bb8d
  - name: get_research_view
    version: "1"
    input_schema_sha256: 6360a11ff59a91de844b9d07d403d46843d452379fb03a49dd823d4879390199
    output_schema_sha256: e2ae2bfff71907c629df2db793f12a1db0b3d529bb89113f44009553b7055407
  - name: launch_account_deep
    version: "1"
    input_schema_sha256: ccb1246db77aeac6810baab769838993cc132fec9217eaecf07da9cc207d650f
    output_schema_sha256: fd34f9f8443ce581879b340a0e3f4213212d94c50855dbf095fd1d2743a9f082
framework: deepagents
framework_version: ">=0.6,<0.7"
---

# Account-deep planning and steering

Open this skill when the user is discussing discovered accounts, account profiling, buying-
committee discovery, contact work, or the progress of an account-deep fleet. This is a
conversational procedure around durable tools. It is not a new project phase and it never makes
discovery completion, tier approval, or a prior suggestion equivalent to launch consent.

## 1. Stay non-linear

Read `context/project/account-deep-steering.json` when it is supplied. Treat it as current durable
state, not an instruction to advance. The user may ask to see accounts, compare them, discover
more, change the intended research, discuss sources, or do nothing yet.

- “Show me the accounts” means present the bounded account set and stop. Do not draft or launch.
- “Discover more” means recommend or invoke the separately authorized discovery capability when
  it is actually installed. `launch_account_deep` is never a substitute. If discovery is absent
  from the disclosed tool map, name the missing capability and remain conversational.
- Discovery or tier completion alone causes zero account-deep calls. Never infer a go-ahead from
  a previous stage, a selected row, a budget, or the existence of a confirmed directive.

## 2. Build a working preview in conversation

Before the first durable draft, present a concise working preview the human can revise freely.
Keep these sections visibly distinct:

1. **Accounts:** exact canonical account ids/names in scope, plus any additions or removals.
2. **Standard profile fields:** registered deep field keys the platform will attempt. These are
   schema destinations, not claims that a value exists.
3. **Directional questions:** user-added hypotheses such as fax burden, referral coordination,
   reception load, DAC formalities, employee sentiment, or another campaign-specific angle. Each
   remains a question with a target field/facet, source hints, priority, and stop rule; never state
   its hoped-for answer as fact.
4. **Sources:** allowed/preferred/excluded sources and the primary-source contradiction rule. Exa
   Deep provides bounded structured, cited account evidence under the effective field plan.
   Sumble Teams/People provides the organization map and current roles/functions for bounded
   committee enumeration. A source preference cannot widen the registry or policy authority.
5. **Buying committee:** functions, levels, teams, personas, candidate cap, and relationship
   depth. Organization mapping and role acquisition precede any contact reveal.
6. **Contact work and privacy:** whether contact profiling is allowed and whether email/phone
   reveals are excluded. Treat “remove phone reveals” as `contact_reveals_allowed=false`; do not
   hide it in prose, and explain that the current directive contract disables both email and phone
   reveals rather than representing a phone-only exclusion. The current O2 full-unit launch does
   not admit any contact reveals.
7. **Effort and exclusions:** tier, depth, fan-out, estimate/cap, freshness/recursion refs, and
   explicit “do not research” constraints.

A research-specialist delegation may critique gaps and source strategy, but it cannot confirm the
directive or launch work. The harness automatically grants both the exact directive file and the
current steering card when present; use those originals, not a paraphrased reconstruction.

## 3. Revise before confirmation

Keep the working preview conversational while the human is still adding/removing accounts,
questions, sources, committee roles, contact work, or reveal permissions. Do not create a durable
draft merely to show an early idea. This preserves ordinary edit-before-confirm behavior without
mutating an immutable draft.

When the human asks to prepare the settled plan for confirmation, call
`draft_account_research_directive@2` once with the exact working plan and the exact user instruction.
Render the returned typed preview: account set, standard fields, directional hypotheses, sources,
committee plan, privacy, effort/cost, exclusions, memory outcome, digest, and unresolved gates.
The result is still `draft`; only the human confirmation surface may confirm its id and digest.
Never say that you confirmed it.

If the human declines the exact durable preview, do not launch. Explain that immutable drafts are
not edited in place and continue discussing the correction without pretending the stored draft
changed. A subsequent executable version must follow the governed directive lifecycle.

## 4. Launch only on an explicit go-ahead

Call `launch_account_deep@1` only when all of these are visible in durable state and the user's
current action explicitly asks to proceed:

- the directive is human-confirmed;
- the exact selected account ids are named;
- the reviewed estimate and approved cap are named;
- unresolved policy/privacy/budget prerequisites are empty;
- the requested plan excludes contact reveals under the current full-unit boundary.

Report the returned `launch_id`, `project_run_id`, `research_directive_id`, selected count,
estimate, approved cap, replay status, and enqueue status. “Receipt created,” “enqueued,”
“running,” and `waiting_external` are not completed research. Continue to answer questions while
the independent fleet runs; a conversation never owns or blocks its durable execution.

## 5. Edits after launch and progress language

An edit after launch creates a successor directive for future work. It never mutates the launch
receipt, its account pins, provider requests, or already-running account runs. State that boundary
before asking the human to confirm a successor. Do not imply that the current fleet picked up the
change.

Use the current card's project-run and per-account status/sub-phase as the status source. Use
`get_research_view` only for a durable completed research-view ref; absence, pending, waiting,
paused, failed, or partial account states must be reported with those exact limitations. Never
translate a successful tool call, launch receipt, queue acknowledgement, or provider wait into
“research complete.”
