# 4c-C managed-gestures browser e2e verdict (2026-07-05, opus, 1 agent turn)

Env: editor :3002 / API :8002, engine 4b726011618f both sides. Console 0
errors / 0 warnings throughout. Doc: doc_0162396f89fa448a9623edea3c93bb44.
10/10 PASS (incl. user-requested 5b middle-child resize).

| Step | Result | Evidence |
|---|---|---|
| 1 Toggle ON → agent card → Accept | PASS | layout_managed_editing:true; `card` live stack, children [eyebrow,heading,body,cta] |
| 2 Drag-to-reorder | PASS | mid-drag: reorder-insertion-indicator line #4c8dff sw=2 above first child, dragged heading UNMOVED; release → [heading,eyebrow,body,cta], siblings re-flowed, stays stack |
| 3 Undo/redo | PASS | one ⌘Z restores order+bounds; ⌘⇧Z re-applies |
| 4a Own-slot no-op | PASS | jiggle-in-place committed NOTHING (next ⌘Z undid the reorder, proving no extra history entry) |
| 4b Outside-cancel | PASS | indicator disappears >40pt outside; release → unchanged |
| 5 Resize end child | PASS | 8 resize handles, 0 rotate; heading h hug→fixed 148; siblings re-flowed; solver-placed; ⌘Z restores |
| 5b Resize MIDDLE child | PASS | body h hug→fixed 160; sibling ABOVE re-flowed up (eyebrow y491→422, heading 474→405) and BELOW down (cta 531→600), no overlap; ⌘Z restores all |
| 6 Inspector copy | PASS | hint now: "in layout-managed mode you can also drag it on the canvas to reorder it and resize it directly" |
| 7 Default-mode regression | PASS | toggle OFF → drag: NO indicator, containers flip layout_mode→"free", node moves freely |
| 8 Reload persistence | PASS | order+bounds identical after reload; flag persisted |

Reorder: [eyebrow,heading,body,cta] → [heading,eyebrow,body,cta].
Resize boxes: heading (96,474,792,16)→(96,408,881,148); body
(96,509,792,22)→(96,440,881,160).

Notes:
- Engine scene serialization OMITS layout.layout_mode when live ("stack" is
  the default); only explicit "free" appears — detect frozen via
  layout_mode==="free", live via key-absent.
- Step-7 nuance (expected): first-gesture freeze is its own committed batch;
  one ⌘Z after the drag restores geometry but the containers stay Free (a
  second ⌘Z would unwind the freeze).
- Resize converts hug→fixed on the resized axis — human resize = fixed
  intent, consistent with drag/detach semantics.
- The scenario's agent turn ended "Repair budget reached — best
  preflight-clean draft" with 3 advisory critiques and was structurally
  correct — best-draft-wins path exercised again in passing.

Screenshots (this dir): 1-accepted, 2-indicator-middrag, 3-reordered,
4-handles, 5-resized, 5b-middle-resized, 6-inspector-hint,
7-freeze-regression, 8-reloaded (+ dbg-inspect-view, dbg-fit).
