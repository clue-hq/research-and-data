# Website quality: supervised source-reproduction checkpoint

The four-brand goal remains incomplete. Shared capture and source reproduction are improving; the checks below do not approve generated account pages or arbitrary source JavaScript/WebGL behavior.

## What is verified

| Brand | Production rendering against frozen source | Remaining failures |
| --- | --- | --- |
| Clue | 8/8 fragments admitted. Top 1,000px screenshots are byte-identical at 1440px and 375px in source, delivery and committed editor renders. Hero measurements and page height match. | Full-page visual, interaction and animation acceptance not performed. |
| Conduit | 11/12 fragments admitted. Top screenshots and hero measurements match source/delivery/committed editor at both widths. The refused shell is empty script/embed content. | Mobile page is 56px shorter. Lazy offscreen images and interactions still need checking. |
| AWS | Prior production proof matches source/delivery typography and hero geometry at both widths. | Committed editor H3 remains 14px/22.4px versus source/delivery 16.38px/26.208px; captured support widget and excess CSS remain. |
| Google Cloud | Source fonts, hero width/height and image bytes survive; no document-wide overflow. | Hero is 96px too high, cloud mark is displaced/clipped, and retained desktop video is absent from reconstructed output. Fails source fidelity. |

The new Clue/Conduit/Google proof uses the real `CoreClient.web_render` with captured fragment artifacts and local retained dependencies. Source means frozen DOM/CSS/assets rendered offline with source scripts disabled and the same reduced-motion preference. It is not a fresh live-site comparison. Parent independently inspected screenshots and checked source/delivery PNG equality; the editor-only replay pins committed renderer files to `7ca33e20` and verifies their hashes before and after. Frozen snapshots predate ordered CSS acquisition changes.

No observed completed-image failures or failed font faces occurred in these six final editor views. Lazy images not requested by the viewport are not counted as proven loaded. Google editor/delivery top views differ by 150 desktop pixels and 66 mobile pixels; the main geometry/video failures are present in both modes.

## Why Google still fails

The 96px displacement combines omitted intermediate wrapper layout (65px header padding plus 24px margin) and a 7px image baseline change. The host renderer's global `img { display:block }` changes an originally inline, centered logo. This needs a general source-environment/ancestor-layout solution, not Google-specific padding or logo coordinates.

The video contains a retained desktop source plus an unconditional fallback URL that returned 404. At mobile width the original captured page itself has no usable video. Dependency validation refuses the incomplete section; recovery preserves independent sections but loses this video and shared ancestor layout. Silently deleting the failed fallback or using the desktop source everywhere would conceal the failure. A future partial-media recovery contract must name its viewport limits and preserve the existing byte-custody gate.

## Shared pipeline proof

The third URL-only Linear ingestion completed in 175 seconds: six pages, 164 registered assets, 67 draft sections. Twelve formerly missing customer SVGs are now downloaded, durably hash-verified, registered and discoverable through agent asset search. All 857 saved stylesheet occurrences carry source-order/raw-source metadata. The customer page improves from 6/7 to 7/7 admitted sections. Homepage and one large-video page remain partial.

The page planner also now distinguishes product customer features from proof and story collections from individual stories. All 64 focused discovery/capture tests passed after parent implementation and independent review. Details are in `website-page-role-validation-2026-09-20.md` and `website-capture-unseeded-proof-2026-09-20.md`.

## Supervision and rejected work

Three bounded specialists handled typography, rendering comparison and independent review; parent owned integration and fresh ingestion verification. An editor `@scope` proposal improved AWS headings but changed native equal-specificity CSS precedence. Review also found a marker-text collision. The proposal was rejected and all six owned source/test files were restored; patch, failing examples and measurements remain in ignored evidence. The final editor comparison was rerun against restored code without reminting fragments. No part of that proposed renderer fix is shipped by this checkpoint.

One specialist accidentally ran broader DB-backed tests without the explicit disposable DSN. Those results are excluded. The target was the default local `clue` DB, separate from live `clue_sept7_dev`. Parent's read-only audit found no new workspace rows and no changes in 45 design/artifact/fleet timestamp checks during the bounded test window. No cleanup or live database writes were performed. Future commands must explicitly bind the disposable DB and disable embedded workers except in deliberate ingestion proofs.

## Next acceptance work

1. Isolate host/default element styles without changing native page cascade semantics; test source inline images as well as headings/buttons.
2. Preserve shared ancestor layout once when recovering sibling sections, with provenance and explicit unsupported cases.
3. Define honest viewport-specific media recovery; verify video playback and reduced-motion behavior.
4. Repeat fresh four-brand library capture and full-page/source checks, then actual agent-generated account pages with the standard runtime available.

Docker runtime provisioning remains pending; no sandbox requirement was bypassed. The original design checkout, its four live instances and environment files were left unchanged. No push or merge occurred.

## Local evidence

- `.local-setup/website-capture/four-brand-source-context-20260920/report.md`: detailed measurements, Google diagnosis and exact reproduction scripts.
- `four-brand-source-context-20260920/editor-committed-head/`: final editor screenshots, module hashes and measurements.
- `fresh-url-linear-custody-20260920/verification.json`: actual acquired media, registry and ordered stylesheet verification.
- `rejected-preflight-20260920/`: rejected proposal and counterexamples.
- `preflight-default-db-audit.json`: read-only incidental test-scope audit.

Raw source bytes and screenshots remain in ignored local evidence, not Git.
