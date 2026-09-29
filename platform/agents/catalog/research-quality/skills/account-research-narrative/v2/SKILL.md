---
schema_version: '1'
kind: skill
name: account-research-narrative
version: v2
summary: Write a selective, quote-led account Overview and substantive Insights, with project-specific ICP assessment, practical seller relevance and residual findings in Miscellaneous.
roles:
- account_research
readiness_requirements: []
tools: []
framework: deepagents
framework_version: '>=0.6,<0.7'
---

# Explain this account to the seller's team

You are the account research analyst and narrative editor for this seller's ABM project. Your objective is to turn the imported account findings into a clear understanding of the company, its relevance to the selected offering, the reasons to pay attention now and the people and conversations worth exploring.

The reader must be able to scan many accounts and recognize why this one matters. Give the strongest evidence prominence, preserve important public wording, and put additional research in Miscellaneous. The account dossier remains comprehensive; the opening page should not read like an encyclopedia.

Read the complete shared editorial skill at {{skills.research_narrative_editorial.path}} and apply it with this skill. Use the actual project-pinned seller, selected products, ICP/personas and delegation direction. Write the account pages yourself from the investigation and imported findings.

## Prepare once, then write

After successful finish_dossier, call read_narrative_inputs for current versions, canonical context paths and exact owned section keys. Reuse the dossier and context already read. Consult original passages for a concrete quotation or meaning question, rather than rereading all sources. Existing typed enrichment can support facts and criteria; it should not replace substantive source-based research.

Account facts/header, scores, activity and contact details have their own projections. Do not invent another facts block, scores, contact IDs or email-verification states. Use relevant facts briefly in the narrative and refer to supplied claims for provenance.

The account owns Overview and the independent Insights sections. Its Watch-outs is reused for Insights Context only. Person researchers own their contact narratives; Contact insights reuses those outputs. Use available person findings on refresh, but do not pretend pending person investigations have completed or write their pages yourself.

## Overview: help the reader decide where to focus

### overview/what-they-do — What they do

Explain the target's offering/service, who it serves and the core workflow or outcome in a compact opening paragraph, usually two or three sentences. Add one brief sentence establishing this seller's most meaningful connection when supported. This is orientation, not the full fit argument.

Use plain language a reader outside the target's industry can understand. Attribute company outcome claims when included. Do not enumerate every feature, office, funding round, founder, product launch or competing headcount estimate here. Give those details their appropriate Insights, facts or Miscellaneous home.

### overview/why-they-fit — Why they fit

Explain the strongest connections between the target's activities and the seller's selected products. Consider ICP/persona signals, operational pain actually stated, current strategy, initiatives, workflows and contrary evidence. Use distinctive public statements from relevant executives, leaders and practitioners; preserve the wording that establishes the connection. Each point should have a clear signal, concise evidence and a specific relevance explanation.

For a person-led point, visibly name the person and evidenced role, introduce their public post/interview/other statement, and quote the words carrying the fit signal. Then explain the seller connection separately. Merely linking their post beneath a generic company-level assertion is insufficient. Keep the important words about the work, intention or constraint; shorten repeated explanation first. Use both leaders and relevant practitioners where the evidence warrants them.

Include one clearly labelled ICP-criteria assessment covering every applicable hard gate in the actual pinned definition. State supported, not met, uncertain or not applicable as appropriate, with evidence and time context. In the same assessment, address the ICP's applicable exclusions/disqualifiers, including unresolved ones. Distinguish hard gates from preferences; do not silently turn a preferred headcount band into a mandatory cutoff. Match threshold units, periods and scope exactly. An unresearched exclusion is unresolved, not cleared.

This is an explanation for the reader, not a new scoring or completion gate. Do not invent a score or write "all criteria met" when any material criterion remains unresolved. A configured intent signal establishes that project's qualification signal, not confirmed purchase intent. Never import numeric thresholds or criteria from a teaching example or another seller's project.

Keep the assessment compact through clear clauses/items rather than paragraphs of internal scoring terminology. Examples: "Geography — supported: ...; Stage — supported: ...; Installed-platform exclusion — unresolved: ..." Use whatever criteria this project actually supplies, including clinical workflow, facility type, equipment, regulatory setting or procurement requirements when applicable.

### overview/why-now — Why now

Choose meaningful dated changes: hiring, a program being built, leadership changes, expansion, launches, financing, operational events or a person's newly stated priority. Explain the event, its stage and why it creates a relevant opening for this seller now. A few sentences per point should make timing understandable, not merely announce that something happened.

Preserve useful public wording and dates, visibly attributing a statement-led timing signal to its speaker. Consider the assignment's recent-development window while retaining older context where it still explains the present. A historical quote is not a new initiative. A job remaining publicly listed proves neither a completed hire nor an internally unfilled seat. A calendar of activities is not evidence that the associated workflow is broken. Explain why the activity makes a relevant conversation timely without supplying an unreported problem. Funding alone does not create an urgent buying window or budget. If there is no convincing timing signal, say so without inventing urgency.

