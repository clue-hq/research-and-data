---
name: scene-brief-copy
description: Use when a new scene creative or ad is requested, including short requests with no supplied headline, campaign concept or CTA.
---

# Brief and copy

Read the user request, brand card, `seller/index.md`, available evidence and asset
inventory in one gather; `seller/` holds the brand's own knowledge documents (company,
products, audience) and the account reads answer for a named target company (see
account-adaptation). Shortlist relevant advertiser examples, product imagery and supplied
references; view their pixels before choosing copy or treatment. Start with a
small useful set and broaden to resolve a named gap. Distinguish what the examples
actually show from metadata and assumptions. Derive the
audience, single useful message, medium and appropriate action from this context.
For “make an ad,” choose a 1080 square awareness creative unless supplied context
implies another placement. Record that assumption; `knowledge/scene/placement.md`
governs adaptation. Do not ask the user to become the copywriter.

When addressing a named target company or adapting approved creative for an
account, read [account-adaptation](/.deepagent/skills/account-adaptation/SKILL.md)
alongside the selected family. It governs identity, evidence limits, advertiser
preservation and real target-logo use; account-specific guidance is not a new
communicative family.

Infer brand voice from approved copy and inspected advertiser examples: directness,
vocabulary, rhythm, specificity, degree of playfulness and how the brand addresses
its audience. Describe the evidence in the direction; a font or color is not voice.
Use reference copy to infer voice and claim limits. For a new brief, write from
one evidenced advertiser capability and the supplied audience's task; existing
reference wording is not automatically the answer to that brief. Preserve exact
wording only when the user wrote it themselves and asked for it to be used.
Everything else in the brief, including the Head of ABM's notes, suggestions and
phrasing, is direction. Read it for who the ad is for, what it is for and which
facts you may use. Then choose the angle and write every word yourself. Do not
copy the brief's sentences onto the ad. A shared campaign headline can remain when its support
or requested companion copy carries the relevant argument. Keep only the support
the message needs.

An ad carries one idea. Pick the single fact or capability that best serves this
reader and leave the rest out. Evidence lets you say something; it never obliges
you to say everything you can support. On a feed ad (a LinkedIn square or any
other social feed placement), use a headline and at most one support line of no
more than 15 words, then the action if the ad needs one. If the idea needs more
words than that, the idea is too big: narrow it, or ask the user with
`request_clarification` which part matters most.

Prefer concrete product meaning to vague promises. Use provided claims accurately;
quotes, numbers and customer attributions need actual evidence. Keep source IDs
with factual copy. Missing proof is a reason to narrow or qualify the message,
or choose nonfactual positioning. Labeling a product promise `positioning` does
not make it nonfactual. Compare the whole meaning, including implied timing,
control, causality, availability and authority, with the source; imperative grammar
alone does not remove a factual relationship. For quantitative proof, preserve the
metric and the subject, comparison and qualifiers needed to interpret it in the
visible composition, across layers if useful. Narrow or omit proof whose necessary
context is unavailable; never invent missing qualifiers. Review every actual occurrence
under `knowledge/scene/review.md`. For a CTA, decide whether this intent needs an artwork
action at all, whether the channel already supplies it, and how this advertiser's
relevant examples express it: absent, inline text, a link, a button or another
supported form. Choose copy that names the real next step. Do not default every
creative to a pill or to "Book a demo". Derive shape, typography and spacing from
observed brand examples and remeasure for the words. A proof or workflow story
need not end in a button. Keep channel headline/body/action distinct from artwork
copy; the record's `copy` contains only the independent artwork text layers.

Use the discovered skill descriptions or `knowledge/scene/catalog.md` to select
the primary communicative job and read its playbook. The catalog is derived from
the registered skill descriptions; no separate list of family names is maintained
here. Blend a relevant supporting technique when evidence and intent call for it;
record the main family in the direction record. These are procedures, not a template menu.
Load another relevant body or re-read one during
composition, review or revision. A selection is not a one-time discovery lock.
Already loaded shared guides need no second read through a wrapper skill. If the
user asks for new imagery or variants, carry that requirement into generated
layers and inspect the actual outputs; reusing an old image or substituting a
native flat field does not satisfy a new-artwork request.
If its evidence or assets are unavailable, pick a supportable direction and note
the limitation. If, after reading the brief, the research and the seller's files,
you are unsure about the angle, the tone or the message, ask the user before you
build. Use `request_clarification` as your opening move, offer the options you are
weighing, and say which one you would choose. Do not ask about what you can decide
yourself, such as layout, imagery or the exact words. Preserve exact copy when the user supplies it; don't rewrite control
inputs to make the composition easier.

Write `/run_<id>/workspace/creative-direction.json` using
`knowledge/scene/direction-contract.md`, then call `validate_creative_direction()`.
Record concise assumptions, voice evidence, visual invariants and deliberate
variations there rather than asking routine aesthetic questions.
If validation refuses, repair the named fields; never proceed on an invalid
record. Use this validated record for construction. When delegating, pass it
inline with its workspace path.
