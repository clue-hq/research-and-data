---
name: account-claim-writing-trial
description: Convert one saved account dossier and original evidence into source-linked claims without losing meaningful detail, retaining flagged records and separating interpretation.
---

# Account claim writing

## What you are producing

Preserve the substance of an account investigation in claim records. A good result
lets a reader reconstruct its meaningful findings, source attribution, operational
detail, uncertainty and disagreements without relying on your final summary.
You are not writing campaign copy, scoring fit, or assigning every detail to a
large field catalog. Use the admitted account research-finding tool.

## Understand the material and track coverage

Read the task manifest, delegation context and account dossier. Access the linked
originals through the evidence index. Batch independent context reads when useful;
reuse material you have already read. Do not reconstruct paths or reread entire
files when you need a specific passage.

Build a concise working inventory of distinct findings by dossier section. You
may process and write section by section; do not spend the whole turn constructing
an elaborate inventory before recording anything. Track each finding's passage
or source location and its eventual claim ID. Keep the inventory updated as you
recover further findings from sources.

Inspect the returned source material alongside the dossier. Look for concrete
details it compressed or omitted: process steps, named tools and their actual
roles, public statements, responsible people, product or organizational changes,
numbers and qualifications. Read the relevant retained original when an excerpt
is insufficient. Do not automatically recrawl URLs or request new research.

Distinguish original provider/page/transcript material from an agent's report,
seller brief or tool instruction. A dossier assertion is not its own independent
evidence. If underlying support cannot be located in the saved material, retain
the dossier assertion with that provenance and insufficient-context status.
Do not invent a source reference or cite a page you have not inspected.

Record which sources you reviewed and which remain unread or unavailable. Repeated
provider wrappers or identical snapshots need not be read as independent evidence.
The same URL is not proof of identical content: company/profile pages may contain
different posts, dates or excerpts in different captures. Inspect these differences
before selecting a representative copy; retain each distinct meaningful finding.
Repeated boilerplate, menus and cookie text are not research findings. Summarize
their omission at source level. Preserve meaningful findings even when they are
not helpful to the seller's proposition.

## Write the information faithfully

Use `observation` for what inspected material establishes and `reported_statement`
for what an identified speaker, company, publication or provider reports. Preserve
the attribution in the finding itself where needed so it survives a simple export.
A company saying revenue grew is not an independently verified revenue result.

### Required granularity

One claim must contain one independently assessable finding. Apply this rule before
writing, not just during the final review:

- Each distinct product launch, investment, conference participation, appointment
  or organizational change gets its own finding with its own date and attribution.
  A report listing several launches must not become one umbrella claim.
- A leadership roster becomes separate person/role observations relevant to the
  account. Different people's roles can change independently.
- Distinct public statements with different authors, occasions or substantive
  messages retain their own evidence occurrences. Do not replace a leader's stated
  intent with a generic inference extracted from a job description.
- A coherent multi-step workflow can stay together with its steps, purpose,
  cadence, ownership and tools. Splitting every step into isolated fragments can
  destroy the useful relationship. Do not reduce it to "uses automation" either.
- Within one source, split facts that can be independently corrected or have
  different dates or uncertainty. Keep context needed to understand each finding;
  do not repeat the whole source in every record.
- A new source is a new evidence occurrence, not automatically a new unique fact.
  If it adds no substantive detail, retain the occurrence with `duplicate` and
  the canonical claim reference. Identical snapshots and repeated reads do not
  create additional evidence occurrences.

Illustration: a post announcing an acquisition and a separate conference talk
contains two events. Write two event findings. If its author also explains a
meaningful operational frustration, preserve that attributed statement separately.
An interview explaining one weekly handoff process can remain one finding with
all process steps and its original explanatory passage.

Preserve numbers, units, ranges, dates, qualifications and relationship direction.
Distinguish requirements from current practice, tools a person used historically
from the account's current tools, and a department label from a reporting line.
Different job titles do not automatically conflict. Where dates are ambiguous,
say what each date describes rather than guessing an exact chronology.

Use quotations only for text actually present in the inspected original. Do not
stitch separate passages into one purported verbatim quote. Preserve the source
URL through its saved reference. For transcripts, preserve known speaker and
timestamp information; leave either unknown when the saved material does not
establish it. A statement from an unidentified speaker may be retained as such.

### Give public statements deliberate priority

Public statements are often the strongest signals of intention, resonance,
operating priorities and frustrations. Preserve their useful wording, not merely
what subject they mention. Treat LinkedIn and other social posts, podcast/video
transcripts, interviews, conference talks, webinars, personal or company websites,
blogs, authored articles, books and any other retained source consistently. The
medium does not determine importance; what was actually said and its context do.

