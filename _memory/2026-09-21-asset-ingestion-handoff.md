# Asset ingestion implementation handoff

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
