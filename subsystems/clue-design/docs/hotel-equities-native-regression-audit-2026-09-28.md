# Native website regression audit — 28 September 2026

This is an audit of the completed native test, not a successful quality qualification.
No follow-up generation, saved-page edit, new ingestion, publication, or remote push
was performed during the investigation. The numbered findings record the failed
run; the follow-up checkpoints below distinguish implemented repairs from remaining
qualification work. General design requirements now belong to shared skills, not
Project Instructions, under the founder's later correction.

## Exact case and evidence

- Chat: `thr_a7807c40f8c855e89498ed90d0e823fb` in Conduit Fresh.
- Run: `run_25af62e80280522cb1ebf1c8f6ba4791`.
- Design session: `dsess_cf97dbc453a05e94b9f439934fc31ee1`.
- Document: `doc_36478cffebd05e1c87aaeaaf9d01fcde`.
- Runtime source checkpoint: `cff9484c`, `codex/design-agent-v1`.
- Saved revision 1; final local generation version 14. Runtime succeeded with
  `completed_with_warnings`; this is distinct from acceptable creative quality.
- Original request was a short request to create a one-to-one page using saved
  account research and Conduit branding, with the correct account mention.

Inspected the Head-of-ABM checkpoint messages and tool results, design checkpoint
calls/results, all 982 lines of the design run log, plan/brief, final WebDoc,
rendered layout/font observations, review receipts, and native desktop/tablet/mobile
previews. Local checkpoints and files provided the necessary traces; no LangSmith
inspection is claimed.

Local evidence is retained under:

- `.local-setup/native-account-skills/approved-native-20260928/`: sanitized Head
  checkpoint messages, native-run trace audit, model-cost receipts, browser captures.
- `.deepagent-workspace/sessions/dsess_cf97dbc453a05e94b9f439934fc31ee1/` relative
  to this subsystem: `workspace/brief.md`, `workspace/plan.md`, and
  `turns/run_25af62e80280522cb1ebf1c8f6ba4791/`.
- Within that turn: `logs/run.jsonl`, `final.json`, `final_web_doc.json`,
  `iter_3/layout_{1440,768,375}.json`, previews, and earlier clone-review captures.

Raw customer context and trace bodies remain in ignored local diagnostics.

## 1. The two sections use different authoring paths and typography

The user's first screenshot is the new `compose_web_section` fragment
`frag_5770a008a92daa9d`, `#abm_workflow`. The second is the source-derived agent
three-up `frag_c400a456d8d7b626`, with text slots rebound while retaining captured CSS.

Measured actual glyph faces and computed styles at 1440px:

| Role | Source-derived section | Newly composed section |
| --- | --- | --- |
| Section heading | Season Mix Regular; 48px; weight 400; line height 48px; tracking -1.44px | Season Mix Medium; 32px; weight 500; line height 35.2px; tracking -0.32px |
| Smaller heading | Season Mix Regular; 24px; weight 400; line height 25.92px | PP Neue Montreal Medium; 20px; weight 500; line height 26px |
| Section heading at 375px | Season Mix Regular; 32px; weight 400 | Season Mix Medium; 28px; weight 500 |

The fonts are loaded. These are observed rendered glyph faces, not merely font-family
declarations. A missing font, stale frontend cache, or fallback font is not the cause
of this specific mismatch. Not every heading should have identical size; the defect
is that the agent invented a separate role hierarchy without grounding it in an
equivalent source role.

At physical log line 486, the model explicitly authored `font-weight:500` for the
custom H2 and `font-family:bodyFont` for its H3s. The plan's typography inventory
named families but omitted a measured role-by-role size/weight/line-height/breakpoint
contract. Source inspections included text-only reads and a product CSS tail window
containing unrelated styles; they did not establish equivalent heading-role rules
before composition. Raw composition accepts these independent CSS choices, and the
review path does not compare their resolved roles against source measurements.

## 2. The logo regression begins in old project context

The Head agent's checkpoint message 17 contains the materialized
`project/decisions.md`. It includes an older Hyatt test instruction to place both
corporate logos in a balanced header, and a later instruction to put the target
logo on the landing page. The later no-navigation correction from this Codex
conversation is absent from the context delivered to this run.

