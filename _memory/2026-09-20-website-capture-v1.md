# Website capture fidelity V1

- Approved long-running implementation goal isolated in `codex/website-capture-v1`, based on design-agent `0e509e9d`. Original checkout and running instances untouched. Full plan in `docs/superpowers/plans/2026-09-20-website-capture-v1.md`.
- Existing artifact + ingestion capture tests were green. Added source-shaped AWS SVG regressions; quoted local gradient/filter URLs reproduced `fragment.unreadable_reference`. Narrow fix accepts a single quoted same-document reference, preserving external custody, malformed-reference refusal and style-breakout escaping. Artifact suite: 107 passed.
- Auto-review rejected an initial broader None-return fix before execution; read-time verification showed None denotes empty or local references. Used the narrower explicit `#` check plus single-argument validation and additional refusal tests instead. No security gate relaxed.
- Conduit missing-src hypothesis disproved: collector already explicitly preserves img src. Need trace actual network/capture timing rather than normalize query strings or weaken the reference gate.
- Google video references remain unsupported; multipage coverage, kit associations, live expanded captures, fidelity evaluation and skill/account work still pending.
- Runtime: original generation fleet still lacks Docker sandbox prerequisite. Do not silently disable it. Continue capture/source repair while resolving standard runtime setup.

## Media capture checkpoint

- Conduit root cause verified against original DB metadata: requested `https://conduit.ai`, final `https://www.conduit.ai/`; the live fragment adapter incorrectly resolved relative assets against requested_url. Both live and persisted segmentation now use the final page URL. Exact query parameters remain intact.
- Added video/source and poster candidates, 50 MiB per-video cap, supported MIME validation, stream-time byte limits and redirect-hop SSRF checks. Video bytes bypass image analysis and remain in snapshot/fragment storage.
- Snapshots now retain all downloaded dependencies and exact URL/kind/hash metadata, even if no section could be minted; snapshot diagnostics are retained too. No schema migration for this additive metadata.
- Fresh source-only Conduit homepage probe: 856 downloads (~59 MiB self-contained JSON), all visual dependencies resolve; one 404 favicon plus informational renderer notice. Only scripts/tracker references remain missing from raw HTML; these are stripped from reusable fragments by design. Probe saved privately in isolated worktree; no live workspace write yet.
- Disposable database `clue_website_capture_test_20260920_1500` created and upgraded to existing head for tests. No live DB changes. Focused capture/snapshot/mint matrix passed (238 pass, one skip before final added image-analysis check).
- Full-file Ruff has inherited findings; introduced lines are checked separately. New media test file is lint-clean.

## Kit association checkpoint

- Added `design_web_fragment_kit_binding` (migration `d27183d13445`, parent `5cac3234cfb3`) to retain each capture's kit/version association without replacing immutable fragment content/origin. Existing rows backfill from their original kit binding.
- New associations start unreleased; human kit approval updates only that capture's association. A separate explicit release remains valid if another capture is revoked. Deprecated/dormant fragments and individually governed repairs retain existing lifecycle protections.
- Registry/agent discovery now returns capture bindings; legal/footer and campaign-shell selection can recognize an associated newer kit. Cross-workspace duplicate insertion fails at composite foreign keys.
- 152 registry/lifecycle/approval/agent-discovery tests passed; added foreign-kit-on-duplicate regression also passed. Migration up/down/up passed on separate empty `clue_website_capture_migration_20260920_1510`; exactly one head. Live DB has NOT received this migration.
- Fresh isolated homepage captures complete for all four brands. Google original `MultiPath_2X_V2.webm` now captured (~494 KB). AWS reports ten over-limit font resources; these are visible partial-capture gaps, not a full-fidelity pass. Supporting page capture and skill/fidelity work remain pending.

## Multipage coverage checkpoint

