# Native website quality: trace audit and skill repair

2026-09-27. Branch: `codex/design-agent-v1`. This pass changes the native Clue
website agent's canonical skills, role routing and tool guidance. It does not
modify the saved customer pages or launch another provider generation.

## What the saved runs establish

The latest Hotel Equities revision is `run_e1c6758102d95db2a245a70bdafd55dc`;
the preceding create run is `run_b4bd402ca8475c60addf2a97f0991323`, both in
session `dsess_2c2741c027db5344badce796469dcbd7`. Read their saved `trace.jsonl`,
`logs/run.jsonl`, `final.json` and the current checkpoint audit. A read-only DB
query confirms the latest run is terminal `succeeded`; the design verdict was
`completed_with_warnings`. These statuses describe execution, not quality.

| Run | Logged model calls | Run-log elapsed | Summed model-call time | Logged model cost |
| --- | ---: | ---: | ---: | ---: |
| Initial create | 32 | 587.7 s | 555.0 s | $3.361372 |
| Revision | 26 | 345.7 s | 323.6 s | $2.339290 |

These are sums of the existing `model_call_usage` receipts for these two runs,
not the whole project's spend or an independently reconciled provider invoice.
Prompt-token totals include repeated context and cached input. Model reasoning
dominates elapsed time here; rendering alone does not explain the wait.

The latest run made three paginated account reads (offsets 0, 4, 7), two renders
and one clone review. Pagination was necessary; the second render followed a
header mutation. The previous run made three differently phrased broad source
queries returning the identical ordered set of 20 fragments (trace lines 11,
25, 37); the latter two did not add inventory. Do not treat every repeat as waste.

No hard tool failure/refusal was found in the latest compact trace or audited
checkpoint results. Its worker log records successful persistence. A missing
header preview (`cloned_section_no_preview`, trace line 19) is a coverage gap,
not a failed mutation. The agent did read account research and 17 skill/reference
files successfully; missing research/tool access is not the whole explanation.
File-resolution logs show account/workflow/edit/campaign/motion/plan guidance,
then identity/copy/repair references, with create and review later. They do not
show design-guidance or web-media-composition reads in this revision.

## Failures and their consequences

1. **Argument came too late in the workflow.** The roadmap explicitly built,
   adapted and composed sections before its copy pass. That conflicts with the
   copy skill's brief-before-slots instruction. It encourages retrofitting a
   biography and feature labels into a layout instead of explaining a useful
   account-specific application.
2. **Actions and identity were over-prescribed.** Repeated demo buttons were
   inherited from source material; fixed-shell guidance still imposed the
   Prepared-for header in several roles. The actual shell compatibility default
   is `Book a walkthrough` → `#contact`, not `Book a demo`. Neither default is a
   campaign strategy or proof of a valid destination.
3. **Generic design advice competed with source fidelity.** The previous
   design-guidance skill imposed generic color-band/type rules and suggested
   composing product UI from primitives. Source-first composition/media guidance
   requires preserving authentic UI, background, crop and typography instead.
4. **Interaction success was overstated.** Latest trace line 53 reports 6/6
   capture classes and no broken clones, but only the default and second of four
   product states were observed. The final calls the switcher working while
   admitting limited coverage and another static inbox control. The saved tab
   component has four distinct asset bindings: repeated-first-image wiring is
   not established for this version. The missing evidence is all-state behavior,
   including phone, not merely the existence of four image IDs.
5. **A clean geometry result hid important limits.** The review reports a
   reference viewport mismatch and an unmeasured composed/draft band. Both renders
   retain CSS class-collision and incomplete-isolation warnings; final also notes
   slight phone header overflow. Those warnings identify risks, not proof that
   every named class caused a visible defect. Compare affected properties before
   deciding whether to repair them.
6. **Contact depth was weak.** Earlier named-contact material leaned on title and
   appointment rather than a separately read, eligible professional criterion.
   A title cannot establish buying authority, personal pain or motivation.

