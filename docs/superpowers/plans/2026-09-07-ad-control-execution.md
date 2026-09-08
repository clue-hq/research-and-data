# Ad control: what we are testing now

Execution began September 7 in the existing local checkout. The full architecture proposal remains the design reference; this page explains the actual test order.

## First: does supplying the right ad improve the current engine?

Run two business briefs twice each, under one local Conduit control project:

| Brief | Current engine | Same engine with reference |
| --- | --- | --- |
| Hospitality awareness | Normal brand inputs | Supplied editorial gradient ad |
| Guest-message product demonstration | Exact authentic product UI | Same UI plus supplied product-stage ad |

Each pair receives identical generation instructions and the same brand kit/model settings. Each run owns its own chat, document and checkpoint. The reference attachment is the intended difference. Preserve all outputs, including failures. Four runs are exploratory evidence, not proof that one approach always wins.

The engine code and active resources stay frozen while this batch runs. Supplied files enter through the real browser upload flow and are checked against the frozen Design envelope. A file attached to Codex alone is not an input to Clue.

## Second: inspect what actually happened

For each run, check whether Design viewed the reference, selected the relevant product asset, generated artwork when useful, and kept copy/logo/button/artwork separate. Inspect the pixels at full size and at a small ad viewing size. Then edit text, move/resize the logo, change button styling, replace an image, save, reload and export in the mounted platform editor.

Record unavailable controls honestly. The current platform editor exposes image fit modes and box resizing; it does not expose manual crop focal positioning.

## Third: change the restrictions supported by evidence

Current source review identifies these candidates:

- Remove mandatory split layouts, universal headline limits and fixed button geometry from the candidate policy.
- Use ad references to guide ad composition; keep website-specific layout rules scoped to websites.
- Choose readable approved foreground/background combinations by contrast, including light brand colors.
- Distinguish exact product UI, exact logo, style reference and generated artwork. Authentic screenshot text is allowed; flattened ad headlines are not.
- Generate artwork variants separately and compose native copy over them.
- Keep retrieved ads tied to the selected brand/kit and each generation group tied to its own references.

These are candidate changes, not completed improvements. Test them in a later frozen batch with the same candidate configuration for every run. Process-wide flags and resources must not change underneath running jobs. Mixed per-run candidate/reviewer treatments remain deferred; that experiment needs the proposed envelope seam and would isolate effects that this combined policy comparison cannot.

## First results and repairs

**Founder feedback:** all four baseline outputs fail the requested creative standard. Technical completion does not count as creative acceptance. The next step is one strong case with two actual reference-conditioned image-generation variants and native editable overlays, reviewed against the supplied reference before expanding the test matrix. No further baseline-style assembly runs are warranted.

All four selected creative runs completed, after three initial failures were retained and retried against warmed shared resources. Runtime durations were 8m54s, 16m06s, 13m11s and 17m16s, with 40, 56, 60 and 49 model calls respectively. Both reference cases viewed their attached image, but none of the four generated new artwork or invoked an independent reviewer. The references changed composition; they did not reliably ensure brand typography, contrast or high visual quality.

The browser verified native copy/button editing, independent logo movement/resizing, product image crop and saved persistence. A separate font replay defect means the accepted preview's type sizes are lost on the saved editor path. That blocks a quality verdict even when the scene compiles successfully.

- PE-11: shared workspace materialization serialized; local commit `b68b3717`, 1,646 runtime tests pass with 7 skips. Next concurrent frozen batch supplies live refresh acceptance.
- PE-12: non-writing handoff opener no longer leaves the editor permanently locked; local commit `5cbfa7a9`, 52 regression tests and frontend gates pass. Previously stuck Hospitality A entered Edit in the browser.
- PE-14: preserve deliberate type-token intent through runtime operation replay; implementation and parity verification underway.

Original pixels, run envelopes, metrics and QA receipts remain under ignored `.local-setup/ad-control/`. Keep baseline results distinct from later manual QA edits and candidate outputs. One sample per arm, wrapper differences and warm retries prevent a causal uplift claim.

## Ownership and finish

Head of ABM creates the business brief and opens the Design handoff. Design's director chooses direction; its author writes copy and constructs the scene. Opening a handoff alone does not generate the ad. Head-of-ABM implementation and skill work remain with the separate Fable effort; this project records handoff observations only.

The control project closes when useful quality gains and actual editing/persistence/export are demonstrated, with failures and remaining work recorded. A render, an average visual score, or ten completed ticket descriptions cannot substitute for that evidence. Generalization to another brand and more formats remains a separate validation step.

Tracking: [Editable Ad Quality — Control Test](https://linear.app/deeppresence/project/editable-ad-quality-control-test-170a09e4cc95). Architecture: [design spec](../specs/2026-09-07-editable-ad-control-design.md). Detailed tasks: [implementation plan](2026-09-07-editable-ad-control.md).
