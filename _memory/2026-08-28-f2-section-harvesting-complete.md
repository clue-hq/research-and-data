# 2026-08-28 — Phase F2 (section harvesting) COMPLETE

Plan: `docs/superpowers/plans/2026-08-27-clone-fidelity-master-plan.md` (status header updated).
Commits `339ddd466..61fa11db7` on `integration/frontend-design-part-iv-v2` (on top of F1's
`0a038db28`), LOCAL ONLY. Process: SDD, Opus implementers + Opus-only reviewers, one fix round
per task, final whole-phase review, ONE fix wave + completion round, live re-walk. Full ledger:
`.superpowers/sdd/2026-08-27-clone-fidelity-master-plan/progress.md` (preserved).

## What F2 delivered
- **F2.1 segmentation** (`lumen_ingestion/sections/segment.py`): deterministic landmarks ×
  measured-bands segmentation; per-band feasibility binding (forward/backward greedy windows —
  provably refuses exactly the ambiguous span, binds the rest); probe-skip evidence records
  (capture/geometry.py now records each skipped child {tag,id,classes,reason}); verified
  resolve_section (tag+id/class, drift ⇒ None); HTML-AAM ancestry landmarks; rendered-text
  (script/style never read as prose).
- **F2.2 minting** (`sections/{cssmatch,slotdetect,mint}.py` + pipeline stage): escape-aware
  CSS rule matching; spec-faithful srcset grammar; prelude-strip mode (mint path only);
  recursive conditional-at-rule descent in ALL capture CSS walkers (the stripe blocker) +
  narrow @font-face-src degradation; deterministic slot detection (no slot inside a consuming
  slot, engine-faithful); empty-after-sanitize refusal; preview crops from the stored
  screenshot (nav/footer estimated extents); draft→approved kit-approval cascade (same
  transaction); new-pin-requires-approved gate with derive/template pins INHERITED from the
  source doc; content-addressed idempotent re-mint w/ kit-version rebinding (migration
  20757986d457); mint backstop 40 = capture ceiling (founder: floor-not-cap).
- **F2.3 agent access**: "cloned section" vocabulary (insert_cloned_section; the unrelated
  web_ingest_fragment untouched); approved-only discovery in page order w/ total+truncation;
  insert wraps in a section (LUMW0011); gate refusals legible; loud LUMA0601 when a rewrite
  drops pins; reuse-ladder prompt blocks (DRAFT — founder review pending).
- **F2.4 Brand Grammar Audit**: deterministic five-field grammar (type law leads; cadence;
  color-frequency; surface; anti-patterns) from measured evidence, honest abstention when
  bands unreadable; rides the kit; injected via the BrandBrief seam bounded at 4000 chars
  (whole-rule drops, loud). Wording DRAFT — founder review pending.
- **W7**: export site.css compiled from DOCUMENT-ONLY HTML (fragment classes no longer
  generate Tailwind utilities; cascade warnings de-noised).

## Acceptance: walk FAIL → general fixes → RE-WALK PASS (both sites)
First walk failed honestly (insight: 0 previews via ambiguous band binding on a class-hidden
section; stripe: 0/10 minted via un-collected @media-nested @font-face). Final review traced
both to seams, ruled wave W1–W8 (NO site-tuned fixes). Re-walk: insight 9/9 approved,
8 previews; stripe 10/10, 10 previews; bands bound by EVIDENCE (skip records live); Sohne
58,852B durable; gate + agent path live on both sites. Reports: task-15-walk-report.md (FAIL)
+ task-15-rewalk-report.md (PASS) in the SDD workspace; /tmp/f2_rewalk evidence retained.

## Suite gates (founder-ruled focused; full suite waived)
API 438/438 (12 fragment-family files), runtime 84/84. Known environmental family unchanged
(custom-component/typescript). One process lesson (ledgered twice): a status-gate change
touches EVERY suite that pins a fragment — three test files were hit in sequence; closed by
RUNNING every candidate, not grepping. Second lesson: a caplog test dies as ERROR under
`-p no:logging` (harness-flag coverage gap).

## FOUNDER QUEUE (open)
1. Prompt wording drafts: reuse ladder (`prompts_web.py` step 1c + REUSE BEFORE YOU COMPOSE)
   and grammar audit (`brand_brief.py::_AUDIT_HEADER` + `grammar_audit.py` rule templates) —
   real rendered output quoted in the re-walk report.
2. Reviewer/exit-judge is untaught about cloned sections AND the audit — a composed page that
   breaks the measured law or mismatches a clone is checked by nobody (one decision, unowned).
3. Hidden-section product ruling: a class-hidden pricing band is dropped loud (LUMI0525) but
   unreachable — mint it hidden? offer it? (walk 2 concern).

## Carry register (owners)
- **F3**: role-vocabulary recall re-measure (post-rendered-text fix; "Testimonials" still
  `other@0.30`); compound-band segmentation refinement (Testimonials+Blog+GetStarted one
  fragment; 4598px stripe row); CSS byte budget (1.35MB/page) + preview bytes at rest (6MB) +
  cross-fragment CSS sharing; author_web_page preserve-through-rewrite (loud-drop shipped);
  duplicate-pin instance drop; stale node_id locator; fragmentless second-render guard;
  audit prose round (n≥2 dark wording, implausible leading abstention, sohne caveat);
  LUMW0606 double duty; diagnostic id escaping; /brand-context audit mirror; bands_were_
  truncated consumer.
- **F4**: protocol-relative href posture; og:image background-only pages; source_document_id
  inheritance hardening.
- **Capture-probe/F0 family**: nav/footer geometry on <main> pages (estimates ship);
  outside-root hidden elements (the `hide` banner residual); collapsed-element leading
  measurements; capture/imgsrc.parse_srcset second parser.
- **Register**: pdf.py:78 pre-existing site-tuned literal (2026-07-05, PDF path);
  _band_matches looseness is T11's OWN drift ruling (changing it = contract decision).
