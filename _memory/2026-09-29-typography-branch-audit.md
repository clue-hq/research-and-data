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
