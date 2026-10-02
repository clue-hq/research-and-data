---
schema_version: '1'
kind: skill
name: person-research-narrative
version: v1
summary: The person researcher writes its own source-linked display narrative after
  dossier import.
roles:
- account_research
readiness_requirements: []
tools: []
framework: deepagents
framework_version: '>=0.6,<0.7'
---


# Explain the person you researched

You own this person's investigation and its narrative. The JSON dossier preserves acquired findings; the contact page helps a human understand this individual, their priorities, public voice, relevant background and possible relationship to the seller. Write the narrative yourself after dossier formation. No classifier or narrative specialist is needed. Apply writing instructions without printing them in page prose; label passages containing your interpretation as inference or separate their factual and inferred sentences.

Use the saved person brief, dossier, original sources and actual seller/ICP/persona references. The prior conversation and native archive remain available. Do not restart research or rebuild the findings. Make targeted source reads only when a writing question needs them; batch independent reads. Field names, section names and review labels help navigation but do not determine truth or mechanically hide evidence. The complete dossier remains accessible alongside the page.

## Complete the page

Follow the exact five contact sections returned by read_narrative_inputs. Explain why this person matters, their current priorities or problems, concrete opening lines, distinct engagement themes, and research cautions. The existing contact header retains typed details. Include meaningful career, education, public-project background and public perspective in Why this person; do not invent a separate frontend facts section. Facts can be unavailable; never invent contact details, engagement history, scores or email verification. Public projects and self-described interests deserve meaningful treatment, not just a passing name check or an artificial business justification.

Each section should do its own job. Why this person includes relevant career, demonstrated strengths and public perspective, not just a generic title-to-persona match. Their problem right now may describe a stated priority or a successful practice if no problem is evidenced. Openers should provide actual suggested wording and its source hook. Angles should develop different themes or possible demonstrations, not rephrase those opening lines. Research cautions retain uncertainty and mistaken associations visibly; the historical UI key do-not-mention is not a new eligibility gate. Do not repeat every qualification throughout the page.

Write for a human reader, not a validator or internal auditor. Keep reasoning readable. Do not print field keys, finding IDs, schema labels, registry language or scoring codes in prose. References go in their arrays. Necessary uncertainty belongs beside the relevant assertion; broader research limitations can be explained once in the cautions section. No fixed item quota or arbitrary word limit. Avoid filler, repeated background and defensive boilerplate.

## Preserve what makes this person distinctive

Public statements are important research signals. Keep substantive original wording about responsibilities, priorities, intentions, methods, constraints and judgment. Preserve independent speakers, events and source contexts. Quotes are exact contiguous passages, not stitched fragments, invented speech or rewritten paraphrases. Distinguish a person's own view from material they share or summarize. A post's current profile byline does not establish the person's employer when the historical post was written.

Give useful public professional and outside-work evidence its appropriate place: career changes and motivations; education and early background; authored projects/books/channels; public recommendations and interests; interviews, talks and demonstrations. A podcast listing or show note is not a transcript or proof of the speaker's exact words. Do not invent timestamps. A promising but unread link is a lead, not acquired evidence.

Keep company and personal evidence separate. Hiring-post responsibilities may describe the desired hire, not the poster's own daily remit. Advertising an opening does not establish that the poster completed a hire. Another team leader's responsibilities are not automatically this person's. An employer event or tool is not proof of personal ownership or use. A previous employer's tool or certification does not establish the current company's installed stack. A job title does not establish budget authority. A public hobby does not establish personality or buying criteria. Preserve namesake exclusions without attributing another person's history to the target.

Personal projects can support an informed opener. Do not assert whether the sender has or has not watched/read the material unless that experience was actually supplied. Do not invent shared interests or a personal relationship. Do not force private-life milestones into a sales hook; useful public information can remain in background/findings rather than the suggested message. Proposed wording is new advice, not a source quotation or evidence of outreach permission.

Use actual seller capabilities and pinned context. Explain relevance as a hypothesis supported by the person's findings and seller evidence, not as demonstrated purchase intent. Do not assign all company problems to this person or turn strengths into fabricated pain. Prior interpretations remain interpretations. If a finding is questionable, qualify the narrative and note the concern without changing the frozen dossier.


## Section-by-section writing purpose

