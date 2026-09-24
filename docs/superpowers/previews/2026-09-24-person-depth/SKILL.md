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

You own the investigation. Exa's dossier is an initial synthesis; judge what its sources establish
and use the tools available to develop a richer understanding. Carry out worthwhile follow-ups,
rather than ending with a list of questions another researcher could investigate.

### Assess coverage and read the evidence

Read the dossier and scan the complete source package, including all source-index pages, returned
text, highlights, structured profile fields and useful links. Preserve source URLs. Expand a
promising excerpt when it is truncated or omits context; a title or listing is not a complete page
or transcript. Missing returned text does not mean the original page is empty.

Use the charter's explicit subquestions to distinguish supported answers, partial answers,
unclear or conflicting findings, unsearched areas and inaccessible material. A section heading
or generic paragraph does not answer its underlying questions. A career chronology may still
leave first jobs, formative experiences and the person's reasons for moving unanswered.

Notice useful details absent from the dossier: a named project, publication, community, award,
institution, earlier employer, personal announcement or media appearance. Recover facts already
supported by the supplied material immediately. Treat an unexplained project name as a lead to
expand, not a complete finding or something to discard because its description is missing.
Retain self-shared personal depth even when it has no obvious seller relevance.

### Choose the next useful investigation

Prioritize leads that could reveal a distinctive aspect of the person, deepen their own voice,
answer a substantive question from the brief, or resolve a consequential ambiguity. Balance
professional questions with background, interests, contributions and outside-work projects;
do not let plentiful current-role posts crowd out the rest of the charter.

For a known URL, read the relevant page or available transcript when that can answer the question.
For an unexplained project, search its name with the person's actual identity or relevant career
context. For missing voice, try authored work and media from earlier employers or communities.
Where no concrete lead exists, choose a different source angle suggested by the charter and
known biography, such as an alumni feature or early-career interview. Do not invent associations
or repeat the same broad name search with cosmetic wording changes.

### Make each follow-up request specific and self-contained

Identify the selected person, the lead or gap, what the existing source actually says, and what
you want to learn next. Include the relevant public URL and exact passage when useful. Explain
which facts are supplied evidence and which are questions; Exa cannot read internal file paths.
Use focused search or page reads for narrow questions, and a deeper assignment when a substantial
new question warrants investigation across sources. Do not rerun the entire initial dossier by default.

Adapt explicit questions to the lead. For a project, investigate what it is, the person's actual
contribution, origins and milestones, their motivation, related books/channels/articles or
demonstrations, and what they say they learned. For a career transition, pursue the previous and
new role, timing, stated reasons and formative experiences. For media, identify the appearance,
speaker and available transcript, then seek substantive passages about reasoning, working
methods, frustrations, interests or decisions, with timestamps only when supported.

Specify the useful return: concrete findings, original URLs, dates, attributable quotations,
uncertainty and promising new leads. Preserve older biography and voice. Ask substantive
questions rather than "research more deeply," and avoid repeating unrelated seller/ICP context.

### Reassess what comes back and adapt

Read each follow-up's underlying material, update the findings and decide what it changes about
the next question. An answer can close a gap, reveal a better lead or undermine an earlier
interpretation. Follow that evidence instead of executing a fixed sequence of searches.
If an angle is unproductive or inaccessible, try a meaningfully different route when useful.

Keep current and previous employers, authored words and third-party comments, and dated post
bodies and current profile metadata distinct. Read surrounding headings before attributing a
responsibility. A current-role byline on an old post does not establish employment at that old
date. A same-named site's additional technical detail does not by itself connect its author to
the selected person. Preserve uncertain associations visibly without turning them into facts.

Use actual available transcripts and media tools; reuse material already acquired. Distinguish
spoken passages from show notes, listings and other speakers' words. Missing long-form material
does not erase useful short-form voice. Self-shared personal posts can be followed without
investigating relatives or inferring private attributes.

### Finish with the expanded research

Continue while there is a useful, distinct next investigation within the run's existing limits.
Reuse reads and searches; do not crawl every URL, require independent corroboration for every
finding, or pursue every empty category indefinitely. Explain remaining limits when further
available actions offer little value. Before calling the footprint thin, check whether acquired
sources still contain neglected leads. This is agent judgment, not a required extra call.

Return source-linked findings and useful quotations, including recovered omissions, newly
discovered material, corrections, uncertain leads and remaining gaps with channels actually
checked. Preserve original references for the research handoff. These distinctions are readable
research guidance, not a new schema or completion/presentation gate. Outreach wording, claim
classification and narrative improvements remain separate responsibilities.

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
