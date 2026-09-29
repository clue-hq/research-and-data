---
schema_version: '1'
kind: skill
name: claim-ready-person-dossier
version: v1
summary: Researcher-owned JSON dossier formation and mechanical claim import.
roles:
- account_research
readiness_requirements: []
tools: []
framework: deepagents
framework_version: '>=0.6,<0.7'
---

# Form the dossier as individual findings

## Responsibility and coverage

Your output carries the substance of the investigation into durable claims.
Preserve every meaningful person observation and reported statement you find in
the acquired material, including qualifications and contrary evidence. The goal
is faithful coverage, not a shorter narrative or a larger claim count.

Read the assignment and seller context, the existing dossier, and the evidence
index. Batch independent reads, reuse completed reads and inspect relevant source
passages when a report or excerpt is incomplete. Work section by section and
write incrementally; do not spend the entire execution preparing an inventory.

The report is a map, not the limit of research already acquired. Inspect original
pages, returned search excerpts, job records, media and typed enrichment for
meaningful source-only details. Track processed source material and what remains
unread. A repeated URL may contain different posts or snapshots; compare content
before treating captures as interchangeable. Menus, cookie text, repeated boilerplate
and identical copies are not additional findings. Record their treatment in coverage
notes. An unseen recording or linked page is a lead, not available evidence.

Seller context helps you recognize significance; it cannot establish target facts.
Keep provider-reported typed facts attributed to that provider. Do not copy an
enrichment provider's promotional description into a substantive company finding.
Build company descriptions from acquired research and company-page evidence.

## Decide what the finding actually establishes

Before writing an entry, identify its subject, the specific source assertion and
the passage supporting it. Choose `reported_statement` when recording what an
identified speaker or publisher says; choose `observation` for what the inspected
material directly establishes. Neither type licenses adding your own conclusion.

Keep these destinations distinct:

- **Finding:** the observed fact or attributed statement, with its original scope.
- **agent_interpretation:** your optional inference about relevance, consequences,
  likely needs or buying roles, attached to the underlying finding.
- **Working notes:** research questions, missing channels, next steps and judgments
  without a specific underlying finding. These are not account facts.

For example, an announced office opening is a finding. “This may increase demand
for workflow software” is interpretation. Adding “possibly,” “likely” or “hypothesis”
inside FACTUAL text does not make that inference an observation. An identified
leader's prediction can instead be a reported statement, attributed as a prediction.

“I could not find a budget” belongs in notes. A source stating that the company
declined to disclose its budget is a reported statement. Preserve genuinely partial
source assertions with `insufficient_context`; do not manufacture a source assertion
from an unanswered research question. These distinctions organize information, not
discard uncertainty or introduce an automated verification gate.

Keep one canonical entry for a finding across the dossier. Before adding it, compare
existing entries' subject, event, time and assertion. Add complementary evidence or
detail to that entry; use references in notes for relevance to other sections. A
fit summary repeating existing facts is not another fact. A genuinely distinct
retained occurrence with no added substance may be marked `duplicate` and linked;
new events or materially different statements should remain independently recorded.

### Worked example: your reasoning and coverage assessment are not source facts

During an investigation you will form conclusions of your own, reason about the
seller's relevance, plan follow-ups and evaluate how complete your coverage is.
These are useful parts of your work, but they are not automatically facts about
the target account. Identify whether a proposed entry came from a source or from
your assessment of the investigation before deciding where to store it.

For example, after reviewing a fictional company Acme's website, vacancies and
interviews, you assess your coverage and conclude: “We have not established Acme's
marketing headcount, campaign budget or installed ABM platform. These remain open
questions before we can understand its marketing operation fully.” This is your
research status, not a statement Acme made and not evidence that it has no budget,
marketing team or ABM platform. A research dossier's “Open questions” section can
contain exactly this kind of analyst reasoning; copying it does not make it an
externally supported fact.

**Wrong destination — a finding:**

```text
claim_type: observation
finding: Acme's marketing headcount, campaign budget and ABM platform remain unknown.
review.status: supported
qualifications: This records research gaps, not account facts.
```

This still becomes a stored claim. “Not a fact,” “research note,” or “for evaluation
only” in its text or qualifications does not change the record's destination.
Attaching pages you searched does not make those pages assert your research gap.

**Right destination — separate questions in /work/review.md:**

```text
Unknown: Acme's marketing headcount.
Evidence reviewed: [actual retained source references].
Current conclusion: Not established from the material reviewed.
Possible follow-up: Inspect current team information or an attributable statement.
```

