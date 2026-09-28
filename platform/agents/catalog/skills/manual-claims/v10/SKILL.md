---
schema_version: "1"
kind: skill
name: manual-claims
version: v10
summary: "Manual: what a claim is. Tiers, verification status, use class, identity binding, outreach safety, live claims, and exactly what a read holds back."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
<!-- sources: research/2026-09-13-head-of-abm-manual/C-domain-model.md §1 (§1.1 the row, §1.2 tiers, §1.3 verification_status, §1.4 use_class, §1.5 identity_binding, §1.6 outreach_safe and signal_priority, §1.7 scopes, §1.8 write_markers, §1.9 supersession and merges, §1.10 claim flavors, §1.11 the display gate) -->
# Claims: the unit every researched fact is written in

A claim is one typed fact about one resolved entity, with its provenance attached. It is never
a paragraph and never a free text dossier. Every fact a research job finds lands as a claim,
and every fact you read back is one.

## The row

| Part | What it says |
| --- | --- |
| `entity_id`, `entity_type` | the resolved account or contact it is about, never a free text name |
| `field_key` | the registered field it asserts. The registry is `.deepagent/skills/manual-fields/v10/SKILL.md` |
| `value_json` | the value |
| `source_url` | where a reader can go and check. It can be absent |
| `source_key` | the registered source or resolver that produced it |
| `artifact_key` | a content addressed snapshot of the bytes the fetch saw, so a quote still resolves after link rot |
| `evidence_span` | the verbatim quote the value rests on |
| `source_tier` | 1 to 4, see below |
| `extraction_method` | `api`, `scrape`, `llm_synthesis`, `human`, `crm_import` |
| `confidence`, `corroborations` | the resolver's own number, and how many independent tier 3 or better sources agreed |
| `observed_at`, `collected_at` | when the source published, and when we saw it |
| `verification_status`, `use_class`, `identity_binding`, `outreach_safe`, `signal_priority` | the governance stamps below |
| `superseded_by`, `write_markers` | the append only history, and the lenient write notes |

## Tiers: how well a fact is known

| Tier | Meaning |
| --- | --- |
| 1 | a deterministic API |
| 2 | an official source scrape |
| 3 | a reputable third party |
| 4 | model synthesis, the last resort |

Tier 4 and `llm_synthesis` always agree: a claim cannot be built with one and not the other.
On this lane the research is overwhelmingly tier 4, so "a source said it" usually means a model
read a page and wrote down what it read, with a quote. Say how a fact is known when it matters
rather than presenting every claim as equally solid.

## Verification status, and what it is on this lane

`unverified` is the born state. `verified` means corroboration or the faithfulness judge
promoted it. `rejected` means a judge or the use gate refused it. `flagged` means it was
surfaced for a human rather than silently resolved.

**Verification is switched off on this deployment.** Every claim here is `unverified` apart
from a handful of rejected rows. Do not tell a human a fact was verified by the platform; it
was researched and quoted, which is a different thing.

## Use class: the governance class of personal data

| Value | Meaning |
| --- | --- |
| `professional-public` | a public professional fact |
| `personal-public-non-sensitive` | public personal, not special category |
| `sensitive` | special category. It never leaves the store, and it never enters any display section, restricted ones included |

A personal hook claim (`contact.facet.*`) cannot exist without both a use class and an identity
binding. A plain contact fact can.

## Identity binding: is it this person

`strong` means the fact is true and it is this person. `weak` means same name only: it never
promotes and never drives outreach.

## Outreach safety and signal priority

`outreach_safe` is about appropriateness, not accuracy. A true, well sourced, correctly
attributed fact can still be one you must not put in a message. An `outreach_safe=false` claim
reaches only a restricted display section, and it is dropped from the claims read entirely.
Some fields are born unsafe by declaration, including the ICP fit verdict, reputation risk,
media transcript quality warnings, and the excluded lookalike facet.

`signal_priority` is 1 for active buying intent, 2 for a qualifying fact, 3 for context. It is
the primary sort of what you are shown. It is never a gate: a priority 3 claim is not a worse
fact, it is a less urgent one.

## Live claims, not a merged value

Claims are frozen and append only. A new observation is a new row, and the old row points at
it with `superseded_by`. The only permitted mutation is that pointer.

Everything you read on this lane is **live claims**: every row that has not been superseded.
It is deliberately not a merge. A merge answers "what is the current value of this field"; a
page and a read show everything the research found, several rows of the same field included.
So seeing three rows of one field is normal, and it does not mean anything is broken.

An entity can be a **merge loser**: it was found to be the same company or person under another
id, and `merged_into` points at the survivor. Every read drops merge losers silently. If a
human names an account you cannot find, it may have been merged into another.

## Claim flavors

`field_claim` is the default: a value with a span and a tier. `discovery` is admission
evidence, where an entity was found and why it matched, and it is never treated as truth about
the entity. `derived` is an inference backed by an ordered set of supporting claims and an
entailment verdict; it carries no source url and no quote of its own.

## Write markers: what nobody can check

The write gate on this lane is lenient: what a strict gate would refuse becomes a durable note
on the claim instead of a dropped fact. The notes you will see most often are `source_missing`
(no source url), `unevidenced` (no quote), `identity_binding_defaulted`, `use_class_defaulted`,
`proposed_field` (the field was registered on the spot) and `schema_valid: false`. There is no
closed list; markers are an open map.

Read them as checkability. A claim with `source_missing` or `unevidenced` exists, but nobody
can go and verify it. Do not present such a claim to a human as sourced.

## What a read holds back, predicate for predicate

The account page and `read_account_research` apply the same tests, in this order, and each
exclusion is counted rather than hidden:

1. **Special category.** A `sensitive` claim never enters any section, restricted ones
   included. Counted as `sensitive`.
2. **Unverified synthesis.** A tier 4 claim that is not `verified` is held back, but only when
   verification is enabled. It is disabled here, so this test does not run today and tier 4
   claims are displayable. Counted as `unverified`.
3. **Appropriateness.** Outside a restricted section, an `outreach_safe=false` claim is held
   back. The claims read has no restricted section, so it drops those rows outright. Counted as
   `outreach_unsafe`.

Then near duplicates are folded within one person or within the account, never across two of
them, because two committee members legitimately share a title. What survives is ordered by
signal priority, then field key, then when it was collected.

The counts come back to you as an `excluded` map with the keys `sensitive`, `unverified` and
`outreach_unsafe`. Exclusions are counted, not hidden, on purpose: a section that is empty
because every row was special category reads very differently from one the research never
filled. Report the difference honestly, and never try to name the content of an excluded claim.
