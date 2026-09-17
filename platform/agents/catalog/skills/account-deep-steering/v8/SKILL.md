---
schema_version: "1"
kind: skill
name: account-deep-steering
version: v8
summary: Discuss, exactly scope, confirm, separately launch, and read account and contact research fleets without automatic progression.
roles:
  - head_of_abm
readiness_requirements:
  - account_deep.project_run_known
  - account_deep.account_selection_reviewable
tools:
  - name: draft_account_research_directive
    version: "5"
    input_schema_sha256: 5cf321a59b2aa856a98ecca7ed85e90b0c6c89eb2f4092bbe74042f4e5b23292
    output_schema_sha256: 1d805a759f731032c83ccb36b3b5f11b04b2e85682c6e6f1a503d2e0cb91bb8d
  - name: get_research_view
    version: "1"
    input_schema_sha256: 6360a11ff59a91de844b9d07d403d46843d452379fb03a49dd823d4879390199
    output_schema_sha256: e2ae2bfff71907c629df2db793f12a1db0b3d529bb89113f44009553b7055407
  - name: open_directive_confirmation_gate
    version: "1"
    input_schema_sha256: 12d9a95bb3d8b4dc76fab84022edc45eeb1fb8fbd14aa18b0c6b597dff3dad69
    output_schema_sha256: d07d0ec4416189ddf5395245bda7207587e256bfdc2f16b7e7a6f949e712786c
  - name: launch_account_research
    version: "1"
    input_schema_sha256: 0353c1ee6f11954e96dea5b243ce36313a6b447d93af49aa75476238350cd9a2
    output_schema_sha256: 1d8c05f105846db02c980f9da60d83b25a22f84ec3224b7cffd4d02a49d2f960
  - name: launch_selected_account_research
    version: "1"
    input_schema_sha256: 9e4fa1021449e79ad4e0bb1851b445d896510fd0dc9ebbf2f63c769be74cfacc
    output_schema_sha256: 1d8c05f105846db02c980f9da60d83b25a22f84ec3224b7cffd4d02a49d2f960
  - name: read_account_research_run
    version: "1"
    input_schema_sha256: 7435881a205953298a535dde450a17634f5f86beaa18848f9a1f0a505056ed52
    output_schema_sha256: 5a2e786ce447ab94f9c61545b4fae1cfd8d020275f8ba3cf2f6fb042b716ffd0
  - name: launch_contact_research
    version: "1"
    input_schema_sha256: b3eed222972f43c1b46c49fe7c2aad74edb6674c6f80851b877e169441fe413c
    output_schema_sha256: 564042e1d84be2e27e350c3acc1c123d936508430175584d16615c1cd3382b1d
  - name: read_contact_research_run
    version: "1"
    input_schema_sha256: 7435881a205953298a535dde450a17634f5f86beaa18848f9a1f0a505056ed52
    output_schema_sha256: 5a2e786ce447ab94f9c61545b4fae1cfd8d020275f8ba3cf2f6fb042b716ffd0
framework: deepagents
framework_version: ">=0.6,<0.7"
---

# Account and contact research steering

Use this skill for discovered-account discussion, account profiling, buying-committee work,
contact selection, or account/contact fleet status. This is a conversational procedure around
explicitly requested durable launches. It is not a compulsory platform phase.

## Stay non-linear

The user may inspect accounts, discover more, refine questions, revise source policy, launch a
subset, or do nothing. Discovery and tiering never imply account research. A completed account
fleet never implies contact selection or contact research.

Before account launch, establish the exact accounts, fields, directional questions, admitted
source plans, committee scope, privacy constraints, and unresolved prerequisites. Keep qualitative
Exa questions distinct from structured Sumble organization fields. Do not invent deterministic
attempts for fields whose effective source plan starts with Exa.

## Co-define the buying committee with the user before you draft one

The committee plan is a decision you and the user reach together, never a field you quietly fill
in at draft time. Before drafting any account-research directive that will discover a committee —
any directive whose sources include `sumble_people` — settle two things in conversation:

1. **What this project is selling.** When confirmed product context already answers this, say what
   you have and ask the user to confirm it; do not re-ask from zero. Ask openly only when the
   project carries no confirmed product.
2. **Who fills the four persona shoes at this kind of company.** Champion, economic buyer,
   technical evaluator, blocker — for the target companies actually in front of you, expressed as
   functions, seniority levels, and job titles the user recognizes. Propose a first mapping from
   what you know about the product and the accounts and ask the user to correct it; one concrete
   proposal a user can edit beats an open question.

Then encode the outcome into `directive.committee_plan` — the only committee authority the
per-account research agents ever receive. They copy it and never invent position specs of their
own, so whatever you leave out is unavailable downstream:

- `personas` — always name the personas you agreed to look for, using the platform's persona keys
  `champion`, `economic_buyer`, `technical_evaluator`, `blocker`.
- `functions` — the job functions those personas actually sit in at these companies.
- `levels` and `teams` — the seniority bands or named teams the discussion settled. Leave a
  selector empty only when the user genuinely wants that dimension unrestricted.
- `candidate_cap` and `relationship_depth` — the breadth and reach the user asked for.

An all-empty plan is a real statement and it is almost never the one you mean: with no functions
confirmed, the account agent must pick target functions itself from whatever evidence its account
happens to carry, and a plausible guess in the wrong vocabulary silently drops real committee
members. That happened live — an empty plan against a multi-site physician group lost two
physician-executives because the account agent guessed a function word the people provider's
taxonomy does not use.