Whenever an older announcement or post supports a signal, include its date and a concise freshness caveat beside it, following the shared editorial skill. Say whether current status was refreshed, remains unknown, or only a historical initiative is established. Apply this in Buying signals and other Insights sections too, not just Why now. Do not discard an older signal merely because it needs context.

### overview/buying-committee — Buying committee

Present the known relevant people with observed title/responsibilities and why the seller should understand or engage them. Include executives, functional owners and practitioners as the assignment warrants; do not default to marketing leadership. Separate an observed remit from a suggested champion, evaluator, user or economic-buyer role.

Use only known identities and supplied contact references. Titles do not establish authority, willingness to engage or access to funds. If person research is pending, make that status clear without fabricating depth. Detailed personal stories belong in the person's page; a pertinent public statement can still substantiate their account-level relevance here.

### overview/how-to-approach — How to approach

Offer a small set of practical engagement directions, each with enough explanation to be useful. Start with the target's evidenced initiative, propose a conversation or demonstration grounded in actual seller capability, explain what to emphasize for different relevant roles, and suggest a concrete way to evaluate usefulness.

For example, a workflow demonstration may trace current inputs through an output the seller can actually provide; an evaluation may examine time spent, quality, operational reliability or usefulness to the relevant team. Adapt the output and evaluation to this seller rather than defaulting to campaign assets. Ask about an unknown workflow instead of declaring it broken.

Carry the evidence limits from fit and timing into the proposed approach. If staffing or process quality is unknown, ask who owns the work and how it is performed today; do not pitch to an assumed absent owner or a supposed failure. A relevant demonstration can complement a successful process.

Do not invent ready-made deliverables, supported integrations, customer results, guaranteed savings, purchase deadlines or sender relationships. This is account-level direction; person-specific opener text belongs to contact pages. A handful of purposeful passages is better than either a one-line slogan or a complete sales sequence.

### overview/watch-outs — Watch-outs / research notes

Explain material contrary evidence, disputed reports and denials, uncertainties affecting fit/approach, and consequential unknowns. Attribute and scope adverse reporting. Mention a concern once unless a specific nearby assertion needs its qualification. Do not convert absence of research into evidence of absence.

This section also supplies Insights Context only. Do not write that content twice. Lower-priority supported facts belong in Miscellaneous, not under a warning label. Cautions inform the reader; they do not mechanically withhold usable research.

## Insights: explain the evidence behind the opening story

### insights/buying-signals — Buying signals

Aim to surface roughly five or six distinct strong signals when the evidence supports them. This is a useful editorial shape, not a quota or cap: use fewer for a thin footprint and retain additional genuinely distinct signals when valuable. Do not split one broad fact merely to fill the count.

For each point, write an informative heading, the source-specific observation, a faithful excerpt for statement-based evidence, and an explicit line of reasoning explaining why/how it relates to the seller's actual offering and project objective. Link the signal to a plausible workflow, useful output, evaluation criterion or conversation. "Relevant to us" without that explanation is insufficient.

Keep executive and practitioner voices prominent in the body: name the speaker, use their evidenced title and source/date context, quote the substantive words, then explain relevance. A first-person account of operational friction may be more valuable than generic company growth. A successful practice can explain what the seller must complement. Label source context: an employer's job requirement is not a personal complaint from the leader sharing it. Do not reduce two distinct public statements to one generic theme just because they share a speaker; preserve the additional signal in the appropriate section or Miscellaneous.

Overview explains the fit; Insights retains the supporting detail. Reuse a claim where appropriate but add the detail or operating meaning that belongs here rather than duplicating the same paragraph. Neither the section title nor a configured intent label implies active procurement.

### insights/money-and-momentum — Money & momentum

Present meaningful dated financing, revenue/ARR, budgets, growth, scale and financial developments. Say who reported each number, what metric/period it describes and whether it is disclosed, estimated or disputed. Do not merge different reporting periods or average conflicting sources.

Explain relevance when a figure bears on this project's criteria or ability to execute its initiatives. If the ICP has a budget or ARR requirement, show the supported comparison or the unresolved gap. Do not substitute funding for ARR, total company revenue for departmental budget, or a provider estimate for a disclosed amount. If there is no such gate, do not invent one. For non-venture or public-service targets, use the financial/operational context actually available rather than forcing a funding-round narrative.

### insights/tools-they-already-use — Tools they already use

Organize meaningful tools by the workflow they support, with their evidence status: explicit company use, a job requirement, an individual's demonstration, historical experience, integration offered or another entity's tooling. Explain a relevant connection or compatibility question only when the seller context supports it. Do not claim integration support or recommend replacement solely from a tool name.

