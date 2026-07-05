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

## SHIPPED (e64957a, 2026-07-05; user go-ahead "proceed with this, before
## we start with phase-4d")

- `accommodation.py`: pure detector — `clearance()` (hypot / single-axis /
  overlap regimes), `turn_introduced_conflicts()` (baseline diff, ancestor
  exclusion, roll-up to topmost conflicting container with edited-ancestor
  guard), `CONFLICT_CLEARANCE_THRESHOLD = 16.0` per the calibration above.
- `loop.py`: baseline SCENE deep-copied beside baseline_preflight;
  `_detect_accommodation_conflicts()` after every preflight-clean draft →
  trace event + `mechanical_crowding` previous_feedback entry (critic sees
  it same-iteration, repair author next); crowded neighbors + descendants
  join edit-scoped-acceptance scope (blocker on the crowded neighbor can
  block; control: unrelated blockers still wave through); every finalize
  carries `accommodation_json` → final.json["accommodation"] =
  {detected, applied_nudges, unresolved} — applied_nudges diffs the
  CONFLICT LOG against baseline geometry, so a resolved conflict still
  announces the nudge that resolved it.
- `prompts.py`: the single carve-out to "byte-identical outside the ask"
  (position-only p() on NAMED neighbors, >=16pt, announce, skip if the
  user asked for the adjacency); frozen-container-resize rider; reviewer
  verifies mechanical conflicts ("you missed exactly this once at 0.9")
  and treats text escaping its own container as clipping even on freehand.
- Enforcement note: the surgical gate (`is_surgical_dsl`) is id-agnostic,
  so accommodation `#<neighbor> p(x,y)` lines pass mechanically; a
  position-ONLY mechanical filter per accommodated id is a recorded
  fast-follow if evals show property-drift. Cluster-gate allowlist
  expansion likewise deferred until a real drop is observed.
- Tests: 130→150 runtime (15 detector on run_e0bb1733's real geometry
  incl. all five calibration cases; 5 loop-integration scenarios incl.
  scope-expansion block + control, log-vs-latest nudge announcement,
  unseeded no-op).
- Browser e2e replays (evidence-driven hardening, three rounds):
  1. run_7ff4ac79 (.context/phase-acc/e2e/): detector + honest payload
     WORKED; but the pixel critic accepted the −0.31pt overlap at 0.9
     with a false "visible vertical space" note — a hairline overlap is
     SUB-VISUAL, pixel judgment cannot catch it. → **Forced accommodation
     round (f54cbe1)**: critic acceptance over unresolved conflicts is
     withheld ONCE for a repair round carrying the nudge instruction;
     bounded (once per run, only while an iteration remains, keep-best
     holds the accepted draft so it can never wedge).
  2. run_e3bbb02e (.context/phase-acc/e2e-round2/): forced round FIRED
     correctly and its nudge resolved the crowding (22.7pt) — but the
     model nudged using the LABEL's box (+46pt x drift), clipped
     off-artboard, critic rejected it, keep-best restored the accepted
     draft… and `unresolved` was read from the LAST detection (the
     discarded draft) → silent again. → **5bb279e**: unresolved is
     RE-MEASURED per logged pair on the scene finalize actually returns;
     the forced repair instruction now carries both nodes' page-space
     boxes + one-axis minimal-move + stay-on-artboard guidance.
  Runtime suite 130 → 152 across the feature.

## Editor-side bugs found in passing (NOT this feature; follow-ups)

- **Undo 409 after Accept**: post-accept, a system `preflight` envelope
  (30 update_node ops) lands after the accept envelope and bumps the
  revision; a then-issued client undo POSTs against the stale revision →
  409 Conflict, client pops its local stack anyway → undo/redo desync
  until reload. (run_e3bbb02e session, evidence in e2e-round2 report.)
- Proposal card surfaces the DISCARDED draft's critique as an Advisory
  (iteration 3's "organizer clipped" shown although ops_valid_through=2).

## Over-engineering audit (user asked; honest answer)

Every mechanism traces to a specific live failure — nothing speculative
shipped: calibration killed the naive threshold; replay 1 forced the
forced-round; replay 2 forced the re-measurement. Explicitly DEFERRED
until evidence demands them: mechanical position-only filter per
accommodated id, numeric nudge caps, cluster-gate allowlist expansion,
composite auto-unit moves. The honest structural smell: accommodation is
a PARALLEL quality channel beside preflight/critic (5 pieces of per-turn
state). If it grows, the consolidation is known: make turn-introduced
crowding a first-class preflight diagnostic (rides the existing gate/
repair machinery; needs baseline geometry engine-side), and delete the
forced round if evals show the boxed-numbers critic hint alone suffices.