The visible-page audit covered the five Hotel Equities-related artifacts' copy
and heading styles, with selected rendered bands inspected. It was not a complete
seven-artifact, all-width/all-state acceptance run. Concrete observations include
an opening heading at 32px beside a later product heading at 51px on the contact
page; biography/analyst caveats on account copy; repeated evaluation/demo framing;
and stronger authentic product compositions that subsequent edits must preserve.
Some browser artifact transitions were not stable enough to pair a screenshot
with a selected title; those views are not counted as visual proof. Two older
Hyatt baselines were not fully re-audited in this pass.

Zero design grounding-source/citation counters do not negate the account reads:
`provenance()` currently accepts registered fetched-page/library-asset sources,
while shared-platform research has its own claim/source lineage. Do not pass claim
IDs into that registry as invented design source IDs or equate the counters.

## Changes implemented

Three new progressive skills:

- `web-decision-material`: converts an evidenced priority into a concrete product
  application, demonstration or useful decision exhibit; explanation before an
  optional worksheet, no biography-padding or generic feature tour.
- `web-contact-personalization`: exact contact evidence, professional criterion,
  substantive difference from the account page, and honest role-only fallback.
- `web-product-story`: authentic UI on its branded background, source crop/frame,
  coherent typography and preserved wrapper when repairing interaction.

The workflow now writes the argument, copy and action before assembly. Campaign
skills include an action-selection guide: navigation, evaluation resources,
registration or a supported sales action according to the reader's actual job.
No obligatory demo, invented download, mandatory navbar or false partnership.

The design guide now gives inspected/approved source composition precedence over
generic defaults. Editing records keeper properties and changes only the defect.
Review distinguishes capture coverage from behavior proof and rejects lost
product/background/type strengths. Source readiness reuses identical inventory
instead of repeating broad searches. All web roles route to the relevant new
skills; fixed-shell instructions are conditional in each role and the tool help.
The compatibility shell implementation itself is unchanged.

## Verification and limits

- Packaging RED baseline: the new skills/references were initially unavailable
  to materialized agents. Delivery/routing checks pass after implementation.
- Focused existing suites pass: skill-family delivery, account prompt contracts,
  solo runtime composition, campaign shells and concurrent materialization.
  Final skill/routing changes were rechecked with the first two suites.
- An offline fictional held-out-brand text probe produced materially different
  account/contact decisions, preserved authentic background/UI requirements,
  used no demo, and distinguished team routing from accepted responsibility.
  Its first output was too questionnaire-oriented; the technique/examples were
  refined to explain a worked application before asking the reader to evaluate.
- Bounded subagent review found leftover shell/Prepared-for instructions in two
  role branches; corrected. This reviewer had performed the text probe, so the
  review was not independent of that probe.
- Python compilation and whitespace checks pass. No model/provider generation
  was invoked by these checks. No source capture, customer dossier or artifact
  was seeded or rewritten by this pass.

After confirming zero nonterminal fleet jobs, reloaded the four workers whose
process cwd matches this checkout. All four emitted fresh `worker.start` and
slot-start events. Frontend/APIs, workspace data and existing artifacts were not
restarted or changed. Canonical knowledge syncs by content hash before the next
native turn; no prompt was submitted during activation.

These checks establish delivery and clearer guidance, not persuasive rendered
native-model output. Responsive source-capture gaps, CSS isolation risks and
all-state interaction coverage remain qualification work. The full quality goal
is still open. The next paid validation should be one bounded native run after
its evidence, copy/action brief and preservation checks are ready; avoid another
broad regenerate-and-polish cycle.

Reference patterns informing the audit, not quality guarantees:
[Mutiny's 1:1 ABM example](https://www.mutinyhq.com/blueprints/1-1-abm) and
[Folloze personalization](https://www.folloze.com/platform/personalization)
illustrate account/role relevance and appropriate content selection. They do not
establish a universal page length, required CTA or promised conversion lift.
