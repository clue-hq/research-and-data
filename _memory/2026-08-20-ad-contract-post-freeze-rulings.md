# 2026-08-20 — Ad-inspector contract: post-freeze founder rulings (amendments 1–3)

Session scope: fold the founder's three follow-up answers (after the contract froze at
`94f398c4`) into `docs/specs/ad-editor-integration/ad-inspector-mapping-contract.md` and the
plan `docs/superpowers/plans/2026-08-19-ad-editor-integration.md`.

## Rulings recorded

1. **Interpretation flag resolved** ("yes both only you have to remove"): both removals stand —
   the two Link-to sections removed AND the button schema hidden in v1. No contract text
   changed; recorded as amendment 1.
2. **Merged multi-select panel → OUT of v1** (amendment 2). Founder made it conditional:
   "see if it's a huge effort — then keep it out of scope for now." Effort assessed as large:
   the lifted inspector (`apps/frontend/src/features/chat-shell/components/image-inspector.tsx`
   and `ad-dummy-inspectors.tsx`) is per-kind schema components with individually bound
   controls; a merged panel needs (a) net-new design existing in neither dummy nor MVP editor,
   (b) "Mixed" presentation + edit semantics per control kind, (c) one edit fanning out to N
   node patches in a single editQueue CAS batch under per-node lock/token-detach rules.
   → v1 = first-selected element's schema; Arrange acts on whole selection. §1.8 rewritten,
   §6 item 4 removed from the active mockup queue, added to §7 future work.
3. **D7–D10 closed as recommended** (amendment 3): D7 drop Konva fallback from the lift;
   D8 asset/font bytes via narrow headerless BFF passthrough; D9 stamp-mismatch = loud banner +
   read-only canvas; D10 CAS conflict = web-style reload message. Banner/message *wording*
   remains §6 mockup-gated. Interpretation note: the founder approved the pre-build three-item list
   ("these three things to do sound good") which contained the standing D7–D10 recommendations;
   I recorded them as ratified and flagged the interpretation in my reply so the founder can
   veto — same pattern as the earlier button-schema flag.

## State after this session

- Contract: v1 RATIFIED + amendments 1–3 (2026-08-20). §6 mockup queue is now 5 items:
  selection handles, brand-palette-departure note, crop focal dot, export print-extras
  (browser demo), engine-forced banner wording.
- Plan §5 register: all twelve decisions closed (status note added above the table).
- Still pending before the AD0 verbatim lift can pin: the co-founder must commit/push the
  23-file dummy delta (contract header has the blank hash slot).
- AD0 and AD1 are unblocked and can start in parallel on founder go.

## Follow-ups

- If the founder vetoes the D7–D10 interpretation, revert amendment 3 + the plan-register
  RULED markers.
- Fill the dummy-delta commit hash into the contract header when the co-founder pushes.
