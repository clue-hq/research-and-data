---
name: review-website
description: Use when judging a rendered website, checking source fidelity, verifying a scoped web edit, or deciding whether the current page is accepted, a draft or failed.
---

# Review the current rendered result

Review three responsibilities: source-visible layout/type/media fidelity;
responsive behavior, interaction, conversion and evidence; honest final status.
A successful operation, valid document or screenshot path proves none of these.

1. Establish the active page, current artifact/version context, requested scope,
   preserved properties and unresolved requirements. Current previews must follow
   the last relevant mutation. `render_web_preview()` captures 1440/768/375 and
   supported states; inspect them with `view("preview:<width>")` and `view("state:<n>")`.
   Reuse a verified unchanged render instead of repeating the loop.
2. Read [fidelity and behavior checks](references/fidelity-and-behavior.md).
   For reused/derived bands, inspect source pixels and compare their hierarchy,
   geometry, typography, media and supported states with the final output.
   The orchestrator/solo tool `review_cloned_page()` supplies measured clone
   findings and advisory page findings; missing observations remain gaps. It can record library verdicts,
   so use it within the authorized review scope, not as an assumed read-only test.
3. Check copy against accessible evidence and inspect each primary CTA's actual
   destination/behavior. Read `web-account-personalization` when targets or personal
   facets appear. A name/logo alone is not verified relevance or relationship proof.
   For an account-content build,
   read [account argument](../web-account-personalization/references/account-argument.md) and compare its decision map with the visitor-visible page.
   Verify read coverage includes relevant overview/committee/approach/watch-outs;
   then point to the real relevance, product mechanism, evidence and evaluation
   material. Missing substance, internal provenance/disclaimer copy, or identity
   placement that contradicts the shell brief is an actionable request-satisfaction
   defect. Green geometry checks do not make a thin or incoherent account page acceptable.
   For requested alternatives, compare the rendered pages against the campaign
   skill's distinct-page-directions plan. Reworded copies of one layout do not
   satisfy a request for different layouts; report undelivered pages separately.
4. Use [verdict and tool contract](references/verdict-and-tools.md). If an independent
   reviewer is exposed, give it the current brief, source evidence, preserved
   requirements, previews/states and scope. If unavailable, identify self-review;
   never invent a delegation or change runtime configuration to obtain one.
5. Report observed defects with page/node, viewport/state and smallest repair.
   After repair, judge new current evidence. For a small edit, certify only that
   change and its affected neighbors; do not re-plan or re-generate the entire page.

`finalize_web_run` records the existing outcome and summary; it is not a new visual
acceptance gate. No skill instruction recovers missing source React/JS/WebGL,
imports frozen evaluations into a live workspace or proves publication.
