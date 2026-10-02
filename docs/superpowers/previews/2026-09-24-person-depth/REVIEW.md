# Person-depth charter and Exa instructions — review draft

24 September 2026. This folder contains the authored instruction drafts and their review record.
Model-generated requests and Exa trial outputs are preserved separately in isolated artifacts.
These drafts remain outside the active catalog. Editing them does not change runtime selection,
application data or fleet workers; the latest revision and outstanding test are described below.

## Follow-up instruction revision — 24 September 2026

After the isolated person trials, the founder clarified that the person agent owns assessing
coverage, identifying ambiguity and adaptively asking concrete follow-up questions. Updated the
person-agent draft and the skill's "After Exa" section accordingly. The concise prompt delegates
the detailed procedure to the skill: read every source field, assess explicit charter questions,
choose useful next investigations, compose self-contained requests, reassess results and return
expanded findings with remaining gaps. No target-specific benchmark answers are inserted.

The full initial charter and Exa system prompt are unchanged. Captured prior prompts, requests
and responses remain preserved in the isolated trial directories. This revision is draft text
only at that checkpoint. The isolated continuation is now implemented in
`scripts/continue_person_research.py`; its live follow-up result is recorded separately. No
production catalog selection or runtime behavior changed. The implementation notes below are
the original draft's snapshot, not evidence that this follow-up stage has been integrated.

The isolated continuation completed after explicit approval. Its unchanged generated report,
source inventory, requests, transcript, cost/trace receipts and comparison are retained under
`.artifacts/person-exa-comparison-20260924/nick-continuation-03/`. It improved personal discovery
and source use, but did not achieve complete PoC coverage; the comparison records remaining
attribution/date, follow-up priority and quote-fidelity issues. This does not activate the draft
instructions in production. Operational record: `_memory/2026-09-24-person-continuation.md`.

## Exact text for review

- [charter.md](charter.md): the complete provider-facing assignment shape, with explicit
  subquestions and slots the person agent fills from its brief and acquired evidence.
- [SKILL.md](SKILL.md): the person agent's research procedure, query composition, additional-query
  guidance, source review and a clearly fictional Clue → Acme → Dana teaching example.
- [exa-system.md](exa-system.md): the proposed fixed Exa system prompt. Actual identity, dates,
  seller/account context, known URLs and person-specific probes belong in the generated query.
- [person-agent-instructions.md](person-agent-instructions.md): concise person-agent research
  instructions, for later composition with the existing output/finalization contract.

The charter is intentionally more detailed than the delegation brief. The founder's approximate
750-word guidance is for the account → person brief, not a ceiling on the Exa request. No hard
word cap, completeness validator or new research/display gate is proposed here.

## What the references contributed

| Reference inspected | Retained in this draft |
| --- | --- |
| `.context/arv2-person-depth/p3_deep.py`, `BRIEF.md` | Hometown, degree/subject/years/campus activities, first jobs and career origin, non-corporate background, languages; self-shared hobbies, pets, milestones, contributions, projects and recommendations; 3–5 long-form quotations; pride, frustrations and evaluation methods; distinctive findings and gaps. |
| `.context/arv2-person-depth/p1_sweep.py` | Breadth of source angles: writing, media, alumni, awards, personal sites, public posts and communities. Converted into adaptive query choices rather than a mandatory eleven-search preflight. |
| `.context/arv2-person-depth/p1c_targeted.py` | Search known aliases and prior employers to recover earlier public voice. Its hardcoded employer guesses are not a reusable factual source; actual supplied/discovered career evidence must drive searches. |
| `.context/arv2-person-depth/person_vari_kaur.md`, `person_nick_fisher.md`, `PERSON-DEPTH-REPORT.md` | Useful distinctions between short posts and long-form voice, missing subcategories, overlapping career dates, self-described side projects and substantive authored work. Retain source detail beyond a broad summary. Historical results are examples, not guaranteed findings for a fresh run. |
| Chicago `.context/arv2-one-account-conduit-hotelequities/h11_person_deep.py` | Named source leads tailored to each person, career chronology, public writing inventory, personally owned responsibilities, vendor/technology evaluation and pilot/rollout lessons. Generalized beyond hospitality. |
| `.context/arv2-one-account-aiark/z5_exa_deep.py` | Concrete questions and known findings rather than a generic request to "research deeply." This is an account PoC; its company/customer inventory is not a person charter. |
| `/Users/aryankeshri/Downloads/ARV2-research-agent-system-prompt.md` | Separation of concise agent guidance, reusable skill, run-specific brief and provider instructions; public voice and useful personal depth; media and honest thin outcomes. |
| Current account-dossier skill and founder-approved person-briefing skill | Seller/ICP context directs questions without imposing an Exa fit verdict; explicit additional queries; source review alongside the dossier; reuse, no repetitive preparation, email-only enrichment. |

The earlier reference's code-compiled runtime block, mandatory web-first discovery, independent
employment/location proof, outreach restrictions and presentation gates are not reinstated.
Current founder decisions govern: the account agent authors the person brief; the person is
already selected; uncertain useful findings can be retained with attribution.

The PoCs' cold-openers section is deliberately excluded from this research request. Its
underlying discoveries and supporting quotations remain in scope for later writing. Long-form
quote count is an investigative aim, not a reason to manufacture quotes or reject thinner work.
The nine-month window applies to recent developments, not lifetime biography or earlier voice.

## What the current implementation still needs

The active quality person profile is `quality-person-research@v9-person`. It still references
the older shared research prompt v6 and only the governed-evidence skill. None of this draft's
instructions are currently selected by it.

`account_research_tools.py::ResearchDeepArgs` still exposes `charter`, `probes`,
`same_name_exclusions` and 10–25 results to person jobs. `_research_deep` composes the older
identity/evidence system prompt and structured report format. The newer account path uses a
self-contained assignment, separate additional queries and versioned provider instructions.

`quality_provider_tools.py` currently attaches the newer `source_navigation` receipt only to
account deep research. Complete retained originals exist, but the same explicit dossier/source
navigation must be made available for person results; a prompt must not claim otherwise.

The later integration should pin the reviewed person skill, its referenced charter, person
prompt and Exa system together; expose actual supported additional-query arguments; preserve the
full generated query and provider result in existing tracing/ledger paths; and retain original
source navigation. Historical launch pins must remain valid. No model, budget, concurrency,
claim-specialist or page-synthesis change is part of this charter review.

## Review and sample sequence

1. Review the exact text above, especially the nine detailed sections and the adaptation of
   the PoC's openers/unique-insight requirements.
2. Wire the accepted resources and provider handoff. Keep the complete charter accessible to the
   person agent; its final Exa query must carry the explicit subquestions, not just a skill name.
3. Generate one prompt-only sample from the approved account-to-person brief and retained
   original context. Save exactly the system prompt, query, additional queries and tool settings
   the person agent would submit. Clearly separate model-authored output from this authored draft.
4. Review specificity, source leads, useful query breadth and seller context before a live Exa
   call. Later compare dossier and returned sources separately; a richer dossier alone does not
   prove better source coverage.

## Verification of this draft

The skill metadata and relative references were checked locally, and the nine-section charter
was manually compared against the personal-depth PoC and Hotel Equities person questions. No
automated quality score, live model/provider call or runtime acceptance is claimed.
