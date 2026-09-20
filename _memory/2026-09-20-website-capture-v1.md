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
