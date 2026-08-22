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
