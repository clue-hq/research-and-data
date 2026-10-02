# Research narrative skills — editorial revision

Status: **Founder-approved skills selected for new research launches in revision 23.** Account/person profiles v23/v23-person select their narrative v2 plus shared editorial v1. The existing v22 system-prompt templates resolve these paths from the selected profile; their wording is unchanged. Historical run pins remain unchanged. This is local catalog integration, not a deployed-service restart or another live research run.

The founder accepted the latest account and both contact previews in `.artifacts/narrative-editorial-round-02-20260927/REVIEW.md`. No further brevity or content rewrite is included in promotion. Account/contact Miscellaneous page sections were subsequently integrated in commit `296922df1`, including recipes, persistence and frontend support. The skill fallback applies only when a supplied runtime recipe lacks that section. Loaded deployment/seed state requires separate verification.

Sections below retain the design and trial history, including the earlier pending Miscellaneous work; statements describing unselected drafts refer to those earlier checkpoints. See the final promotion record for current verification.

## Exact instructions

- [Shared editorial skill](../../../../platform/agents/catalog/research-quality/skills/research-narrative-editorial/v1/SKILL.md): purpose, context, selection, faithful public quotations, evidence versus relevance, residual coverage, examples, critical review and efficient operation.
- [Account narrative v2](../../../../platform/agents/catalog/research-quality/skills/account-research-narrative/v2/SKILL.md): every account section, complete pinned-ICP assessment, timing, practical engagement directions, five-to-six-signal editorial preference, financial relevance and account Miscellaneous.
- [Person narrative v2](../../../../platform/agents/catalog/research-quality/skills/person-research-narrative/v2/SKILL.md): distinctive person introduction, priorities without invented pain, sourced openers, separate angles, public projects, cautions and person Miscellaneous.

Both entity skills explicitly direct the researcher to read the shared skill through `{{skills.research_narrative_editorial.path}}`. The shared skill is a passive instruction resource, not another agent or model call. Revision 23 pins all three relevant resources and their exact hashes. System-prompt role openings remain untouched.

## Decisions captured

| Founder direction | Instruction |
|---|---|
| Preserve research intensity without overwhelming the reader | Select a concise main story; retain residual substantive findings in Miscellaneous. Do not reduce research or alter claims. |
| Quote important public statements | Exact meaningful excerpts across relevant sections, preserving speaker, context and available date; no manufactured or stitched speech. |
| Explain fit and all hard gates | Use the actual project-pinned ICP, including variants, and distinguish hard gates, preferences and exclusions. Unknown criteria remain unknown. |
| Give Why now and How to approach more substance | Explain the event and timing connection; offer concrete, role-aware engagement/evaluation directions. |
| Buying signals need a relevance argument | Evidence plus explicit connection to an actual seller capability, workflow or project outcome; five or six strong points when warranted, no quota. |
| Money should explain relevance | Assess the actual financial criterion when one exists; never substitute funding for revenue, ARR or budget. |
| Keep meaningful person depth | Preserve public wording, experience and distinctive public work without forcing personal facts into a commercial hook. |
| Keep all residual findings accessible | Miscellaneous contains concrete entries, not category names or a link to the full dossier. Citation coverage is not semantic coverage. |
| Avoid new blockers | Brevity, count and 60-second performance expectations are editorial/measurement targets, not new pipeline gates. |
| Generalize beyond the example | Fictional healthcare, manufacturing, procurement and engineering examples; no live account/person names or fixed seller criteria in the skills. |

## Founder review refinements

- Prominent public hobbies, interests and creative projects are first-class contact-page material, even when not product-related. Include an evidence-grounded personal opener where warranted; explain possible email/direct-mail creative use as advice, without inventing sender experience or current preferences.
- Miscellaneous entries need useful specifics and evidence: publication subject/date, the reason for a recommendation, or the scope/period of a prior role. Do not reduce them to names or a generic pointer.
- Older announcement-based signals receive visible dates and specific freshness caveats at the point of use. Distinguish historical facts from unconfirmed continuing activity and do not treat retrieval date as publication date.
- Added contextual bad/better examples using Acme, John Doe and Jane Doe: short Overview versus an encyclopedia, fit versus generic praise, freshness-aware Why now, explicit buying-signal relevance, practical approach, repeated section copy, residual preservation, prominent personal interests, fuller evidence-backed background and grounded personal openers.
- These remain unselected drafts; refinements change neither active prompts nor runtime behavior. The first paid saved-input account trial is complete; its outcome and the subsequent instruction changes are recorded below. A live trial of the latest refinement remains pending.

