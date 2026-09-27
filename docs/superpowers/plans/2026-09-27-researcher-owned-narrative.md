# Researcher-owned display narrative

Status: implemented locally and verified offline. Founder authorized integration after account and Nick person-page trials. Live integrated narrative quality has not yet been measured.

## Contract and ownership

New quality launches use revision 20. Account researcher authors Overview and four independent Insights sections after its JSON dossier import. Person researcher authors its own five Contact sections after its own import. No classification model, narrative specialist or new research pass is added. Historical launch pins remain unchanged. Use existing role/model configuration, C5 execution, Langfuse tracing, durable storage and compact acknowledgements.

Frontend contract remains ResearchDisplayBlock/ResearchSection/ResearchItem/ResearchSentence: current section keys, headings, intro/body, claimIds, sendLine, contactRefs, pending/empty/restricted flags. No component, transport, endpoint or database schema change. Keep existing account facts and contact details projections. Trial account_facts/person_facts are not new application metadata.

Agents use a typed tool to save their complete narrative. Source references are the own dossier's F identifiers, separately scoped parent-account F identifiers for person context, or existing scoped claim UUIDs for provider enrichment. Deterministic code resolves references through committed import receipts. It does not rewrite, reclassify or judge prose. Unknown references and wrong page ownership return actionable feedback; uncertain findings are not blocked. Complete findings remain independently available.

Account Watch-outs feeds Insights Context only mechanically. Contact insights reads each current person-owned Why this person block with exact run/project/context bindings; the account agent must not author or overwrite it. Existing refresh/reconciliation scheduling remains, but new profiles perform their own narrative refresh from saved dossier/claims rather than delegate it. A refresh must not repeat research/import merely to write prose. Existing release of people after account import remains unchanged.

## Writing guidance

Versioned account/person skills adapt the reviewed trial: distinct section purposes, preserve public wording, maintain attribution, separate facts from hypotheses, use actual pinned seller capabilities, retain useful uncertain findings and review both directions. Correct known trial defects: a recruiting post is not a completed hire; do not invent sender viewing/reading history; apply writer instructions rather than print them; keep inference labels accurate. Preserve existing research/formation instructions except replacing narrative delegation. No target-specific rules.

## Implementation sequence and checks

1. Add scoped reference translation, typed authoring tool, compact result and input navigation; persist through existing contextual display storage.
2. Add exact-context shared-section projections; preserve API shape and read-only behavior.
3. Version prompts/skills/profiles/recipe/manifest, remove new parent narrative delegation, select revision 20 for new launches.
4. Test reference collisions, malformed/cross-subject references, page ownership, import prerequisite, replay, stored wire payloads, shared sections and historical profile pins. Run isolated Postgres and focused offline checks; no live research or paid call is needed for this integration.
5. Record limitations and commit only this change. Live integrated narrative quality remains a subsequent verification run; the saved-context trials do not certify it.

## Implemented resources

- Account: `platform/agents/catalog/research-quality/prompts/quality-account-research/v20/SYSTEM.md`, profile v20 and `skills/account-research-narrative/v1/SKILL.md`.
- Person: `platform/agents/catalog/research-quality/prompts/quality-person-research/v20-person/SYSTEM.md`, profile v20-person and `skills/person-research-narrative/v1/SKILL.md`.
- `quality_owned_narrative.py`: read_narrative_inputs / write_research_narrative, current imported-version checks, scoped finding-to-claim translation and atomic page publication with compact receipts.
- `quality_shared_narrative.py`: read-time reuse of account notes and person-authored Why this person. Original contextual blocks remain the single owners.
- recipe-v20 / launch-v4-r20 pin all resources. Earlier resources remain untouched. Both new tools use the existing governed tool invocation and tracing path, not direct out-of-band calls.

## Verification, 2026-09-27

23 focused tests passed across owned narrative, page storage, driver, person release, JSON dossier and account-resource selection. Scripted native Deep Agents completed both subject types, journaled both tools, wrote ten/five owned blocks, finalized, and replayed without another model build. Tests also cover identical F001 references belonging to different entities, unavailable citations, wrong page ownership, stale dossier versions, incomplete import, compact receipts, shared sections and rollback of Overview when a later Insights save fails.

Actual persisted Overview, Insights and Contact JSON passed the existing frontend ResearchDisplayBlockSchema (7/7/6 rendered sections including findings/shared projections). No frontend changes. Ruff and formatting passed; mypy passed all four changed narrative/runtime modules. After carrying over the exact trial section-purpose guidance, all 11 resource/reference tests passed again. Native recipe tests initially caught mismatched compatibility/tool allowlists; these were corrected before the passing run. A scripted fixture allowance mismatch was also corrected without changing production allowances.

Evidence: `.artifacts/researcher-narrative-integration-20260927/` contains test logs, actual wire payloads and the frontend validation script. Database work used only the dedicated `clue-narrative-owner-test-20260927` Postgres container. No application database writes, live research/model calls, fleet restarts or publication. Existing workers need to load this checkout before new launches use revision 20. Historical launches retain their pins.

Remaining verification: a fresh live integrated run must establish narrative quality, added wall time/cost and remote Langfuse trace completeness. Scripted execution proves the mechanics, not those live outcomes. The existing broader reconciliation lifecycle has not been redesigned.