The causal chain is visible without inference about hidden model reasoning:

1. The project library presents these decisions as what the human told the project.
2. Head checkpoint message 35 calls `open_design_leg`, changing the old target to
   Hotel Equities and explicitly requesting both logos in a balanced header.
3. Design `workspace/plan.md:5` labels the expanded brief as verbatim user
   requirements. Lines 28 and 100 justify the header by saying the user asked for it.
4. Log line 477 calls `compose_web_section` with `section_role: nav` and target
   identity inside `#abm_header`. The mobile layout wraps that identity below the
   seller row inside the same header; it is not a separate hero identity treatment.

The new brief does identify itself as agent-authored context, but the model still
promoted its contents to direct user requirements. The earlier provenance repair
was instruction-level guidance and did not enforce this distinction. It also did
not reconcile the stale project instruction. Both failures matter.

Current persistence already supports corrections: `stage0/governed.py:618`
`read_statements` excludes rows superseded by `correction_of_id`. However,
`project_status.py:495` projects rows into `DecisionItem(route_key, quote)`, then
`:628` renders only those two fields. The delivered file drops statement/input IDs,
creation time, and route reference. The read model also omits the table's actor and
entity fields. Downstream agents consequently lack useful scope/attribution detail.

This proves the no-nav correction was absent from delivered context; it does not
claim an exhaustive search found no such statement anywhere in the database.
The user should not need to repeat this correction in every generation prompt.

## 3. Review collected evidence but did not enforce qualification

`final.json.review_evidence` is explicit:

- `status: incomplete`, `quality_verdict: not_computed`.
- `persisted_revision_checked: false`.
- Final local version 14: only the last preview tile was opened at each width
  (1440: tile 4 of 5; 768: tile 5 of 6; 375: tile 7 of 8).
- The clone walk was version 13 and therefore stale after the footer change.
- Source comparison was unavailable because reference width 1920 differed from
  rendered width 1440. An empty `broken_clones` list is not source-parity proof.
- No interaction-state captures establish retained JavaScript behavior.

Earlier versions had additional inspection; the point is that full current-version
coverage was incomplete. Yet the model's final prose described strict checks as
having no blank/missing/unusable-height issues. `finalize_web_run` in
`apps/agent_runtime/lumen_agent/tools/web_substrate.py:10973` validates the outcome
enum and attaches evidence; it does not enforce these coverage/quality conditions.
Saving a recoverable draft with warnings is useful. Presenting it as qualified is
not supported. Metadata instrumentation was incorrectly treated as if it were an
acceptance mechanism.

## 4. Other limitations verified in the same run

- The latest mounted skills were available. There were ten successful skill or
  reference reads, covering workflow, planning, account personalization, source
  readiness, campaign composition, decision material, and copywriting. There were
  no reads of the motion, media, or review skill files. This is not an old-library
  deployment explanation.
- Native tab reuse was available in earlier offline work, but this run did not use
  it. Source feature behavior reported a missing retained controller; the agent
  chose a static replacement. Inbox Todo/Follow Up/Done controls also remain static.
  The live Follow Up activation left Todo selected. No original-JavaScript parity
  is established by copying source HTML/CSS into the React-backed WebDoc renderer.
- The phone page is 8267px tall at 375px. The agent retained an Inbox band showing
  background without the desktop product chrome and acknowledged that in its
  final note. All checked images loaded; successful fetch does not make this a
  useful mobile composition.
- The page reads account research but still spends much of its eight sections on
  generic source product material. One custom workflow and a few evaluation
  questions do not establish a strong account-specific argument. The zero-count
  grounding ledger should not be misread as proof no research was read.
- Five primary demo links share one destination. CTA wording is consistent in this
  run, but that choice came from old project instructions. The current short
  request did not independently request a demo offer.

## Proposed repair order and tests before another paid run

1. **Correct shared behavior and request attribution.** The original proposal to
   record the no-target-logo-in-nav rule in project context is superseded by the
   founder's correction: it must be shared skill behavior in every new project.
   Do not add or restore general rules in Project Instructions. Preserve
   statement identity, origin, target/artifact scope, and supersession through
   project rendering and Head-to-Design handoff. A delegated proposal must remain
   distinguishable from a direct, attributable user request. Test stale assistant
   placement claims separately from genuine explicit user placement requirements.
