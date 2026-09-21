# Editor preflight isolation — bounded checkpoint, 2026-09-20

The editor now excludes resolved fragment interiors from Tailwind browser preflight without changing the specificity, cascade layer, importance or ordering of native rules. This repairs the measured AWS heading/button difference: source and delivery used 16.38px / 26.208px while the editor used 14px / 22.4px. This report covers the preflight change; the separately reviewed source-context and host-default changes remain separate evidence.

## Mechanism and ownership

`lumen_api/fragments/editor_preflight.py` reads an unchanged, licensed Tailwind 4.3.3 preflight resource. A bounded tinycss2 walk locates selector subjects and inserts `:not(:where([data-lumen-fragment="true"] *))`, before terminal double-colon pseudo-elements. It edits the original source by parser offsets: declarations, comments, string spelling and source order are preserved exactly. The qualifier adds zero specificity. It does not introduce `@scope`, a sublayer, computed pixel overrides, or vendor-runtime changes.

The parent-owned renderer emits `data-lumen-fragment="true"` only on resolved fragment wrappers in both modes. The exclusion covers their interiors, including nested fragment wrappers; the outer native wrapper keeps its native defaults and utilities. Candidate isolation remains independently responsible for source-only utility names. Shared native/source class collisions remain an explicit limitation.

The canonical compiler input receives the original layer order, a theme import nested inside the existing `theme` layer, the qualified preflight in the same `base` layer, and a utilities import nested inside the existing `utilities` layer. Nesting prevents the native HTML preload scanner from requesting package-style import URLs. Existing theme and candidate directives follow unchanged. `editor_compiler.py` validates a single renderer-owned direct head block with a bounded prefix; the large source CSS after it stays opaque. Missing or ambiguous structure, foreign imports, resource drift, unsupported grammar, or scan limits retain the entire original HTML and emit a typed warning.

No-fragment renders are unchanged. Delivery receives no Tailwind preflight change. Source artifact HTML/CSS, sanitization and custody rules are unchanged by this helper.

## Runtime identity and failure contract

The supported pair is `tailwindcss` / `@tailwindcss/browser` 4.3.3, from the existing local npm installation:

- Preflight SHA-256: `ace8310eed6dc5568a56fc16e1d695cf58da7528d81d66d81649e93cce644df6`.
- Browser bundle SHA-256: `a60c785630a06196808cbe79e6f7bdb4abcc8f4421a47b56f29338fc84805e3b`.
- Unchanged CSS, package provenance and MIT license are retained under `lumen_api/fragments/resources/`.

The browser package exposes built-in stylesheet imports only; it has no public plugin or replacement stylesheet-loader seam. Pinning the separate upstream preflight is therefore an explicit supported-version contract, not an assumption that arbitrary later browser releases have identical defaults. Upgrading requires new provenance and re-running native cascade parity against that runtime.

For an external runtime URL, `CoreClient.web_render` qualifies only resolved-fragment editor output and adds SHA-256 SRI plus `crossorigin="anonymous"` to the exact adjacent engine-emitted script. The browser must receive the pinned bytes, regardless of URL spelling. A mismatch or unsuccessful load cannot execute the runtime.

Both editor shells use opaque-origin `sandbox="allow-scripts"` srcdoc. Even the same-host vendor URL therefore needs CORS permission for SRI. Both Next configs now expose `Access-Control-Allow-Origin: *` on the exact public `/vendor/tailwind-browser.js` file. No other routes or sandbox permissions change. A custom runtime URL must serve the exact supported bytes and permit anonymous CORS.

**External SRI is enforcement, not evidence that playback succeeded.** This change emits no verified-runtime success status merely for inserting SRI. Browser integrity/CORS failures currently appear in its console and leave compiled utilities absent. The existing frontend marks fetched render HTML ready without consuming these runtime failures; a dedicated editor load-error status remains a follow-up. No new UI success or fidelity-complete claim is added.

For inline agent previews, `_render_page_html` reads the runtime bytes once, qualifies only a matching digest, and inlines those same bytes. Unsupported bytes retain the original compiler input and produce `fragment.editor_preflight_runtime_unsupported`. Review remains unsettled. Public preview/review results use `tailwind_runtime_unverified`; `tailwind_runtime_missing` remains reserved for absent runtime bytes. The existing internal boolean name is transitional and now covers unavailable or unverified runtime evidence.

## Verification

The initial identity-only implementation failed the subject/nested-selector checks. Runtime-hook baselines then failed five external-pinning, unsupported-version and invalid-shape contracts. A malformed provenance object exposed an AttributeError and was corrected to typed refusal.

The first integrated standalone pack passed **49 tests in 10.49 seconds**; after the parser-request correction below, all **51 tests passed in 12.20 seconds**. It uses no application startup, API fixtures, DB access, provider calls or installs. The exact command, from the isolated worktree, was:

```sh
CLUE_DATABASE_URL="$(cat .local-setup/website-capture/test-dsn)" \
LUMEN_EMBEDDED_FLEET_WORKER=0 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=subsystems/clue-design/apps/api:subsystems/clue-design/packages/py-lumen-config \
/Users/shashank/Documents/clue-latest-pull-sept7/.venv/bin/python -m pytest -q \
-c /dev/null --noconftest -p no:cacheprovider --basetemp=/tmp/preflight-zero-wired-full \
subsystems/clue-design/tests/offline/test_editor_preflight.py
```

Coverage includes exact text preservation, unsupported grammar/bounds, resource/provenance drift, canonical insertion, marker text collisions, external idempotence, and no-fragment/delivery preservation. Twelve real-browser comparisons cover both external and inline runtime ordering with ordinary, equal-specificity, zero-specificity, same-layer important, nested-layer important, and utilities-layer important overrides. Native sampled computed styles remain identical. The earlier rejected `@scope` counterexample now remains `display:inline` before and after.

The compiled CSS token trees are identical after removing only the 77 guard additions and normalizing whitespace/comments/string quoting. This checks declarations, rule/layer order and importance against the actual bundled default compiler output, beyond keyword assertions. Browser-default heading/button/image, file control, placeholder, pseudo-element, option and nested-fragment observations were also checked in the mechanism probe. Host semantic defaults are a separate change; preflight isolation alone does not remove the renderer's old global image/box-sizing rules.

Six transport cases exercise actual browser SRI under top-level and sandboxed srcdoc loads, cross-origin requests, denied/allowed CORS, and altered runtime bytes. Playwright `route.fulfill` automatically grants an origin when ACAO is absent, so negative CORS fixtures explicitly supply an empty denying header. An initial probe lacking that control was discarded as CORS evidence.

Inline tests execute the actual `_render_page_html` method and actual review acceptance/public-flag expressions extracted from the source AST, with a minimal transport fixture, avoiding application/DB imports. A separate Core hook contract checks external qualification and inline deferral. These are scoped seam checks, not full application-flow proof; the parent owns broader gated suites.

The actual final frozen AWS render proof uses the production Core helper, plus the actual inline method over the same frozen document/fragments. At 1440px and 375px, external SRI and inline output both compile successfully and match source/delivery H3 and nested button font size/line height at 16.38 / 26.208. H1 boxes remain 504×88 and 279×108 respectively. The desktop CTA remains 44px tall. External and inline typography screenshots were inspected; captured support-widget and other pre-existing source limitations remain visible. No new assets were fetched or minted.

The exact vendor header methods in both Next configs were evaluated through the existing local TypeScript parser, confirming only the one route/header pair. The API Hatch wheel configuration includes the `lumen_api` package and the resources are inside it. Actual wheel enumeration was **not run**: `hatchling` is absent from the approved venv, and no install was attempted. This packaging verification limit remains explicit.

New Python helper/test lint and diff whitespace checks pass. The initial throwaway probe had a source fixture without a doctype and an over-specific utility-readiness assumption; those harness errors were corrected before the parity results above. No pass from the earlier unintended DB-backed run is included here.

## Evidence and remaining limits

Ignored evidence lives at `.local-setup/website-capture/preflight-zero-20260920/`: exact RED/GREEN logs, probes, provenance, compiled CSS, SRI matrix, final production HTML, computed measurements and screenshots. Earlier rejected `@scope` evidence remains intact in its own directory. The parent independently reviewed the change and owns integration gates/commit decisions.

This is a bounded browser-default/cascade repair, not a universal clone-fidelity claim. It does not recover arbitrary source JavaScript, React/WebGL programs, missing assets, unsupported ancestor topology, motion, all browser engines or all brands. External runtime error propagation to editor UI, exact packaging verification, and source CSS volume remain follow-ups.


## Parser-request correction after parent replay

The parent's actual four-brand navigation replay exposed one unexpected request in every editor render: `/tailwindcss/theme.css`. A standalone audit reproduced the request with a parser initiator even after removing the runtime script. The compiler-input style had no CSSOM sheet, while the compiled Tailwind output had no remaining imports. Padding, palette colors, custom primary token, rounded corners, mono font and text sizing all matched the original runtime. This was a real unwanted native/speculative browser request from inert compiler text, not a missing built-in theme or a replay-harness error. The earlier browser checks aborted unknown requests but did not assert their absence, so those passes did not prove a network-free compiler input.

Two new real-navigation cases, external and inline, failed on that exact request while their token comparisons passed. The correction places the built-in imports *inside* their same existing named layers instead of using top-level import `layer(...)` parameters. The actual compiler accepts this, all native precedence and compiled-token parity cases remain green, and both new cases observe zero unowned requests. SRI, digest pins, source text, unsupported-runtime diagnostics and cascade order are unchanged. No new style mutation or vendor patch was added.

The complete standalone pack passed 51 tests; the parent owns the refreshed four-brand replay. The earlier frozen AWS transport screenshots in this report predate this final import-spelling correction; the new parity and zero-request cases prove the compiler change, rather than implying those screenshots were regenerated by the implementer.
