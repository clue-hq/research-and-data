# AD4.D (Lane D — export binding) partial: D1–D3 complete, paused before D4 (2026-08-22)

Worktree `.claude/worktrees/ad4d-lane`, branch `ad4d-export-binding` off the AD4.R tip
`c22f3ef9` (base attested: 1754/1754 — a fresh worktree first shows 1738; the 16-test delta is the
wasm-gated tests, fixed by copying the built `lumen_wasm` artifacts from the colombo checkout into
`subsystems/clue-design/apps/editor/public/wasm/`). Regime: fresh Opus implementer per slice, Opus
review per diff, scoped Opus re-review per fix round, base attestation on every dispatch. Ledger
with every ruling: `.superpowers/sdd/2026-08-20-ad-editor-integration-execution-plan/progress.md`
(gitignored — this note + git history are the durable record).

## Shipped (5 code commits, all local, nothing pushed)

- **D1** `b0c20dbf` — pure `adapter/scene-export.ts`: `sceneExportProfile` (ad_png raster
  {scale, dpi:96}; ad_svg/ad_pdf raster:null, embed_fonts:true; pdf_intent "preview" on PDF;
  include_marks:false explicit) + `exportFilename` (pinned sanitize contract). Review clean.
- **D2** `0e3d28af` + fix `db1ec69e` — `hooks/use-scene-export.ts` download leg: listener on the
  existing `clue:artifact-export-request` event (parse guard refuses non-ad kinds and non-PNG/SVG/PDF
  formats), runner = extracted `createApiExportRunner` (persist_preflight:false verified pinned
  upstream), upstream-mirrored data_url download (`exportArtifactActions.ts` mechanics), status
  stamped-and-derived per document, threaded as optional props session → both surfaces →
  ArtifactStage → ArtifactHeader → ImageExportMenu (`exportStatus ?? controller.statusMessage`).
  Fix round: listener arms unconditionally (pre-load "No document to export" refusal live),
  in-flight flag inside try/finally.
