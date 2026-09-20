# Website capture fidelity V1

- Approved long-running implementation goal isolated in `codex/website-capture-v1`, based on design-agent `0e509e9d`. Original checkout and running instances untouched. Full plan in `docs/superpowers/plans/2026-09-20-website-capture-v1.md`.
- Existing artifact + ingestion capture tests were green. Added source-shaped AWS SVG regressions; quoted local gradient/filter URLs reproduced `fragment.unreadable_reference`. Narrow fix accepts a single quoted same-document reference, preserving external custody, malformed-reference refusal and style-breakout escaping. Artifact suite: 107 passed.
- Auto-review rejected an initial broader None-return fix before execution; read-time verification showed None denotes empty or local references. Used the narrower explicit `#` check plus single-argument validation and additional refusal tests instead. No security gate relaxed.
- Conduit missing-src hypothesis disproved: collector already explicitly preserves img src. Need trace actual network/capture timing rather than normalize query strings or weaken the reference gate.
- Google video references remain unsupported; multipage coverage, kit associations, live expanded captures, fidelity evaluation and skill/account work still pending.
- Runtime: original generation fleet still lacks Docker sandbox prerequisite. Do not silently disable it. Continue capture/source repair while resolving standard runtime setup.
