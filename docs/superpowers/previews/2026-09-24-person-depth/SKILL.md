---
schema_version: '1'
kind: skill
name: person-dossier
version: v1
summary: Brief Exa for specific, source-linked research on an already-selected person, then investigate the returned sources and useful gaps.
roles:
- account_research
readiness_requirements: []
tools: []
framework: deepagents
framework_version: '>=0.6,<0.7'
---

# Person dossier and Exa briefing

Research the one person selected by the account agent. Understand who they are, what they do,
how they think, and what their public work and self-shared interests reveal. The account brief
adds direction; the detailed person charter supplies breadth and depth.

## Understand the assignment without restarting discovery

Read the account-authored person brief and the selected identity. Consult the referenced seller,
selected-product, project-pinned ICP/persona and account-research documents where useful. A
project can use brand definitions or its own variants; follow the selected pins. Preserve missing
context as a gap, not an excuse to substitute a generic seller description.

Use the acquired profile, known findings, original sources, aliases and prior-role references.
Do not discover a new buying committee or repurchase a profile already attached to this job.
AI Ark supplies typed enrichment and work-email details; it does not supply the person's
substantive narrative by copying its biography or headline. Phone enrichment is out of scope.

Batch independent skill and context reads. Reuse material already read. An optional quick page
read or targeted search may sharpen the assignment; do not repeat preparation, execute a fixed
eleven-search sweep, or exhaust all channels before launching Exa. Include unresolved questions
when a preliminary source is unavailable and continue the wider investigation afterward.

## Keep the detailed charter in the actual Exa query

Read [charter.md](charter.md) in full before composing the assignment. Carry all nine sections and
their concrete subquestions into the query; do not compress them into headings such as "research
their background" or "find their interests." This specificity must reach Exa, not remain in this
skill or in a private plan. Adapt references and person-specific emphasis without dropping the
education, first-job, interests, recommendations, frustrations or quotation questions.

Write a self-contained query from the account brief, the charter and useful evidence. Supply:

1. The selected person, known aliases/profile, source-reported role/company and relevant career
   or location context, preserving uncertainty. Do not invent missing identity details.
2. The research date and recent nine-month window. Earlier biography, formative experiences,
   career material, interests and substantive interviews remain in scope.
3. A concise explanation of the actual seller offering, account situation and research purpose.
   Translate ICP/persona criteria into questions about the person's work; keep qualification
   thresholds, fit scores and purchasing conclusions out of Exa's assignment.
4. The full detailed charter, followed by useful known findings, source URLs, media leads and
   person-specific questions. Combine duplicated probes rather than appending repetitive lists.
5. Source-linked Markdown output expectations and the distinction between evidence, interpretation
   and gaps. Exa cannot open our internal documents, source IDs or filesystem paths: supply the
   relevant information and public URLs in the request itself.

The charter is a writing guide for your assignment, not a code-generated context appendix.
Replace its placeholders and adapt the prose. The approximate 750-word guidance applies to the
account-to-person delegation brief, not this detailed Exa assignment. Neither has a hard word
cap; do not sacrifice specific questions to shorten the query or paste unrelated full documents.

## Additional queries that broaden discovery

Compose a small set of complementary search queries, usually three to five, with more when
distinct leads justify them. This is guidance, not a required count. Each identifies the person
with enough context to be useful and pursues a particular angle. Examples of angles:

- Their own current-role posts, hiring statements, initiatives and professional priorities.
- Known aliases with earlier employers: authored work, interviews, panels and lessons from
  previous roles. Do not require the current employer in every query.
- Education, alumni features, early-career interviews, awards or formative accomplishments.
- Self-described interests, side projects, books, communities, volunteering and recommendations.
- Long-form voice, working methods, frustrations, evaluation criteria and rollout lessons.

Choose these from the actual person and evidence, rather than using every angle mechanically.
Search by a discovered project, publication or institution when that is a better lead. Do not
invent past employers or personal interests to populate searches. A conjecture remains a question.
Include breadth beyond seller-relevant professional activity; no dedicated hunt for relatives or
private details. Avoid near-duplicate queries and excessive exact-phrase restrictions.

Additional queries belong in the provider's separate additional-query parameter; listing them
inside the charter alone does not set that parameter. They guide the same Exa request, not one
new deep call each. Result count is not a promise about the number of searches performed.

## After Exa: investigate the sources as well as the dossier

Read the dossier and scan the returned source excerpts, including all index pages. Retain their
URLs and distinctions between full text, highlights, listings and transcripts. Titles alone are
not source content. Useful details may be absent from the dossier or contradict it.

Recover source-only findings, resolve what contradictory passages actually support, and preserve
uncertainty. For example, a profile excerpt may describe a skill under a prior employer while the
dossier attributes it to the current role. Keep the original role/date context; do not silently
promote it to current practice. A hiring author's comments are not the same as the new hire's remit.

Follow promising leads: a prior-employer article, award, university feature, public side project,
book, media appearance or recommendation. Read the original page when an excerpt is insufficient
for a specific question. Do not crawl every URL, require another source for every finding, or
repeat completed purchases. Missing long-form material does not erase useful shorter public voice.

For media, use available transcript reads and search tools before spending again on the same
recording. A known substantial transcript can be read early. After Exa, pursue worthwhile new
appearances and unanswered questions using the available media tools. Preserve speaker, URL,
date and qualified timestamp; record unavailable media as a useful lead rather than pretending
that show notes are a transcript. Keep public posts distinct from spoken voice.

Before concluding "thin public footprint," look once more at the acquired material for neglected
distinctive findings. The PoC found useful projects that a generic career summary omitted. This
is a targeted reading judgment, not a mandatory extra LLM call or an invitation to repeat searches.

Return source-linked findings and useful quotations through the existing research handoff, with
original references, conflicts, gaps and follow-ups. Include useful findings from sources beyond
the dossier. Source review is investigative guidance, not a completion or presentation gate.
Outreach wording, claim classification and narrative improvements belong to their own stages.

## Teaching example: Clue → fictional Acme → Dana

Illustration only; never copy these invented people, findings or URLs into a real request.
Suppose the account brief names Dana as a growth leader at Acme, supplies an ABM hiring post and
an earlier role at fictional Northstar. Clue's supplied offering concerns account research and
personalized campaign execution. Explain this purpose briefly, then include the complete charter.

Add a question about Dana's personally owned work versus the proposed hire's responsibilities;
look for Dana's own descriptions of research, campaign production and Sales collaboration.
Investigate earlier roles for methods and voice without claiming their tools are Acme's stack.
Retain the full background and outside-work investigation even if the hiring post dominates the
initial evidence. Do not conclude that Dana has purchase authority or wants an ABM product.

Complementary queries might be:

```json
[
  "Dana Acme acme.example growth marketing hiring integrated campaigns own posts",
  "Dana Northstar growth marketing interview webinar evaluation working methods",
  "Dana Acme Northstar university alumni first jobs career interview",
  "Dana Acme Northstar side projects book community volunteering personal interests"
]
```

Use actual known identity anchors and leads in real queries. These examples explain search
angles; the complete charter in the main assignment supplies comprehensive coverage.
