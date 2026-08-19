# Brand-kit onboarding — Slice 4 manual trigger and approval (2026-08-18)

Branch `feature/brandkit-onboarding-integration`. Local commits only; never pushed.

## Frozen founder decisions

- Option A: status chip + secondary Re-extract + primary Approve in the header action row, before
  existing view controls. Approved hides Approve, not Re-extract.
- Colors/Typography empties are job-aware while ingestion runs, minimal otherwise.
- Failed automatic ingestion never auto-refires; manual Re-extract is the only rescue.
- Each manual run targets the current kit lineage, creates a new draft, and returns to the approval
  gate. The page always reads the latest published version.

## Implementation

- Frontend keeps kit metadata separate from the frozen `BrandContextWorkspace` presentation
  schema. A pure model maps approval chips, active jobs, requests, and empty copy. Browser transport
  uses only the authenticated `/api/clue/design` BFF.
- Job state is fail-closed: `null` means unknown, so both mutations remain disabled and the read is
  retried. ANY queued/running job holds the controls; a newer terminal row cannot hide an older
  runner. Approval and extraction share one single-flight guard to prevent double posts and the
  dangerous approve-vs-new-version race.
- Existing-kit extraction sends `{url, brand_kit_id}`. `_publish_ingested_kit` publishes the next
  version through `design_publish_brand_kit_version`; the DAL inherits the lineage head's
  `brand_id` under lock. A client-supplied absent id still creates version 1 with refusal semantics.
- `ingestion_job_dto` adds only `website_url` for website jobs so a kit-less failed auto job can be
  rescued. PDF/assets request bodies remain hidden.
- `/brand-context` is explicitly dynamic. This is required because its fail-soft repository can
  otherwise swallow Next's build-time dynamic-usage signal and pre-render an empty workspace;
  `router.refresh()` must perform a real store read.

## Verification and failure found

Frontend final gate: 609/609 tests, lint, design-system build, production build. Focused backend:
3/3 brand-lineage DB tests and 3/3 re-ingest/approval/DTO API tests. Earlier full relevant design
API modules, root mypy (726 files), import-linter (26 contracts), and root ruff were green.

Authenticated browser proof on design API :8012 / platform :8032 / frontend :3032, with the design
API isolated to the per-branch Postgres :55170:

- v1 draft → explicit-kit re-extract v2 draft, identical non-null `brand_id`;
- approval POST 200 with exact body; UI/column/mirrored JSON all Approved;
- approved v2 → re-extract v3 draft; Draft chip and Approve returned; final approval passed;
- controls disabled during the active job; desktop + 390px wrap held; clean session had zero app
  console errors (Clerk dev-key warning only). Evidence is under `.context/evidence/brandkit-slice4/`.
- All verification services stopped; ports 8012/8032/3032 re-checked clear.

The first live probe used shared dev Postgres :55040 and failed with
`design_brand_kit_exists` even though this checkout sent the correct explicit kit id. Cause: the
already-running istanbul design API claimed the shared fleet task and executed its older pipeline.
Restarting this API could not prove code provenance; isolating the design DB did. For future worker
acceptance, never share a fleet DB with another live embedded worker unless both checkouts are meant
to be interchangeable.

## Accepted residual / future boundary

If an existing-lineage worker dies after publishing but before terminalizing its job, a re-offer
can create one additional draft version. No durable producing-job identity exists on the version
row, so Slice 4 leaves the residual explicit rather than inventing schema. Latest-only display and
the approval gate keep it safe. A fresh URL picker / brand selector for a workspace with neither a
kit nor prior website job remains future founder-ruling work.