- **D3** `ed39d34c` + `14d04aa0` + fix `e29940c8` — preview region: pure (format,scale) cache
  anchored on SCENE OBJECT IDENTITY (never serves a superseded scene; shared `previewAnchorsMatch`
  used by lookup/store/in-flight so they cannot disagree), anchored generational in-flight registry
  (a doomed export cannot swallow the next request nor retire the live generation's key),
  `previewRenderMode` → img for image/*, **iframe for PDF** (upstream `ExportPreviewSurface.tsx:64-77`
  mirrored — the engine returns application/pdf data URLs), one §1.11-cited CSS rule
  (`.imageExportPreview > div img, iframe`). Suite **1801/1801**; lint 0 errors; tsc baseline 84 held.

## Key rulings (full list + costs in the ledger)

R-D3 export is a read, never G-H turn-gated; R-D4 results ride props, no new window events;
R-D10 the sharing-menu `{PDF, kind:"ad"}` shape is UI-unreachable (defensive parse kept);
R-D13 "document version changed" ⇒ scene object identity (conservative); R-D14 pending/failed
preview = the designed empty region, failures speak only through the aria-live status;
R-D16 PDF previews via iframe (AD4.A adopt-upstream precedent); R-D17 write-while-preview-open
blanks until reopen (plan-mandated deps — founder disclosure item).

## Paused before D4 (founder order). Resume checklist

D4 = plan Steps 4+5: verify G-E transparency checkbox + G-F print extras still absent; browser
proof (PNG@2x/SVG/PDF downloads open; preview walks incl. the PDF-iframe visual verdict at ~128px
and the blank-until-reopen walk; document version UNCHANGED after exports — persist_preflight
proof; status-line honesty; BOTH routes); frontend gate + root `make check`; close-out. Stack notes:
this worktree has NO `.env.local` (copy from the main bangalore checkout); colombo's session used
:3033/:8032/:8010; the fleet turn-drain is broken platform-wide (irrelevant to export proofs).
Deferred minors for the final whole-branch review are itemized in the ledger (scale-multiplier
parallel array; preview-leg tests are browser-only; cache retention across document switch;
scrub-cost no-debounce; PDF iframe fills not letterboxes; pre-load refusal evaporation window).

---

## Close-out — D4 complete, Lane D DONE (2026-08-22)

Branch `ad4d-export-binding`, code range `c22f3ef9..e02b8532` (8 code commits + docs), all local,
nothing pushed. Suite **1805/1805**; lint 0 errors; build green; tsc 84-line baseline; root
`make check` at exactly the five documented pre-existing reds (3× pilot_budget, 1×
unified_agent_gate_migration, 1× o3_account_deep) — zero backend files in the lane.

**D4 verification.** G-E (transparency) and G-F (print extras) verified held: comments only, no
live controls, no JPEG. Browser proof on BOTH routes against the live stack (:3030 serving this
worktree): three-format UI downloads with honest aria-live status and byte-identity to the
D1-profile server exports (PNG@2x 375,801 B = 2400×2400 RGBA; SVG 61,800 B with embedded Inter
@font-face; PDF 47,166 B v1.4 %PDF..%%EOF); preview renders the real ad letterboxed in the
designed region; scale 3x re-exports / back-to-2x cache-hits; ⌘Z under the open menu blanked the
preview honestly (and proved identity-anchoring — the undone op was same-value); reopen → fresh
render; **no export or preview ever bumped the document version** (619 held across all of them).

**Final whole-branch review found the lane's one real Critical** (invisible to per-task reviews):
both export legs raced the edit queue's persist — the server renders the PERSISTED document while
the optimistic scene leads by one round-trip; a download could deliver a pre-edit file announced
as exported, and the preview could cache that stale render under the post-edit anchor. Partly a
plan defect (Step 2 mandates the documentId branch). Fixed under ruling R-D19 (`e02b8532`):
`awaitWritesSettled` (the queue's `idle()`, promoted from AD3.3's inline drain) awaited on both
legs before `runExport`; no timeout by verified design (the chain always settles — a timeout
would resume mid-persist and re-open the race). Scoped re-review clean; the gated path then
browser-proven live: edit → immediate export → 260,208 B = the settled post-edit server render
(pre-edit was 260,101 B).

**Benign incident:** the founder was invited to test :3030 mid-lane and wrote to the seeded doc
during the re-walk (headline token picks, an X commit); my restore was correctly CAS-refused in
that window. Restored via server undo to the audited baseline hash `b225d5bc…` (corner 32/32/96/32,
headline `$text.inverse`) at v643 — values node-identical, history append-only as designed.

**Founder items (none block merge):** (1) the PDF preview iframe needs one real-browser glance —
headless Chromium ships no PDF viewer, the iframe src is verified correct, upstream ships the same
mechanism; fallback = suppress PDF preview (one line). (2) The dummy's caption pill ("PNG preview")
overlays the real render — kept per R-D14; relabel/move is founder copy. (3) A write while the
preview is open blanks it until reopen (R-D17, plan-mandated deps); the generation-dep fix is
costed and small. (4) Scale scrubbing fires one real export per new key (4x = 23 MP) — debounce is
one line if wanted. Deferred minors are itemized in the lane ledger section of the execution
plan's SDD workspace (deleted at close; this note + git history are the record): stale
preview-failure status outliving the closed menu; downloadDataUrl's unconditional true; dead
iframe object-fit + no sandbox (defense-in-depth candidate); dot-leading filename titles;
preview cache retention across document switch; one-frame caption/format mismatch.

**Rulings register (R-D1a..R-D21) — the full list with costs-if-wrong lived in the ledger and is
summarized in the close-out session message.** Key ones: R-D3 export is a read, never G-H
turn-gated; R-D13 version-changed ⇒ scene-object identity; R-D16 PDF preview via iframe
(upstream's mechanism, AD4.A precedent); R-D19 write-quiescence gating (supersedes nothing in the
plan — it closes the plan's own unreconciled race).

**Merge coordination:** zero file overlap with Lane B (adapter/panel) — Lane D's scene-apply/
scene-hydrate are untouched; Lane C shares only `use-scene-editing-session.ts` returns consumed by
`artifact-stage.tsx` props (additive on both sides). Whichever lands second rebases trivially.

---

## Merged into the integration branch (2026-08-23)

Merge commit `14413cd1` on `integration/frontend-design-part-iv-v4` (parents: the HUG-FREEZE
close-out `bb8603a2` + Lane D tip `868307e8`), local only, nothing pushed. Two real conflicts,
both additive-in-the-same-slot, resolved by keeping both sides:

- `use-scene-manual-edits.ts` — Lane B/C-9's `applyEdit` + `persistAppliedOps` alongside Lane D's
  `awaitWritesSettled` (interface + implementation). Lane D's copy of the old `runHistory` doc
  header was superseded by HEAD's generalized `runDocumentStep` header (the function Lane D's
  drain comment references still performs the same inline drain). `QueueHandle` shape
  (`.documentId`/`.queue`) verified unchanged, so `awaitWritesSettled`'s reads hold.
- `use-scene-editing-session.ts` — the AD4.B arrange binding alongside the AD4.D `useSceneExport`
  hook; both ride the session return (verified: `arrange`, `exportPreview`, `exportStatus`,
  `requestExportPreview` all present).

Auto-merged prop threading verified by grep: export props flow session → chat-surface AND
editor-surface → artifact-stage → artifact-header → image-export-menu.

Gates: combined frontend suite **1970/1970, 0 fail, 0 skipped** (1919 on HEAD + Lane D's 51 —
exactly additive); lint 0 errors (3 pre-existing warnings); build clean; tsc baseline exactly 84
lines, none in merged files; root `make check` = exactly the five documented pre-existing reds
(3× pilot_budget, 1× unified_agent_gate_migration, 1× o3_account_deep), zero new.

Not re-proven here: a live-browser export walk on the merged tree (Lane D's own browser proofs
ran on its worktree at :3030). The R-D19 quiescence gate + Lane C's freeze transport co-exist in
`use-scene-manual-edits.ts` and the combined suite exercises both, but a manual export-after-edit
walk on :3033 is the cheap remaining confidence step. Lane D's founder items (PDF-iframe real-
browser glance, caption pill copy, preview blank-until-reopen, scale-scrub debounce) carry over
unchanged.
