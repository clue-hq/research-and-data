# Account Exa briefing integration — 24 September 2026

- Founder approved review drafts and requested the next step: integration, focused offline
  checks, then an actual account-agent prompt-only preview. No Exa/full research execution.
- Added pinned governed quality recipe 7, account prompt/profile 7, dossier skill 1 and
  separately pinned provider request resources. Prior resources stay immutable. Person and
  claim/narrative profiles remain revision 6; older launches resolve their existing pins.
- New account schema exposes a complete charter, additional queries, optional same-name
  exclusions and result count (default 40). Removed the separate probes field after the first
  model preview duplicated it. Legacy/person schemas unchanged.
- Uses default highlights, one extra page link and text output. Extended client/replay parsing,
  preserved text-report retry checking and full request fingerprint/ledger behavior. Retains
  highlights as source-addressable excerpts; historical structured-report locators stay stable.
- Settings now accepts the existing governed v4 runtime. Local and example values remain v2;
  this implementation does not silently activate a different research runtime.
- Verification: 63 focused offline tests, scoped mypy (7 source files), Ruff and diff checks.
  Replayed the supplied response offline: plain report plus all 40 source results retained.
  Six existing AI Ark contact.headline test failures reproduced with HEAD's pre-change tool
  module. Left those prior provider-boundary expectations untouched.
- uv cache access failed in the sandbox; used the existing .venv binaries successfully.
- Two preserved configured-model previews under .artifacts/account-exa-step4-preview-20260924
  and account-exa-step4-preview-02-20260924. First exposed duplicate probes; second uses the
  final schema. Their reported combined model cost was about $0.1494; no research-provider
  calls or application writes. Retained context was reused with existing user authorization.
- Latest query still inherits an old six-month emphasis and a numeric ICP threshold despite
  the approved separation. It is review material, not an accepted-quality result. Additional
  queries are also rather keyword-heavy. Do not silently edit the saved model output.
- First preview's native skill index skipped governed frontmatter but the agent explicitly read
  the whole skill. Second uses explicit production-style disclosure; read 100/115 skill lines,
  omitting the end of the fictional example, and paged the ICP. Preserve this limitation.
- Langfuse root trace/observation IDs are saved; gateway model/cost records and local tool/model
  traces retained. Langfuse model-name parsing warning persists; UI attribution not certified.
- Founder source-consumption follow-up remains separate: parent should inspect original
  sources for dossier omissions, without blanket refetch or verification gates. This slice
  enables excerpt availability, not that later investigation loop.
- Next: founder reviews exact captured request and instruction drift before Exa spending.
  No production workers started, deployment, remote push or PR. Existing unrelated edits to
  briefing skill, account catalog policy and cumulative review remain outside this checkpoint.
