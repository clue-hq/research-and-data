# 2026-08-22 — C-9 panel parity: panel geometry commits freeze-then-write (close-out)

Branch `integration/frontend-design-part-iv-v4`, commits `0f0b0b0b` + fix `812379df` on the Lane C
merge base `92ab9cfa` (all local). Suite 1900 → **1918/1918** (0 skipped). Regime: Opus scout
(controller-vetted at the four load-bearing claims) → Opus implementer under base attestation →
Opus review → one fix round → scoped re-review (which re-derived the bake math from
`editing.rs:1888-1938` and ran a 51-value adapter/intent differential — zero divergences) →
controller browser proof on the Story ad.

## What shipped
A panel geometry commit (`position.x/y`, `rotation`, `width`, `height`) on a solver-managed node
is never refused: `panelWriteIntent` (pure, `adapter/scene-panel-freeze.ts`, same
`isNodeFreezableOnGesture` predicate as the canvas grab) → the hook mirrors the canvas host's
freeze sequence exactly (engine `applyStructuredEdit(freezeLayoutEdit())` → persist-only →
rebuild the op from **outcome.scene** — never the stale node) → `applyOps`. Disclosed behavior
change (founder-ruled): a managed child's W/H commit now freezes first — neighbors never move
(previously taffy reflowed siblings). The fix round added: managed-child position DISPLAYS the
solved parent-relative offset (display == the space writes land in — Ruling C9-P2, the AD4.R
display/write-agreement rule), and a dead commit ("abc", width 0) never freezes. The L19
align/distribute revival is test-pinned and browser-proven (Align enables post-freeze).

## Browser proof highlights (Story ad, v12 clean-stack baseline → left at v17)
Display truth (44,40 not 0,0); abc → zero writes; one freeze envelope + one write envelope;
typed X with baked Y preserved; L19 revival live. Doc left FROZEN (headline restored to 44,40);
un-freezing was unsafe through foreign undo-stack interleaves (a second writer was live on the
doc throughout — every claim attributed via `/history`).

## Findings for the founder (with evidence)
1. **★ Freeze is NOT zero-motion for a padded hug container** (the §2e unknown, answered live):
   the freeze bakes children and fill widths but NOT the container's own `hug` dimension, and
   hug-in-Free-mode natural-sizes WITHOUT padding — the Copy row's card visibly contracted on
   first freeze (screenshots /tmp/c9-before-freeze.png / c9-after-freeze.png). Engine-owned fix
   candidate: the freeze builder bakes hug→fixed(solved) exactly as it bakes fill. This is the
   "no snaps" class the founder explicitly rejected — recommend fixing before marketers meet it.
2. **⌘Z anomaly (recorded, unattributed)**: after freeze+write, one ⌘Z left the engine mirror at
   the undone value while the server kept the old version — silent divergence, no D10 note.
   Matches the KNOWN pre-existing "editQueue rejected-batch replay is timing-dependent" deferred
   minor under foreign-writer base drift; the slice's undo tail is reviewer-verified
   byte-identical to the canvas's proven path. FOLLOW-UP: clean-room repro without foreign
   writers; if it reproduces → new Important on the AD3.3 history path.
3. **Pending founder decisions** (facts attached, deliberately not decided):
   a. Auto Layout section on a frozen container — writes are durable but visually INERT (the
      engine skips the flex solve for Free; layout_mode survives the spread) with no panel
      signal. Options: hide/disable the section on frozen containers (agent-facing per the
      founder's own framing) or leave visible.
   b. Bare-click freeze (canvas): a click with no drag writes the freeze version. The panel side
      is naturally commit-gated (only Enter/blur commits freeze). Gate the canvas on a drag
      threshold, or accept the click-freeze.
4. Residual class (deferred): locked node / locked-container child keep stored-transform display
   with no landable write (no disabled affordance on those rows); rejected-freeze server message
   dropped silently; widthMode/heightMode commits keep pre-C-9 reflow physics on managed children
   (mode changes are arguably size changes under the founder ruling — follow-up row).
