---
name: review-website
description: Use when judging a rendered website, checking source fidelity, verifying a scoped web edit, or deciding whether the current page is accepted, a draft or failed.
---

# Review the current rendered result

Review three responsibilities: source-visible layout/type/media fidelity;
responsive behavior, interaction, conversion and evidence; honest final status.
A successful operation, valid document or screenshot path proves none of these.

Apply the same [source and format contract](../create-website/references/source-format-contract.md)
the builder received. For each selected/derived component, compare the plan's
`Preserve` and `Type` records with the final section. A family-name match does not
excuse a different face, weight, scale, hierarchy or layout. Target identity in
navigation without an explicit user source for that placement fails this contract;
an agent-authored brief claiming approval is insufficient. Report the concrete
deviation even when clone geometry or another typography role passes.

1. Establish the active page, current artifact/version context, requested scope,
   preserved properties and unresolved requirements. Current previews must follow
   the last relevant mutation. `render_web_preview()` captures 1440/768/375 and
   supported states; inspect them with `view("preview:<width>")` and `view("state:<n>")`.
   A tall full-page image is only an overview: inspect readable saved strips with
   `view("preview:375:tile:0")`, following `coverage.next_target` for the mobile
   page and using the same syntax for 768/1440 when details are too small. Check
   required product imagery and copy in those pixels; a gradient placeholder is
   not a working product visual. Match source hashes/version when combining
   observations and report any required tiles left unseen.
   Read `view("review")` before a verdict: it aggregates pixels actually returned
   this turn and retains missing/stale views, source-comparison limits and capture
   omissions. A report of `observations_recorded` is not a quality pass. For tall
   state captures, use `view("state:<n>:tile:<i>")`. For a scoped edit, resolve the
   relevant gaps without demanding a new full-page generation.
   Reuse a verified unchanged render instead of repeating the loop.
2. Read [fidelity and behavior checks](references/fidelity-and-behavior.md).
   For reused/derived bands, inspect source pixels and compare their hierarchy,
   geometry, typography, media and supported states with the final output.
   The orchestrator/solo tool `review_cloned_page()` supplies measured clone
   findings and advisory page findings; missing observations remain gaps. It can record library verdicts,
   so use it within the authorized review scope, not as an assumed read-only test.
   A walk's “6/6 observations” counts capture classes, not all tab states or all
   responsive details. Check `reference_unavailable`, comparison abstentions and
   unmeasured composed/draft sections even when `broken_clones` is empty. If only
   the default and second of four panels were observed, report two states observed
   and two unverified; never summarize that as a fully working four-panel experience.
   `fragment.class_collision` or incomplete-isolation warnings require comparison
   of the named bands/properties. Do not dismiss them from geometry alone or mutate
   unrelated components merely to silence a warning. Reuse current evidence when
   it actually covers the same property, viewport and final revision.
   Compare affected bands with their recorded keeper properties. Preserving the
   product asset but losing its branded background, crop, scale or phone visibility
   is a regression. Read `web-product-story` when product staging or type hierarchy
   is in scope; compiled tabs do not prove all their media states still work.
3. Check copy against accessible evidence and inspect each primary CTA's actual
   destination/behavior. Read `web-account-personalization` when targets or personal
   facets appear. A name/logo alone is not verified relevance or relationship proof.
   For an account-content build,
   read [account argument](../web-account-personalization/references/account-argument.md) and compare its decision map with the visitor-visible page.
   Compare each section's Words, Evidence and Actions record with the actual
   rendered text and buttons, including captured unslotted labels. Name omitted
   explanations, unsupported additions and repeated mechanisms by section. The
   plan is a comparison aid, not evidence that its claims or promises are true.
   Verify read coverage includes relevant overview/committee/approach/watch-outs;
   then point to the real relevance, product mechanism, evidence and evaluation
   material. Missing substance, internal provenance/disclaimer copy, or identity
   placement that contradicts the shell brief is an actionable request-satisfaction
   defect. Green geometry checks do not make a thin or incoherent account page acceptable.
   For account builds, use `web-decision-material`: identify what the reader can
   learn, inspect or decide from the exhibit beyond a company biography. For a
   named reader, use `web-contact-personalization`: check the permitted contact
   evidence and what materially differs from the account page. Read the campaign
   action-selection guide when judging CTA intent; a valid URL alone cannot show
   that a demo, assessment or download is the right promise.
   For requested alternatives, compare the rendered pages against the campaign
   skill's distinct-page-directions plan. Reworded copies of one layout do not
   satisfy a request for different layouts; report undelivered pages separately.
4. Use [verdict and tool contract](references/verdict-and-tools.md). If an independent
   reviewer is exposed, give it the current brief, source evidence, preserved
   requirements, previews/states and scope. If unavailable, identify self-review;
   never invent a delegation or change runtime configuration to obtain one.
5. Report observed defects with page/node, viewport/state and smallest repair.
   For type/media/spacing defects, use cached
   [layout evidence](../web-source-readiness/references/layout-evidence.md)
   to locate the constraint; computed styles are not proof of font or visual fidelity.
   After repair, judge new current evidence. For a small edit, certify only that
   change and its affected neighbors; do not re-plan or re-generate the entire page.
   Distinguish tool completion from request satisfaction. A saved draft can be
   `completed_with_warnings` while required visual/interaction acceptance remains
   open. Name those unmet requirements prominently rather than calling them polish.

`finalize_web_run` records the existing outcome, summary and observation report;
it is not a new visual acceptance gate. No skill instruction recovers missing source React/JS/WebGL,
imports frozen evaluations into a live workspace or proves publication.
