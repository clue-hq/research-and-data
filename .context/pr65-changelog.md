## Summary

Brings the accumulated design, research, and platform integration work on `design/account-binding` into `integration/design-improvement`. The comparison spans **1,631 changed files** and includes the previously merged research-streaming, Settings, artifacts library, composer tagging, and design-agent work, alongside persistent design sessions and the revised exit judge.

## Changelog

### Design sessions and conversation routing

- Give each design document one persistent session: a continued LangGraph thread, shared workspace folder, and per-turn subfolders preserve context across design iterations.
- Resume retried runs, queue another thread targeting the same document, and reload the current document before a turn with a bounded note describing intervening edits.
- Sync session files and conversation history to blob storage, restore them on a fresh worker, and remove them through the existing erasure path.
- Record provider reasoning in run traces; keep direct editor turns on their existing per-run lifecycle.
- Replace the exit judge's intent categories with three engine actions: close the session, hand the message back to the strategy agent, and record acceptance of the current artifact.
- Show the judge the bound artifact and tagged references, preserve its reasoning in the handoff/journal, and default to continuing when its output is malformed.

### Scene editor and creative generation

- Add inline rich-text editing, range formatting, improved typography controls, text bounds, selection behavior, and page-first canvas positioning.
- Add copy, cut, paste, and duplicate for scene content, including asset transfer between documents and external image/text ingestion.
- Stream checkpoints and scene operations into the canvas, support late joining, and lock conflicting human edits while a design run is active.
- Add image replacement from uploads or the workspace asset library and improve generated-image hydration and previews.
- Expand reference-led creative generation into eighteen discoverable scene skill families, including account adaptation, with reference inspection, artwork variants, and image-provider receipt handling.

### Websites, publishing, and brand assets

- Add multipage website routes, per-page publishing records, route-aware public rendering, internal-link rewriting, and static-site ZIP export.
- Wire the frontend Publish action to the real backend response and derive stable workspace handles for published addresses.
- Add numbered web annotations and constrained inline text edits inside cloned sections; improve clone inspection and section naming.
- Add vendor-first logo families with a durable workspace/domain cache and ladder fallback.
- Decode ingested WOFF/WOFF2 fonts to engine-compatible font files and re-encode exported web fonts; improve font previews and brand-asset inspection.

### Research, onboarding, and agent workspaces

- Verify discovery candidates as results arrive with bounded concurrency, durable progress counters, and automatic opening/refreshing of the Target accounts tab.
- Add staged research progress cards and reads for project accounts, discovery results, account research, and claims.
- Page and spill large reads, repair read-contract validation, and preserve a thread's scratch workspace across turns.
- Mount brand and project libraries, pin their context, and support versioned ICP, persona, and plan documents through ordinary file authoring.
- Add the Head of ABM operating manual and document-authoring skills.
- Make onboarding v2 the default path, align setup progress with the actual ingestion run, and add version-checked Markdown editing for brand context.

### Gallery, composer, and application shell

- Integrate a workspace-wide artifacts library with project filters/grouping, sorting, previews, saved/last-viewed marks, rename/archive, and ad/web exports.
- Open project documents and artifacts in their corresponding tabs, including links from the library.
- Add composer tagging for files, microsites, and accounts with typed reference validation, version pinning, stale-reference refusal, and transcript chips.
- Add canonical workspace display names, membership-based switching, optional company naming during onboarding, and a dry-run-first legacy-name backfill.
- Improve chat scrolling, project/chat naming, account logos, and brand-asset previews.

### Settings and workspace administration

- Integrate profile settings, workspace administration, membership/invitation flows, and Research fields backed by the live registry.
- Preserve custom research-source access and enforce settings authority at the backend seam.
- Improve narrow-screen Settings navigation; retain the documented placeholder status of unfinished settings surfaces.

### Spend, tracing, and provider incidents

- Introduce shared provider-call accounting and a workspace-scoped cost report/API covering provider, model, job, and project spend.
- Move onboarding and other provider receipts onto Postgres ledgers and include design operations and design model calls.
- Install shared OpenTelemetry, Sentry, and Langfuse instrumentation across API/worker roots, with run/entity correlation, priced generations, tool observations, and guardrail events.
- Add durable provider incident classification, opening/counting/recovery, Sentry reporting, and inline explanations on failed chat, research, and overview surfaces.
- Fix queued design-job envelope parsing when trace context is present.

### Schema, configuration, and documentation

- Include migrations and merge revisions for publishing, design events/cache/handles, artifact marks/archive state, project documents, research progress, settings, tagging, incidents, and telemetry.
- Update environment examples, API contracts, operational runbooks, regression tests, design specifications, and implementation records.
- Include the approved custom-domain publishing design as **documentation only**; this PR does not establish that the custom-domain rollout is implemented or live.

## Validation and remaining acceptance

- **Passed during PR preparation:** 40 tests across `test_exit_judgment_golden.py`, `test_design_sessions.py`, and `test_p37_exit_judge_unit.py`.
- **Previously recorded for session continuity:** platform lint/format, mypy, import boundaries, 433 no-DB runtime/purger tests, and DB/design-API groups of 106, 74, and 66 tests passed; see `_memory/2026-09-18-design-session-continuity.md`.
- **Not rerun during PR preparation:** the full combined branch suite, migration smoke, and frontend build gate.
- **Still outstanding:** session-continuity live acceptance, retry/redrive double-apply and live erasure proofs, plus the five design spend/tracing live proofs recorded in `_memory/2026-09-18-lane3-slice5-design-subsystem.md`.
- Local `.context` attachments and drafts are excluded from the PR.
