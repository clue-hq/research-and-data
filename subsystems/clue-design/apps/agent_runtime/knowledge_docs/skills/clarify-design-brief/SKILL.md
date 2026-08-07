---
name: clarify-design-brief
description: Decide whether a design brief needs clarification before authoring, and if so ask up to 4 well-formed questions (each with a default) in ONE round via request_clarification. Use as the orchestrator's opening move on a vague create-turn — never mid-design, never on a specific brief or a chip-seeded edit.
---

# Clarify a Design Brief (opening move only)

A vague brief ("make us a social ad") authored blind wastes a whole turn on the
wrong design. A specific brief interrogated with obvious questions annoys the
user. This skill is how the orchestrator tells the two apart and, when it must
ask, asks *well*: at most one round, at most four questions, each carrying a
proposed default so an unanswered question never blocks the work.

The tool is `request_clarification(questions)`. Calling it **ends the turn** —
no authoring, no rendering, no finalize. The user's next message answers the
questions and that turn continues the design.

## Derive first (asking about something derivable is a failure)

Before writing a single question, exhaust the four sources you already have:

1. **The prompt** — read it literally. "A launch post for our new pricing on
   LinkedIn" already names surface (LinkedIn), message (pricing launch), intent
   (promotional). Nothing to ask.
2. **The conversation** — earlier turns and any answer to a prior clarification
   ride forward as ordinary conversation. Consume it; never re-ask it.
3. **The document** — its size fixes the format; existing content fixes the
   subject; chips fix the edit target.
4. **The brand kit** — the brand card (`brand_card.json`) carries tone, colors,
   type roles, logo variants, and the imagery inventory. Adherence is
   `balanced` by default; imagery preference is decided by the imagery skill.

Only a decision that (a) shapes the whole design AND (b) cannot be derived from
any of the four is a candidate question.

## The decision-critical spec table

| Spec | Derivable from | Ask when |
|---|---|---|
| Canvas format/dims + target platform | document size, prompt | doc is default-sized AND the prompt names a platform ambiguously |
| Message focus (the ONE thing) | prompt | the prompt is a topic, not a message |
| Primary CTA | prompt, kit site | promotional intent with no CTA anywhere derivable |
| Brand adherence: strict / balanced / loose | default `balanced` | never — unless references conflict with the kit |
| Variations count | default `1` | never — the user opts in |
| Imagery preference (kit / generate / none) | the imagery skill decides | only if the prompt hints conflicting intent |
| References | attachments | never — use them if present |
| Copy density | default `minimal-punchy` | never in v1 |

Most rows are "never ask." The live candidates are almost always just **format**
(when genuinely ambiguous) and **message focus** (when the prompt is a topic,
not a message).

## Zero-questions rules (the default is to NOT ask)

- **A specific brief ⇒ zero questions.** If format, message, and intent are all
  derivable, do not ask — design.
- **A chip-seeded edit turn ⇒ (almost) never ask.** The chip IS the intent; the
  request names the change. Design it.
- **A seeded/continuation turn ⇒ default to no questions.** You are continuing
  the user's live document; its state answers most of what a fresh brief would
  not.
- When in doubt between asking and picking a sensible default, **pick the
  default and note the assumption in your finalize summary.** A good default
  beats a question the user did not need.

## How to phrase questions (defaults, not interrogation)

Every question is one decision, in plain language, with a default framed as
"if you don't care, I'll do X." Give suggested `options` as chips when the
answer space is small and known. Keep `why_it_matters` to one line.

```
request_clarification(questions=[
  {
    "id": "format",
    "question": "What surface is this for?",
    "why_it_matters": "It fixes the canvas size and the whole layout.",
    "options": ["Instagram square (1080x1080)", "LinkedIn landscape", "A4 flyer"],
    "default": "an Instagram square (1080x1080)",
    "allow_freeform": true
  },
  {
    "id": "message_focus",
    "question": "What's the ONE thing this should say?",
    "why_it_matters": "One dominant message reads; three compete and none land.",
    "options": [],
    "default": "lead with your strongest product benefit",
    "allow_freeform": true
  }
])
```

Rules the tool enforces (a violation returns a machine-readable error you fix
and retry, it does not end the turn):

- **1 to 4 questions.** More than four is rejected — cut to the four that matter.
- **Every question carries a non-empty `default`.** No default = rejected.

## Consume answers, never re-ask

When the user answers, their reply arrives as ordinary conversation on the next
turn — and `request_clarification` is **absent from your tools that turn** (the
harness enforces one round per turn structurally). Read the answer, fill any
unanswered question with its default, and design. Recording an applied default
via `record_gap` is optional here but always honest.

## Headless / auto-defaults mode

When `request_clarification` is absent and it is *not* because a prior turn
asked — i.e. the run is in `LUMEN_AGENT_AUTO_DEFAULTS=1` (probes and sweeps) —
do not ask at all. Apply this skill's defaults to every ambiguous spec and
`record_gap` each assumption (assumption-class, not failure-class) so the design
proceeds and sweep results stay comparable across runs.
