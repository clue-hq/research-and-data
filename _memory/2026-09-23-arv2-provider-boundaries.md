# ARV2 roadmap step 2: provider responsibilities — 2026-09-23

## Scope and decisions
- Founder authorized step 2 only; pause for review before runtime brief / account charter /
  person charter changes. Raw research quality is judged by founder before claim/narrative work.
- Latest clarification supersedes earlier Exa-only company_about direction: synthesize the
  description from Exa research and company website evidence; AI Ark typed facts add context.
  Do not copy AI Ark promotional descriptions. No new verification/display gates.
- Keep typed company/person enrichment, work email, web discovery and AI Ark SMART discovery.
  Phone enrichment remains disabled from preceding commit 8e5b1c82b.

## Implementation
- Removed automatic core.company_about and contact.headline AI Ark mappings from shared mappers
  used by both older and quality research flows. Raw responses and historical claims retained.
- Added one shared runtime provider policy after legacy pinned instructions and in the quality
  project card inherited by specialists. Updated tool guidance for both discovery choices.
- Existing provider ledger, original evidence storage, profile reuse and operation replay remain
  unchanged. No source deletion, provider-call changes, migration, or new environment setting.
- Documented current boundaries in platform/api/clue_api/arv2/README.md.

## Verification and closing state
- Seven focused offline modules passed: account_research_claims, account_research_catalog,
  committee_discovery_v2, committee_discovery_v2_db, quality_provider_db, quality_runtime_db,
  quality_nomination_db. Providers/models scripted, isolated local regression DB only.
- Extended DB checks prove original promotional description is still readable while no company
  description claim is automatically mapped; employee count and replay remain correct.
- Captured all eight model inputs in parent/claim-specialist tests for recipe revisions 5/6;
  runtime provider policy survives context assembly and delegation.
- Added researched-description provenance check, reran claims module successfully (63 cases).
- Mypy passed six changed source modules. Ruff initially found one overlong tool-description
  line; split the string, then reran lint/format/diff checks.
- No paid provider calls, no fleet worker restart, no remote publication. Agent adherence and
  live research quality are not certified by scripted tests. Step 3 remains unstarted.
- Unrelated preexisting cumulative review doc, comparison artifacts, attachments and report
  compilation memory note were left untouched and excluded from this checkpoint.