2. **Bind authored sections to measured brand roles.** Make equivalent source
   heading/body/label roles available with family, actual face, weight, scale,
   line-height, tracking, and responsive behavior. Use them in new composition and
   compare rendered roles against that reference. Test this actual failed custom
   fragment beside the source fragment at desktop and phone widths. Avoid
   Conduit-only constants in global skills.
3. **Separate draft persistence from quality acceptance.** Check explicit critical
   constraints against final DOM/roles, current-version readable coverage, and
   required interaction behavior. Report incomplete evidence as incomplete, even
   when saving a draft succeeds. Bound the repair loop; missing evidence must not
   trigger endless provider calls or an invented pass.
4. **Make behavior and account content decisions before composition.** For required
   dynamic sections select supported native reconstruction and verify state
   changes; name unsupported behavior before choosing a static treatment. Give
   each retained section a distinct account question, evidence, product mechanism,
   and useful reader takeaway. Treat research limitations outside visitor copy.

These are cross-layer corrections, not a proposal to add more general prose to the
skill library. Existing instruction and packaging tests do not prove compliance.
First run offline regressions against this saved failure and inspect the native
renderer. Only after those checks should another separately authorized generation
be considered. No source or live-project correction was made in this audit.

## Time, spend, and boundary

The completed test took about 12m36s including Head orchestration; design execution
was about 10m54s. Recorded model receipts: 7 Head calls / $0.365542 and 36 Design
calls / $3.061164, totaling $3.426706. A prior accidentally submitted account-picker
entry was canceled before design and incurred 2 Head calls / $0.119156. Combined
recorded model spend is $3.545862; this is not a claim about all provider charges.

The native output is a failed quality test and is retained for regression evidence.
The broader website-quality goal remains incomplete. No additional generation was
started during the audit.

## Follow-up checkpoint: project decision provenance

The first code repair now preserves statement/input IDs, captured-input actor and
kind/time, recording actor/time, recorded entity and route/source references, and
correction lineage in `project/decisions.md`. Recorder identity is deliberately
separate from input authorship. Missing scope stays null; it does not become an
all-account instruction. Existing quote verification and erased-evidence exclusion
still run before rendering. The library digest now includes its format version so
fresh turns receive the new representation even with unchanged project rows;
historical pinned generations remain unchanged.

Three regressions failed before implementation: lost source IDs, lost target and
correction references, and unchanged cache identity after a renderer change. They
pass with the repair. Eleven pure rendering tests pass. The surrounding DB suite
returned 56 passes and one unrelated product-confirmation failure:
`test_a_superseded_icp_proposal_file_marks_itself_stale_instead_of_bricking_the_session`.
The same missing `Project.updated_at` error was reproduced with all three modified
production modules loaded from the prior commit. Scoped Ruff/type checks and all
28 dependency contracts pass. Root `make check` stops at formatting in the pre-existing
untracked `tests/arv2/display/test_seller_context_db.py`; that file was not changed.

This checkpoint repairs context information loss, not model compliance. It does
not record the missing live correction, enforce Head-to-Design attribution, alter
typography, or qualify the saved page. No paid probe, generation, live workspace data write,
runtime restart, or remote push was performed. Database checks used fresh disposable
databases removed afterward. The next work remains the canonical correction/handoff,
measured typography roles, and current-render acceptance checks above.

## Selected component preservation requirement

The founder clarified that the typography repair must retain the selected page
component's structure and format. Matching a font family alone does not satisfy
this requirement. The selected source/pin, its heading hierarchy, measured type
roles, layout, spacing, media treatment and responsive behavior form the reference.
Account copy must fit that reference; adding personalization does not authorize
rebuilding it as a differently styled section. A genuinely new section must name
the equivalent source roles it reuses. This is a requirement for the pending repair,
not a claim that a runtime constraint has now been implemented.

The existing exact-copy lane is `repair_cloned_section(text_edits_json=...)` after
`inspect_cloned_section(text_only=True)`, or existing slot bindings when available.
The exact-copy lane retains the captured markup/CSS and preserves the selected pin;
it refuses stale text and conflicting human overrides. Raw HTML/CSS composition is
not an equivalent preservation guarantee. Preserving source bytes still requires
checking the new copy's wrapping, overflow and mobile height.

