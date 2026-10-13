---
schema_version: '1'
kind: skill
name: person-dossier
version: v6
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
AI Ark supplies typed enrichment and work-email details; biographies, headlines and promotional prose are excluded from research inputs.
Use substantive sources for the person's narrative. Phone enrichment is out of scope.

## Discover broadly before composing the deep-research assignment

Own the search strategy for this already-selected person. Read the delegation brief, selected
identity and complete person charter first; consult the original seller, account and pinned
project references where useful. Keep the purpose clear without letting seller-relevant work
crowd out background, outside-work interests, creative projects and first-person voice.

Before the initial deep-research call, run several distinct ordinary `search_web` investigations.
Choose complementary angles from the person's known context and the charter. Useful angles include podcasts/interviews, talks/videos, podcast directories, authored articles,
writing platforms, education/alumni, awards, personal sites/projects, public social writing,
community contributions and publicly described formative background. These are research routes,
not eleven mandatory calls. Do not invent employers, institutions or hobbies to fill a query.
Use earlier employers and known aliases where appropriate; the current company need not appear
in every search. Reuse existing coverage instead of repeating a completed investigation.

Batch independent searches and reading operations. Start with a useful, modest batch, inspect
what it yields and adapt. Do not exhaust every channel before making the deep call, repeatedly
read the same context, or make cosmetic variations of an unproductive broad name search.
The separate `additional_queries` parameter on a deep call complements these actual preliminary
searches; it is not evidence that an ordinary search or source read has happened.

Read the returned source records, not just their titles or the receipt. Review text, highlights,
structured profile fields and useful links. Consolidate repeated URLs in your working notes
without discarding original records; retain which queries found them. Distinguish selected-person
material from namesakes and uncertain associations. Location is context, not a prerequisite.
A current profile byline on an old post describes the current profile unless the post itself
states otherwise; do not turn that into a historical employment contradiction. A name inferred
from a profile slug is not a confirmed alias. Retained summaries remain interpretations to revisit.

### Read what the person has done recently

Deep research and search results lean toward older, widely linked material, so look at the
present yourself. Early in the investigation, open the person's recent activity directly: their
recent posts and comments, talks, interviews, articles, hiring posts, and announcements that name
them. Take the research date from /research/context.json and look back nine months. Record each
meaningful item from that window as a finding, with its date and the person's own words where
they wrote or said something. If you find nothing in that window, write in /work/review.md that
you looked and where, so a reader knows the absence was checked.

Before composing the initial deep assignment, write `/work/pre-deep-review.md`: the angles
actually searched, useful source URLs and supported findings, promising leads and concrete
questions, and charter areas still partial, unsearched or inaccessible. Explain why the next
deep investigation is useful. This is a working research note, not a scored completeness gate.
Preserve uncertainty and useful partial answers. Do not demand corroboration of every source.

Then use `research_deep` for one comprehensive, evidence-informed person assignment. Preserve
the full charter's explicit subquestions and add focused questions from the preliminary findings.
Supply public URLs, useful source passages, known identity and concise mission context; Exa cannot
read internal paths. Distinguish supplied facts from questions. Remove repeated professional
probes rather than letting them overwhelm personal depth. Leave room for unexpected discoveries.
The agent authors this assignment; code does not append seller documents or benchmark answers.

After Exa returns, follow the skill's adaptive source-review procedure. Read the dossier and
underlying sources, recover omissions and pursue useful leads with searches, page or media reads.
Use another deep call only when a substantial unresolved investigation warrants it. Do not
automatically repeat the entire dossier. An unavailable source should lead to an honest gap or a
useful alternative route, not prevent the rest of the investigation from finishing.

Compile a detailed source-linked person JSON dossier covering the charter. Retain specific findings,
attributable quotations, dates, corrections and uncertainty; include channels actually checked
and worthwhile remaining questions. Interesting personal discoveries need no forced seller-fit
argument. Form the expanded findings into your own JSON dossier using the claim-ready-person-dossier skill. Preserve original evidence references and source-only discoveries. You own formation and code imports your entries. After successful import, write the contact narrative yourself using the installed narrative skill and tools.


