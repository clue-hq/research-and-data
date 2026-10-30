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

## Review minors — resolved at the founder's ask (2026-10-30), except M-10
M-2 design sandbox containers carry the worker area label (clue_agents.worker_area.process_area_name);
M-3 + founder ruling: design outputs/ 500 MB and session snapshots carry files up to 500 MB;
M-4 images already in the library are reused (no re-ingest, label kept); M-5 an undecodable image is
not described as shown — new L7 sentence "it could not be shown to you as a picture." AWAITS FOUNDER
WORDING APPROVAL; M-6 agent_runtime pyproject declares clue-agents/config/core/design (+ guard test);
M-7 image setup fully inside the guarded step; M-8 SVG check reads the whole document; M-11 one
safe-name rule (clue_agents.attachment_names); HEIC/HEIF/TIFF chips show the icon, not a broken
thumbnail. STILL PARKED for the privacy sprint: M-10 attached images in the library survive erasure
of the chat upload. Stale pre-existing test: test_frontend_read_uploads_db::test_upload_refuses_a_pdf.