Offline verification on the current checkout: all 11 native text-repair tests
passed. The browser preservation test initially failed to launch Chromium because
of the filesystem/process sandbox's macOS Mach-port restriction. Re-running that
single network-blocked test outside the sandbox passed at 1440, 768 and 375px:
the synthetic selected component retained type, padding, radius and width, showed
the replacement copy, had no horizontal overflow, and kept its disclosure behavior.
This verifies the existing tool capability on that fixture. It does not prove the
agent selects that lane, validate the saved customer page, or repair its custom
typography. The remaining implementation must carry the selected reference into
composition and check the final rendered result against it. The no-account-logo-
in-navigation correction remains a separate requirement.

No generation, live-page edit, provider call, service restart or push was made for
this verification. The failed native page remains preserved as regression evidence.

## Follow-up checkpoint: measured typography references

The native web runtime now exposes `set_web_typography_reference` to the solo
agent, director and author. It freezes explicitly selected source text roles from
current native layout observations at 1440, 768 and 375px. Each mapping names an
exact reference node/path and target node/path; equivalent roles are selected
deliberately rather than inferred from a shared font family. The same node/path
can be registered before a selected-element edit. Re-registration is idempotent;
a later draft cannot reset an existing reference to its new styling.

The comparison covers family, actual rendered glyph faces, weight, size,
line-height, tracking, alignment, font synthesis, visibility and element tag.
Copy and glyph counts may change. Missing, ambiguous, stale or wrong-page
measurements remain incomplete. Registration is atomic and bounded (1–8 mappings
per call, 24 per turn). Frozen references are archived with the run and the current
comparison is included in `view("review")` and final evidence. This operation does
not mutate the document, render it, or call a model/provider.

If a declared reference mismatches or lacks current measurements, an attempted
`accepted` finalization is downgraded to `completed_with_warnings`, preserving draft
saving and the requested outcome for audit. There is no automatic regeneration or
repair loop. Shared native prompts explicitly retain selected markup/CSS, layout,
heading hierarchy, spacing, media framing and responsive rules; they direct copy
changes through slots or exact text edits and require overflow/mobile-height checks.

Verification:

- A new regression first failed because the native reference tool was absent.
  All 24 focused tests now pass, including real Chromium measurements showing a
  typography mismatch followed by a matching local CSS repair at all three widths.
- All 218 tests in the surrounding native typography, layout capture, solo mode,
  account prompt, review gate, substrate and text-repair suites passed. The 19
  solo/account-prompt tests passed again after the final tool-exposure assertions
  and preservation wording changes. The new module and tests pass scoped Ruff;
  the new module passes scoped mypy; `git diff --check` passes.
- A read-only replay against this failed run's saved final layout observations
  flags both chosen H2 and H3 roles at all three widths. It detects the actual
  Regular-to-Medium face change, the H2 scale/weight drift, and the H3 switch from
  the source serif heading face to the authored sans body face. The ignored replay
  receipt is `approved-native-20260928/typography-reference-replay.json` under
  `.local-setup/native-account-skills/`. This is retained-data verification, not a
  new live capture or model run.

Limits: this is a check of explicitly registered roles within one turn. It does
not make the agent's choice of source correct, cover unregistered text, enforce
all component structure, or persist a brand policy across turns. An undeclared
reference does not block acceptance. Italic style and text-transform are not
separately compared. Exact-copy tooling preserves source markup/CSS, but agent
selection of that path and final content fit still require qualification. The
missing canonical no-logo-in-navigation correction and its handoff remain open.
No native generation, live workspace edit, service restart or push was made; the
saved page and broader quality goal remain unqualified.

## Follow-up checkpoint: original project sources in Design

The original human turn was already present in the design envelope. The missing
context was the original project instructions and decision records behind Head's
expanded delegation. Design previously received the summary and seller knowledge,
without a way to inspect those project source files.

The platform adapter now exposes only the opening turn's pinned `instructions.md`
and `decisions.md`. Their exact text, version/status, artifact key/digest, opening
turn, pin digest and timestamp cross the existing injected adapter seam. Existing
workspace, project and stored-artifact verification apply. No current-state read,
research duplication, new model call or synthesized instruction is introduced.

