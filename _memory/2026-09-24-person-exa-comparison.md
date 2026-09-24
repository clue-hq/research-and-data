# Person Exa comparison — 2026-09-24

- Founder approved proceeding with request generation and research comparison against the saved
  person-depth PoC. Scope is one selected person, isolated research output; no production catalog,
  application database, fleet, claim or display changes.
- Added `scripts/preview_person_exa.py` with separate prepare/generate/research stages. Uses the
  configured person-model role, shared Deep Agents/model gateway, tracing, provider caller,
  redacted raw sink and metered ledger. Existing attempt directories cannot be rerun silently.
- Prepared `.artifacts/person-exa-comparison-20260924/vari-01/` from the founder-approved editorial
  person brief and retained complete account context. Draft skill supplied in full; charter is
  a readable file. Added aliases for pinned document paths referenced by the brief. Historical
  final person answers remain outside the agent filesystem, available only for comparison.
- Result count and returned-content settings copied from the saved baseline request; new text
  output and additional queries differ. Different initial source leads mean this is historical
  outcome comparison, not a controlled causal prompt-only A/B.
- Preparation passed input hashes and reference checks. Ruff initially found five long strings;
  line wraps corrected and check passed. Model-only preview launched with explicit scoped sandbox
  approval. Await result and inspect specificity before executing any Exa call.

## Completed run and findings

- Model preview completed: seven calls, 118.29 seconds, $0.22515 gateway-recorded cost. Generated
  2,846-word query plus five additional queries. All nine detailed charter sections preserved
  apart from whitespace. Skill full-body supplied; complete charter read across two reads.
- Whole pinned documents were accessible, but 80-line reads did not consume the entire product
  document or ICP. Preserve that limitation; do not claim complete context-reading acceptance.
- Initial Exa command rejected by automatic approval review for payload authorization. Founder
  explicitly approved the captured seller/account/person query, system and additional queries
  for Exa with Langfuse tracing. Same command then succeeded; no workaround or duplicate call.
- Exa: HTTP 200, 40.99 seconds, 20 returned results, $0.025 metered, no retry. Total recorded
  cost $0.25015. Request ID and trace IDs retained in local receipts. Original files unchanged.
- Comparison at `COMPARISON.md`, request audit at `REQUEST-AUDIT.md`, raw results and readable
  source collection in `live/`; baseline outside agent root. Reading copy only links numbered
  citations via ordered provider grounding; it does not rewrite the dossier or certify support.
- Mixed result: more complete professional report and some additional source leads, but no
  demonstrated new long-form/personal-interest coverage. Confirmed past/current-role attribution
  error tied to a missing heading in an earlier highlight; full fresh source had the role boundary.
  Other source detail still omitted; date/citation issues and irrelevant/duplicate results remain.
- This did not run the person agent's post-Exa source-review/follow-up stage; Codex audited sources.
  Recommended next experiment is source review on saved response, not another unreviewed purchase.

## Closing verification

- Ruff lint/format and diff checks pass. Frozen input hashes and identical captured/live request
  verified. Local duplicate-purchase refusal exercised successfully with no change to the ledger.
  Review links resolve. No application changes, DB writes, fleet workers, AI Ark calls or push.
- Preview script updated after the run only to record completion/request-response hashes in the
  manifest; the existing run's manifest received the same fields locally without a provider call.