Record the budget and platform questions separately in those notes as well. Do not
assign finding IDs to these questions or put them in the findings array. If your
thought is instead “this workflow could benefit from the seller's offering,” place
it in the underlying finding's agent_interpretation, or in notes if there is no
specific underlying finding. Do not create a factual entry just to house reasoning.

By contrast, if an actual interview says “Acme declined to disclose its budget,”
retain that as an attributed reported_statement with its source. If a source offers
only a partial assertion, preserve that assertion with its limitations; uncertainty
does not require omission. The distinction is between evidence about the account
and your own unanswered question, not between complete and incomplete research.

All worked examples in this skill are fictional teaching material. They are not
research, expected discoveries, source paths to copy, or a target record count.
Field excerpts illustrate decisions; use the full output contract for actual writes.

## Format: structured sections and findings

Call save_dossier_section(section, findings) with a section heading and a list of
finding objects. The tool durably saves the dossier; read its document property at /research/dossier/latest.json. This view also carries draft/import state and receipts. It replaces the
complete named section on revision and preserves other sections. Write sections
incrementally. Read the saved JSON before revising a section so you retain its
existing findings. Do not manually serialize or edit that file.

The canonical shape is {"sections":[{"section":"Heading","findings":[...]}]}.
The tool accepts the following finding fields. Claim records are imported
mechanically from these objects; no second authored report is needed.

```json
{"id":"F001","topic":"Short finding title","claim_type":"reported_statement","finding":"The attributed finding and its meaningful supporting detail.","source_paths":["/evidence/exact-path-from-index.json"],"attribution":"Speaker or publisher; role if known","time_context":"Date and what it describes, or null","qualifications":[],"review":{"status":"supported","reason":"What the inspected material supports","duplicate_of":null,"conflicts_with":[],"expected_entity":null},"agent_interpretation":null}
```

The example is a shape, not research to copy. Copy actual source paths from the
inventory. `finding` may also be an object, for example separate `statement` and
`context` strings. Preserve exact source URLs inline where useful; stored sources
also carry their retained URLs. Use JSON null for unknown optional values.

- `id`: unique stable readable identifier, e.g. F001. Never reuse it for another
  finding. No dependence on database UUIDs or the file's changing line numbers.
- `claim_type`: `observation` or `reported_statement`. A reported statement records
  who said what; it does not certify the underlying statement as independently true.
- `source_paths`: exact inspected retained sources; all relevant sources may be
  attached. If only the saved report supports an assertion, cite its labelled
  research-report source and use insufficient_context. Do not invent evidence.
- `attribution`, `time_context`, `qualifications`: preserve who, when, scope and
  caveats. Unknown values may stay null or be explained; do not guess.
- `review`: your advisory assessment, with the statuses below. Related entries use
  their F-identifiers. Code resolves these to claim IDs after storage.
- `agent_interpretation`: optional significance or hypothesis, separate from
  evidence. Pure fit judgments belong in notes or attached to a sourced finding;
  they are not independent factual records.

The containing section becomes the stored section. Code preserves the entry
content; it does not choose a more specific field catalog key or infer metadata.

## Meaningful units: required granularity

One entry must be independently assessable and correctable. Separate different
product launches, investments, appointments, departures, conference appearances
and organizational changes. A list of initiatives is several findings. A leadership
roster is separate person/role findings, each with its own time and attribution.

One coherent workflow may retain multiple steps, tools, owners, cadence and purpose
in one entry. Keep the relationships that make the workflow useful. Distinct pains
or intentions expressed about it may deserve their own attributed statement.
Do not split every sentence automatically or compress everything from one page
into a single claim. Source count is not claim count.

A post announcing a partnership and a later conference talk contains two events.
If the author also describes a meaningful operational frustration, preserve that
statement separately with its wording. These are generic illustrations, not expected
findings or mandatory categories to fill.

A calendar containing several appearances needs separate event entries. A page
quoting several employees needs separately attributed statements. Shared sources,
topics or seller relevance do not justify bundling independently correctable facts.
Conversely, multiple sources supporting the same event need not create extra entries.

Preserve numbers, units, ranges and relationship direction. Distinguish a job
requirement from installed practice, a provider estimate from a disclosed figure,
personal experience from company tooling, and a department label from a reporting
line. Keep substantive findings even when they do not favor the seller.

## Public statements are first-class findings

Statements by leaders, team members and practitioners can reveal intentions,
priorities, methods, frustrations and motivations that generic enrichment misses.
Give them deliberate attention across social posts, podcasts, interviews, conference
talks, webinars, personal/company websites, articles, blogs, books and other sources.

