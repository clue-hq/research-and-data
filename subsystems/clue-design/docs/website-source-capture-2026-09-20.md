# Four-brand source capture and first fidelity probe — 2026-09-20

Branch: `codex/website-capture-v1`. These are frozen official-source captures and offline fragment-builder checks. They are not agent-generated pages, live workspace imports, or fidelity approvals. Original captures and the first failed probe remain intact.

## Acquisition

| Brand | Captured pages | Distinct asset hashes, excluding screenshots | Captured asset types | Missing page categories |
|---|---:|---:|---|---|
| aws | 6 | 174 | 58 font, 88 image, 28 logo | None in selected plan |
| clue | 1 | 24 | 3 font, 17 image, 4 logo | product, customers, case-study |
| conduit | 6 | 760 | 19 font, 717 image, 24 logo | None in selected plan |
| google-cloud | 6 | 376 | 211 font, 120 image, 41 logo, 4 video | None in selected plan |

Asset hashes measure saved files, not the number of useful distinct images. Conduit includes many responsive image renditions. Counts also do not prove that every captured asset has a usable placement or adequate labeling.

All 19 selected HTML pages were acquired. Several are partial at the dependency level: AWS repeatedly reports ten oversized international font resources; Clue and Conduit report a missing favicon; Google reports missing video fallback URLs on two pages. Informational renderer and overlay-removal notices also remain in the manifests. Missing roles on Clue describe this observed-link sample; they do not prove the site has no unlinked pages.

Google has four distinct saved video files across the selected pages. CSS keyframe definitions are retained in source stylesheets. Two AWS pages contain canvas elements; their JS/WebGL runtime has not been recovered. Canvas presence alone does not prove a WebGL scene.

## First homepage fragment admission and rendering

| Brand | Segmented | Admitted before follow-up | Current finding |
|---|---:|---:|---|
| Clue | 8 | 8 | Original imagery survives the raw-fragment preview; source comparison and interactive verification remain open. |
| Conduit | 12 | 10 | One empty embed/script shell is correctly refused. A customer-story band failed because comment nodes shifted slot selectors. After the fix, 11/12 admit; the empty shell remains refused. |
| AWS | 12 | 12 | Admission does not prevent layout problems: raw staging overflows at 1440 and 375. Captured support-chat chrome also appears in the result. |
| Google Cloud | 3 | 2 | A framework wrapper contains nine authored sections. Its missing video fallback initially rejected the whole wrapper. Bounded recovery now admits eight independent content sections plus navigation/footer (10 total); the closing video section still refuses. |

Offline renders are diagnostic staging, without the app’s full theme/runtime assembly. They are not a replacement for the production renderer or a controlled screenshot-diff benchmark. Initial rendering also exposed missing inherited typography context in Conduit. The probe HTML omitted UTF-8 metadata; resulting character corruption was a probe defect, not a product finding. Offscreen lazy images were initially counted as unloaded; that metric is not evidence of broken image URLs.

## Repairs and remaining work

- Shipped locally: source URL resolution, video custody, quoted SVG references, kit capture associations, bounded multipage discovery, durable coverage, fair fragment allocation, React-comment-safe slot indexing, bounded independent-section recovery from refused framework wrappers, and captured HTML-root font-variable preservation.
- Still needed: preserve broader body/ancestor context and compound/state-qualified root rules; distinguish source content from transient support/consent overlays; validate recovered section context and supported responsive-media fallbacks.
- Compare frozen source and production output at matching viewport sizes and supported interaction states. No brand has received a final fidelity pass.
- Import through the existing workspace-scoped ingestion/storage seams as new draft versions after the isolated integration checks. Do not overwrite prior kit versions or approve fragments automatically.
- The live generation fleet still needs the standard Docker sandbox runtime. Docker, Colima and OrbStack were not found on this Mac during this pass. A user question about providing that runtime is pending; no sandbox requirement has been disabled.
- The seven skill families remain downstream of this evidence. More prompting cannot repair missing source custody, incorrect section boundaries or unusable fragment selectors.

## Verification

- Multipage capture/API/snapshot/mint compatibility: 223 passed, 2 skipped.
- Comment-slot regression: failed before the fix with `fragment.slot_selector_unmatched`; fragment/slot/artifact matrix after fix: 244 passed.
- Frozen Conduit homepage admission: 10 → 11 fragments; no new network capture or messaging edits.
- Wrapper recovery regression matrix: 350 passed, including a pipeline-level fair-budget/partial-status check and non-dependency refusal/backstop tests, and a guard against borrowing the original footer crop for a recovered section. New-line Ruff findings: zero after import/line-length cleanup; full touched files retain inherited findings.
- Frozen four-brand re-probe: Clue 8, Conduit 11, AWS 12, Google Cloud 10 admitted fragments. Google raw staging rendered at 1440 and 375 pixels with matching document scroll widths (no horizontal overflow in those views). Hero, source imagery and responsive layout were visually inspected. Carousel/tab interaction and motion were not verified; lazy offscreen image counts still must not be treated as broken dependencies.
- Library and offline probe data live under ignored `.local-setup/website-capture/`. No source media was committed, no push occurred, and the original four-instance checkout was not changed.

