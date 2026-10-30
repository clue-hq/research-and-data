# Design agents read what was attached (2026-10-30, branch fix/leg-turn-attachments, trenton)

Spec docs/superpowers/specs/2026-10-30-design-agent-attachments-design.md; plan
docs/superpowers/plans/2026-10-30-design-agent-attachments.md; executed Native (founder choice).
Ledger (rulings) in .superpowers/sdd/2026-10-30-design-agent-attachments/progress.md.

## Done (local commits, unpushed)
- T1 1279c55: first turn + out-of-scope hand-back copy the message's attachment rows;
  `thread_attachment_refs`, `as_validated_attachment` (clue_api.chat.attachments).
- T2 5f811dd: leg turns write attachment chips (AgentTurnRequest.attachment_refs); envelope
  `config["attachments"]` (thread files, newest per filename, `current` by upload id).
- T4 81fc492: SVG/HEIC/HEIF/AVIF/TIFF/BMP/ICO accepted; `clue_agents.attachment_images`
  (PNG copy for models; SVG never a picture); pillow-heif on clue-agents; frontend accept list.
- T5 24d99ec: `DesignPlatformReads.thread_attachments()` -> AttachedFile (bytes, viewable,
  unavailable erased|missing, safe filename).
- T6 b652c37: read-only `attachments/` in scene/site/web workspaces, rebuilt every turn,
  150 MB budget, note appended to the turn message (plain listing pending wording approval).
- T7 d3c32fb: attached images -> library (`asset_att_<sha[:32]>`, tag attached-in-chat); ad
  references = tags + this message's images (cap 4); site brand.md lists them, view_asset works.
- T8 5c3c452: sandbox moved clue_api.sandbox -> clue_agents.sandbox.
- T11 7568d46: composer has one intake (design-reference route removed).

## Waiting on founder wording approval
T3 (exit judgment v5 FILES block + paragraph), T9 (design run_python description), T10 (prompt
paragraph + turn note wording). Then T12 live proof on the trenton lane.

## Pre-existing failures seen (not ours)
test_deepagent_harness::test_tool_surfaces_are_exactly_the_ledger (extra search_assets);
test_scene_turn_persist 4x duplicate run_id; tests/api/sandbox/test_docker_runner 1x (no
`python` on host PATH). Frontend tsc 60 errors pre-existing.
