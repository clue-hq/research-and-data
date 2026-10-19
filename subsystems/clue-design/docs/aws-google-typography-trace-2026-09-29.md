# AWS and Google Cloud: typography trace audit

Read-only audit on `brand-context-fixes/typography`, September 29, 2026.
This follows the actual kits pinned to the native September 20 pages, their
ingestion evidence, historical `view(brand)` responses, component inspections,
authoring calls, review results, saved screenshots and worker completion logs.
No workspace restart, generation, provider call, kit update or page edit occurred.

## Conclusion

Both workspaces received incorrect normalized typography even though ingestion
had captured a more complete rendered heading. AWS carried the bad kit values
into newly authored CSS. Google Cloud had an additional problem: it reused a
previously agent-authored component, preserving that component's own divergent
typography rather than an original source-site component.

| Evidence stage | AWS | Google Cloud |
| --- | --- | --- |
| Saved rendered H1 | Amazon Ember Display, 40px / 500 | Google Sans, 45px / 500 |
| Approved kit headline | Amazon Ember, 32px / 700 | Google Sans, 20px / 500 |
| Actual agent `view(brand)` headline | Amazon Ember, 32px / 700 | Google Sans, 20px / 500 |
| Authored hero CSS | Amazon Ember first in stack, 32px / 700; 36px at width >=1024px | Google Sans, 40px / 700; 28px at width <=767px |
| Review against source page | Unavailable | Unavailable |

These are historical samples and authored CSS, not a prescription to use one
size across every heading or viewport. Saved screenshots confirm the generated
layouts and bold headings. This audit did not remeasure the actual glyph font
used by either browser render or recapture today's source websites.

## AWS: the wrong selection reached the generated CSS

- Ingestion `ingest_3a4984408b764613aee98fa319575f10`, September 17,
  completed successfully with no ingestion error. Its first H1 CSS sample has
  an unresolved `var(--font-family-heading-5zaew9` family and no size or weight.
  A later rendered sample contains Amazon Ember Display, 40px, weight 500.
- The published kit `brand_kit_ing_3a4984408b764613aee98fa319575f10` v1
  instead contains Amazon Ember, 32px, weight 700. Its section-title token is
  18px/700 and points at cookie-modal H2 CSS. The headline's provenance also
  points at that modal H2 with confidence 0.9; the stored provenance did not
  faithfully identify a measured headline.
- Native run `run_58249835168352f2a87a572455d71a99` pins that exact approved
  kit. Its actual brand-tool response contains the same 32px/700 headline.
- The agent inspected original hero `frag_c32b9611bbc8815e`. The response
  reported **2,705,755 CSS characters** and `css_truncated=true`. Its final
  explanation explicitly says the original hero CSS could not be inherited in
  full. The agent used `compose_web_section` for a replacement hero, features,
  header and CTA, while retaining original resource/footer fragments.
- Its replacement hero sets 32px/700, then 36px above 1024px. Its font stack
  puts Amazon Ember before Amazon Ember Display. Thus bad normalization and
  incomplete component delivery both contributed; obtaining the font files
  alone would not correct the authored style.

## Google Cloud: bad input plus reuse of a previous generated component

- The native run's pin is the **September 13 approved kit**
  `brand_kit_ing_2c3777ede07b4ab8b2558ec892cdd54a` v3. Its ingestion evidence
  includes `.oi5iof h1` at 20px/500 before a rendered H1 at 45px/500. The kit
  and actual brand-tool response both expose 20px/500. Stored headline
  provenance points at `body`, rather than the measured rendered H1.
- The newer September 17 kit
  `brand_kit_ing_772576920abe4b5fbd0100566a3a02c8` v1 remains **draft**.
  The generated page did not consume it. A later successful ingestion alone
  does not replace an approved kit or a document's pinned version.
- Native run `run_f48876345d5e561eabd958189b4f1b18` inspected hero
  `frag_5fdbb57bd72e936f`. That fragment was created September 19 and explicitly
  reports `source_url="composed:agent"`, `composed="agent"`, no source-kit
  binding and no capture evidence. Its existing CSS already used 40px/700,
  with 28px on mobile.
- The agent retained those values in its `repair_cloned_section` variant.
  Its final report states that the available library had no captured
  cloud.google.com bands and it remixed prior composed fragments. The observed
  40px/700 output therefore cannot be explained as directly copying the kit's
  20px headline; there is a second source of drift in the reusable library.
- The later copy-edit run `run_7422ab7901e85be7af4200d2e057cf35` records a
  separate repair: CSS remained scoped to the prior fragment ID and no longer
  applied to the derived variant, making product images grow excessively. Its
  subsequent repair notes describe removing the stale scope and adding a
  maximum width to prevent expansion to the images' native 2500px width.
  Those notes establish the failure and attempted repair, not a complete
  visual certification of the later page.

## Why the runs still completed

Both initial `review_cloned_page` responses have `comparison=null`,
`reference_unavailable="no_snapshot_provenance"`, and diagnostic `LUMA0801`.
They captured desktop/mobile output but could not compare it with the original
site. Empty `broken_clones` and `page_findings` arrays were not fidelity proof.

Both agents finalized `completed_with_warnings`. The fleet recorded
`design_job.finished` with `status=succeeded`: AWS in `fleet-2.log:302`, Google
in `fleet-3.log:1640`. Execution success did not mean typography matched.
These September 20 runs also predate the September 28 typography-reference
coverage check; they are not evidence that an agent ignored that newer check.

## Consequences for the fix

1. Correct selection of complete, visible rendered samples while preserving
   each component's family, weight, dimensions and responsive context. This
   addresses the shared ingestion defect documented in the main audit.
2. Repair stored typography through reviewed, versioned kit updates. Explicitly
   handle draft/approved state and document pins; changing the normalizer is
   not a retroactive update to existing kits or literal page CSS.
3. Keep original captured components distinguishable from agent-authored
   variants in retrieval and selection. An approved generated fragment is not
   evidence of source-site fidelity.
4. Make component CSS usable without truncating critical dependencies, and
   preserve/remap selectors correctly when deriving a variant. Cover the AWS
   large-CSS and Google stale-scope cases with deterministic fixtures.
5. Verify source-reference coverage and rendered typography before claiming
   fidelity. Where source evidence is absent, report the missing evidence;
   do not treat a clean console or successful render as a typography pass.

The previous normalizer/provenance correction addresses part of item 1. The
remaining capture, representation and migration work is described in
`typography-ingestion-audit-and-plan-2026-09-29.md`. This audit adds evidence,
not implementation or a new generation trial.

## Local evidence locations

- `.local-setup/typography-branch-audit-20260929/aws-google-trace/evidence-chain.json`
  joins each actual run to its source job, approved kit, agent context, CSS and
  review result. Scoped read-only database snapshots are in the same directory.
- `.local-setup/native-website-runtime/native-run-trace-audit.json` contains
  the original tool arguments and results; `fleet-2.log` and `fleet-3.log`
  contain worker completion events.
- `.local-setup/native-account-skills/native-run-trace-audit.json` contains
  the subsequent Google CSS repair notes.
- Saved output screenshots are under
  `.deepagent-workspace/sessions/dsess_0145cb0c9b9b5a0284ffce76347a5e94/turns/run_58249835168352f2a87a572455d71a99/review_1/`
  and
  `.deepagent-workspace/sessions/dsess_c4397722bdb252b1a4d29aec16acca55/turns/run_f48876345d5e561eabd958189b4f1b18/review_1/`
  within `subsystems/clue-design/`. Raw runtime evidence remains local/ignored.