- New guarded website requests default to bounded observed-link discovery (home + two products + customer index + two stories), accept up to 19 explicit supporting pages, and never exceed 20 total pages. Existing frozen jobs keep their recorded semantics. HTTP error pages are refused; individual supporting-page failures are retained.
- Added durable per-page acquisition/mint coverage and CSS/video/canvas inventory. The existing public job outcome exposes a bounded summary, always fidelity_verified=false. Frontend coverage UI remains unimplemented; API visibility is not a UI claim.
- New library pool 240 per visible/dormant lane, existing 40 per page; fair allocation prevents homepage starvation. Both config examples updated. First-time onboarding idempotency is unchanged; explicit Re-extract is refresh/retry.
- Red/green regressions verified. Final focused matrix: 223 passed, 2 skipped, 3 warnings. The skips are existing live/optional checks. New-line Ruff findings: zero; full touched-file lint has inherited debt. Initial test failures traced to original-checkout editable imports; isolated PYTHONPATH now includes py-lumen-config, and subprocess import tests preserve it. No shared venv or runtime configuration changed.
- Expanded source-only capture is running from observed official URLs in ignored local setup artifacts; no live workspace import or fidelity approval yet.

## Source-library and first reproduction checkpoint

- All 19 selected official HTML pages captured: Clue 1; AWS, Conduit and Google Cloud 6 each. Supporting product/customer/story URLs came from observed links. Per-brand distinct asset hashes excluding screenshots: Clue 24, AWS 174, Conduit 760, Google 376; counts include responsive renditions. Google has four distinct videos. These remain isolated frozen files, not live workspace imports.
- Offline homepage admission using production builders: Clue 8/8; Conduit initially 10/12; AWS 12/12; Google 2/3. Original raw preview artifacts and reports preserved. This is not final fidelity evidence: inherited typography, AWS responsive overflow, transient support widgets and Google segmentation need work. Google main content is grouped as one hero, refused because the source really includes a fake.webm fallback returning 404. Do not weaken dependency custody or invent a replacement original.
- Conduit root cause: Lexbor iter(include_text=False) still yields -comment nodes; React suspense markers were included in CSS nth-child arithmetic. Added a source-shaped failing regression, excluded non-element pseudo-tags, 244 fragment/slot/artifact checks passed. Frozen Conduit re-probe now admits 11/12; remaining refusal is an empty script/embed shell.
- Raw diagnostic preview lacked UTF-8 metadata, causing apparent glyph corruption; not a product defect. Lazy offscreen image count is not broken-URL evidence. Report these limitations rather than overclaim screenshots.
- Task 4 complete in local commits 269ee376 and af4097d4. Task 5 remains in progress: source capture done, durable workspace import and production reproduction pending. Standard Docker runtime absent; user runtime choice requested asynchronously. No original .env/service/workspace writes, no migration to live DB, no push.

## Framework-wrapper recovery checkpoint

- Google source DOM has nine authored sections below c-wiz/div wrappers; a missing closing-section fake.webm fallback rejected all content at once. Added generic recovery inventory using exact original DOM paths, activated only for missing-dependency refusals. Healthy parents are retained unchanged; semantic compositions/nested sections/explicitly hidden ancestors stay intact. Each recovered fragment is a draft with parent provenance, no invented crop, and explicit unverified wrapper/context fidelity.
- Fair multipage allocation now reserves potential recovery slots. Public coverage remains partial after any refusal, even when recovered fragment counts happen to match original segmented counts. Recovery attempts are capped per wrapper using the documented section cap; omissions are reported. No asset custody, security or budget refusal is bypassed.
- Red/green tests reproduced both loss and unbounded-attempt risk; final matrix: 350 passed in 16.53s. Disposable DB only. Ruff initially failed to write its cache in sandbox; reran --no-cache. New-line findings fixed, inherited file lint debt remains.
- Frozen four-brand probe: Clue 8, Conduit 11, AWS 12, Google 10 admitted; Google previously 2. Desktop/mobile diagnostic renders have scroll widths 1440/375 and visually contain source imagery/type/layout again. Interaction, motion and production fidelity remain unverified; original probes preserved.
- Conduit typography root cause remains open: Next font-variable classes live on html, outside fragment subtree; inherited custom properties are lost. Do not patch with hardcoded font values or claim original React/WebGL runtime recovery. Live workspace import, production generation (Docker choice pending), and seven skill families remain pending. No original runtime, env, database, branch or remote writes.

- Closing verification: caught a crop-inference edge case during diff review; recovered footer-like sections are outside the original flow and may not borrow its bottom-of-page pixels. Added failing regression then guarded inference. Final changed-line Ruff: 0 findings (78 inherited full-file findings); diff whitespace clean. Checkpoint remains Task 5 in progress, full goal active.
