# Site agent alignment — founder rulings

One section per conflict group, in the order ruled. Wording comes later (step 4); these record decisions.

## Before the ledger (2026-10-27)
- **R0.1** The site agent's skill set is fixed: every skill is available on every turn, whatever the page kind. No dynamic skill routing. *("Delivered" refined by S2: skills are listed in the prompt and read on demand.)*
- **R0.2** Skills are of two families: mechanics/operations, and direction/judgement (semantic outline, copywriting, messaging, imagery, image generation, brand-themed creative). The direction side is thin and is filled from the legacy web skills, with contradictions resolved and web-document language rewritten for site documents.
- **R1** (P1 direction) The site agent handles every kind of landing page, not only one-account pages.

## P1 · Which kind of page, and how the agent learns it — RULED 2026-10-27
- **R1.1** No page-kind field. The site agent works out the page kind itself from the brief, the artifact note and whether account research exists, and writes it as the first line of its message plan: "Who this page is for".
- **R1.2** The Head of ABM's brief opens by saying who the page is for, in plain words (brief template in `manual-siblings`, new version + Head of ABM re-mint; in scope for step 4).
- **R1.3** An untagged page's workspace says plainly that the page is not for one account, so there is no account research, and stops using the title as an account name. Where no account is tagged, the site document gets a name that fits the page, and headings and document names are written for the context (founder: "headings and doc names should be written appropriately based on the context").
  - **R1.3a** (founder addition) With no account tagged, the agent still gathers a little context about the targeted audience: it reads the persona/ICP documents for that audience, and may run a few web searches of its own. (Founder: "the design agent could read the persona-icp doc related to the targetted company audience, or do exa web search itself, a bit to gather a little context.")
  - Already reachable: the brand's pinned knowledge documents are in `seller/`, and `seller/index.md` names the project's confirmed ICP when one is pinned; `web_search` runs on Exa (`web_search@1`). Step 4: the prompt's `web_search` line (today "for the seller's own published case studies") and the `seller/` description widen to cover this. What such context may put on the page as a fact is family 2 (evidence).
- **R1.4** Supported page kinds now: one account; a segment or audience (e.g. "freight brokers"); an event; a product or offer campaign for anyone arriving from an ad or email. ~~**Not now:** a page for several named accounts.~~ **Amended 2026-10-27 (P2 discussion): one-to-few is back in** — pages for a few named accounts are supported. (Pages for one person: P10.)
  - Follow-up for step 3: the site rules written for "a site for several accounts" (D2 account line, account logo, `menuExtra`) keep their case (one-to-few is in).

## P2 · The message plan — RULED 2026-10-27
- **R2.1** One base planning skill, always started first on a new page. From the Head of ABM's brief it walks the agent through a fixed sequence of questions — what kind of page, for whom and for what purpose; the traffic source; the audience and its scale; what the page offers; what evidence it needs; what the visitor already knows — and teaches how to think each one through, not just which fields to fill. It ends by naming the case and sending the agent to that case's skill.
- **R2.2** A case skill per scenario — one-to-one, one-to-few, general campaign landing page (a whole audience or segment), event page, product campaign page (one product or offer, for traffic from a specific ad or email); contact pages added by R10.1. Each covers how to understand and evaluate that reader, what to look for in the research or the seller's files, messaging and tone, and the page's purpose. All are available every turn and read on demand (R0.1, S2).
- **R2.3** Layout approved: base skill `planning-a-page` (the eight-step question sequence: task → who and at what scale → where they arrive from → what they already know → offer and decision → evidence needed and available → the argument → sections and left out, then "follow the skill for your case"), and five case skills (six with contact pages, R10.1; packaged separately, S1.2): one-to-one, one-to-few, general campaign, event, product campaign, each covering the reader, what to read, message and tone, purpose, usual awareness, identity, fitting proof and usual action. Wording moves to a family-2 copy skill and proof sourcing to a family-2 evidence skill; `account-page-copy` splits across the base skill, one-to-one and the copy skill.
- **R2.4** The case skills' expertise is borrowed from the legacy skills Shashank Keshri created or rewrote (campaign-landing-page and references, campaign-page-workflow, web-account-personalization and references, web-contact-personalization, web-decision-material, plan-design), rewritten in site-document language.
- **R2.5** A one-to-few page works from the brief. No set of accounts is tagged to it, and no several-account research path is built. As in R1.3a, the agent may also read the persona/ICP documents for the targeted audience and run a few web searches of its own for a little context. (Founder addition.)