## Source-root typography follow-up

Conduit attaches four font-variable classes to its source `<html>`. Their definitions were
absent from section CSS even though the font bytes were captured. The extractor now aliases
custom-property declarations from observed, single-class root rules onto the existing fragment
root, preserving media/layer nesting, importance and source order. It does not copy the
original document's layout box or flatten body/ancestor/compound-state context. Variable asset
URLs remain subject to the existing rehosting gate; missing dependencies still refuse.

Offline browser comparison used the frozen source HTML/CSS and before/after fragment builds,
with all outbound requests intercepted. At 1440 pixels, 71 matched heading/paragraph samples
now agree on font family, size, line height and weight; at 375 pixels, 69 agree. Before the fix,
none of those samples matched the source font family (Times fallback). Source and repaired
pages loaded the expected bodyFont/seasonFont families without font-load errors; desktop Inter
also loaded. First-viewport screenshots were visually compared. This verifies this typography
repair, not full-page interaction, animation or production generation fidelity.

Conduit still admits 11/12 fragments, with the empty embed shell refused. Source root-rule
inventory found four affected definitions in Conduit and zero in the other three homepages.
The regression matrix passes 357 checks. Detailed immutable before/after evidence is under
`.local-setup/website-capture/fragment-probe-20260920-root-vars/conduit/`.

## AWS root-unit diagnosis

The offline frozen-source comparison isolates the main scaling problem: source `<html>` is
10px at both 1440 and 375, while diagnostic fragment documents use the browser's 16px root.
Extracting `html { font-size: ... }` onto a fragment wrapper does not change what `rem` means.
At desktop, the source hero is 40px and the fragment is 64px; at mobile, 28px becomes 44.8px.
Source 16px body copy becomes 25.6px. This explains the 1.6x text/spacing inflation and is an
unresolved root-unit transport issue, not evidence that a new prompt should shrink each element.

The next repair must preserve the source root-unit context without changing the platform shell's
global font size or breaking media-query thresholds and responsive source rules. Root computed
font size is not currently recorded explicitly in the capture geometry. Exact comparison data
and source/fragment first-viewport screenshots are saved under
`.local-setup/website-capture/fragment-probe-20260920-recovery/aws/`. This diagnosis does not
claim the AWS layout or support-widget contamination is fixed.

## Selected official pages

### aws

- homepage: [https://aws.amazon.com/](https://aws.amazon.com/) — partial
- product: [https://aws.amazon.com/bedrock/?nc2=h_prod_fs_br](https://aws.amazon.com/bedrock/?nc2=h_prod_fs_br) — partial
- product: [https://aws.amazon.com/products/connect/customer/?nc2=h_prod_fs_cnct](https://aws.amazon.com/products/connect/customer/?nc2=h_prod_fs_cnct) — partial
- customers: [https://aws.amazon.com/solutions/case-studies/?nc2=h_rc_cs](https://aws.amazon.com/solutions/case-studies/?nc2=h_rc_cs) — partial
- case-study: [https://aws.amazon.com/solutions/case-studies/innovators/siemens/?hp=cs](https://aws.amazon.com/solutions/case-studies/innovators/siemens/?hp=cs) — partial
- case-study: [https://aws.amazon.com/solutions/case-studies/innovators/booking/?hp=cs](https://aws.amazon.com/solutions/case-studies/innovators/booking/?hp=cs) — partial

### clue

- homepage: [https://cluehq.ai/](https://cluehq.ai/) — partial

### conduit

- homepage: [https://www.conduit.ai/](https://www.conduit.ai/) — partial
- product: [https://www.conduit.ai/product/agents](https://www.conduit.ai/product/agents) — partial
- product: [https://www.conduit.ai/product/inbox](https://www.conduit.ai/product/inbox) — partial
- customers: [https://www.conduit.ai/customers](https://www.conduit.ai/customers) — partial
- case-study: [https://www.conduit.ai/customers/lauderdale-hotel](https://www.conduit.ai/customers/lauderdale-hotel) — partial
- case-study: [https://www.conduit.ai/customers/homehop](https://www.conduit.ai/customers/homehop) — partial

### google-cloud

- homepage: [https://cloud.google.com/](https://cloud.google.com/) — partial
- product: [https://cloud.google.com/products/gemini-enterprise-agent-platform](https://cloud.google.com/products/gemini-enterprise-agent-platform) — captured
- product: [https://cloud.google.com/gemini-enterprise-cx/cx-agent-studio](https://cloud.google.com/gemini-enterprise-cx/cx-agent-studio) — captured
- customers: [https://cloud.google.com/customers](https://cloud.google.com/customers) — partial
- case-study: [https://cloud.google.com/customers/fairpricegroup](https://cloud.google.com/customers/fairpricegroup) — captured
- case-study: [https://cloud.google.com/customers/hershey](https://cloud.google.com/customers/hershey) — captured

