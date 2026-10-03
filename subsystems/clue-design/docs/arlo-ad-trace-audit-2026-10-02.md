# Last two native Arlo ad runs — trace audit

Read-only audit, 2026-10-02, against `brand-context-fixes/typography` at `e460f83f4`. No new generation, model request, ingestion, database write, runtime change, or product-code edit. Proposed repairs below are not implemented or qualified.

## Conclusion

The skills and usable brand assets reached both agents. These were successful native executions with weak creative decisions, not missing-skill or failed-harvest runs. The concrete failure chain is: sparse account argument → type-led direction with a large contrast card → review against a weak self-authored plan → accepted output. There are also two specific shared-system gaps: the account-relevance test permits industry-level relevance, and the reference-fidelity gate does not activate from merely viewing/reusing a Brand Context asset.

This corrects the initial diagnostic hypothesis that another harvest/reference-ingestion pass should be the first repair. These traces do not justify blanket re-ingestion. Fetching a specifically missing example may later help, but the current inputs already support a much stronger result.

## Exact runs

These are the latest two local scene-candidate runs by completion time. They started together in the same two-artifact request, not as sequential revisions.

| Item | Guest messaging | Front office |
|---|---|---|
| Run | `run_736347f87149576f8cdc4bfe5eae5f67` | `run_d82c3cd7f2b25c45aa088ad3d9e86de4` |
| Session | `dsess_f4613444472a533cafbeaee8f7d90f5d` | `dsess_72c0542167f85ba4ba4509d76f2394ef` |
| Document | `doc_d1461d4fb8b45db29302dc5c38073443` | `doc_0f99a6aa783751a380934b04c1ada601` |
| UTC start / finish | 20:24:06 / 20:30:43 | 20:24:06 / 20:31:31 |
| Elapsed | 397.476 seconds | 444.706 seconds |
| Model calls / failed model calls | 28 / 0 | 34 / 0 |
| Compile attempts / failed attempts | 5 / 1 | 7 / 1 |
| Preview renders | 2 | 2 |
| Formal critique rounds | 1 | 2 |
| Final status | Accepted | Accepted |
| Playbook | `type-led-positioning` | `type-led-positioning` |

Both were inside Conduit Fresh, workspace `ws_23c8a42f25f3429f8f2921e21a484b3b`, project `prj_3163f6dba3d45cbca2ef995361f9bd07`. Model-role traces show solo mode: one orchestrator authors and reviews, no delegated reviewer. This topology is confirmed; its causal effect versus another topology is not established by these two runs.

The brief explicitly asked for two new ads, short copy, gradients, and only one Brand Context image per ad. Reusing a gradient, avoiding a second product screenshot, and omitting an invented CTA were reasonable interpretations. Choosing the same playbook is not inherently an error. Neither run called image generation; they composed authentic assets and editable text through the native scene tools.

## Inputs and skill delivery were working

- Both received a catalog of 97 available asset entries, with `unavailable_count: 0`.
- Both received 15 seller knowledge documents; the trace reports zero refused documents.
- Both read the account-adaptation and account-identity-composition skills, brief/copy guidance, type-led-positioning, problem-solution, creation guidance, and the shared review guide. The front-office run also explicitly read brand-imagery and reference guidance; the guest run explicitly read brand-and-tokens. Pinned resources are additional context, so lack of an explicit read does not prove absence.
- Both queried project accounts, then read Arlo's `overview`. Neither called `read_claims`, a claims-section read, or a contact-research read. Those read tools were attached. This establishes what they used, not whether richer unused account research exists in storage.
- Both viewed three Conduit backgrounds, the Conduit OG creative, two Conduit marks, and three Arlo logo alternatives. Their two preview views bring each total to 11 `view` calls.
- Relevant materialized skill files match current tracked source bytes. There is no evidence here of a missing or stale skill load. This file comparison is a current-state check; the explicit skill-read requests are run-time evidence.

## What happened in each run

### Guest messaging