## First account trial and focused correction

The first saved-input account trial is at `.artifacts/account-narrative-editorial-trial-20260927-run-01/REVIEW.md`. It improved the introduction and source visibility, but still compressed important public wording, exposed internal ICP codes and sometimes turned activities into assumed problems. Citation coverage was complete while semantic coverage was not. Its frozen prompts, skill snapshots and generated page remain unchanged for comparison.

The founder selected three weaknesses to address next. The shared skill now teaches:

1. **Visible attribution and quotation.** For a statement-led point, name the person, their evidenced role and source/date context, quote the words carrying the signal, and then explain seller relevance separately. A link or citation alone is insufficient. Apply this across sections; quote only acquired wording, use an attributed paraphrase when wording is unavailable, and do not manufacture a speaker for ordinary facts.
2. **Preserve the specific signal.** Keep the action, object and meaningful qualifier. A hiring statement about shipping real workflows and a separate statement about idea-to-demo speed are not covered by “interested in AI.” A contextual fictional example preserves each independently, with a relevance explanation and a suitable main-section or Miscellaneous home.
3. **Do not invent the premise of a fit argument.** Separate observed activity, a potentially useful seller capability and the unknown condition to explore. A still-listed role does not establish an internally vacant seat; an event calendar does not establish bad follow-up. A fictional bad/better example shows how to offer a useful demonstration without inventing pain. An inference label or distant disclaimer does not repair an unsupported premise.

Account and person skills reinforce these rules at the relevant section instructions. The account example that previously said a role “remains open” was itself corrected to “remains publicly listed,” with internal staffing status explicitly unknown. Final review now compares headings, fit, timing and proposed approach for contradictions: a condition left uncertain in one section cannot become an asserted fact elsewhere.

All new examples use fictional Acme / John Doe / Jane Doe context. No real-account fix list is encoded in production instructions. System prompts, active profiles, data contracts, selection logic and runtime validators are unchanged. This correction is editorial guidance, not another verification/display gate.

The local trial's overly broad introduction-reference check, stale-fixture eligibility, other remaining editorial defects, contact live testing and the parallel performance target remain separate follow-ups. No additional paid call is included in this focused edit.

Verification after this correction: 11 existing resource-reference/owned-narrative tests passed. Both isolated candidate profiles resolved and materialized the revised narrative/shared skills through the real registry, including cold verification. Active profiles still select v1. Results are retained at `.artifacts/narrative-editorial-refinement-20260927/verification.json`. These checks establish instruction delivery and unchanged ownership mechanics, not live semantic improvement.

## Page-contract limitation before activation

The current `ReadNarrativeInputsTool` returns section recipes from `display/recipes.py`. The current account writer owns six Overview plus four independent Insights sections. The person writer owns five contact sections. Neither contract currently supplies `insights/miscellaneous` or `contact/miscellaneous`.

Do not activate these drafts by only bumping skill pins and then claim the complete preview is supported. Dedicated Miscellaneous needs a separately reviewed section/renderer contract and persistence verification. The user approved the editorial section; this task does not silently decide its frontend transport or component implementation.

The skills explicitly instruct an agent encountering a missing section to retain the prepared residual entries in `/work/narrative-review.md`, save supported sections where possible, and report the surface limitation. That is an honest fallback, **not equivalent to publishing the full residual section** and not a research/import blocker. We do not repurpose How they sell or Research cautions as an unrelated overflow bucket.

At activation:

1. Reconcile account/contact Miscellaneous sections with the backend page recipes, wire schemas and frontend repository/rendering seam; preserve source references, review states and account/person ownership.
2. Confirm residual information is rendered as additional findings rather than silently truncated or treated as a display exclusion. A collapsed section is reader navigation, not deletion.
3. Pin account-narrative v2 + editorial v1 for the account profile, and person-narrative v2 + editorial v1 for the person profile, in a new research revision. Existing runs retain old pins.
4. Existing narrative-skill placeholders in the system prompts resolve the new versions; their role/purpose starters need no rewrite. Verify shared-skill progressive disclosure and materialization too.
5. Run a saved-dossier narrative trial and compare it with the approved preview. No new research is necessary. Measure time/cost and verify the resulting page, not only schema success.

## Review scenarios for the next narrative trial

