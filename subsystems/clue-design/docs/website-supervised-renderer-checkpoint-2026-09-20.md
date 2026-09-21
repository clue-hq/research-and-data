# Supervised website fidelity checkpoint — 2026-09-20

This checkpoint improves generic source preservation and review coverage. It does **not** certify complete website fidelity or the full website goal. All work is isolated on `codex/website-capture-v1`; the four live workspaces, their databases, and environment files were not updated by this checkpoint.

## Supervision and scope

Three bounded specialists worked under parent review: editor preflight isolation, captured ancestor layout assembly, and independent source-context/review. The parent owned native renderer defaults, coverage counting, four-brand replay, dependency setup, and full-suite verification. Files were assigned explicitly; agents could not accept their own results as final. No new production agent roles or brand-specific behavior were introduced.

Several proposed changes were rejected or corrected before acceptance: editor-only and generic-class boundaries, preflight cascade-priority changes, document box-sizing inheritance, rem fallback specificity, unsupported ancestor properties, malformed selectors, missing body margins, context-sensitive custom-property reuse, and an unexpected browser stylesheet request. Each substantive issue received a regression case or explicit refusal.

## Changes

- Resolved source fragments carry a renderer-owned semantic boundary in both editor and delivery. Native image, box, button and typography defaults stop at that boundary without changing the priority of native rules. Placeholders remain native.
- Editor preflight uses the exact supported Tailwind browser/preflight bytes. Selector exclusions preserve specificity and original cascade layers. External scripts require integrity verification and anonymous CORS on the public vendor file; inline previews verify the bytes they execute. Unsupported versions remain explicitly unverified. Nested built-in imports prevent an unwanted browser parser request while retaining token utilities.
- Source HTML/body contexts retain source box-sizing, including inherited values and bounded custom-property fallbacks. This fixes measured 100px source boxes that previously became 160px.
- Recovered sibling sections can share a bounded, source-authored normal-flow envelope. It is persisted as ordinary document nodes and CSS; original fragment pins and slot data remain intact. Unsupported layout returns a named gap. Repairs require their own verified source-layout evidence.
- Captured source order follows original parent/member positions. Review coverage counts bands inside nested envelopes instead of treating an eight-band group as one measured section.
- The Chrome-fingerprint asset client now supplies native streaming expected by the shared downloader. Request-local ownership preserves concurrent requests, aborts unread/oversized transfers, retains total deadlines, propagates cancellation and prevents double release of a native connection handle. The existing buffered page-fetch contract is preserved. Retained bodies remain capped; the native library queue can read ahead, so this is not a hard transport-memory ceiling.

## Four-brand renderer replay

Inputs are existing immutable capture artifacts and their held asset bytes. The replay does not fetch new pages, remint fragments, write registry records, seed live brand assets, or call a model. It renders the actual engine in delivery/editor at 1440px and 375px widths. All external requests are intercepted; only held source assets and the exact local compiler are served.

| Brand | Observed result | Remaining limit |
|---|---|---|
| Clue | Both editor and delivery top-viewport PNGs match the captured source at both widths. | Frozen DOM/CSS view; full interactions and original programs are not established. |
| Conduit | Both editor and delivery top-viewport PNGs match the captured source at both widths. | Original animations/programs and whole-page fidelity remain separate checks. |
| Google Cloud | Editor/delivery headline geometry agrees; the native image baseline is restored. | Hero remains 89px above source because the shared document layout is not yet represented. Missing captured video is still explicit. |
| AWS | Headline is 504×88px desktop and 279×108px mobile in both modes; source typography parity is preserved in the focused proof. | Captured support widgets remain; this is not a full-page/motion acceptance. |

All 16 final renderer views have zero page errors, zero failed completed images, and zero unowned requests. Editor/delivery PNGs are byte-identical for Clue/Conduit at both widths and Google mobile. Google desktop differs at 127 pixels; AWS differs at 20 desktop/18 mobile pixels, so those views are not claimed pixel-exact. These comparisons concern the top viewport only.

The production source-flow reader correctly refuses the frozen Google document's `body min-height:1080px`: it cannot be faithfully projected into a non-layout context surrounding only one recovered sibling group. The earlier +89px prototype is not a production-accepted recovery. The actual registry/recreate proof returns the named gap, preserves ten pins, reads one scoped snapshot, and keeps source order. Its registry release gate is a test fixture; it is not evidence of live release approval.

## Evidence and verification

- Rust workspace: 1,196 tests passed across 74 suites. Missing ignored PNG fixtures were copied unchanged from the existing checkout; no visual baselines were regenerated.
- New isolated release helper built. WASM rebuilt and handshake matched engine stamp `bb1aaeea610a`; unrelated binary churn was not retained.
- Native defaults plus existing editor candidates: 26 passed.
- Source-context/mint/root-unit checks: 183 passed.
- Editor preflight: 51 standalone checks passed, including source defaults, native precedence, token utilities, integrity failures, unsupported versions, and no unowned import requests.
- Nested band coverage: 4 passed. A mistaken test assumption about the existing missing-page fallback was corrected without changing production fallback behavior.
- Shared flow: 46 focused implementing-agent checks passed. The parent independently verified 50 shared-flow and coverage checks.
- Frontend design-system build, lint and production build passed. Lint retains two existing unused-function warnings.
- Full agent-runtime suite: **2,687 passed, one opt-in live test skipped, zero failures/errors** (76.125 seconds). The first pass found 39 failures: missing isolated editor dependencies, obsolete provider mocks and moved vocabulary references, plus genuine missing repair/review guidance. The guidance was restored and its actual materialized skill/reference chain verified; assertions were not weakened.
- API repair group: 114 tests passed after installing the isolated compiler's existing locked dependencies and correcting subprocess import paths, documented DSN scheme handling, and DOM-versus-CSS assertions. Independent review found no important issues in these and the provider-transport test repairs.
- Full API regression gate: **2,763 passed, nine skipped, zero failures/errors** on the fresh disposable database (335.833 seconds). Its first pass completed with 2,712 passed, 41 failures and nine skips. Beyond missing compiler dependencies and fixture drift, it caught the real streaming incompatibility described above. All 114 capture/ingestion checks now pass in both the specialist run and the parent's full suite. Independent review caught and verified fixes for pre-response cancellation, cleanup cancellation, and duplicate native handle release; genuine local-server regressions reproduce each defect.
- The subsequent full API run had 2,762 passed, one failure and nine skips (337.859 seconds). Read-only diagnosis found 112 old rows for a shared test PNG, exceeding the existing 50-candidate public lookup bound; a focused repeat also exposed the same issue for another fixture with 59 rows. No production lookup rule was changed. The fresh, uniquely named disposable database passed the full unchanged suite; previous and live databases were preserved. The bounded public lookup remains unchanged, including its existing limit when old metadata points to unavailable storage.

Ignored local evidence lives under `.local-setup/website-capture/`: `native-preflight-final-20260920/`, `source-flow-implementation-20260920/`, `preflight-zero-20260920/parser-request-correction/`, and the named `renderer-*`/`native-defaults-*` logs and XML files. No source asset or credential is embedded in this report.

## Remaining work

Whole-document layout projection, viewport-specific media recovery, support-widget exclusion, original motion/WebGL behavior, repeated CSS cost, and live generated-page acceptance remain open. The standard Docker generation runtime is still absent (`command -v docker` returned no executable); offline renderer checks do not establish a live generation pass. Public rendered HTML/CSS capture is not recovery of a site's original React component source or JavaScript programs. The skills must report the distinction between preserved source, authored replacements, and unverified behavior.
