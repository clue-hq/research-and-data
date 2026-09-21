# Asset ingestion implementation handoff

## Transcript received; implementation resumed

- User supplied Fredericton attachment `OHcfM7/Transcript of ICP-definition
  experiments study.md`; all 832 lines were read. Missing-context blocker resolved.
- Transcript confirms this is production asset-ingestion work, separate from ICP
  PoC improvements. Preserve source evidence vs inferred usage and the pilot's
  original/preview distinction. Current request authorizes the proposed contract.
- Implementation checklist is recorded under `docs/superpowers/plans/2026-09-21-asset-context-and-bulk-upload.md`.

- User authorizes implementation of Fredericton's asset-context/bulk-upload design
  in San Diego and requires reading the attached ICP-definition transcript first.
- Workspace branch remains `asset-ingestion/improvements`; starting HEAD was
  `ab31814a2`, matching the implementation-base snapshot in the spec. The current
  workspace instruction names `origin/integration/design-improvement` as the
  comparison/publication target; do not silently change it to the spec's older target.
- Copied `docs/superpowers/specs/2026-09-21-asset-context-and-bulk-upload-design.md`
  unchanged from Fredericton and committed it locally as `8147c2335`. `cmp` and
  SHA-256 both verify identical contents. No experiment files or ancestry imported.
- Required attachment `.context/attachments/wuuRNd/Transcript of ICP-definition
  experiments study.md` is absent. Filename searches of workspace attachments
  found no copy. Asked for its existing local path; application implementation
  awaits this explicitly required context. Read Fredericton's matching September
  21 review note, but do not claim that is the conversation transcript.
- Initial source inspection confirms: `lumen_ingestion/describe.py` processes
  misses serially, caps non-logo images at 16, and uses legacy cache semantics;
  `clue_design/descriptions.py` protects entire human-authored rows. New behavior
  needs field-level overrides, versioned structured analysis and resumable work.
- Existing integration points: `lumen_api/main.py` upload, batch description read,
  governed description edit and `_ingestion_offer_payload`; durable ingestion
  executes through `lumen_api/fleet_handler.py` and `clue_design/envelopes.py`.
  Preserve the transaction/lease/tenancy boundaries when adding enrichment.
- Approved spec direction: every eligible image, default 15 concurrent calls,
  `LUMEN_INGESTION_DESCRIBE_MODEL=deepseek/deepseek-v4.1-flash`, no separate batch
  action; website/ad/agent integration precedes the bulk upload UI. Historical
  paid backfill is explicitly outside authorization.
- Closing state: specification only committed; no application/config/database
  changes, provider spend, runtime restart, tests or push. Existing unrelated
  untracked files were preserved. Root `.venv` exists; frontend `node_modules`
  and subsystem `.venv` were absent in the inspected paths. `rg` is unavailable;
  use `grep`/`find` as fallback.


Implementation in progress: structured asset context, per-field overrides, fingerprints,
continuous 15-slot analysis, durable upload/retry offers, source context and lazy agent
inventory are implemented but not yet fully validated/committed. UI bulk dialog, batch reads,
no-kit pagination and edits are wired. New migration 403bce58bdcf (single head) is on the
throwaway DB only. Migration can still change before first code commit.

Runtime isolation: clue-pg-san-diego-assets container, localhost:55170; test database
clue_san_diego_assets; realistic database clue_san_diego cloned from clue_san-salvador
on clue-pg-istanbul (55040), NOT the empty clue DB in clue-pg-san-salvador. Verified clone
counts 2622 workspaces / 916 design assets / 63 description rows; source and initial clone
head 5cac3234cfb3. Source unchanged. San Diego root .env now points at local clone.
No live provider calls or servers yet. Redis/ports/storage still need isolation verification.

Verification so far: initial 10 DAL/concurrency checks passed; 53 scene/web search tests
passed after shared discovery refactor. Frontend token build and lint passed (two existing
unused canvas helper warnings). Standalone tsc has existing project-wide test typing errors;
no new production brand-context errors. Authority tests exposed new-tool counts and duplicate
version aliases; addressing with retained @1 plus explicit @2 defaults before rerun.

Verification checkpoint: isolated Redis is now localhost:65170 and root .env is aligned.
Clean migration up/down/up passed on clue_san_diego_migration. Five image custody/preview/
analysis/override API tests passed against the real helper. Initial provider sample returned
incorrect pixels despite valid schema; retained its evidence, added strict provider-parameter
support and an observation-first prompt, then verified all four visible strings, chart and CTA
on the structured synthetic sample. Probe and revised structured sample drained to the test DB.
No historical backfill. Fixture browser exposed overlapping filters (fixed) and an existing
sidebar-projects auth-disabled error; browser upload close/reopen retained its two selected files.
Added a BFF workspace precondition so pending uploads cannot follow a changed workspace cookie.
New shared Redis capacity leases prevent independent asset jobs multiplying the configured cap.

## Closing implementation state

- Backend/worker/agent committed as 9cc82d08d; frontend/repository/BFF as 8e725c2c2.
  No pushes or PRs. Canonical copied spec still byte-identical (SHA ca329414…eaf).
- Migration applied to cloned clue_san_diego after clean up/down/up; 2622 workspaces,
  916 assets and 63 descriptions preserved. Separate test and migration DBs remain.
  No worker ran against the clone; historical blob contents were not copied with Postgres.
- Final format tests pass custody, preview, analysis, original retention, scene pixels
  and web rendering URLs for PNG/JPEG/WebP/transparent SVG/GIF (animated GIF/WebP).
  Initial web-format assertion used the wrong asset URL convention; corrected to the
  existing digest-addressed renderer contract, without changing production rendering.
- 106 frontend Brand Context tests, 23 focused frontend/BFF checks, root focused 26,
  API ingestion/ads/spend 67 + 1 skip, and agent discovery checks passed. New checks
  cover full pagination, pinned context, lazy bytes, spend totals and shared Redis slots.
- Frontend token/lint/build pass (two pre-existing unused canvas warnings). Root changed
  files pass Ruff; 28 import contracts pass. Root mypy remains blocked only by existing
  design_leg_wiring.py:1627 Mapping-to-dict assignment. Full make check not claimed.
- API/runtime test trees import different unqualified conftest modules; mixing their
  collection order produced an import collision. Run those test trees separately.
- Browser validation is fixture-mode only; authenticated end-to-end acceptance remains
  unperformed. The unrelated sidebar-projects hook errors with authentication disabled.
- Detailed verification and remaining limits: docs/superpowers/verification/2026-09-21-asset-ingestion.md.
- Fixture browser session and frontend port 3039 were stopped after verification.
  Isolated Postgres and Redis containers remain available; no backend demo stack is running.