For each meaningful statement, retain:

1. The speaker/author and relevant role, distinguishing the interviewer, host,
   commenter, quoted customer and author of the surrounding article.
2. The meaningful original passage. Keep the words expressing pain, priorities,
   ownership, methods, constraints, intentions and motivations, including negation,
   caveats and contrast. Preserve the context needed to understand it.
3. Source URL/reference and available publication or statement date. For media,
   keep known speaker labels and timestamps; for books, retain available title,
   edition and page/chapter. Do not invent missing locators or dates.
4. Optional seller relevance in `agent_interpretation`, separated from the passage.
   Read supplied seller context to understand relevance; do not only preserve
   seller-aligned words or change a statement to strengthen fit.

Use the existing JSON-capable `finding` for a clearly labelled `statement` passage
and necessary factual `context`, or equivalent unambiguous prose. Keep a contiguous
verbatim passage whenever useful; there is no fixed quote length or sentence quota.
If shortening is necessary, retain the signal-bearing language, mark omissions and
keep separated passages separate. Do not silently repair words, join sentences or
turn a paraphrase into a quotation. If acquisition retained only a paraphrase, label
it as such rather than reconstructing an original. An unseen book, recording or
linked page supplies a lead, not an available quotation.

For example, "We need someone to build campaigns end-to-end, work directly with
Sales, and do it without a large team" must not become merely "hiring marketer."
Preserve that illustrative passage and attribution as the reported statement;
any inference about capacity constraints belongs in the separate interpretation.

The research subject is this account. A leader's statement about its workflow can
support an account finding, with the leader attributed. Personal biography and
unrelated personal material belong outside this trial: note their presence in the
coverage map without launching person research or manufacturing account claims.

Your own implication or hypothesis may appear in optional `agent_interpretation`.
Keep it distinct from the sourced finding and explain its limits. Pure judgments
such as "strong fit" are not standalone claims. Record interpretation-only dossier
passages in review notes or attach them to their underlying observation. Do not
invent an observation merely to retain an interpretation.

## Retain records with honest status

Choose a primary review status and a brief reason:

- `supported`: material supports the observation or the attributed statement.
  This means neither independently verified nor approved by a human.
- `duplicate`: an equivalent finding is already stored. Include its real claim ID
  in `duplicate_of`; preserve the duplicate's source occurrence and qualifications.
- `wrong_entity`: material concerns a different entity. Describe the mismatch and
  record the actual entity if known; otherwise leave it unknown. Do not write the
  value as if true of this account or create another entity.
- `insufficient_context`: material is too incomplete to settle the proposed
  assertion. Record what it actually says and precisely what remains unclear.
- `potential_conflict`: another retained claim appears inconsistent about the same
  entity, subject and period. Preserve this statement and link the other claim's
  returned ID in `review.conflicts_with`. Explain the specific disagreement and
  any recency preference. This status does not mean either statement is fabricated.

When concerns overlap, prioritize wrong entity, then insufficient context, then
potential conflict, then duplicate. Keep `conflicts_with` references when a higher-
priority status applies. Both statements may have real evidence even when their
contents conflict. Do not hide uncertainty or perform verification calls.

### Recency and conflict handling

Before declaring conflict, compare actual source passages. Check whether a flattened
name/title line was misparsed, whether the roles differ, and whether statements
refer to different periods, regions or responsibilities. A Field CTO and company
CTO can coexist; a formatting ambiguity does not establish two people claiming the
same job. Unresolved parsing belongs in insufficient context.

When a newer clearly dated appointment or updated attributable statement describes
the current state, prefer it over the older account and retain the older fact with
its historical period. Explain that preference in time context and review reasons.
A newer crawl, profile tenure string, unrelated page update or recent article about
an old event is not necessarily newer factual evidence. An undated source does not
automatically outrank a dated one. A newer secondary repetition does not automatically
resolve a contradiction with original evidence.

If both statements still concern the same period and disagree, or relevant dates
cannot be established, preserve both. Write the preferred current statement first
if justified; otherwise either may be first. After receiving its ID, write the
competing record with `potential_conflict` and `conflicts_with`. If unresolved, say
so without pretending the first write is a proven winner. This one-way reference
connects the pair; never invent an ID or claim a reciprocal update that the tool
did not perform. Recency preference is advisory, not deletion or an automatic
`superseded_by` mutation. Use an actual correction tool to amend existing records
when available; otherwise report the needed change without creating a fake fix.

## Work through the dossier section by section

Match sections by meaning, not an assumed fixed count. For each section: identify
distinct findings, inspect relevant originals, apply the units below, preserve
meaningful statements separately, write and record receipts, then note remaining
material. Return to source-only findings; the dossier is not the boundary.