## P3 · How long a page is — RULED 2026-10-27
- **R3.1** No fixed cap in the base skill. Length follows the decision: every section answers one question this reader still has; nothing is padded to look complete; nothing the decision needs is cut. Replaces "up to five" and "rarely more than 600 words".
- **R3.2** Each case skill gives its usual shape as guidance, never a limit: one-to-one and one-to-few often five to seven sections (decision material); general campaign similar; event — what it is, why attend, agenda or speakers, the details, register; product campaign — the shortest: the promise, proof, product-specific case studies or testimonials, and the action; when the company has only one product, also a customer logo wall and similar proof.
  - Note for step 4: a logo wall is proof that sits beside the argument, never a substitute for it (legacy L3b), and on a one-account page it must not suggest the account is a customer (site D3).
- **R3.3** A word budget per section stays as a planning aid, set by what the section has to explain, not by the clone's original slot (slot length: P4).
- **R3.4** "Short beats complete" goes. "Clear beats clever" stays and moves to the copy skill.

## P4 · How much a page explains, and slot length — RULED 2026-10-27
- **R4.1** Substance before container: the plan writes what each section must explain, then picks the section that can carry it (base skill). *(Suggestion item 1; no objection raised.)*
- **R4.2** Decision material lives in the case skills — mainly one-to-one and one-to-few (walkthrough, criterion → mechanism → proof, worksheet only as an optional later aid, attributed proof); a lighter version in general and product campaign skills (the product doing its job, not a feature list). *(Item 2; no objection raised.)*
- **R4.3** Slot length: a rewritten clone line should simply not be overly verbose — a light rule, not a length match. (Founder: "it should just not be overly verbose, that's it… not much emphasis around this though.") When the material needs more room, never cut the material — and prefer, strongly, the clone's own slots or the clone rebuilt as a component; a brand section or a section of the agent's own only when neither can carry it.
- **R4.4** Checks kept/added: swap test, feature dumping, the utility test, and "explain before asking the reader to evaluate". *(Item 4; no objection raised.)*
- **R4.5** "Research is input, not prose" stays in the base skill; turning research into page prose follows the copy skill (family 2). What may never appear on the page is family 2.
- **R4.6** Depth, never over-explaining: write statements that appeal to the reader; do not spell out the logic or inference behind them. (Founder: LLMs tend to over-explain.)
- **R4.7** In drafted page copy, no paragraph runs over 20 words: clear and concise. Home: the copy skill (family 2).
  - Note for family 2: the legacy line "Do not shrink copy into slogans" must be reconciled with R4.6–R4.7 (concise statements, not slogans).

## P5 · Where buttons go — RULED 2026-10-27
- **R5.1** The action is chosen from the reader's decision (base skill step 5), never from the seller's homepage button or an available booking link. Case skills give the usual action: one-to-one and one-to-few — the next step the brief names (meeting, assessment, proposal) at its real scope; general campaign — the demo, trial, contact or resource the brief names; event — register; product campaign — the offer the ad or email made.
- **R5.2** One primary action, same label and destination everywhere it appears (header button included), placed at decision points (after the promise, after the explanation, at the close), not in every section.
- **R5.3** Secondary links: one-account and one-to-few pages carry no links that take the reader away (a cited case study may open in a new tab); general, event and product pages may carry a few relevant secondary links (product page, pricing, agenda).
- **R5.4** Every inherited clone button is decided on purpose: kept with its real purpose, label and destination changed together, or removed. A label never promises what its destination does not deliver.
- **R5.5** The final check's "CTA competition" becomes "more than one primary offer"; "forms ask only what the next step needs" is added.