**Speak the provider's vocabulary as well as the user's.** Candidate admission never filters on
functions — every provider-returned person is admitted (founder ruling 2026-08-20) — but your
`functions` are the position brief the account agent judges personas against, and the
account agent may narrow your `functions` but may never invent one, so a function the plan omits
cannot be recovered later. When the user's word for a function is not the word a people provider is
likely to return, carry both as separate entries — `Clinical` alongside `Physician` in healthcare,
`Information Technology` alongside `IT`, `Finance` alongside `Accounting`. Synonyms cost nothing
and are the difference between a found committee and an empty one. Keep every entry a short
function word, never a sentence.

A plan that departs from the defaults states committee intent, so it must be executable: include
`sumble_people` in `source_policy.allowed_source_keys` and keep committee discovery allowed in the
privacy policy. Leave `committee_plan` at its defaults only to state deliberately that this
directive discovers no committee.

If the user will not work through the personas, neither stall nor leave the plan empty: propose the
persona-to-position mapping yourself, put it in the plan, and state it in plain words — persona by
persona, with the functions and levels you chose — in the same message that carries the directive
confirmation gate, so the human approving the directive is approving that mapping too. On the
exact-subject same-turn launch path there is no gate to read, so state the mapping in that turn's
message instead. This is a conversation you owe the user, not a check anything will enforce on you.

## A message with Account references is an exact subject, never a suggestion

When the current human message carries Account references, words such as “these,” “them,” or “the
selected accounts” mean exactly those ordered references. Never add another Account, infer the
whole table or project, replace an ineligible Account, or turn Contact references into their parent
Accounts. You may narrow only when the user explicitly names a subset.

If the user explicitly commands account research in that same message, draft the directive with
an explicit Account scope equal to those references. When the FI pilot has budget controls off,
call `launch_selected_account_research@1` in the same turn with that exact ordered set. The server
derives the human action from the captured turn, rechecks membership and permission, requires the
latest directive to name the identical set, computes the estimate itself, and refuses this path if
budget controls require a gate. A successful result means launched/enqueued or replayed; it never
means research completed.

Do not use the direct tool when the message merely asks to discuss, compare, preview, explain, or
revise research. Attaching references expresses context; the user's words must explicitly request
the launch.

## Use the pinned research vocabulary; never manufacture field keys

The account-deep steering card carries the exact approved tier for every selected Account. The
directive's `effort_policy.tier` must be exactly that Account row's approved tier value (for
example `high`) — not a project-wide guess, and never the word `comprehensive`: `comprehensive`
names the field-breadth profile only and is not a tier, so a directive carrying it as the effort
tier can never match the account's human-selected tier checkpoint and its confirmation gate will
be refused.

Field breadth is a contract, not a choice. The normal account research request is the complete
fixed 21-field account profile: call `draft_account_research_directive@5` with
`profile="comprehensive"` and omit `directive.field_keys` entirely (the key is optional and must
stay absent), and the tool expands the directive to all 21 rows
itself. Do not retype the profile, do not shorten it, and do not describe a narrower set as the
normal request. Use `profile="custom"` with an explicit field list only when the user explicitly
asks for a narrower subset; declaring `comprehensive` together with an explicit field list is
refused as an ambiguous request. Every field must still be a registered deep field that is active
in the pinned ICP.

`account.summary` and `account.value_narrative` are derived outputs after acquisition; never put
them in a research directive. Never invent a field from natural-language phrasing.

Exactly four account field-sources are permitted: `exa_deep`, `sumble_organizations`, `sumble_jobs`
and `sumble_tech_stack`. `exa_deep` is the qualitative source (operational pain, strategic moves,
resonance, revenue); `sumble_organizations` carries structured firmographics and funding;
`sumble_jobs` owns engineering hiring velocity; `sumble_tech_stack` owns the technology stack. The
`core.*` identity and firmographic rows are reused from discovery when the existing claim is fresh,
so a comprehensive directive does not mean every row is re-bought. When a field has no frozen
source plan or source-profile override, choose only active sources whose registry manifest declares
capability for that exact field. Use `sumble_teams` or `sumble_people` only when committee
discovery is enabled and requested. The server validates all of these bounds.

With budget controls off, an explicit launch command for the current Account references should be
drafted and launched in the same turn. Do not introduce another spend decision, product-context
compilation, or user confirmation when the subject, fields, sources, and privacy scope are already
unambiguous.

## The durable gate remains the general route

For a launch not admitted by the exact current-message path, call
`open_directive_confirmation_gate@1` with the settled project run, directive, and Account set. The
platform computes the maximum spend and records the directive revision on a durable gate addressed
to the person whose turn you are answering. End the turn awaiting input and do not launch in that
turn.

When the structured human answer approves the gate, the platform has already confirmed the exact
directive. Call `launch_account_research@1` with the same Account set and stored maximum. Rejection
or revision confirms nothing. Never treat your own summary, inferred agreement, or a previous gate
as authority for a changed directive.

Call `launch_account_research@1` only after the current user action explicitly approves the exact
confirmed directive, account set, estimate, and cap.

Both launch routes create one Account research job per admitted Account on the detached fleet.
They produce Account claims and an organization-map-backed committee, never Contact deep research.
Use `read_account_research_run@1` for progress and terminal results.
A queue receipt or provider wait is not completed research.

Contact research remains separately governed. A Contact selection is not an inferred committee,
and attached Contact references never authorize Account research. Only after an exact durable
Contact selection and the applicable confirmation may you call `launch_contact_research@1`; use
`read_contact_research_run@1` for progress. Email/phone acquisition and validation remain separate.

Keep conversing while a detached fleet runs. Report durable run ids, states, result refs, review
refs, and spend. Never translate a successful tool call, launch receipt, replay, or model stop into
successful research.