| Dossier area | How to convert its information |
| --- | --- |
| Business and operating model | Preserve product function, commercial model and described operating process as distinct findings. Attribute company claims. Keep a coherent process together; do not bundle all business facts into a company summary. |
| Ownership, financing and resources | Separate rounds/investments, ownership changes, headcount and resource estimates. Keep currency, amount, date, source and estimate qualifiers. Link conflicting estimates; do not average them or invent a budget from funding. |
| Strategy and active initiatives | One finding per initiative or launch, with purpose, owner, timing and stage when reported. Preserve an executive's substantive explanation separately instead of replacing it with an initiative label. |
| Workflows and operating demands | Keep each complete workflow, steps, cadence, people and tools together. Record a separate reported pain/constraint in the speaker's words. A job requirement describes expected work, not proven current practice. |
| Hiring and organizational change | Separate roles, appointments, departures and changes. Keep open/closed/historical status and scope. Preserve a hiring author's distinctive mission or frustration, not just the vacancy title. |
| Tools, vendors and execution approaches | One independently assessable tool/use observation, or tools within one coherent workflow. Preserve what the tool does, who uses it and when. Personal experience, a job requirement or vendor mention does not establish company-wide installation. |
| People and responsibilities | One person/role/responsibility finding at a time, with source and period. Separate observed responsibilities from buying-role hypotheses; do not write a roster as one claim. |
| Public professional voice and culture | Inventory meaningful attributed statements across all media. Preserve original passages and speaking context. Do not replace first-person priorities with a culture label or attribute host questions to a guest. |
| Timing and meaningful developments | Link timeline entries to existing event claims; create missing distinct events, not duplicate timelines. Separate event, publication and retrieval dates; retain relevant historical context. |
| Contrary evidence and business risks | Preserve adverse reports and responses as separately attributed records. Keep qualifications; link unresolved disagreements. Risk significance is interpretation, not another unsupported fact. |
| Unexpected findings and open questions | Write concrete source-only discoveries. Retain incomplete assertions with insufficient context. Record unanswered questions without turning absence from inspected sources into proof of nonexistence. |
| Seller-fit assessment and committee hypotheses | Attach interpretation to the underlying observation or retain it in notes. Do not create factual claims for fit scores, assumed buying roles or seller product descriptions. Actual appointments belong in people findings. |
| Source notes and corrections | Distinguish evidence from acquisition/synthesis errors. Preserve uncertain assertions with status and references. Correction requires a real write operation; reviewing a dossier does not overwrite its source or repair an old claim. |

This is writing guidance, not a mandatory tool-call-per-section procedure. Do not
omit a finding because its section is unfamiliar. Repeated mentions across sections
can point to the same claim; meaningful differences in public statements cannot be
silently collapsed. Keep personal biography outside this account-only trial.

## Write, read back, and handle overlap

Inspect existing trial claims and your receipts before writing a related finding.
An exact retry should reuse its existing receipt. The writer's retry protection
does not detect synonymous wording. Do not repeatedly rephrase the same finding.

When a distinct source occurrence restates an existing fact, retain it as a
duplicate record pointing to the canonical claim. If it adds meaningful detail,
preserve that complementary detail instead of labelling it a pure duplicate.
Multiple inventory entries may point to one claim; do not fabricate duplicate
records for repeated paragraphs or repeated reads of the same source.

Use returned IDs; never invent them. Confirm the canonical claim exists before
linking a duplicate. Do not claim to have merged sources or corrected an earlier
record unless the advertised tool performed that operation and returned a receipt.
Changing a write payload creates a separate record; it is not implicit correction.
If a needed correction is unavailable, record the unresolved correction openly.

Independent writes may be batched. A duplicate or conflict link depends on the other
claim's successful receipt and therefore follows it. Read the complete batch
feedback before correcting failures; do not repeat successful calls needlessly.
Follow the advertised recovery mechanism and retain unresolved failures in review.

## Check coverage against what you actually saved

Read back saved claims, including every review status. Compare them with the
inventory and dossier sections. Check that detailed processes, attribution,
numbers and meaningful quotations survived; uncertainty did not become certainty;
interpretation stayed separate; and source references resolve to the right material.

Return a coverage map linking passages and recovered source findings to claim IDs,
a readable claim export, and review notes for unread material, inaccessible sources,
unresolved corrections or ambiguity. Separate preserved dossier findings, recovered
source omissions and corrected/qualified dossier statements. Do not report a claim
as stored merely because you intended to write it.

Coverage notes support human review; they are not a new completion gate. Do not
claim exhaustive preservation just because your own inventory has no unchecked
items. Explain the remaining limits and finalize after pending writes settle.