1. Read sparse Arlo overview, Conduit company overview, Inbox product evidence, and the hotel-groups ICP.
2. Viewed the existing backgrounds and OG creative. Chose the peach/orange/teal halftone background and fetched the authentic Arlo 10 Years lockup.
3. Wrote a type-led plan with a white card for logos and copy. Its recorded justification was that the supplied dark logos need a light surface. Its initial copy was “Guest messaging for Arlo” / “One inbox. Every guest channel.”
4. Constructed the card at `(60, 628)`, width 960 on a 1080-square canvas. This left most of the upper canvas as texture. That geometry is authored, not a layout failure.
5. After the first preview, narrowed “Every guest channel” to “messages and calls” to avoid unsupported universal coverage. This was a legitimate evidence correction, but the resulting message remained generic to hotel operators.
6. Tried unsupported update syntax, `#support_text text ...`; the compiler refused with `LUMD0210`. Retried with `content(...)` and succeeded.
7. Accepted the result with no issues and confidence 0.86. The critique explicitly states: “Name-removal test still leaves a hotel guest-communications task plus a unified inbox, so this is not identity-only.” `reference_fidelity` was null.

That last statement is the clearest account-quality gap: a useful industry task was treated as enough to establish personalization. Swapping Arlo for another hotel group would preserve essentially the entire proposition.

### Front office

1. Read sparse Arlo overview plus Operator, company overview, and agents product evidence. Used founding/location facts about SoHo and NoMad rather than a verified current buying trigger or operational priority.
2. Viewed the same brand candidates and logo alternatives. Chose the same background and logo treatment.
3. Wrote “Keep Arlo's desk on the floor.” / “Operator handles routine tasks so SoHo and NoMad stay with guests.” The light plate was part of the plan before rendering.
4. Created an initially oversized 952×608 plate. The first critique rejected the support's unsupported causal outcome and a roughly 117-point gap between headline and support.
5. Shortened support to “Operator handles routine tasks for SoHo and NoMad.” Moved it upward and reduced the plate to 952×348. Some direction-file edits did not take effect on the first attempt; subsequent reads and corrected edits added calls.
6. Hit the same `LUMD0210` text-update syntax error and recovered with `content(...)`. Reapplied plate/style changes before the second preview.
7. Accepted the result with no issues and confidence 0.82. It assigned fidelity 2/3 while acknowledging that the white plate was not part of the inspected OG treatment. The awkward headline survived unchanged. The review treated “for SoHo and NoMad” as a proposed invitation, although the visible sentence can also read as an existing deployment claim.

The review repaired evidence scope and spacing but did not repair immediate meaning, account relevance, or the underlying composition.

## Why the current skills allowed this

### 1. The account test's minimum bar is too weak for researched 1:1 quality

This is not simply the model ignoring a strong rule. `account-adaptation/SKILL.md:58–97` defines the name-removal check around retaining a task and advertiser mechanism, explicitly allowing shared tasks across accounts. `knowledge/scene/review.md:175–190` repeats that criterion. Both appropriately allow hypothetical use cases when research is sparse and prohibit fabricated account facts.

The guest review follows that weaker criterion. The missing distinction is between a legitimate industry/persona invitation and a deeply account-specific asset. They should not receive the same personalization qualification. Stronger evidence should change the message or proof when available; absence should remain explicit, without inventing distinctions or forcing long copy.

### 2. A logo-placement default became an unnecessary composition rule

The frozen brand card lists `surface.page` and `surface.card` as the Conduit logos' allowed backgrounds. Both directions cite this as justification for the white card. These values are generated by shared policy, not demonstrated source-site art direction:

- `apps/api/lumen_ingestion/normalizer/emit.py:323` calls `allowed_backgrounds_for`.
- `apps/api/lumen_ingestion/logo_policy.py:49–77` starts with those two light surfaces and widens the list for light/reversed variants.
- The module's own rationale says it preserves compatibility and keeps logo diagnostics advisory; it is not a requirement to introduce a large card.

The underlying rule has a purpose and should not be deleted casually. The failure is treating an advisory slot-level token policy as proof that a large white content panel is the right visual treatment. The skill already tells the agent to preserve the advertiser's field and avoid unrelated panels, but the review did not challenge this conflict.

### 3. Available references were inspected but not enforced as composition references

Both saw the real Conduit OG creative: soft cyan/green atmosphere, white type directly over the background, a clear centered hierarchy. Rejecting its baked headline as reusable artwork was appropriate. Its spatial and typographic relationships could still have guided the new composition.

Both directions instead assigned only the halftone image as `treatment` plus two logos. No source was recorded as `composition`. They preserved the material but introduced the card layout themselves.