These are human/model quality-review cases, not runtime completion gates or string-matching tests. Use available saved input or clearly fictional inputs. Do not seed a real research run with fictional example facts.

| Scenario | Expected behavior | Defect to look for |
|---|---|---|
| Statement reveals a concrete workflow | Quote the important words, identify speaker/source, explain the seller connection | Generic paraphrase erases the signal; pain or intent invented |
| One claim holds a launch plus a distinct public view | Represent both meanings across main narrative/Miscellaneous | Single citation counted as complete preservation |
| Project ICP differs from brand ICP | Use the project pin and assess every applicable criterion/exclusion | Familiar seller defaults or sample thresholds substituted |
| Funding available, revenue gate unresolved | Keep financing and revenue distinct; explain the unresolved criterion | Raise amount treated as ARR/budget |
| Target is a clinic or industrial operator | Adapt teams, workflows and operating motion | Unprompted SaaS, GTM, venture or US-only assumptions |
| Practitioner has relevant responsibility, no spending authority | Explain possible user/evaluator relevance | Seniority or persona match presented as a confirmed buyer |
| Public statement describes a successful practice | Preserve the practice and suggest a complementary discussion | Success rewritten as dysfunction |
| Person shares employer hiring post | Distinguish sharing, job requirements and personal statements | Hire's duties assigned to the poster |
| Public book/project is distinctive | Give enough substance to understand it; optional grounded opener | Name-dropping, fabricated sender experience, personality diagnosis |
| A weak or conflicted residual finding exists | Show qualified content and relationship in additional research | Disappears, or becomes an ordinary supported target fact |
| Thin public footprint | Shorter useful page, honest gaps | Filler to reach five/six signals or forced hobbies |
| Rich account dossier | Compact orientation, stronger quoted signals, fuller Insights, residual findings | Wikipedia-like opening or loss of distinct details |

Review completeness by meaning, not count. No schema or profile-loading test can establish the model's editorial quality or prove all findings are represented.

## Verification

- Isolated candidate account and person profiles successfully load the draft skills through the real catalog/registry. Only temporary profile copies select the new versions.
- The existing prompt placeholders select narrative v2; the narrative skill's shared placeholder resolves editorial v1. All selected skills materialize correctly and pass cold verification. Tool grants remain unchanged. Active revision 22 continues to resolve narrative v1.
- `tests/agents/test_skill_references.py` and `tests/arv2/test_quality_owned_narrative.py`: **11 passed**. These check resource/reference mechanics and existing ownership behavior, not model writing quality.
- Manual contract review checked page/key separation, `send_line`, sentence kinds, account/person reference namespaces, versioned saves, shared-section ownership and the missing Miscellaneous recipes. Skills use the current writer contract and explicitly disclose that missing surface.
- No live-account names, example-specific tools or fixed Clue/Zafran criteria appear in the new skills. Fictional examples are explicitly marked as teaching material, never research evidence.
- Initial isolated verification failed because macOS's temporary-directory path included a symlink. Resolving the temporary path to its canonical form fixed the harness setup; no production loader restriction was changed.
- Local loader evidence: `.artifacts/research-narrative-skills-20260927/catalog-verification.json`. No paid calls, workers, application database writes, frontend changes or promotion. Actual generated quality, completeness and latency remain to be tested with saved dossiers.


## Revision 23 promotion — 27 September 2026

- Founder accepted the current trial output and approved proceeding with the skills as reviewed. Exact account/person v2 and shared editorial v1 bodies are unchanged from the approved trial snapshots.
- New profiles v23/v23-person pin the two narrative skills and shared editorial dependency. New recipe/launch revision 23 selects those profiles; new-launch resource loading defaults to revision 23. Existing pinned revisions still resolve their original resources.
- No system-prompt rewrite: v22/v22-person prompt templates remain selected, with profile-derived narrative paths automatically resolving to v2. Tools, model configuration, research, dossier/claim import, ownership and pipeline behavior remain unchanged.
- Miscellaneous production recipe/renderer work remains pending. The skill-defined fallback preserves additional findings in the agent workspace and reports the unavailable surface; it is not equivalent to displaying them in the application.
- Verification includes default launch hashes, both real profile loads, nested shared-skill references, workspace materialization and cold verification, historical pin recovery, unchanged non-editorial profile fields and existing dossier/narrative checks. No paid call or database migration is required for this catalog-only promotion.