- **contact/why-this-person** — Why this person: explain the individual's observed responsibilities, relevant career/experience, demonstrated methods and public perspectives, and why they might matter for the selected seller. Preserve meaningful background and distinctive public work with attribution. Proposed buying role is interpretation, not title-based authority. Do not reduce the person to a job title or company facts.

- **contact/problem-right-now** — Their problem right now: actual stated priorities, constraints and current initiatives. Preserve their public wording and substantive workflow details. Separate their remit from team members' and from prospective hires' duties. If no personal pain is established, describe current priorities rather than inventing pain. Account events are context, not their first-person statements.

- **contact/openers** — Openers: distinct, usable opening questions or lines based on the person's own public statements, projects, work or appropriate self-disclosed interests. Explain the exact source hook and cite it. Proposed message goes in send_line; do not present it as a quote or pretend the sender consumed a podcast/book or has a personal relationship. No flattery or invented seller results. Meaningful personal public work can be a hook without a forced seller connection.

- **contact/angles** — Angles: distinct research-grounded themes, demonstrations or content directions informed by this person's methods, experience, public interests and actual seller capabilities. Explain the proposed relevance as interpretation. Keep meaningful quotations/details. Do not repeat opener wording, diagnose personality from hobbies, or claim unavailable integrations or pre-existing deliverables.

- **contact/do-not-mention** — Research cautions and gaps (current UI recipe key do-not-mention): retain uncertain identity associations, source limitations, disagreements, attribution risks and meaningful unanswered questions visibly for review. Explain mistaken namesake associations without attaching their biography to the person. Do not hide usable findings behind this section or invent a mandatory outreach-eligibility gate. Gaps are not personal facts.

## References, review and save

After successful finish_dossier, call read_narrative_inputs once for the current versions, owned section keys and canonical context paths. Use the existing conversation and dossier. Do not reread all sources or rebuild a classification inventory. Read additional passages only for a concrete writing question; batch independent reads.

write_research_narrative exposes the complete typed schema. Submit all owned pages together: person contact only. Use the exact section keys returned. Each section has intro, items and gaps; each item has h2, body, optional contact_ids and optional send_line. Each intro/body/send_line sentence has text, kind, qualifications and source reference arrays. Use items for the contact sections; put proposed opener wording in send_line with its grounding in body. Order items by usefulness, without arbitrary claim-count quotas. An honestly empty section may have gaps and no items.

finding_ids are your own saved dossier's F identifiers. For a person only, account_finding_ids are the parent account's separate F identifiers; identical local names never mean the same finding across entities. Additional provider enrichment may cite exact claim_ids from /research/claims/0.json. Never reconstruct UUIDs. Use /research/context.json and its complete pinned documents for seller, selected products, ICP and personas. Do not turn seller claims into target claims. The contextual page retains its pinned context; identify seller capabilities and qualifications clearly in the narrative.

Cite the applicable findings for every substantive assertion. Gap statements may have none. Use kind=inference for seller relevance, hypotheses and suggested approaches. Do not mark a block factual when it includes an invented objection or purchase intent. send_line holds actual proposed outreach text with its supporting references, not a quote from the person. Do not invent sender experiences, existing relationships or approval to contact someone. Recruiting establishes an advertised role, not a completed hire. Source quotations remain exact and attributed. Avoid broad absence assertions beyond inspected evidence.

Comprehensively and critically review your complete narrative against ALL the rules and guidance in this skill and the section assignments. Compare findings to narrative for important omitted statements and distinct details, then narrative to findings for unsupported additions, inflated relationships, incorrect attribution and inferred meaning labelled as fact. Correct defects in the actual draft before saving. Keep necessary uncertainty readable; apply instructions rather than reproducing them. No second specialist or mandatory complete source reread is required.

Call write_research_narrative with the reviewed pages and dossier_version (and account_dossier_version for a person) from read_narrative_inputs. Code maps finding references through the committed import receipts and stores existing display blocks without rewriting or classifying your text. Inspect status=published and its compact block_ids receipt before reporting success. On an actionable shape/reference error, fix that error; do not change factual meaning to appease validation. All findings remain available separately, regardless of narrative selection.

On a narrative-only refresh, reuse the imported dossier and current scoped claims, complete the same owned pages and finish. Do not repeat research, import or create a dossier revision merely to refresh prose. Actual new evidence or corrections use the existing explicit dossier revision flow first. Account refreshes do not author contact-owned prose; person refreshes do not overwrite account pages.
