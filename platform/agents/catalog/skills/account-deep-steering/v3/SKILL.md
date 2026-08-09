---
schema_version: "1"
kind: skill
name: account-deep-steering
version: v3
summary: Discuss, gate, confirm, separately launch, and read account and contact research fleets without automatic progression.
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
  - name: open_directive_confirmation_gate
    version: "1"
    input_schema_sha256: 12d9a95bb3d8b4dc76fab84022edc45eeb1fb8fbd14aa18b0c6b597dff3dad69
    output_schema_sha256: d07d0ec4416189ddf5395245bda7207587e256bfdc2f16b7e7a6f949e712786c
  - name: launch_account_research
    version: "1"
    input_schema_sha256: 0353c1ee6f11954e96dea5b243ce36313a6b447d93af49aa75476238350cd9a2
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
separately confirmed durable launches. It is not a compulsory platform phase.

## Stay non-linear

The user may inspect accounts, discover more, refine questions, revise source policy, launch a
subset, or do nothing. Discovery and tiering never imply account research. A completed account
fleet never implies contact selection or contact research.

Before account launch, present the exact accounts, fields, directional questions, admitted source
plans, committee scope, privacy constraints, estimate, cap, and unresolved gates. Keep qualitative
Exa questions distinct from structured Sumble organization fields. Do not invent
deterministic attempts for fields whose effective source plan starts with Exa.

## The confirmation gate is the only route to a launch

When the directive is drafted and the account set is settled, call
`open_directive_confirmation_gate@1` with that exact project run, directive, and account set. The
platform computes the maximum spend itself and records it, together with the directive revision
being approved, on a durable gate addressed to the person whose turn you are answering. You do not
compute, estimate, negotiate, or restate the amount, and you do not choose who may answer.

Then end the turn awaiting input, carrying the returned gate reference. Do not call any launch
tool in that turn: the gate is a question, and the answer arrives as the user's own next turn.

The user's answer is a structured turn recorded by the platform. When it approves, the platform
has already confirmed the directive under that person's authority by the time you are woken, and
`launch_account_research@1` will accept the same account set at the same maximum spend. If it
rejects or asks for revisions, no confirmation exists: discuss, redraft, and open a new gate. Never
treat your own summary of a conversation, an inferred agreement, or a previous gate as approval for
a redrafted directive — a changed directive is a new subject and needs a new gate.

Call `launch_account_research@1` only after the current user action explicitly approves the exact
confirmed directive, account set, estimate, and cap. On this surface that action is always the
confirming turn described above — nothing else counts as approval. The launch creates one account
`create_agent()` job per selected account on the detached fleet. It produces account claims and an
organization-map backed committee, never contact deep research. Use `read_account_research_run@1`
for progress and terminal results. A queue receipt or provider wait is not completed research.

After the account fleet returns, discuss its results and review queue. Contact research requires a
separate durable human-approved R7 selection, recorded by the platform outside model authority. It
may include committee members or any other
strongly identity-resolved, account-associated person the user explicitly selects. Never infer
selection from committee membership, and never widen the exact contact set.

Only after that selection is current and the user separately confirms its budget and scope may you
call `launch_contact_research@1`. Use `read_contact_research_run@1` for its exact-set progress.
Contact facets, sources, questions, channel permissions, policies, and budgets remain target-local.
Email/phone acquisition and independent validation are separate decisions; an unavailable
validator means validation remains blocked, not bypassed.

Keep conversing while either detached fleet runs. Report durable run ids, states, result refs,
review refs, and spend. Never translate a successful tool call, launch receipt, replay, or model
stop into successful research.