## Keep the detailed charter in the actual Exa query

Read the person-depth-charter skill at `{{skills.person_depth_charter.path}}` in full before composing the assignment. Carry all nine sections and
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

Treat the deep-research report as a set of leads. Before you write a finding that quotes the
person, or credits them with a statement, post, role or event, open the source page yourself
and check that the words are there and belong to this person. Deep research can attach someone
else's post to the person or turn a paraphrase into a quote. If you cannot open the page, keep
the finding only with a note that it comes from the deep-research report and was not checked
against the page.

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
professional questions with background, interests, contributions and outside-work projects.
Once their recent activity is covered, do not let plentiful current-role posts crowd out the
rest of the charter.

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
research guidance, not a new schema or completion/presentation gate. Compile your own findings into the person JSON dossier, import them and write the contact
narrative using the installed formation and narrative skills. Campaign outreach copy belongs
to the downstream content workflow.

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


## Review new material from familiar sources

After each search, page read or deep acquisition, open the returned result_path and then its
source_review_path. Scan the overview, including its verbatim highlight segments,
and any continuation pages. A URL you read earlier may now contain different excerpts, highlights,
structured fields or links. Reuse established findings, but review newly supplied material before
treating that source as covered. Capture history is not a record of what you have read.

Read the full referenced result where a new field, useful lead or unclear passage merits context.
The overview lists available, added and changed fields; it does not replace the source. Compare
the dossier with these fields and retain useful source-only findings. If a passage introduces a
project, contribution, recommendation or other relevant detail, investigate it as the charter
warrants. Preserve attribution and uncertainty, including who wrote a recommendation.

Before saying something was not found, check the newly returned source fields already available
for that question. Distinguish material not yet read from material read without an answer. This
does not require recrawling every URL, corroborating every finding or passing a completeness gate.


## Follow relevant media through to its content

An interview page, recording candidate, transcript and show notes are different stages of work.
Use `read_media` for a relevant public appearance and inspect the returned state and candidates.

If the result is `ambiguous`, the recordings have not yet been attempted. Use the source page,
episode title, description and candidate type to choose a relevant recording. Pass that candidate's
candidate_ref or URL back to `read_media` with a purpose and an exact episode hint where useful. Do not repeat the unchanged
landing-page call or stop merely because it returned multiple candidates. If audio and video may
be the same episode, start with one useful version; investigate another only when it adds value
or the first route fails. Do not assume two formats are the same recording solely from their host.

If no recording link was recognized, use the publisher page, an explicit player/download link,
feed, indexed transcript or targeted search to find a useful alternative. `unsupported` describes
this retrieval route, not proof that no recording exists. Reuse returned links and completed work.

Use `open_transcript` with the returned version_ref and its continuations to read the transcript;
use `search_transcripts` to locate focused passages. Read the transcript when obtained. Extract substantive speaker-specific passages about the
person's reasoning, experiences, interests or work; retain URLs and supplied timing. Distinguish
their words from an interviewer, other speakers and show notes. Do not invent timestamps.

In the report, distinguish a recording not found, a candidate not yet attempted, a recording
that could not be retrieved, and a transcription attempt that failed. Inspect the saved provider
outcome before retrying a paid call with an uncertain result. Pursue useful leads without an
exhaustive crawl or a requirement to obtain a transcript before completing the investigation.

## Durable person dossier

Read {{skills.claim_ready_person_dossier.path}} in full. Apply its person-specific section guide and critical review to the acquired sources, not only Exa's report. Preserve background, career, outside-work material and public voice without requiring seller relevance. Save initial sections through save_dossier_section. Use update_dossier_findings for corrections or additions to specific finding IDs; omitted entries stay intact. Inspect /research/dossier/latest.json as needed, review against the skill, validate_dossier, then finish_dossier. For changes after import, use begin_dossier_revision and the same targeted editing tools before finish_dossier. This imports the person's findings as contact claims, not account claims. Record meaningful unresolved questions briefly under /work/ when useful. Reuse the resulting claim IDs for narrative and the final typed report. No second model extracts claims.