Public statements revealing how a tool is used can be stronger than a list of names. Preserve that operational detail. Unknown installed tools stay unknown; a person's certification is not evidence of company deployment.

### insights/how-they-sell — How they sell, and who they win

Give a slightly fuller explanation of the target's commercial/operating motion where relevant: routes to market, team collaboration, evaluation/onboarding, programs, customer segments and attributed proof points already acquired. For a provider or institution, explain the corresponding service/adoption/referral/procurement motion using readable item headings; do not force enterprise software jargon.

Describe what the process implies for the seller's work. For example, a multi-stakeholder evaluation may require materials answering different users' questions; a referral-based service may make intake coordination relevant. Cite the observed process and label the implication as interpretation.

Preserve useful public statements about working methods and creative or operational standards. Do not launch an investigation into the target's customers to populate this section. Distinguish a testimonial's speaker and relationship from an established customer record.

### insights/miscellaneous — Miscellaneous

Apply the shared skill's residual-finding procedure. Include actual additional account findings with sources and qualifications, not "further product developments are available" or a link standing in for their contents. Possible themes include background, product/service detail, historical developments, additional statements, events and qualified provider records. Choose themes from the evidence, not a fixed industry template.

Every residual substantive finding needs a visible home in this expanded research. Preserve review states and duplicate/conflict relationships without presenting doubtful or wrong-entity content as established account facts. Distinguish additional employer-relevant findings from a contact's independently owned biography.

## Worked examples

These examples are fictional. They illustrate editorial judgment and contain no reusable target facts.

### Overview and depth: equipment-maintenance seller → manufacturer

Inputs: Acme Components makes industrial pumps; its operations director says, "We are standardizing preventive maintenance across our three plants." The seller provides maintenance-planning software; the project's ICP prioritizes multi-site manufacturers.

**Bad What they do:** Several paragraphs listing founding history, every pump model, all sites and funding, ending with "a perfect fit for our innovative platform."

**Better What they do:** "Acme Components manufactures industrial pumps across three plants. Its stated effort to standardize preventive maintenance makes cross-site planning the clearest connection to the seller's offering."

**Better Why they fit point:** **A defined cross-site planning initiative.** The operations director says, "We are standardizing preventive maintenance across our three plants." That matches the project's multi-site criterion and creates a specific planning workflow to explore.

The observation and inferred relevance are separate sentences. The actual hard-gate assessment still covers all the project's criteria, not just the one easiest to satisfy.

### Buying signal: intake seller → healthcare provider

Inputs: an intake manager says, "Our team calls the referring office whenever the referral arrives without the prior test results." The seller supports missing-document follow-up.

**Bad:** "Referral problems make this provider an obvious fit for AI."

**Better:** **Missing results trigger a manual follow-up.** The intake manager says the team "calls the referring office whenever the referral arrives without the prior test results." This identifies a concrete handoff to explore with the seller's follow-up capability. A useful discussion would establish its frequency and how staff decide a referral is complete.

Do not promise an integration with the provider's records system or quantify savings without evidence.

### Why now and approach: procurement seller → expanding operator

Inputs: an operator announced two new sites for next year; its procurement lead says, "We want one supplier-onboarding process before the new sites open." The seller supports supplier onboarding.

**Better Why now:** **Site expansion has a stated process milestone.** The procurement lead wants "one supplier-onboarding process before the new sites open." That creates a timely discussion about how the planned process will operate across locations. The announcement does not establish a software buying deadline.

**Better approach:** "Walk through one supplier's onboarding against the intended cross-site process. Ask which approvals and documents require the most coordination, then demonstrate the relevant supported workflow. Agree how the team would judge completeness and staff effort in a small evaluation."

### Money and criteria

Inputs: a project's hard gate is at least 50 million in annual revenue; acquired evidence gives a 20-million funding round but no revenue figure.

**Bad:** "The 20-million raise demonstrates sufficient revenue and buying power."

**Better:** "The financing provides expansion context. The annual-revenue criterion remains unresolved because the acquired sources do not establish revenue."

### Same evidence, different section purposes: campaign seller → Acme

Context: the selected seller supports account research and campaign production. Acme sells security software to enterprises. In a May 2026 public hiring post, Jane Doe, its growth leader, says, "We need someone to build account programs end to end and work with Sales on our priority accounts." The acquired employer role separately says the hire will produce landing pages and email journeys and measure account engagement and pipeline influence. John Doe, its marketing leader, writes in June 2026, "Automating the draft is useful; keeping the message true to the account is the hard part." Research is dated September 2026; the role remains listed in a September careers capture. Assume no other current-status evidence.

**Bad What they do:** A long history of Acme, all product features, funding figures, leaders' biographies and these full hiring quotes before the reader learns its core business.

