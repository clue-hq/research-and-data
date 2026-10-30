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

- T3 fee6435 exit judgment v5 (FILES block + approved rule); T9 36c10a7 design run_python
  (lumen_agent/sandbox_tool.py, leg turns only); T10 58bcb51 ATTACHMENTS_GUIDANCE in scene/web/site
  solo prompts (founder approved 2026-10-30; refused an ad-only "reference images" line).
- Final review (fresh Opus reviewer) found 1 Critical + 5 Important; fixed test-first:
  C-1 engine has no `chat_attachment` AssetSource → now `uploaded` + tag/provenance label;
  I-1 thread list stops at the turn's own message; I-2 session snapshots skip attachments/;
  I-3 DecompressionBombError → not shown; I-4 budget before fetch, per-file reads, decode off the
  platform loop; I-5 upload-bytes route sends CSP sandbox + nosniff; M-1 (re-graded) long Unicode
  filenames shortened. Report: .superpowers/sdd/.../final-review.md (scratch, gitignored).

## Live proof (trenton lane, Pallet ws_42e41df16b9b4bbd886d1c57a5be3dcb, 2026-10-30)
1. Ad session open, panel closed, two PNGs → chips kept, asset_att_* registered via real engine,
   saved ad v26 places both (run_6fc57c65…). 2. Site from a message with brief.md + PDF → hero
   exact from brief, PDF opened via run_python (page render in outputs/), CTA exact (run_941b9b85…;
   test PDF's line overflowed its page, agent kept the visible "2,400 pa" verbatim and flagged it).
3. HEIC → library PNG copy, placed in v28 (run_09eb871e…). 4. "Calculate the ROI from this Excel"
   → exit judge v5 handed back with the xlsx on the redelivery; Head of ABM read it (ROI 140% /
   171%). Sign-in: the founder signs in to Clerk in the pane (never type passwords into Clerk).

## Deferred minors (review)
M-2 design sandbox containers lack the worker-area label; M-3 outputs per-file cap 50 MB > session
snapshot 25 MB; M-4 thread images re-registered each turn (label overwrite); M-5 HoA told an
undecodable image is shown; M-6 clue-agents/clue-config not declared in the agent_runtime
pyproject; M-7 setup helpers outside the try; M-8 SVG sniff reads only 4 KB; M-10 library copies
survive chat-upload erasure (privacy sprint); M-11 two safe-filename helpers; HEIC chip thumbnail
broken in Chrome; stale test_upload_refuses_a_pdf.

## Pre-existing failures seen (not ours)
test_deepagent_harness::test_tool_surfaces_are_exactly_the_ledger (extra search_assets);
test_scene_turn_persist 4x duplicate run_id; tests/api/sandbox/test_docker_runner 1x (no
`python` on host PATH). Frontend tsc 60 errors pre-existing.
