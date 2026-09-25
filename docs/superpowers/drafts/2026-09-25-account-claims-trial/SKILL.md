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
provider wrappers or duplicated snapshots need not be read as independent evidence.
Repeated boilerplate, menus and cookie text are not research findings. Summarize
their omission at source level. Preserve meaningful findings even when they are
not helpful to the seller's proposition.

## Write the information faithfully

Use `observation` for what inspected material establishes and `reported_statement`
for what an identified speaker, company, publication or provider reports. Preserve
the attribution in the finding itself where needed so it survives a simple export.
A company saying revenue grew is not an independently verified revenue result.

Keep coherent information together. A multi-step workflow can be one structured
finding containing every meaningful step, its purpose, cadence and ownership.
Separate independently meaningful facts when combining them would obscure their
sources, dates or differing uncertainty. Do not reduce a detailed workflow to
"uses automation", and do not split every sentence into a separate claim.

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

When concerns overlap, prioritize wrong entity, then insufficient context, then
duplicate. Preserve other concerns in qualifications. Two conflicting reported
statements can both be supported as statements; attribute each and explicitly
describe the disagreement. Do not hide uncertainty or perform verification calls.

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

Independent writes may be batched. A duplicate link depends on the canonical
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
