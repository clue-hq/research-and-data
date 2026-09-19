---
schema_version: "1"
kind: skill
name: manual-documents-decisions
version: v2
summary: "Manual: knowledge documents and recorded decisions. Kinds, statuses, versions, pins, the quote rule, and the route keys to record a decision under."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
<!-- sources: research/2026-09-13-head-of-abm-manual/C-domain-model.md §6 (documents, the ICP/persona/plan formats, the ICP pin, the product set, onboarding runs) and §7 (volunteered statements, the quote rule, current effective semantics, DSAR reverse binding, route keys in use) -->
# Documents and decisions: what is written down about this project

## Document kinds and where they live

| Kind | Folder |
| --- | --- |
| `company-overview` | `company` |
| `product-catalog`, `product-research` | `product` |
| `customer-reviews` | `proof` |
| `icp-definition`, `audience-persona` | `audience` |
| `design-brief` | `design` |
| `project-plan` | `project` |

Statuses are `running`, `ready`, `empty`, `failed`, `proposed`, `confirmed` and `superseded`.
**The servable set is three: `ready`, `proposed`, `confirmed`.** A document is servable while it
has bytes and has not been superseded.

Scope matters. A brand document and a project's own document at the same path are two
histories that never interleave. A project local ICP variant carries `derived_from`, naming the
brand profile it adapts. When two versions of one path are pinned, the pinned one keeps the
plain name and the other carries its version, such as `audience/icp-gi.v3.md`.

A new version supersedes the previous servable one, except a `confirmed` row, which stays
servable because some project may still be pinned to exactly those bytes.

## The ICP document

Four things are enforced in the front matter: `kind` is `icp-definition`; `icp_key` equals the
key you asked for, in lowercase kebab case; `product_ids` is a non empty list; `hard_gates` is
a non empty list. Each hard gate is `{key, rule, test}`. `exclusions`, `persona_map` and
`qualifier_fields` are read by the surfaces that use them rather than validated here, so a
malformed one fails later, not at authoring.

Nine front matter keys belong to the platform and are stripped and re-stamped if you write
them: `confirmed_by`, `confirmed_at`, `confirmed_for_project_id`, `product_selection_version`,
`user_edit`, `derived_from`, `project_id`, `brand_id`, `status`. A draft cannot confirm itself,
scope itself, or claim a lineage.

An ICP you author is always born `proposed`. **Only the gate mints `confirmed`.** Take
`product_ids` from the catalog rather than inventing one; where the ids actually are, and why
the catalog document does not carry them, is `.deepagent/skills/manual-workspace/v2/SKILL.md`.

## The persona document

Front matter is `kind: audience-persona`, `icp_key`, `icp_version`, and `personas`, one entry
per role with `titles`, `buying_triggers` and `evidence_urls`. The body is eleven numbered
sections per role, 300 to 450 words each, in the order economic buyer, champion, user,
technical evaluator, blocker. Every specific fact is cited by file path or url, and an
inference is marked as an inference.

## The plan

One plan per project, at `project/plan.md`, kind `project-plan`. It is **born `ready`; there is
no confirmation gate for a plan.** You write it with `write_file` at `project/plan.md`, or with
`edit_file` for a small change.

Two hands write it, so the version you read is the version you write against — but it is never
an argument you supply. The platform takes it from the file you read this turn, and a stale
write comes back as `revision_conflict: plan.md is at version N, you read version M — read it
again`. The version a write mints is stamped into the front matter, so the version of the file
is legible in the file itself. When a write is refused because the human edited the plan since,
read the file again, keep their edits, and write again.

## Writing under project/

`project/` is the project's library and most of it is compiled, but three paths are yours to
write. `audience/icp-<key>.md` lands a **proposed** ICP version, which you then take to the
confirmation gate. `audience/persona-<key>.md` lands the personas, and only for the key this
project has pinned — any other key is refused `icp_not_pinned`. `plan.md` lands the plan.

Everything else under `project/` is compiled from the rows: `status.md`, `decisions.md`,
`index.json` and anything under `artifacts/` refuse `compiled_file_read_only`, and a path that
is none of the above refuses `unknown_project_path`. A body with nothing in it refuses
`body_empty`, and persona front matter the format does not admit refuses
`persona_front_matter_invalid`.

A write under `project/` is not a governed operation. There is no receipt to report and it does
not count against the turn's governed-failure budget; a refusal is a file-tool answer you read
and act on. The plan card the human sees on the turn comes from the rows the write landed, not
from anything you attach.

## Pins: what this project committed to

The ICP pin is append only and names a **document id**, not a path: the exact version a human
approved. A project pins one ICP version and it is never moved automatically. A newer proposal
appearing later does not change what this project confirmed. Mention a newer one if it is
relevant, but never switch to it on your own.

The product set is one selection version for the whole set, anchored to the gate that confirmed
it. A later change of the set is a new gate and a new version, never an edit.

## Onboarding runs

A run is `full` (the whole brand walk, started from the onboarding flow) or `personas` (one
persona turn for one already pinned ICP, which is the one you can request). Statuses are
`queued`, `running`, `completed`, `completed_with_gaps` and `failed`. Where to read the outcome
is `.deepagent/skills/manual-siblings/v2/SKILL.md`.

## Recorded decisions: how the human's words become durable

There is no project state table. A decision is a **volunteered statement** bound to the exact
words the human wrote. Its route kind is one of `claim`, `memory`, `project_state`,
`field_proposal`, `source_proposal` or `unmapped`. For a project decision the route is
`project_state`; `unmapped` is always legal and is the honest route when nothing else fits,
because it preserves the quote as evidence without asserting a fact.

The quote rule, which the recording tool enforces:

- **Copy the span, do not describe it.** You quote the exact text; the engine finds it by exact
  substring search and computes the offsets. There is no fuzzy matching anywhere on this path,
  so a retyped, tidied or reflowed span is refused.
- **You never send the message back.** The platform loads the captured bytes itself.
- A typed value (a boolean, number, list or object) is admitted only when the quoted sentence
  entails it, judged before the claim exists, so a failure comes back as a refusal you can act
  on.

A statement is never edited. A human who changes their mind lands a new statement that records
which one it corrects, and the latest correction wins: the corrected statement is superseded
and drops out of what is served, while the full history stays for audit. `decisions.md` shows
the current effective set, in the human's own words.

The store only holds offsets and a digest into the captured message, so erasing that captured
input erases the client's words once. That is what makes deletion tractable, and it is why the
quote must be theirs and not your paraphrase.

## Route keys: the vocabulary to record under

`route_key` is free text in the tool today, and earlier turns used about thirty ad hoc keys,
almost all of them once, which makes them useless to read back. They still read back as they
were recorded; do not rewrite history. For anything you record from now on, use one of these
`(asked of you)`:

| Key | Use it for |
| --- | --- |
| `outcome` | what this program is buying |
| `closed_won_pattern` | what recent closed won deals had in common |
| `list_math` | how many right fit accounts and reachable people exist |
| `channels_tried` | what was run before and what happened |
| `follow_up_owner` | who answers a raised hand, and the sales counterpart |
| `day_ninety` | what would make the human call this a failure |
| `product_focus` | which product or products this program is about |
| `icp_scope` | whether a profile change is brand wide or this project only |
| `discovery_target` | how many accounts to look for |
| `persona_seats` | which committee seats matter here |
| `preference.<topic>` | a stated preference, with the topic after the dot |
| `other` | anything none of the above fits |

One statement per `(captured message, entity, route key)`: recording the same key twice for one
message is the same statement, not two.
