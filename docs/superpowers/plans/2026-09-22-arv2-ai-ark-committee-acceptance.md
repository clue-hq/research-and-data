# ARV2 committee discovery — local implementation and acceptance

Date: 2026-09-22. Branch: `codex/ai-ark-committee-discovery-spec`.
Upstream base: `8df27dd25` (`origin/research-streaming`); pulled before implementation and found
up to date. Planning commit: `23ed6e7c0`. The founder then authorized the
[implementation plan](2026-09-22-arv2-ai-ark-committee-discovery.md).

**Implemented locally; v2 now defaults new launches by the founder's later 2026-09-22 ruling.**
Settings, `.env.example` and local `.env` select v2. Existing processes need configuration reload;
historical jobs keep their pins. No deployment or live acceptance is claimed. No paid provider
canary was run in the implementation/default-change sessions. The following evidence uses
synthetic/scripted provider and model responses plus a disposable PostgreSQL database. It proves
contracts and recovery behavior, not live SMART relevance, phone yield or committee recall.

## What changed

The existing account agent now has a v2 tool contract: gather company/ATS/context, complete an
account deep attempt, plan buying responsibilities, discover candidates with SMART titles at the
exact company, inspect/refine/page, then select a committee by judgment. Exa failure is a durable
gap rather than a discovery blocker. Web evidence remains available for gaps and corroboration.

The server resolves candidate facts from saved provider evidence. Provider identity and LinkedIn
conflicts are refused; name-only ambiguity cannot merge people. A provider ID works without
LinkedIn. Ordered selection claims recover fanout; contact and job creation remain idempotent.

Person jobs reuse the selected profile, write deterministic professional facts first, and start
email and phone enrichment while person research continues. Email uses the saved AI Ark ID;
phone uses domain/name and requires returned ID or LinkedIn agreement. Independent failures,
empty results, identity uncertainty and unknown dispatch are distinct. A saved response can be
used after a claim-write failure without paying again. Unseeded on-demand jobs retain their
LinkedIn-bound lookup and then use the same channel path.

## Principal implementation seams

| Area | Files |
| --- | --- |
| Adapter and credit accounting | `platform/api/clue_api/arv2/ai_ark_client.py`, `ai_ark_functions.txt`; shared `clue_spend.calls` / `ledger` |
| Durable operations and privacy authority | `platform/api/clue_api/arv2/research_operations.py` |
| Role discovery, candidate references, seed reuse, channels | `platform/api/clue_api/arv2/committee_discovery.py` |
| Persona pins | `platform/api/clue_api/arv2/research_context.py` |
| Existing agent composition / recovery / fanout | ARV2 `account_research_{launch,store,driver,tools,claims,catalog}.py`, `committee_step.py` |
| Shared identity seam | `subsystems/research/clue_research/identity/provider.py` |
| Claim and privacy floor | ARV2 `claim_writer.py`, `person_compliance.py`, `catalog_seed.py` |
| Artifact retention and erasure | `libs/clue-storage/clue_storage/artifacts.py`, shared `compliance/dsar.py`, API `storage_wiring.py` |
| Catalog authority | Five new files each under `platform/agents/catalog/entity-research/arv2-{account,person}/v2/`; v1 bytes unchanged |
| Additive schema | `alembic/versions/0ab01fe27c1e_arv2_committee_discovery_references_and_.py` |

Operational tables hold identifiers, fingerprints, states and evidence references, not duplicated
raw profiles. Personal raw results expire after 30 days. All returned subjects are indexed,
including unselected people. Erasure invalidates a shared page in full, prevents resurrection,
tombstones reachable account-side selections and blocks late channel/profile writes. Source
reads enforce workspace/job/account scope, integrity, expiry and erasure. Existing claims for
other people can survive with an unavailable source reference. Maintenance purges the blob.

## Acceptance mapping

New offline tests: `tests/arv2/test_committee_discovery_v2.py`.
New database tests: `tests/arv2/test_committee_discovery_v2_db.py`.
The latter uses the real store, claim writer, identity, artifact and provider ledger paths with
scripted transports; it does not stub those state transitions.

