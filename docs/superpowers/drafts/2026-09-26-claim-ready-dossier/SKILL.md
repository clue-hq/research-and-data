---
name: claim-ready-account-dossier
description: Form a sectioned account dossier of individually attributable findings that code can store without another semantic extraction pass.
---

# Form the dossier as individual findings

## Responsibility and coverage

Your output carries the substance of the investigation into durable claims.
Preserve every meaningful account observation and reported statement you find in
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

## Format: section headings, one finding per record line

Use a Markdown title and `## Section heading` lines. Preserve the relevant dossier
sections. Beneath each section, each nonblank line must be a complete JSON object
with the following fields. No code fences, bullet prefixes or free-form paragraphs
outside records. JSON encoding protects quotations, pipes and embedded newlines
from delimiter ambiguity. A long line can wrap visually; that does not split it.

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

The containing heading becomes the stored section. Code preserves the entry
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
Unrelated personal biography belongs in coverage notes for this account-only task.

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
| Fit and committee discussion | Attach judgments to underlying observations or notes. Keep actual appointments as findings; do not turn seller claims or buying-role hypotheses into target facts. |
| Source corrections | Preserve source limitations and suspected errors. Repair this dossier before final submission; do not claim to have corrected historical data. |

## Finish with a reviewable handoff

Maintain /work/coverage.md: section/source location → finding IDs, plus sources
processed, partially read, unread or unavailable. Explain out-of-scope material
and boilerplate separately. Do not use coverage tracking as a new completion gate.

Read back the dossier. Check that entries retain useful public wording, independent
units, correct attribution and relationship targets. Inspect source material for
omissions, not only the older dossier. Write remaining limitations to /work/review.md.

Call validate_dossier for syntax/source-reference feedback. Correct reported format
issues in the same file. This tool does not judge facts or declare coverage complete.
finish_dossier freezes a snapshot and ends generation. Mechanical import follows;
each entry receives a stored claim ID or an explicit error receipt. Do not claim
successful storage before that import occurs.
