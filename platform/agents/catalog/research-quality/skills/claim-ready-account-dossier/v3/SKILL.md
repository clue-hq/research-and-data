---
schema_version: '1'
kind: skill
name: claim-ready-account-dossier
version: v3
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
Preserve every meaningful account observation and reported statement you find in
the acquired material, including qualifications and contrary evidence. The goal
is faithful coverage, not a shorter narrative or a larger claim count.

Compile the investigation directly into the JSON dossier using the evidence already
in context. Write coherent batches of independent findings as the material is understood.
On a resumed job, inspect the saved dossier state and recover only the context needed
for the remaining work. Batch independent reads. Reopen a source when a specific
missing detail, attribution, quotation or uncertainty requires it.

Preserve useful source-only discoveries as well as the Exa report. A report is one
input, not a completeness guarantee. Reuse source material already inspected during
research. Menus, cookie text and identical boilerplate are not additional findings;
you do not need to record their exclusion. An unseen recording or linked page is
a lead, not available evidence. No source-by-source coverage ledger is required.

Seller context helps you recognize significance; it cannot establish target facts.
Keep provider-reported typed facts attributed to that provider. Do not copy an
enrichment provider's promotional description into a substantive company finding.
Build company descriptions from acquired research and company-page evidence.

Keep review.reason concise and specific to the assessment; do not restate the finding
or its full quotation there. Leave optional agent_interpretation null unless it adds
a useful, distinct interpretation. Preserve detail in the finding, attribution and
qualifications rather than repeating it across fields.

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

Use save_dossier_section(section, findings) to create a complete initial section.
Use update_dossier_findings(section, findings) to add or correct specific findings:
supply the affected complete entries with stable F-IDs; omitted entries stay intact.
The tools durably save the document. /research/dossier/latest.json exposes its document,
draft/import state and receipts. Inspect affected entries when their saved state is
needed for a correction. Edit through these tools; the view is read-only.
A save_dossier_section call replaces the whole named section, so use it only when
intending that complete replacement.

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

A person's statement about the target's operations belongs here with attribution.
Unrelated personal biography is outside this account-only dossier; note a useful person-research lead briefly when relevant.

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
Link the relevant finding IDs when sources genuinely conflict. Either or both entries
may carry the relationship; code resolves forward and reciprocal links during import.
Use existing finding IDs and avoid self-links. Preserve the source judgments.

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

## Section-wise formation guide

Match sections by meaning rather than imposing an exact count. Keep headings and
findings specific to the actual investigation, using these handling principles:

| Area | What to preserve and separate |
| --- | --- |
| Business and operating model | Separate product function, commercial model and operating processes; attribute company descriptions and preserve coherent processes. |
| Ownership, financing and resources | Separate rounds, ownership changes, headcount and resource estimates; retain amounts, units, periods and estimate caveats. Do not infer spending budgets from funding. |
| Strategy and initiatives | One initiative/launch per entry; include stated purpose, owner, timing and stage. Preserve substantive executive explanations separately. |
| Workflows and demands | Complete steps, cadence, handoffs and tools together; separate meaningful statements about pain or constraints. |
| Hiring and organizational change | Separate roles, appointments and departures; retain status and responsibility. Preserve the hiring author's distinctive language as well as the vacancy details. |
| Tools and execution | Preserve tool function, user and time; distinguish required experience, historic use, personal use and reported company deployment. |
| People and responsibilities | Separate each relevant role/mandate and its evidence. Buying-role hypotheses remain interpretations. |
| Public voice and culture | Retain attributed passages and occasion across media. Do not replace expressed priorities with generic culture labels. |
| Timing and developments | Retain independent events and their dates; avoid rewriting the same event as another timeline claim. Historical context stays labelled. |
| Contrary evidence and risks | Preserve adverse reports and responses separately with attribution and unresolved disagreements. Risk significance is optional interpretation. |
| Unexpected findings and gaps | Include concrete source-only discoveries and incomplete assertions. Unanswered questions go in notes; absence from inspected material is not proof of nonexistence. |
| Fit and committee discussion | Attach judgments to underlying observations or notes referencing existing IDs. Do not create repeated factual fit summaries. Keep actual appointments as findings; buying roles and inferred authority remain interpretation unless explicitly supported by an attributed source. |
| Source corrections | Preserve source limitations and suspected errors. Repair this dossier before final submission; do not claim to have corrected historical data. |

## Finish with a reviewable handoff

Use save_dossier_section to create a complete section. Use update_dossier_findings
for new batches or corrections: send only the affected complete entries, with their
stable F-IDs and section name. Omitted findings remain unchanged. Do not regenerate
an entire section to add or correct one finding. Do not use omission as deletion.

Critically review the findings against this skill using the investigation already
in context. Correct concrete defects in the affected entries; consult the relevant
source when needed. Preserve public wording, attribution, independent units and
uncertainty. Keep notes limited to meaningful unresolved questions or limitations,
briefly recorded in /work/review.md when useful.

The tools report saved finding and source-reference counts. These are informational:
an unreferenced source does not establish a missing fact, and a cited source does
not establish that every useful detail was preserved. Judge substance from the
findings and evidence; counts impose no completion threshold.

Call validate_dossier for syntax and reference feedback. Correct affected entries
with update_dossier_findings, then finish_dossier to import. Inspect the receipt;
retry a partial frozen import without rewriting it or repeating acquisition.
Continue narrative writing in this same researcher conversation after import.

## Correct or extend an imported dossier

Read /research/dossier/latest.json first. A completed import is immutable history,
not a reason to repeat research or silently overwrite claims. Start a revision only
when there is a concrete correction, added evidence, or an explicit withdrawal.
Call begin_dossier_revision with the current expected_version and a readable reason.
This copies the imported document into a new draft. It does not change live claims yet.

Keep the same F-ID when revising the same finding. Add a new F-ID for an independent
finding. Preserve all untouched sections and entries. If an existing finding should
be withdrawn entirely, include its F-ID and reason in withdrawals when beginning;
that removes it from the draft while retaining its history. Uncertainty, duplicate
status, wrong entity, or conflicting evidence usually warrants updating the finding's
review metadata rather than deleting it. Do not relabel uncertainty as supported.

Example: Acme's F012 says a public post names a company CTO; closer reading establishes
that it names a Field CTO. Keep F012, correct the precise title and source attribution,
and explain the correction. F013 is an unchanged funding announcement: keep it intact.
An independently discovered event is F014. If F015 was only the researcher's unanswered
question, explicitly withdraw F015 with that reason and retain the question in notes.

Use update_dossier_findings for the affected complete entries, review those changes
against this skill, validate, and finish_dossier. Unchanged findings reuse their claim IDs. Changed findings get
new IDs linked to retired versions; duplicate/conflict references are remapped.
A revision applies atomically: if it fails, previous claims remain current. Read the
errors and fix the draft or retry a transient failure. Do not claim success on failure.
If you need to change the withdrawal list or abandon the edit, use
 discard_dossier_revision with the latest expected_version, then begin again if needed.
A stale-baseline error means another correction occurred; report it rather than
blindly undoing that correction. This workflow only revises this job's own dossier.

After successful import, use read_narrative_inputs and your narrative skill to
refresh your owned pages with write_research_narrative. Use the latest receipt's
claim IDs in the final handoff and inspect the publication receipt before reporting
success. Prior claims, sources, draft versions and correction reasons remain inspectable.