| Design criterion | Local evidence |
| --- | --- |
| A01, A03 | Scripted account model performs deep → SMART discovery of an unknown person → provider selection. Exhausted empty deep research still reaches discovery and a receipt gap. Pre-deep discovery spends nothing. Saved deep retry selects the richer response, not simply the last attempt. |
| A02, A05 | Exact company ID/explicit domain request shape; SMART nested titles; optional-filter validation; page metadata, full profile reads, later pages and title refinement. Equivalent titles with a new rationale reuse the result. |
| A04 | Persona artifact survives a newer document; undeclared lineage is unverified; absent persona is explicit. v2 launch pins profile/manifest and run context, inherited by child composition. |
| A06 | Existing deterministic mapper gains provider artifact, subject and operation provenance. Title is an API fact; committee assignment remains synthesis. Scripted selection needs no invented source URL. |
| A07, A08 | Duplicate selection is deduplicated; no-LinkedIn profile seeds one contact/job; same-name distinct provider IDs remain distinct. Conflicting LinkedIn/provider anchors and an existing contact at another employer are refused. |
| A09 | Scripted child depth and channels buy no named search; unseeded lookup binds the job's existing LinkedIn once and shares the same enrichment implementation. |
| A10, A11 | Independently successful/empty/error channels; wrong-person phone is not claimed; phone arrays preserve provider order and deduplicate; email verdict mapping preserved. Narrow provider-phone exception does not weaken the prose sensitivity floor. |
| A12 | Found/empty/error billing fixtures; provider-reported versus inferred credits. Shared caller/raw/ledger regression tests pass. |
| A13 | Concurrent identical operation has one owner/purchase. New runtime reuses a saved result after injected claim-write failure. Expired abandoned ownership becomes unknown without repurchase. |
| A14 | Ordered live selection checkpoint, repeated settlement and enqueue, and driver recovery from a suspended job reuse one person job. Web-selected children retain their parent reference too. Erased selections are excluded from replay. |
| A15 | Foreign workspace handle, forged candidate, tampered/expired/erased artifact, unselected-person erasure of a shared page, late response after privacy stop and complete DSAR flow. Birth-date scrubbing precedes raw persistence. |
| A16 | v1 catalog/digest regression; full five-file v2 pin; replay and rollback launch tests retain historical v2 rows. |
| A17 | Registered search-assessment field; existing ARV2 claim/read/display suites. No frontend files changed. Phone storage does not assert a phone UI. |
| A18 | Single migration head, disposable full downgrade/rebuild, lint and all 28 dependency contracts. ARV2 legacy-read guards pass; the package-import guard retains its two pre-existing offenders listed below. |

## Verification record

- Broad selection: all `tests/arv2/**/test*.py` except filenames containing `live`, plus
  `tests/storage/test_artifacts_db.py`, `tests/storage/test_snapshot_wiring.py`,
  `tests/compliance/test_dsar.py`, `tests/compliance/test_dsar_snapshots.py`,
  `tests/api/test_storage_wiring.py` and `tests/spend`.
- Broad regression: **1,251 passed, 4 skipped, 2 failed**. One failure was the unchanged
  import guard below. The other was the added crash-recovery fixture retaining a terminal
  timestamp when simulating suspension; clearing that timestamp corrected the fixture.
- Final focused provider/claims/driver/registry/maintenance/v2 rerun: **212 passed**. After the
  final queue-recovery review, provider and web fanout plus existing driver/committee database
  tests: **30 passed** (including all **20 new v2 database tests**). These are overlapping suites,
  not additive test counts. No feature failure remains from the broad run.
- The broad run also verified the earlier registry-count and purge-spy expectation updates.
- Changed Python files pass Ruff lint and formatting. `git diff --check` passes.
- `lint-imports`: **28 contracts kept, 0 broken**.
- Full mypy: one unchanged baseline error at `platform/api/clue_api/design_leg_wiring.py:1627`
  (`Mapping[str, Any]` assigned to a `dict[str, Any]` variable). No new errors in changed code.
- Import guard baseline: `account_research_agent.py` imports `clue_api.langfuse_callbacks`;
  `icp_authoring.py` imports `clue_api.project_library_refresh`. Both imports exist in the starting
  commit. The guard is not relaxed by this change.
- Alembic: **one head `0ab01fe27c1e`**, extending `7c4fe6965720`. Upgrade → full downgrade to base
  → upgrade to head passed on disposable `clue_aiark_test_f36a3ed1d0`, not a shared/runtime DB.
- At implementation completion the selectors were v1. The later founder instruction changed
  Settings, `.env.example` and local `.env` to v2. No models or v1 catalog bytes changed.

Temporary detailed logs live under `/tmp/arv2-*`; this document retains their durable conclusions.
The complete repository `make check` is not claimed green: the two baseline failures above remain,
and no unrelated full frontend/design/live-provider validation was run.

## Live release gate and operation

1. Deploy additive schema and code through the normal separately authorized release. Do not
   downgrade a live database for rollback; source identity and v2 readers must remain available.
2. Explicitly initiate the plan's Probook/Zafran live canaries with current confirmed ICP/persona
   context. Use v2 in that controlled environment. Historical PoC names are not search inputs.
3. Inspect real SMART/title/filter support, exact-employer matching, pagination, email/phone
   identity and empties. Resolve the documented phone domain/name versus LinkedIn discrepancy
   in controlled calls; do not automatically try several paid identities for every person.
4. Review a current human reference set for relevance, missed roles and employment accuracy.
   Reconcile every provider attempt with the ledger; inspect channel yield, cost and latency.
5. The founder subsequently selected v2 as the default before this live review. Complete the
   review without claiming it already passed. Roll back future launches by selecting v1;
   existing jobs retain their original resource pins.

Out of scope: R4 company discovery, new web-search grants, media/transcript changes, outreach,
frontend phone presentation, automatic reruns of historical committees and production activation.
