# 2026-08-24 — Deepagent speed/quality forensics → Fast Loop v1 spec draft

## What happened
Analyzed the 2026-08-24 Stuttgart manual-test logs (platform-api / design-api /
fleet-worker / fleet-worker-2 + `.deepagent-workspace` run traces) for why
scene-ad generation took 20–43 min. Then studied the founder-supplied Moda.app
architecture/skills transcript and drafted the restructure spec.

## Established facts (measured, dedup'd — fleet logs write every line twice)
- Wall time ≈ 99% sequential LLM calls in both long runs. Engine is ms-fast
  (compile ~100ms, preflight ~250ms); APIs healthy.
- `run_9269a8…`: 20m42s, 68 calls, 4.46M input tokens, died on OpenRouter 403
  (weekly key limit) at finalize; save-on-finalize discarded a valid scene.
- `run_7d4ba182…`: 43m18s, 178 calls, 13.5M input tokens, 3 review rounds,
  first preview only at +15.4 min; "succeeded" but export blocked by LUMV0820.
- Call sinks: ~75 calls to first preview (asset-preview bug → disk hunting:
  71 reads/43 greps/22 ls; LUMV0820 impossible-repair probing), 25-call
  reviewer round-trips ×2–3, micro-edit drip (14 compiles ≈ 24 calls for
  iterations 21–34).
- Bugs confirmed: (1) `tools/substrate.py` ~1442 concatenates durable-storage
  refs onto engine-cache root → every `view("asset:…")` = `asset_missing_file`;
  (2) LUMV0820 unrepairable in DSL yet blocks all export; (3) export failure
  message is screen-reader-only in `image-export-menu.tsx`; (4) scene text
  inspector (`AdTextInspector`) has NO content field and canvas double-click
  text is out of AD4.C v1 scope — text *content* uneditable in scene editor
  (write path exists: `structuredEdits.modifyNodeEdit` text.content);
  (5) fleet-worker logs duplicated line-for-line; (6) frontend SSE 5-min body
  timeout leaves stale "Working" UI.
- `render_preview` is orchestrator-only (`harness.py`); author has `view` but
  cannot render its own edits — root of the review round-trips.
- Moda study: single agent, no reviewer, pushed per-turn context (canvas
  index + computed type scale + skill in force), declarative whole-page
  markup, mandatory self-screenshot, ~100-line opinionated format skills
  (defaults + named tests + banned lists + override clause). ~4–5 calls/page.

## Founder rulings (2026-08-24)
- Variants: wanted soon, but do NOT change single-artboard model now (R1).
- Clarifying questions: conditional — assess brief sufficiency, ask 2–4
  batched questions only when material gaps exist, else defaults+record_gap (R2).
- Hard requirement: generation ≤10 min, target ~5.
- Direction agreed in discussion: retire separate reviewer for scene turns,
  fold checklist into author self-audit (author gets render_preview).

## Artifact produced
`subsystems/clue-design/docs/deepagent-fast-loop-v1-spec.md` — DRAFT awaiting
founder review. Contains: frozen baseline + gates (≤45 calls, ≤10 min, TTFP
≤4 min), P0 bug fixes (asset previews, LUMV0820 repairability, export
severity split, checkpoint commits), loop redesign (frame payload, author
micro-loop with render, reviewer→self-audit, deterministic autofix, tool
routing rule, budgets, conditional clarification), format-skill library spec
+ full `linkedin-square-ad` pilot skill draft, instrumentation/rollout plan,
open questions.

## Not done / next
- Spec NOT committed (awaiting founder review per discuss-before-editing).
- Implementation not started. Planned split: P0 bugs (parallelizable),
  instrumentation, loop change flag-gated (`LUMEN_AGENT_FAST_LOOP`), pilot
  skill; then follow-on format skills; variants later per R1.
- Scene text-content editing needs a founder presentation ruling (dummy
  frontend is presentation truth).
- Stuttgart `.env` was set to `LUMEN_AGENT_REASONING=medium` (other session).