## P6 · Where the account's name and logo go — RULED 2026-10-27
- **R6.1** One-to-one: the header lockup is the account's place — "Prepared for <account>" with the account's logo beside the seller's; the logo appears nowhere else. The hero names the account in words. No second logo, no account bar.
- **R6.2** One-to-few: the header line names the group ("Prepared for regional health systems") or is hidden; no single account's logo; the hero names the group.
- **R6.3** General campaign, event and product campaign: no account line and no account logo; the header is the seller's own; the hero names the audience or the offer.
- **R6.4** Every case: placing the account beside the seller never implies a partnership, and a customer logo wall never includes the account or a company that looks like it (similar name, parent, subsidiary).

## P7 · Header and footer — RULED 2026-10-27
- **R7.1** One-to-one and one-to-few: the account header template ("one page") with one button, and the plain footer. No seller menu (follows R5.3).
- **R7.2** General campaign: a judgement written in the plan with its reason — one offer from one campaign → a minimal header with the seller's logo and one button; visitors who will vet the seller or arrive from wider traffic → the seller-styled header with a few links to the seller's real pages, and the brand's footer template allowed.
- **R7.3** Event: a minimal header with the seller's logo and the register button, and the plain footer. Product campaign: a minimal header matching the ad or email, and the plain footer; one or two links to the product page or pricing only when they help the decision.
- **R7.4** Every case: the person's explicit request wins; the agent writes which header and footer it chose, and why, in plan.md; a shorter shell never removes information the decision needs.
- **R7.5** In every case, the header's and footer's visual style (its CSS: colours, type, buttons, borders, spacing feel) is copied from the company's own landing page — not its content, links, size or layout. (Founder clarification 2026-10-27: "only the css style of the original landing page must be copied not necessarily the content and size and all.")
  - Follow-up (mechanics, step 3/4): the plain footer (`SiteFooter`) and plain header are drawn in brand tokens, not from the seller's captured header/footer; the header templates are made from the seller's header, but there is no default footer made from the seller's footer. Check what R7.5 needs before rewriting.

## P8 · How much weight the brief carries — RULED 2026-10-27
- **R8** Keep what the site agent receives today: the brief inside its "agent-authored summary" wrapper, the session history, the person's own message last; and the system prompt's rule that the brief sets the goal, the reader and the offer, its facts, proof and structure are suggestions, and a different choice is explained in plan.md. No change. (Founder: "this is good enough.")

## P9 · When the agent may ask before building — RULED 2026-10-27
- **R9.1** Default: build, don't ask. Where something is missing but a reasonable default exists (a cold reader from an email or ad; the brief's named destination as the action), use it, write the assumption in plan.md and name it in the report.
- **R9.2** Ask one short question, and build nothing, only when the page cannot be right without the answer and no reasonable default exists — e.g. who the page is for cannot be told from the brief or the person's message; there is no action or destination at all; an event page has no date or place.
- **R9.3** Never more than one question per turn, and never to approve a plan.
- **R9.4** Mechanics (step 3/4): give the site agent the scene agent's asking path (a clarification tool and the chat clarification card). Until then, asking means ending the turn with the question in the report and saving nothing.

