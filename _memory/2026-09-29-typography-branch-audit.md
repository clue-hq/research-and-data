# Typography branch audit — 2026-09-29

- User requested an exact cross-brand ingestion diagnosis and implementation plan,
  plus a new branch. Created `brand-context-fixes/typography` at pushed checkpoint
  `b0ccdbb0`, in the existing checkout. Two excluded seller-context tests remain
  unchanged/unstaged. No merge, live generation, service restart or data mutation.
- Replayed saved evidence read-only through pre-fix and current normalizers. All
  four test brands had changed typography roles. This confirms broader exposure;
  historical measurements are not current live source-site certification.
- Current offline Chromium reproduction: hidden complete heading wins over visible
  heading at desktop and mobile. Controlled mixed-family input: global heading
  family overrides a measured role's family. These persist after the prior sample
  selection fix. Network blocked; no provider calls.
- Code confirms website ingestion already forces rendering. Remaining evidence
  gaps: typography samples lack viewport/visibility/component identity, entry-page
  type samples alone feed normalization, and font readiness/actual face evidence
  is not explicitly attached by capture. Static quality-gate escalation is not
  the cause on the current forced-render website path.
- Located old type-unit rederive script. Do not apply it here: assumes historical
  pre-fix units, changes only leading/tracking, can double-convert recent samples.
- Audit and staged implementation/acceptance sequence saved in design docs as
  typography-ingestion-audit-and-plan-2026-09-29.md. Local diagnostic receipts are
  ignored under `.local-setup/typography-branch-audit-20260929/`. No source-code
  changes made; typography correction remains incomplete pending implementation.

## AWS and Google native trace follow-up

- Read-only audit followed each historical page's actual kit pin, saved ingestion
  evidence, brand tool response, component inspect/write calls, review output,
  worker logs and saved screenshots. Confirmed the shared selection defect
  reached both agents. No new generation, runtime restart or live-data write.
- AWS authored CSS carried the wrong kit typography plus a responsive override;
  original hero inspection truncated its very large CSS. Google consumed an older
  approved kit while newer ingestion remained draft, then reused prior composed
  fragments with a separate type scale. Later Google repair notes also expose
  stale fragment CSS scoping that enlarged images.
- Both original reviews lacked source comparison and finalized with warnings;
  worker success was execution success, not fidelity proof. These runs predate
  the newer typography-reference check. Actual glyph fonts were not remeasured.
- Evidence and fix implications recorded in design docs as
  aws-google-typography-trace-2026-09-29.md. Raw scoped receipts remain ignored in
  the existing typography audit directory. Only documentation changed; excluded
  seller-context tests remain untouched. No runtime tests needed for this audit.
