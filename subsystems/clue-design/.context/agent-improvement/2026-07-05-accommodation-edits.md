# Accommodation edits — targeted turns may need bounded neighbor adjustments

User report 2026-07-05 (screenshot: badge moved to top-right, "Presented
by Y Combinator" lockup left crowded directly beneath it — evidence
`.context/attachments/tQzEXh/Screenshot 2026-07-05 at 4.05.21 AM.png`,
observed live during the 4c e2e):

> when the agent is asked to edit an existing design by referencing a
> particular element, right now there is a very strict rule that it
> should not touch other elements. ideally it should be allowed to make
> slight adjustments to the other elements if the need be. [...] it did
> move the badge correctly but failed to make the margins comfortable
> [...] ideally it should have slightly moved that YC thing slightly
> below or to the left. but it was not allowed to touch other elements.

## Where the strictness lives (all reinforce each other)

1. `prompts.py` seeded-edit rules: "Touch ONLY what the request requires:
   every node you do not name must remain byte-identical."
2. Pinned/freehand policy (same block): pinned geometry is human-owned —
   move it only when the user asks. The YC lockup is pinned post-freeze,
   so it is doubly off-limits.
3. Repair gates: `SURGICAL_AUTHORING_CONSTRAINTS` + `is_surgical_dsl` +
   the layout-cluster gate mechanically zero-apply out-of-scope refs.
4. Phase 0b edit-scoped acceptance: critique issues that target nodes
   OUTSIDE the edit scope cannot block the turn — so a spacing critique
   about the crowded neighbor is precisely the kind of issue that gets
   waved through as advisory. The mechanism that stops whole-design
   rejections from holding a user's edit hostage also waves through the
   crowding the edit itself created. (Note the irony; both behaviors are
   correct for their original purpose.)

## Why the rule should NOT simply be relaxed

The strict rule is the trust contract that makes chip-targeted edits
safe on human-arranged documents ("small ask ≠ redesign"). Uncapped
"the agent may adjust neighbors" re-opens exactly the failure Phase 0b
closed: turns that reorganize half the design because the model judged
it "needed".

## Proposed design: bounded accommodation edits (turn-scope expansion)

Reuse the baseline-diff machinery (b707560) — it already defines "what
this turn caused":

1. **Scope expansion rule**: a neighbor node becomes editable for this
   turn IFF a spacing/overlap/margin issue involving BOTH the edited
   node and that neighbor exists now and did NOT exist at the turn's
   baseline snapshot. Turn-introduced conflict = turn scope. Pre-existing
   crowding stays advisory and untouchable, exactly as today.
2. **Bounded surface**: accommodation edits are position nudges (and at
   most size on containers of the conflict) — never restyle, delete,
   re-order, re-stack, or content changes. Delta small relative to the
   element (cap idea: ≤ max(2×gap-token, ~10% of page dimension); pick
   after looking at real cases). Applies to pinned neighbors too — the
   nudge preserves the human's placement intent up to conflict
   resolution, and Accept-preview + single-undo remain the safety net.
3. **Composite/visual-unit expansion** (the second face of the same bug,
   visible in the screenshot: the badge pill and its label appear to be
   separate nodes now misaligned): when the tagged node is part of one
   visual unit (same group parent, or mutually-overlapping bounds),
   the unit moves together by default.
   CONFIRMED via the live scene: `badge` is an auto_layout container
   (the pill) with child `badge_text`. The e2e turn's `s(148,40)` shrank
   the FROZEN pill, and frozen children keep their baked offsets (layout
   engine off by design) — so the text stayed placed for the old 180pt
   width and overflows the pill. Two riders fall out:
   - Brief guidance (cheap): resizing a pinned/frozen container does NOT
     re-flow its children — keep it sized to its content, or adjust the
     children in the same block. (The model shrank a pill below its
     label's width for no requested reason.)
   - Critic gap: the overflowing label was accepted at conf 0.9 with 0
     issues — the visual critic should catch text escaping its
     container even when engine text-fit warnings are advisory-on-
     freehand by policy.
4. **Say it out loud**: the turn summary must name accommodation edits
   ("also nudged the YC lockup 24pt down to clear the badge") so the
   preview reviewer knows what to look at.
5. **Acceptance interaction**: issues on accommodated nodes count as
   in-scope for edit-scoped acceptance (they're turn-caused), so the
   critic can still block a bad accommodation.

## Calibration (2026-07-05, measured from run_e0bb1733's final scene — the
## user-confirmed "too close" case)

- The crowding the user flagged: badge (884,48,148,40) bottom edge flush
  against organizer/yc_mark top edge — **0pt clearance**, 7pt to the label.
- The SAME design's healthy baked gaps: eyebrow→hero **15pt**,
  hero→subtitle **7pt**, subtitle→details **0pt**, label→value 6pt.
- ⇒ **Absolute clearance cannot be the signal** — the design's own frozen
  layout contains deliberate 0pt adjacencies. The signal is
  TURN-INTRODUCED-ness (the pair was not in conflict at baseline), with a
  modest clearance threshold applied only to new adjacencies involving
  edited nodes.
- Threshold pick: **16pt** (just above the smallest deliberate
  inter-element gap observed, 15pt; sub-component pairs run 0–7pt but are
  baseline pairs anyway). Overlap (negative clearance) always flags.
- Pair rules from the same data: exclude ancestor/descendant pairs (badge
  is INSIDE header — containment ≠ conflict); roll the flagged neighbor up
  to the TOPMOST conflicting container on its lineage (organizer, not
  yc_mark) — that container is the correct nudge unit (nudging yc_mark
  alone would break the lockup, re-creating the composite bug).
- Runtime baseline: the loop must deep-copy the pre-turn scene at the same
  spot baseline_preflight is captured (input.json stores only a summary).
- Eval cases: (A) badge (884,48) vs baseline (176,1088) → conflict with
  organizer, clearance 0 [real geometry]; (B) badge overlapping footer
  note (88,948,600,28) → overlap conflict [run_8e7b9f64 iter-1 shape];
  (C) subtitle↔details 0pt NOT flagged (baseline pair, not edited);
  (D) badge to a clear spot → no conflicts; (E) badge↔header not flagged
  (ancestor).

## Where it lands

`prompts.py` (scope rule + accommodation clause), `loop.py` (scope-
expansion from turn-introduced diagnostics; surgical/cluster gate
allowlists grow the accommodated ids), tests mirroring the badge/YC
shape. Agent-quality track; NOT built yet — needs user go-ahead and an
eval pass so the bound is tuned on real cases, not invented.