## P10 · Pages for one person — RULED 2026-10-27
- **R10.1** Contact pages are supported (option B): a sixth case skill, built from Shashank's `web-contact-personalization` (and the contact parts of `web-account-personalization`), rewritten for site documents. R1.4's page kinds gain "one person at an account".
- **R10.2** On a contact page the reader may be identified discreetly (e.g. an eyebrow), never as a navbar label, and the material must differ from the account page (explanation, priority, depth or evidence), driven by the person's own sourced professional criterion or documented responsibility. Never private or sensitive interests, inferred emotional pressure or assumed budget authority. On every other page kind, people at the account are still never named.
- **R10.3** The one-to-one skill also covers a page aimed at a role at the account (shaped by the brief's committee notes), never naming the person.
- **R10.4** Mechanics are part of this work: a page tagged to a contact; that contact's research read into the workspace; the identity-binding and allowed-use gates applied before any personal fact reaches the page. The design of these (how the tag travels, which reads, where the gates sit) is an architecture decision to bring to the founder before building.
  - Note: this brings the contact-page part of the privacy/use gates forward from the deferred privacy sprint (2026-10-14 ruling).

## P11 · Video sections — RULED 2026-10-27
- **R11.1** Ambient video that is part of the seller's design — background loops, animated heroes, GIFs and motion used for the look (Pallet, Garner Health) — is kept as the clone carries it. It is never removed deliberately and never swapped for a still image, including in a rebuilt section. `rebuilding-a-section`'s "use the closest brand image" goes.
- **R11.2** Embedded press-play videos (a YouTube/Vimeo-style player, a brand film) are removed — except a short demo player that directly shows what the page argues, which stays.
- **R11.3** When a video stays, the headline still states the promise and the page reads fully without pressing play.
- **R11.4** Mechanics to family 3: clone cards list a section's videos; rebuilt sections can carry video; Safari playback (byte-range serving).

## P12 · Changing an existing page — RULED 2026-10-27
- **R12.1** Small edits — including "add more depth" or "add a section" — keep the current rule: start with site.md and history.md, change only what was asked, ask before adding something the request names that is not on the page. No full re-plan and no rewriting plan.md beyond the change; the agent consults only the skills and guidance relevant to the request, never a forced read of every skill.
- **R12.2** A re-aim (the person asks the page to serve a new audience, offer or page kind) is the only case that re-plans, and only after the person confirms. Once confirmed: re-run the planning skill for the new aim; keep sections that still answer a question for the new reader; rewrite what the aim changes; remove what no longer answers anything; keep the person's own edits unless the new aim needs them changed; report what changed. Same document (saved versions keep the old one); a copy only if the person asks. *(The details after confirmation: suggestion, no objection raised.)*
  - This confirmation is an exception to R9.3 ("never ask to approve a plan").
- **R12.3** When it is unclear whether a request is a small edit or a re-aim, make the small edit, then ask the person whether they want a complete revamp in a new direction or whether a few small changes or additions to the existing page are enough. The agent never re-aims on its own. (Founder refinement 2026-10-27.)

## P13 · Several directions for the same page — RULED 2026-10-27
- **R13.1** Several directions stay separate documents, opened by the Head of ABM, one per direction; the site agent builds only its assigned one (the leg wrapper's assignment block already says so).
- **R13.2** In the base planning skill: when the artifact's note names a direction, the plan states in one line what makes this direction different — its reader or decision, opening message, decision material, section order or visual emphasis.
- **R13.3** Argument alternatives make a genuinely different case, not synonyms; layout alternatives keep the agreed copy and vary composition (hero arrangement, what each section does, visual weight, media). The brand stays fixed either way; reshuffled sections, recolouring or new icons are not a new direction.
- **R13.4** Several directions as pages inside one document only when the person asks for that.

**Family 1 step 2 complete (P1–P13 ruled, 2026-10-27).**

## S1 · How the skill set is organised — RULED 2026-10-27
- **S1.1** Three layers: a **base** planning skill (always first; names the case); **case direction** for each page kind (one-to-one, contact, one-to-few, general campaign, event, product campaign) — what to aim for in that case across every aspect, pointing to the aspect skills; **aspect skills** that teach the deeper how (copy, evidence, imagery and media, visual design and brand fidelity, review, plus the mechanics skills). Case direction never teaches method; aspect skills never hold case direction. Refines R2.2–R2.3.
- **S1.2** Packaging was left open until family 1 step 3: six case skills (A) or one "page kinds" skill (B). *Ruled A, see below.*
- **S1.3** Work continues aspect by aspect; each family also records its per-case direction (each conflict group is asked "anything specific to a case?"), so the case direction fills up as the families are ruled.

## S2 · How skills reach the agent — RULED 2026-10-27
- **S2.1** The system prompt does not carry skill content. It lists each skill (name, when to use it, its path) and guides the agent to read the relevant ones when it needs them. Reverses the spike's 2026-10-08 efficiency ruling ("skills in the system prompt"); today the 7 skills are 39,227 of the prompt's 45,583 characters, sent on every call.
- **S2.2** Follow the scene agent's pattern (scene alignment I7/R7.1–R7.4, S2, R8.6): the library's skills section with our own wording ("read it in one call … read only the skills this turn needs"); one reading rule in the system prompt (as refined by S2.4); read a skill in one call; never re-read what is already in the prompt; a contract test that every skill path the prompt names exists in the delivery.
- **S2.3** The set stays fixed and always available (R0.1); the agent, not the harness, chooses what to read.
- Site facts that make this cheap: the skills are already copied read-only into the workspace (`/skills/**`, `/skills-e5/**`, `/skills-live/**`), and `WholeFileReads` already gives a limit-less read the whole file.
- Risk to watch in trials: the agent skipping a skill it should have read.
- **S2.4** (founder refinement) The reading rule: on a **new document**, read the base planning skill first, then the case skill that fits the person's request and requirements, then aspect skills when the deeper how is needed. Reading from scratch happens **only when starting a new document**; on follow-up edits and improvements the agent reads only what that request needs.
- **S1.2 RULED (A):** six separate case skills — one-to-one, contact, one-to-few, general campaign, event, product campaign — each one read for its case.
- **R4.2 home RULED:** the decision-material method (what to show for each reader question) is its own small aspect skill, pointed to by the one-to-one, one-to-few and contact case skills.

---
# Family 2 · Wording and evidence

## W1 · Which facts may the page use? — RULED 2026-10-28
- **W1.1** Five sources, each used at its own strength (home: the evidence skill, with a one-line pointer in the system prompt): the seller's files (`seller/`, including the ICP and personas); pages fetched with `fetch_page` (the seller's published case studies, the account's own site — numbers and quotes only from that page); the account's research (`research/` and `claims.md`, claim by claim); the brief's facts, at the strength the brief gives them and with their source when it names one, never made stronger, a number checked against the research or seller's files when they hold it; and the seller's own captured sections (clones).
- **W1.2** The clones' words, stats, customer names and quotes are the **last preference**. They are the seller's own published claims, but before using one — especially on a one-to-one page — the agent decides while writing the copy whether that fact fits this page as it is or needs rewording. (Founder: "before we use it, especially for one-to-one case, the agent needs to think during copy-write, is it okay to put this fact as is, or we need to do some re-wording.") A number moved into new copy keeps the clone's figure and whose result it is.
- **W1.3** Web search results (R1.3a) shape the argument; a fact from one reaches the page only after its page is opened with `fetch_page`. A search snippet is never evidence.
- **W1.4** Never a source: the agent's own memory of a company, or the examples written into skills.
- **W1.5** Per case: one-to-one and contact pages lean on the research; general campaign, event and product pages lean on the seller's files and clones; event pages take dates, times, places and speakers only from the brief or the seller's own event page.

## W2 · What the page may say about this reader — RULED 2026-10-28
- **W2.1** The claim ladder stays: product fact → capability → named customer's result → audience implication → forecast (never).
- **W2.2** Audience implication is allowed as a conditional, qualitative statement joining the seller's documented capability to the reader's sourced context ("could help…", "could give… a clearer…"), written as an inference, never as a fact. (Model: Ploy's copywrite skill §12 level 4.)
- **W2.3** Never for this reader: a number, percentage, money amount or time saved, "will" on an outcome, or any certainty about their result. Numeric results appear only as named customers' results.
- **W2.4** Verbs used deliberately: will (guaranteed operations only), can (capability), could (this reader's possible benefit), supports (architecture), helps (contributes, not sole cause).
- **W2.5** Transformation words ("unlock", "supercharge", "best-in-class") are made concrete, or cut.
- Per case: W2.2–W2.3 apply to one-to-one, one-to-few and contact pages; general, event and product pages use "could" about the audience the same way.

## S3 · Ploy as a reference — RULED 2026-10-28
- **S3.1** Ploy's skills (`copywrite`, `campaign-landing-page`, `plan-design`, `brand-adherence`, `build-site-page`, `redactor-and-code`, and the Stripe-for-Cursor conversation; founder's zip `~/Documents/ploy-inspiration 2.zip`) are a reference source **for discussion only**: brought beside the site and legacy rules when a group is discussed, never quoted or referenced in any skill. Not copied into the repo.

## W3 · A number with a condition, and a line under proof — RULED 2026-10-28
- **W3.1** A short scoping condition (a time window, a plan, a region, a company size) stays with its number, in the same sentence or the proof's source line — e.g. "Wynwood House cut guest resolution time from 15 minutes to 3 in its first year."
- **W3.2** A figure that needs explaining to avoid misleading (combined with other costs, a reporter's estimate, one that needs a second clause) is left out. The site's existing rule stays for these.
- **W3.3** Customer results always carry whose result it is, in the same line as the number.
- **W3.4** On **one-to-one pages**, follow Ploy's practice: a short qualification line near customer proof that sits beside account-specific material, saying the results are each named customer's own and not a promise about this account's outcome (Ploy: "These are results reported for each named Stripe customer. They are evidence for the model—not promises about Cursor's outcome."). **Contact pages too** (founder 2026-10-28). Other page kinds: no disclaimer line; attribution does the job.
  - An exception to the site's "caveats never on the page" and to the legacy "no disclaimer sentence" rule; W4 records the general rule around it.

## W4 · What never reaches the page — RULED 2026-10-28
- **W4.1** One list, in one place (the copy skill): the brief's Notes for Design; the research's Watch-outs and Context only; notes on how to approach the account (who to call, what to offer, overlap or competition); file names, line codes, claim ids; the agent's own caveats, strategy, reasons and evidence limits. All of it goes to plan.md and the report.
- **W4.2** The agent writes its own words: never lifts sentences from the brief or the research (exception: wording the person asked for exactly, W12).
- **W4.3** The leaked-note test stays: a sentence that says what the page is not, what the evidence is not, or what the agent was told to avoid is a leaked note — say what is true instead, or cut it.
- **W4.4** Product limits are not stated on the page, and the skills say nothing about such boundaries. The legacy exception ("retain genuine product limits") is dropped. (Founder: "it should not be visible on purpose… mention nothing about this boundary.")
- **W4.5** No "working model" disclaimer: on one-to-one pages the "how it works" section frames itself through its own heading (e.g. "How it could work at Syracuse"), keeping W2's "could". No partnership-denial line; R6.1's "Prepared for <account>" frames the page.
- **W4.6** To write how the product applies (the "how it could work" material), the agent grounds itself first: it reads the seller's product documents in `seller/`, fetches the relevant pages, and runs a few web searches to understand the product — then writes.
- The only visible qualification on purpose is W3.4's proof line on one-to-one and contact pages.

## W5 · Reading research — RULED 2026-10-28
- **W5.1** The system prompt explains, briefly, what the research files contain and what their tags mean, and makes the agent aware of the resources already researched for it (`research/`, `claims.md`, `seller/` with the ICP and personas) and of its ability to search the web. (Founder: "the system prompt should explain in brief about these things… it should be made aware of these already researched resources, and of its ability to web-search.")
- **W5.2** The full key lives in the evidence skill: a plain statement `[c4]` is a sourced fact (checked against `claims.md`); **(quote)** is the account's own words, usable verbatim; **(qualified)** + note is true only with its condition (W3.1) or not used (W3.2); **(inference)** is the research lane's interpretation — it shapes the angle, is never stated as fact, at most a "could" implication (W2.2); **(gap)** is unknown and never filled; a value-narrative claim (Says / For / Angle) is the research lane's argument for a persona — input for the angle, never a fact on the page.
- **W5.3** Said once: facts, interpretations and the page's angle are kept apart; a signal is not a conclusion (a job opening is not a staffing problem, an initiative is not a budget, a technology fingerprint is not an integration).
- **W5.4** Per case: one-to-one, one-to-few and contact pages use this key; on untagged pages the ICP and persona documents (R1.3a) are the seller's view of an audience — interpretations, never facts about a particular company.

## W6 · Evidence bookkeeping in plan.md — RULED 2026-10-28
- **W6.1** Each section's plan entry lists the facts it uses, one line each, with where each came from (a claim label, a seller file, a fetched page's address, a clone) and any short condition (W3.1). No freshness or verification-status columns.
- **W6.2** On one-to-one, one-to-few and contact pages, each benefit statement gets one bridge line: the account's priority [source] → the seller's capability [source] → the sentence (Ploy's claim ledger, for discussion). Makes W2 and W4.6 checkable.
- **W6.3** Final check: every number and quote on the page traces to a line in the plan.
- **W6.4** The planning skill shows the format with one short example; it is not a schema to fill.
