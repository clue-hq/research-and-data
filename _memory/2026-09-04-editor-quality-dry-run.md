# 2026-09-04 — Apollo dry run: what the founder saw, what was true, the roadmap

Roadmap (binding order + root causes): `docs/superpowers/plans/2026-09-04-editor-quality-roadmap.md`.
Order ruled by the founder: Plan 1 ingestion → Plan 2 fresh document → Plan 3 selection ladder →
Plan 4 text bounds + inspector typography LAST, with a founder preview gate on every inspector
control (icons, layout, icon source) before it lands.

## The run itself (thread `thr_fccf1ba1…`, doc `doc_cf05190c…`)
- First inner run `run_41071629…` was orphaned by my stack restart; the platform retried and
  `run_0452aae9…` finalised `completed_with_warnings`, stop reason `budget_exhausted_before_repair`
  (42/45 target calls, ~14 min). It spent its opening minutes on assets against a PAGELESS
  document (every placement refused by `LUMV0100`), which ate the repair round.
- The repair turn `run_b866…` did a single-node chip edit (headline lh 0.98, box re-fit) in ~6 min
  and STREAMED correctly (checkpoint 19:28:48, op batch 19:30:23): the transport is fine; the
  blank start was the pageless-document gap.
- `design_leg.exit_judge_failed` = the known blocked leg-close judge (gateway timeout policy);
  the message fell through to a normal design turn.

## Verified root causes (details + file:line in the roadmap)
- Kit `type.headline.line_height = 4.5`: `capture/parse.py::_line_height` divides px by 16 (root),
  not the element size. Source of the broken headline AND the stray "x".
- Bold/italic dead: the kit has one face per family (400 normal); the editor never synthesises;
  both fonts are variable (wght axis) and were never instanced.
- CTA unselectable: `representableHit` picks the deepest representable node (the label); no hover
  outline; no walk-up gesture; the agent also overflowed the CTA past its column.
- Box ≠ paint: engine hit-tests/outlines text by the layout box; text paints unclipped; fixed
  boxes authored by the agent.
- Inspector: engine + adapter already support vertical align / line height / letter spacing /
  max lines; the ad inspector just never renders the rows.
- Pageless streaming: `use-scene-document.ts:254` picks `pageId` once at load → null forever on a
  pageless load until a checkpoint reload.
- Page-before-assets: no ordering rule; `generate_image` pays before it checks for a page.

## Ops notes
- Stopped EVERY server on the box at the founder's request; only colombo's four run now.
- Purged all `ws_test_*` data: 214,056 rows / 30 tables / 6,278 workspaces + 59 blob dirs;
  guards re-enabled. The colombo fleet worker now runs with `PYTHONUNBUFFERED=1` so its log
  streams (the old one looked silent because stdout was block-buffered).
- `ls -dt <dir>/` lists the dir itself; `ls -t <dir> | head -1` gives the newest inner run; the
  outer run's `run_started` event also names it.