There is a concrete gate boundary: `tools/substrate.py:5511–5522` requires a fidelity verdict only when configured attachments or `_selected_reference_ids` are present. `_selected_reference_ids` is populated in the image-production path (`:1885–1906`); viewing and placing a kit image does not populate it. These were reuse-only ads. Consequently, the guest ad could finalize with null fidelity despite having viewed brand examples. The front-office ad volunteered a score of 2, which would also satisfy the current threshold.

This is a selection/review contract gap. The remedy is not to force paid image generation merely to activate a reference gate.

### 4. Crop and typography checks covered technical validity more than treatment

The chosen authentic background is 2048×751. Covering a square preserves only about 36.7% of its width and enlarges its texture; it no longer displays the same broad color distribution. The guest run altered the focal point to `(0.42, 0.48)`; front office used center. Source and saved previews were inspected in this audit. The texture is present in the original; it is not fabricated noise from an image-generation call.

Both final scenes declare `seasonFont` at 67.5 for headlines and `bodyFont` at 33.5 for support. The renderer reports a nearest-weight substitution from requested 500 to available 420. That is a distinct font-weight precision issue, not evidence of absent font files. Prior isolated replay disproved the initial missing-font hypothesis for the front-office headline. These checks do not establish that the chosen scale, line breaks, optical weight, or source treatment are good.

### 5. Technical success was mistaken for creative acceptance

The native quality loop did useful work: it read real evidence, preserved authentic assets, removed unsupported claims, and repaired a compiler error. It did not catch the weak proposition or generic composition. A valid direction plus fully marked checks proves consistency with that plan, not that the plan is good. The shared review guide already warns against this; both acceptance records remain self-authored judgments.

Both exceeded their soft targets of 240 seconds / 20 model calls. Model waiting accounts for about 98% of measured runtime. The same syntax mistake, repeated reads/edits, and long direction/review output added overhead. No dollar cost or historical regression cause is inferred from token totals. Neither a larger skill catalog nor more agents is established as the solution by these traces.

## Proposed repair boundaries — no implementation in this audit

1. Distinguish account-specific evidence from industry/persona relevance in the shared account and review skills. Permit honest hypothetical creative, but label its qualification correctly. Retrieve targeted existing research when needed; do not restart discovery indiscriminately.
2. Separate generated logo-policy defaults from observed brand composition. Preserve the compatibility rule while teaching/validating source-grounded placement and the smallest necessary contrast accommodation.
3. Register deliberately chosen composition/treatment references independently of raster generation. Compare reuse-only ads against those actual references, including crop, texture scale, hierarchy, and logo/copy placement.
4. Evaluate the proposition and source treatment before accepting adherence to a self-authored plan. Use these two saved failures as no-spend regression fixtures before any new generation; do not add project instructions or seed an Arlo-specific template.
5. Correct the shared text-update examples/tool repair guidance for `content(...)`. This reduces waste; it is not the creative-quality fix.

A controlled future test should keep the same brief, sources, model and runtime topology while changing one identified boundary. These logs establish present failure mechanisms, not a proven causal comparison with a previously approved ad.

## Evidence navigation

- Local tool-request index: `.local-setup/ad-quality-audit-2026-10-02/LAST-TWO-RUNS-TOOL-INDEX.md`.
- Local machine-readable evidence: `.local-setup/ad-quality-audit-2026-10-02/last-two-runs-facts.json`.
- These derived files and the original runtime traces are ignored local evidence, not included in this commit. The run/session identifiers above allow an operator with access to the original runtime to locate the evidence.
- Guest source folder: `subsystems/clue-design/.deepagent-workspace/scene-candidate/sessions/dsess_f4613444472a533cafbeaee8f7d90f5d/`
- Front-office source folder: `subsystems/clue-design/.deepagent-workspace/scene-candidate/sessions/dsess_72c0542167f85ba4ba4509d76f2394ef/`
- In each folder: `workspace/brief.md`, `workspace/source_assets.json`, `workspace/brand_card.json`, `workspace/creative-direction.json`, `workspace/rounds/*/critique.json`, and `turns/<run>/logs/run.jsonl`, `trace.jsonl`, `final_scene.json`, `metrics.json`.

Original traces, critiques and generated artifacts are unchanged. This tracked report is an engineering handoff, not runtime input. It does not alter the skills, kit, prompt, or customer project instructions.