The native web scaffold writes a read-only `workspace/project-context/snapshot.json`.
Unavailable reads clear the previous snapshot; they do not silently retain stale
instructions. Prompts tell Design to inspect the source attribution and distinguish
an opening-turn snapshot from current explicit user instructions. This makes the
summary auditable; it does not make every recorded statement a human instruction.

The initial regressions failed because the adapter and workspace file were absent.
All 27 tests in the disposable database suite then passed, including exact bytes,
scope and damaged/erased artifact refusals. The adapter passes scoped type checking.
All 312 selected native runtime tests passed: 311 in the sandboxed invocation and
the one synthetic Chromium measurement test on a retry outside the sandbox after
macOS refused its process registration. Changed adapter/read modules and tests
pass scoped Ruff; the harness import-order check passes. Existing unrelated harness
lint warnings were not broadened into this fix.

This source-reading capability neither mutates past turn pins nor proves that the
model reads or obeys the source file. The earlier recommendation to put the general
no-account-logo-in-navigation rule into project context was wrong and is superseded
below. Full selected-component structure and rendered quality remain separate
acceptance requirements. No live generation, page edit, restart or push was performed
for this checkpoint.

## Follow-up checkpoint: shared skills and runtime delivery

The founder rejected storing general website rules in Project Instructions and
said they are deleting that entry. Do not restore it. The shared implementation
must work with a short prompt in a new project, with no project instructions.
The legitimate original-source reader remains useful for project-specific requests;
it is not the owner of general design behavior.

The saved trace explains why adding more optional skill prose alone was insufficient:

- The workflow read requested only its first 200 lines. The file placed review and
  finalization guidance later. The run did not read the construction, edit, media,
  product-story, motion or review entrypoints before its corresponding actions.
- The plan listed family aliases without source role measurements. The custom
  section then used independently authored face, weight and scale choices.
- Runtime author/director prompts told the agent not to draft page prose, while
  the copy workflow required finished words before assembly. A solo account
  example still suggested a co-branded header.
- The construction ladder skipped the existing exact-text lane and claimed variants
  automatically supplied new slots. A missing copy slot could therefore become an
  unnecessary structural reconstruction. Repeated interaction guidance also disagreed
  about when supported typed reconstruction was allowed.

Repairs are shared across brands and projects:

1. `create-website/references/source-format-contract.md` owns the essential source,
   selected-structure, typography, identity, media, motion and review rules. All four
   web roles now receive its exact current contents automatically. A missing/empty
   file fails prompt assembly visibly. Detailed skills remain loaded by need.
2. The workflow is now 102 lines, with construction and review routing before the
   observed read cutoff. The affected planning, source, construction, editing,
   campaign and review skills agree about preserved roles and minimal changes.
3. Source retrieval starts with the selected component or relevant existing inventory,
   then missing page/section roles and reported pagination. Copy-only work uses
   text/anchor inventory rather than complete unrelated stylesheets. Seller source,
   target claims and agent-authored briefs remain distinct.
4. Unbound copy uses the real exact-text repair arguments and a campaign-variant
   note; actual structural changes use original HTML/CSS. No new slots are promised
   by exact-text repair. Observed controllers route to the motion skill even without
   an animation keyword in the request. Supported interactions retain source visuals.
5. Target identity defaults to opening content above the main heading, outside
   navigation. An exception needs the actual user's explicit placement requirement,
   not an assistant's claim that it was approved.

Verification uses fresh-project prompt assembly without instructions or an account
card, account-card branches, missing-file handling, live file revision delivery,
and a supervised read-only skill application review. All 50 focused delivery,
materialization, account-prompt and solo-mode tests pass. Tests demonstrate delivery and
consistent routing; they do not demonstrate production-model obedience or acceptable
pages. Existing artifacts remain unchanged. No native generation, source refetch,
service restart or push was performed for this shared-skill checkpoint. Runtime reload
and one controlled native qualification remain pending after review of these fixes.
The existing source-checkout knowledge layout is retained; a wheel-only installation
omits the knowledge tree and was already unsupported by materialization. No wheel-only
or remote deployment readiness is claimed by these local checks.
