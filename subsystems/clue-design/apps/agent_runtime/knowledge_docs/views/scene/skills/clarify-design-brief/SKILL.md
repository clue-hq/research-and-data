---
name: clarify-design-brief
description: Decide whether a design request needs clarification before you start, and if so ask up to 6 well-formed questions (each with a default) in ONE round with request_clarification. Use it as your opening move, never mid-design.
---

# Clarify a design request (opening move only)

A vague request designed blind wastes a whole turn on the wrong ad. A specific
request interrogated with obvious questions annoys the person. This skill is how
you tell the two apart and, when you must ask, how to ask well: one round, as
many questions as you need up to six, each carrying a proposed default so an
unanswered question never blocks the work. Never pad the list to reach six.

The tool is `request_clarification(questions)`. Calling it **ends the turn**: no
authoring, no rendering, no finalize. The person's next message answers the
questions, and that turn continues the design.

## Look first (asking about something you could find is a failure)

Before writing a single question, check what you already have:

1. **The person's message.** Read it literally. "A launch post for our new
   pricing on LinkedIn" already names the surface, the message and the intent.
2. **The Head of ABM's brief,** when the ad came from a strategy conversation.
3. **The conversation:** earlier turns, and any answer to an earlier question.
4. **The ad itself:** its size fixes the format, and its content fixes the
   subject.
5. **The brand kit:** tone, colours, type roles, logos and images.
6. **The seller's files and the account research.**

Only a choice that shapes the whole design, and that none of these settles, is a
candidate question.

## What is worth asking

| Choice | Found in | Ask when |
|---|---|---|
| Size, format and placement (LinkedIn alone has several) | the ad's size, the message, the brief | neither the message nor the brief names it and the ad has no size yet; default: your best guess, for example a 1080×1080 square feed ad |
| The communicative approach (which playbook) | the message, the brief | neither names or clearly implies it; default: the playbook that fits best |
| The main message (the ONE thing) | the message, the brief | the request is a topic, not a message |
| Primary call to action | the message, the brief, the kit's site | the intent is promotional and no next step can be found |
| Targeted edit or revamp (existing ad) | the person's words | the words don't say whether they want a quick polish or a reworked ad |
| Something that would be untrue (for example a customer story with no confirmed customer) | the evidence | going ahead would state or imply something the evidence doesn't support |
| Brand adherence | default `balanced` | never, unless references conflict with the kit |
| Number of variations | default `1` | never; the person opts in |
| Imagery preference | the imagery skill decides | only if the request hints at conflicting intent |
| References | attachments | never; use them if present |
| Copy density | default `minimal-punchy` | never |

## When not to ask

- **A specific request means zero questions.** If format, approach, message and
  intent can all be found, don't ask. Design.
- **On an existing ad, don't ask about anything the ad already settles.** The
  question worth asking there is whether the person wants a targeted edit or a
  revamp, when their words don't say.
- **For anything outside the "Ask when" column,** pick a sensible default and
  note the assumption in your summary.

## How to phrase questions (defaults, not interrogation)

Every question is one decision, in plain language, with a default framed as "if
you don't care, I'll do X". Give suggested `options` as chips when the answer
space is small and known. Keep `why_it_matters` to one line.

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

Rules the tool enforces (a violation returns an error you can fix and retry; it
doesn't end the turn):

- **1 to 6 questions.** More than six is rejected. Keep the six that matter
  most, use your defaults for the rest, and say so in your summary.
- **Every question carries a non-empty `default`.** A question with no default
  is rejected.

## Use the answers, never re-ask

The person's reply arrives as ordinary conversation on the next turn, and
`request_clarification` is **not available that turn** (one round per turn).
Read the answer, fill any unanswered question with its default, and design.

## Headless / auto-defaults mode

When `request_clarification` is absent and it is *not* because a prior turn
asked — i.e. the run is in `LUMEN_AGENT_AUTO_DEFAULTS=1` (probes and sweeps) —
do not ask at all. Apply this skill's defaults to every ambiguous spec and
`record_gap` each assumption (assumption-class, not failure-class) so the design
proceeds and sweep results stay comparable across runs.