Preserve the meaningful original passage with minimal alteration. Keep words that
express ownership, urgency, constraints, negation, contrast and uncertainty. Do not
turn “build campaigns end-to-end, work directly with Sales, without a large team”
into “hiring marketer.” Seller relevance guides attention, not selective rewriting.

Retain the speaker/author, source URL/reference, occasion and available date.
Keep known media speaker labels/timestamps and book title/edition/page or chapter.
Distinguish a host's question, journalist's narration, quoted customer and actual
speaker. Never invent missing identifiers. Unclear attribution remains explicit.

Use contiguous exact passages when presenting verbatim quotations. Do not silently
correct original words or combine separated passages into one quote. If shortening
is necessary, mark omissions and preserve context. Keep separate quotations separate.
Label a paraphrase as a paraphrase. An acquired paraphrase does not license
reconstructing the original words. There is no arbitrary sentence quota.

Preserve the selected person's public professional and personal biography with attribution. Do not exclude outside-work findings simply for lacking seller relevance.

### Worked example: preserve the words carrying the signal

Fictional source — Maya, Head of Growth, writes:

> Two marketers support forty named accounts. Every campaign brief is rebuilt
> manually, and Sales often receives the material after the meeting. We're trying
> to fix that without adding headcount.

**Wrong:** “Acme is scaling ABM and needs marketing automation.” This drops the
numbers, manual preparation, late handoff and staffing constraint, and invents a
purchasing conclusion.

**Right:** a reported_statement preserving Maya's complete passage above, her
name and stated role, actual retained source path/URL and available statement date.
These sentences describe one coherent workflow problem; keep the connection between
them. Store any seller relevance separately, for example in agent_interpretation:
“The manual preparation and late delivery may be relevant to the seller's workflow
capabilities. This does not establish a purchasing decision or budget.” Do not put
that interpretation inside the quotation or factual finding.

### Worked example: a shared page does not make different speakers one finding

Fictional careers page:

> Maya: “Our campaign briefs are rebuilt manually.”
>
> Arun: “Security reviews determine which vendors we can approve.”

**Wrong:** one observation saying “Acme's leaders report manual workflows and
difficult procurement.” It merges speakers and introduces “difficult.”

**Right:** two reported_statement findings, each with its own speaker, exact words,
available role/date and the same retained page reference. Do not combine the quotes
or replace their wording with a shared theme. A second person's substantive reply
on a post can likewise deserve its own attributed finding. Keep contextual links
without making one person's statement the other person's words.

### Worked example: the interviewer’s question is not the guest’s assertion

Fictional transcript:

> Host: “Are you replacing your CRM?”
>
> Guest: “No. We're keeping it and improving the handoff around it.”

**Wrong:** “The guest discussed plans to replace the CRM.”

**Right:** a reported_statement preserving the guest's answer, including “No,”
with the host's question as explicitly attributed context. Retain the recording URL,
known speaker identity, date and timestamp when available; do not invent missing
labels. Apply the same distinction to narration or quotations in articles and books.
Negation, uncertainty and context are part of the signal even when they weaken fit.

## Status and relationships

- `supported`: material supports the observation or that the statement was made;
  not human approval or independent verification.
- `duplicate`: a distinct retained source occurrence adds no material detail to
  another finding. `duplicate_of` points to its canonical F-ID. Re-reading the same
  capture does not create a duplicate entry. Complementary detail is not a duplicate.
- `wrong_entity`: retain the misattribution, name the expected entity when actually
  known, and explain why it does not establish an account fact.
- `insufficient_context`: preserve what was found and identify what remains unclear.
  Uncertainty alone is not a reason to omit the finding.
- `potential_conflict`: preserve both accounts and set `conflicts_with` to the
  corresponding F-ID(s). Explain the same-subject disagreement and relevant dates.

When concerns overlap use wrong_entity, insufficient_context, potential_conflict,
duplicate, then supported; retain other concerns in qualifications. A higher-priority
status can still carry conflict references. A duplicate must point to a canonical
nonduplicate entry. Link the actual competing statement, not a related event or page.
One-way conflict references suffice. Avoid self-links or cyclic reference chains;
either side can carry the link. Forward references in the file are supported.

Before calling something a conflict, inspect identity, scope, title parsing and
time. Regional and company-wide roles may coexist. Prefer a newer relevant dated
update about current state, while keeping the earlier observation explicitly
historical. Retrieval dates do not establish factual recency. If dates cannot
settle a genuine disagreement, preserve both with an honest conflict explanation.

