# 2026-10-07 — Website path decision and Puck spike phase 1 (trenton, branch spike/puck-phase1)

## Context
- Website agent trials (`trials/web-agent/`, harness that runs the real design runtime with a
  swapped skill set; replays Run 3's stored input): normal run $3.20 / 26 calls; staged run
  (text-only copy stage + narrowed build) $1.12 / 21 calls. Cost driver: one growing conversation
  (52k→200k tokens per call) and the screenshot review loop (~47% of tokens).
- Repo studies (scratchpad/oss/*-report.md): Onlook rejected (abandoned since Nov 2025,
  browser-bound agent, CodeSandbox + Supabase lock-in); Puck chosen (MIT, React page model +
  editor + server render; its AI is closed/paid and not used).
- The 2026-10-04 code-first (Astro) lane was planned but never started; Puck lane replaces it.
- Founder: phase 1 = Opus builds by hand to test compatibility; agent pipeline only after.

## Phase 1 result: all gates and tests pass (trials/puck-spike/FINDINGS.md)
- G1 Tailwind v4 inside Puck editor iframe; G2 clones (stored HTML + scoped CSS, engine slot
  rules copied to `lib/clone.ts`) render as today's engine does, no CSS leaks; G3 kit → theme,
  computed styles equal kit values (both brands, published + editor at 1440).
- Own token-only sections, brand-asset picker, shared shell across routes (`/_shell` editor),
  inline editing of our sections and of clone text, undo, reorder (mouse), publish.
- Six wiring bugs found and fixed (load-time resolveData reset, undo history, pointer events in
  clones, editor code in published bundle, cascade layer, hard-coded dark surfaces).
- Kit gaps (Conduit's button, Garner's heading ink) filled by measuring clones
  (`export/measure_brand.py`); brand ingestion should own this.
- Production issues to carry: ~1 MB HTML per page from duplicated clone CSS; 0.5 MB React
  runtime (static publish would drop it); unused font faces.

## Operational
- Dev server: `.claude/launch.json` "puck-spike" on port 3047 (3045 is taken by another lane).
- Data export (lane DB read only): `.venv/bin/python trials/puck-spike/export/export_brand.py garner|conduit`;
  outputs are gitignored (data/brands, public/brands).
- Conduit accounts other than Dana.AI have no written research (headcount only); Atrium copy is
  seller-led by design.

## Next
- Founder review of brand coherence and editor feel; then phase 2 (agent pipeline on the same
  contracts: copy stage → props JSON → render → one look).