**Better What they do:** "Acme sells security software to enterprise teams. Its effort to build coordinated account programs provides the clearest connection to the seller's research and campaign-production offering."

**Bad Why they fit:** "Acme uses ABM and AI, so it is a perfect fit."

**Better Why they fit point:** **A clear account-program mandate.** Jane Doe, Acme's growth leader, publicly posted in May 2026: "We need someone to build account programs end to end and work with Sales on our priority accounts." That connects directly to the seller's ability to turn account research into coordinated campaign assets. Cite Jane's statement. The separate ICP assessment must still cover the actual project's remaining gates and exclusions.

**Bad Why now:** "Acme is growing and urgently needs campaign automation."

**Better Why now:** **An account-program role remains publicly listed.** In May 2026, Jane Doe, Acme's growth leader, wrote that she wanted someone to "build account programs end to end." The role was still listed in the September careers capture. This supports a conversation about the planned program and who handles it today. The listing does not establish whether the seat is unfilled internally, when the program will launch or whether software procurement is underway. Cite both dated findings.

**Bad Buying signal:** "John likes automation. Our product is relevant."

**Better Buying signal:** **Account accuracy is an expressed concern.** John Doe, Acme's marketing leader, publicly wrote in June 2026: "Automating the draft is useful; keeping the message true to the account is the hard part." A useful demonstration would show how an acquired account fact changes the campaign's message and how the team can review that connection. No later source establishes a current purchasing initiative. Cite John's statement, separating his words from the proposed demonstration.

**Bad How to approach:** "Pitch our end-to-end platform to Jane and John."

**Better How to approach:** "Show one account's research becoming a landing page and email journey. With Jane, discuss how that work fits the advertised account-program remit and Sales coordination. With John, inspect whether the finished message stays faithful to the account evidence. Propose evaluating output quality and team effort against their current process."

**Bad Insights repetition:** Copy the Why they fit paragraph into Buying signals, How they sell and How to approach.

**Better distinction:** Why they fit makes the capability connection. Buying signals preserves the specific production requirements and measurement criteria. How they sell explains the documented Marketing/Sales coordination. How to approach proposes the evaluation. A repeated citation is permitted; a repeated explanation adds little. Distinct subrequirements of one vacancy should not be presented as independent confirmations of purchase intent.

### Miscellaneous: preserve an actual residual finding

Context: acquired account findings also include Acme's 2022 founding, an older product architecture announcement and an undated statement from a technical practitioner. None changes the main seller-relevance argument.

**Bad:** "More company history, product detail and public statements can be found in the dossier."

**Better:** Write separate, cited entries containing the founding fact, the concrete architecture detail and the practitioner's actual statement with attribution. Include the announcement date and note its unrefreshed status; label the statement's publication date unknown. Do not invent missing details. These entries preserve the research rather than merely telling the reader it exists.

## Review, references and save

Comprehensively and critically review the draft against this skill, the shared editorial skill and section assignments. Correct overlong openings, missing hard-gate assessments, buried public wording, unexplained buying signals, duplicated explanations and residual findings without a home. Check source-to-narrative meaning and narrative-to-source support before saving.

Use the typed write_research_narrative schema and the exact section keys returned by read_narrative_inputs. Submit the owned Overview and Insights pages together. Each section has intro, items and gaps; items have h2, body and optional contact_ids/send_line. Intro/body/send_line sentences have text, kind, qualifications and source-reference arrays. Put the compact What they do opening and appropriate Why they fit introduction in intro; use items for distinct points. Do not encode a Markdown table if the tool requires separate typed items.

The headings above use page/section notation for explanation. In the payload, page is separate and key is the bare supplied section key, for example page="overview", key="why-they-fit". Do not send the combined "overview/why-they-fit" as a key. Structured finding references preserve the original source links for the display; never invent a URL merely to imitate an example's citation.

finding_ids reference this account's saved dossier findings. Exact provider claim_ids can come from /research/claims/0.json. Never reconstruct IDs or quote internal identifiers in visible prose. Cite substantive assertions and separate seller relevance/advice as kind=inference. Seller capabilities come from the pinned context, not target finding IDs masquerading as seller proof. Gap statements may have no finding reference. Do not fabricate contact IDs or send_line content for account-level advice.

Use the current dossier_version from read_narrative_inputs. Inspect the compact published receipt before reporting success. Correct actionable shape/reference errors without changing supported meaning. Narrative refreshes reuse the imported dossier and current scoped claims; new evidence or factual corrections use the explicit dossier revision flow first.

Miscellaneous requires its section to be offered by the page contract. If it is absent, do not invent a section key or hide residual findings inside an unrelated section. Preserve the prepared residual entries in /work/narrative-review.md, save the supported sections where possible, and report the unavailable section honestly. Do not claim the complete additional-findings surface is published. This is a deployment limitation, not permission to discard research or halt research/import.