A conflict requires competing assertions about the same subject and attribute in
comparable scope and time. A functional, field or regional role does not by itself
contradict a company-wide role. Flattened headings can concatenate a person's name
and title; preserve ambiguous wording rather than inventing a name, mandate or
contradiction. Reopen the available passage for context and retain unresolved meaning
as a qualification or `insufficient_context` when appropriate.

Read the actual destination entry before adding a related ID, including IDs mentioned
in prose. Verify its subject and assertion; do not reconstruct links from memory.
If validation reports a missing conflict reference, write the actual competing
finding and link it. Do not merge away the disagreement, invent an ID or switch to
`supported` merely to make validation succeed. Change an assessment only when source
review warrants it, and explain that reason. If the existing representation cannot
express a concern, preserve the source assertion and document the limitation in
review notes rather than claiming the concern has been resolved.

## Person-specific section guide

Retain useful headings from the investigation rather than imposing a section count.

| Area | Preserve and distinguish |
| --- | --- |
| Present responsibilities | Title, employer, location, dates, personal remit and first-person ownership language. Separate a hire's responsibilities from the hiring author's own role. |
| Career and transitions | Each employer/role/period, meaningful achievements and the person's explanation of decisions. Earliest indexed work is not necessarily their first job; do not apply a later title to an entire career period. |
| Education and background | Institutions, degrees, subjects, dates, activities, awards, early-career stories, languages and publicly described non-corporate background when found. Keep uncertainty about namesakes and dates. |
| Interests and public personal life | Publicly self-described hobbies, sports, pets, milestones and interests, with the original statement and context. Do not infer interests from an ambiguous image, repost or another person's words. |
| Projects and contributions | Distinct side projects, authored books/articles, newsletters, communities, volunteering, mentoring and boards. Preserve the person's own role, motivation, milestones and lessons when available. |
| Recommendations | Books, people, podcasts and tools explicitly recommended by the person. Naming a tool is not necessarily recommending it; describing a personal experiment does not prove employer-wide use. |
| Voice and working methods | Meaningful original public language from posts, interviews, podcasts, talks, books and websites. Retain constraints, frustrations, methods, priorities and stated vendor-evaluation behavior without generic compression. |
| Media evidence | Distinguish listing metadata from actual speech. Preserve available speaker labels/timestamps, but never manufacture them or treat an interviewer question as the target's opinion. |
| Conflicts and namesakes | Compare person, scope and relevant dates. Preserve incomplete evidence with tags; uncertain associations remain uncertain. Wrong-person records retain the expected identity when known. |
| Distinctive insight and relevance | Preserve the underlying source-backed finding; attach your synthesis as interpretation. An interesting discovery need not be a buying signal to be retained. |
| Gaps and outreach ideas | Unanswered questions and proposed openers go in notes with finding references. Neither absence from the retrieved material nor outreach wording becomes a factual claim. |


## Finish with a reviewable handoff

Maintain /work/coverage.md: section/source location → finding IDs, plus sources
processed, partially read, unread or unavailable. Explain out-of-scope material
and boilerplate separately. Do not use coverage tracking as a new completion gate.

Read back the dossier. Comprehensively and critically review the actual saved dossier
against all the rules, guidance and worked examples in this charter/skill. Check
that entries retain useful public wording, independent units, correct attribution
and relationship targets. Inspect source material for omissions, not only the older
dossier. If you find a defect, correct the affected findings or move the material
to its proper destination; do not merely describe the defect in review notes while
leaving it in the dossier. Re-read the corrected output against the same rules before
finalizing. Preserve genuine source uncertainty and document any remaining evidence
limitations in /work/review.md; do not invent facts to make the review pass.

Review in both directions: source passages → findings for omitted substance, then
findings → passages for unsupported additions. Give meaningful source-only product
developments and public statements the same attention as dossier summaries. Check
specifically for hypotheses in factual text, research questions masquerading as
observations, repeated summaries, bundled speakers/events and unrelated ID links.
This is your reasoning task, not a required second specialist or automated gate.

Call validate_dossier for syntax/source-reference feedback. Correct reported format
issues by resubmitting the complete affected section. This tool does not judge facts or declare coverage complete.
finish_dossier freezes the reviewed snapshot and mechanically imports its entries through the existing claim store. Each entry receives a claim ID or explicit error receipt. Retry finish_dossier after a partial import; do not rewrite its frozen content or repeat acquisition. It does not end the agent turn. Continue the existing narrative and typed report handoff only after inspecting the receipt. Do not claim successful storage before that import occurs.
