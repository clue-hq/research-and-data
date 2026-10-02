name: arv2-account-dossier
version: v3

# The account dossier

## The ladder, and what each rung is for

1. **ATS board first** (`read_ats_board`): the single highest-value, zero-cost action in every run —
   it moved accounts from 4th to 1st and 2nd to 3rd in the smoke test. Read the full job
   descriptions; the SDR stack is often named inside one.
2. **Careers page even without an ATS** (`fetch_page` on `/careers`): a Webflow careers page with no
   board behind it hid five US GTM roles from job-board search. If `board_not_found`, fetch the
   careers page; hiring is not a gap until both are read.
3. **Own site**: homepage, product, about, customers / case studies, the funding announcement on
   their own newsroom. The homepage carries the named-customer testimonials.
4. **Known recordings.** Read a relevant known URL directly with `read_media`; no paid
   discovery is needed. Do not infer speech from a page description or assume speaker identity.
5. **AI Ark company** (`lookup_company`): enrich exact-company facts and retain the company lock.
   Company IDs are supplied by the runtime. Do not discover known names as a prerequisite.
6. **Gap searches** (`search_web`): for named facts and named people. **A signal that lives in
   a person's feed is found by looking up the person, not by describing the feeling** — the
   natural-language "founder pain" query returned vendor blog posts; the founder's actual complaint
   was in his LinkedIn feed.
7. **One deep call** (`research_deep`) with the charter below **plus 3–5 account-specific probes**
   written from what rungs 1–6 found ("who does the ABM req report to, by name", "was the ABM
   manager hired or was the role converted", "why does the campaign-ops req sit in Customer
   Success"). A negative answer to a probe matters as much as a positive one.
8. **One cheap negatives search** (`search_web`, criticism-aimed: complaints, layoffs, reviews,
   rumours, churn, competitor scepticism) in addition to charter section 11 — the deep call is the
   only source of the reputation layer in some runs, and a second angle is cheap. "None found" is a
   real, reportable answer.

After the Exa deep attempt, explicitly plan media questions from its findings and gaps.
Use the v3 manual's discover → read → search → open loop. Media is not a gate on AI Ark SMART
committee discovery or fanout. Stop honestly with evidence and named unsearched channels.

## The dossier charter — twelve sections

1. **Identity and disambiguation** — legal / operating name, HQ address (and where the go-to-market
   team actually sits, if different), founding year, domain(s), company LinkedIn URL, employee count
   with its source, and an explicit list of the same-name entities excluded and why.
2. **Product and who they sell to** — the product in their own words, the exact buyer title, the
   size and enumerability of their target universe (quote any count), integrations, pricing model if
   published, positioning against named competitors.
3. **Traction and named customers** — every customer named anywhere, logo counts, ARR / revenue if
   stated, per-customer outcome metrics, and WHO claimed each number (company vs investor vs press
   vs an automated estimate).
4. **Funding** — every round with exact amount, date, lead and participants; total raised; valuation
   if reported; undisclosed strategic cheques named as undisclosed; stated use of proceeds or a
   public growth commitment.
5. **Go-to-market hiring, with quotes** — every open GTM / marketing / sales role with published
   date and whether still open; quote the parts of the descriptions that describe HOW they find and
   reach target accounts (lists, account research, outbound, campaigns, ABM, field marketing,
   events, tooling to operate); compensation ranges if published; who each role reports to; anything
   open unusually long.
6. **Marketing, ABM and intent tooling** — evidence per named tool: CRM, marketing automation, sales
   engagement, data providers, and specifically the ABM / intent platforms (6sense, Demandbase,
   Terminus, RollWorks, Mutiny, Folloze, Influ2, Madison Logic, ZoomInfo, Clay, Common Room, Gong,
   Salesforce, HubSpot, Marketo, Outreach, Salesloft, Apollo, LinkedIn Sales Navigator — the ICP may
   extend the list). NOT FOUND per tool you cannot evidence; **NOT FOUND is not "not installed"** and
   is written as such.
7. **Leadership and GTM org** — every named executive and marketing / sales / partnerships / RevOps /
   customer-success person with exact title and either a saved provider reference or the URL naming them; when each joined; reporting
   lines where stated; any GTM seat VACANT, being recruited, newly filled or recently departed
   (< 12 months), with dates. A vacancy is recorded as a signal, not a person.
8. **Operational pain and strategic moves** — the constraints the company itself describes about its
   own business (growth, hiring, category competition, partner motion, product gaps) and the moves it
   says it is making next.
9. **Culture and resonance** — how the company and its leaders talk about themselves and their work;
   publicly aired frustration, employee sentiment, attrition signals; awards and recognition.
10. **Timing events**, newest first, each dated — anything in the last nine months that changes
    buying posture.
11. **Reputation and negatives — REQUIRED, never skipped** — acquisition rumours and their settled
    outcome (CONFIRMED / DENIED / UNRESOLVED, by whom, with quotes from both sides), founder
    departures, slowing growth, layoffs, down-rounds, churn, incidents, lawsuits, negative reviews,
    sceptical commentary about the company or its category. For every item: who reported it and
    whether the company responded, and one line on what it means for approach (a bad review of the
    tooling they use today is an opener; a layoff is a landmine). Born `outreach_safe = false`.
12. **The champion's team and vendors** — every other person on the marketing team by name and
    title, and any agency, contractor or vendor they publicly credit.

## The fit verdicts

`finalize_research`'s `fit_verdicts` are one verdict per ICP gate, keyed by the gate's `key` from the
ICP's `hard_gates` — not a label of your own. A gate the ICP does not name is refused
`invalid_arguments` and the refusal lists the keys it does name; an unassessed gate is recorded
`unclear` with the rationale "not assessed" by the tool, so the receipt says plainly what was
checked and what was not. A second verdict for a gate you already answered is dropped (the first
answer stands) and reported back as `duplicate_gates` — never a refusal of the whole call. A `fail`
needs cited contrary evidence (`claim_ids`); a `fail` with none is recorded `unclear`.

## Committee

After the account deep attempt, use the researched company, ICP and pinned persona map to choose
specific buying responsibilities. A founder-led startup may combine buyer and champion; a mature
team may separate budget, operations and technical evaluation. Give concise role hypotheses and
evidence references, not private deliberation.

Call `discover_people(role_key, rationale, evidence_refs, titles, seniority?, functions?, page?, size?)`.
Use SMART matching to broaden title terminology. The server locks the exact company; you cannot
change it. Optional filter values must be supported. Omit unnecessary filters. Page zero is first;
refine titles or inspect later pages when useful roles remain uncovered. No empty-title roster pull.

Use `read_people_result` to inspect full profiles without spending again. Assess responsibilities,
seniority, scope and account relevance. A matching title is a candidate, not an automatic committee
assignment. Explicit employer conflicts cannot be selected. Missing optional fields stay unknown.
Search references are reusable across role hypotheses; an uncertain dispatch is a gap, not a retry.

Finalize through `committee_candidates` in preference order:
- `evidence_kind="provider_candidate"`: `candidate_ref`, persona and concise rationale. Names,
  title and LinkedIn are read from the saved profile by the server; no web URL is required.
- `evidence_kind="web_candidate"`: name, confirming URL, evidence span, optional LinkedIn,
  persona and rationale. Use for provider gaps and corroboration.
- `evidence_kind="unfilled_role"`: role_key, persona and gap_reason. Set vacant_seat only when
  a confirming URL and evidence span establish a real vacancy. No result never proves vacancy.

Deduplicate people before the committee cap; one person can cover several responsibilities in
their rationale. Do not claim exhaustive coverage. Name unresolved roles and channels not searched.
The selected profile is handed into person research; work-email and phone enrichment then run
alongside deeper person research. No extra named-person search is required for selected profiles.

## Structuring, and the second pass

0. **Give it sources, not a wall of text.** Every page, posting, report or transcript goes in as its
   own source with the URL it came from; your own reading of the material goes in `notes`. Quotes may
   only come from inside a source, and a claim cites the URL of the source its quote is actually in —
   so a quote can never end up attributed to a page that did not carry it. Nothing in `notes` can be
   quoted: it names no source, and a claim quoting it is recorded with the quote marked NOT FOUND.
1. One broad `structure_material` call per subject (the account; each committee member) against the
   catalog. The structuring client owns the prompt: verbatim spans, catalog-only keys with proposed
   fields, `outreach_safe` and `use_class` rules, no birth date / age / health / religion / politics /
   family, third-party sources named as such. In R2 the only admitted `subject_kind` is `account`; a
   `person` subject is refused `invalid_arguments` until R3 composes contact entities, so a committee
   member's material is structured as account-scoped material.
2. Then one **narrow intent sweep** per subject (`mode="intent_sweep"`): every VERBATIM public
   statement by the subject about a named tool praised or criticised, the state of or a gap in their
   GTM stack, target lists / account research / outbound / ABM, a named bottleneck, a team size they
   are scaling to or a hiring mandate. One row per statement, priority 1, at most four per subject,
   never a placeholder. This pass found the run's best claim after two broad passes missed it.
3. `structure_material` **writes** the claims it extracts and returns them to you with their claim
   ids and markers — nothing is echoed back through you for re-typing, because re-typing a verbatim
   span is the fabrication risk the structuring pass exists to remove. Each claim is written on its
   own, so one value the store will not take is reported back as a `write_failures` row and costs
   the rest of the batch nothing. Your review of **field
   meaning** therefore happens on what came back: "Open Positions (14)" is not a headcount band; open
   engineering roles are not total open positions. A value that validates but does not mean what the
   field means is corrected by writing a new claim with `write_claims` carrying
   `corrects_claim_id` — the id of the claim it replaces. Signal priority (P1 / P2 / P3) is emitted
   by the structuring pass, never asked of you as a separate step.
   The catalog names each field's shape (`[shape: …]`), and a `write_claims` receipt whose
   `schema_valid` is false carries `expected_shape` and a `hint` — rewrite the value in that shape
   and write it again with `corrects_claim_id`; never leave a value you can reshape.
