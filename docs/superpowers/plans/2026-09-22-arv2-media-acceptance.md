# ARV2 media research — implementation and acceptance record

**Date:** 2026-09-22. **Workspace:** Jerusalem v1.
**Branch:** `codex/ai-ark-committee-discovery-spec`.
**Base:** `79520ffca`; the authorized pull reported already up to date.
**Implementation commit:** `5d90cdbe3` (local only).
**Status:** offline implementation verified; authorized v3 live cohort completed with quality defects. Full acceptance remains open; see the [live comparison](2026-09-22-arv3-live-poc-comparison.md).
**Default:** AI Ark v2. Media v3 is available for explicit selection; it has not been activated.

Authority: [approved design](../specs/archive/2026-09-22-arv2-media-research-design.md),
[implementation plan](2026-09-22-arv2-media-research.md), and the activation-scoped amendment
in [ARV2 master plan](../../specs/ARV2-MASTER-PLAN.md).

## Implemented behavior

- Four shared account/person tools: discover media, resolve/read recordings, search transcripts,
  and open complete passages/quote qualifications. Exa discovery results are saved and paged;
  recorded candidates are not automatically verified people.
- Public YouTube uses native Gemini. RSS/Atom episodes, explicit publisher transcripts/captions,
  public audio/video files and supported embeds use the same evidence path. Explicit links and
  identifiers resolve identity; ambiguous recordings require selection. Apple episode IDs are
  not guessed to be RSS GUIDs/numbers. Relative links use the validated redirect destination.
- Canonical Unicode text and segments are immutable artifacts, with exact offsets, separate
  attribution/timing, loop reports and truncation flags. Source descriptions and malformed
  structured responses lacking a transcript section do not become speech. Captions retain real
  source timing; missing time stays null. ASR labels remain unverified for personal voice.
- Lexical and compatible vector indexes live in Postgres. Queries use exact cosine ranking and
  reciprocal-rank fusion, scoped before ranking. Saved search cursors pin index generations.
  Missing embeddings preserve lexical/full-passage access. Reopening evidence does not buy
  another transcription.
- Source acquisition has durable ownership, dispatch state, seconds reservations and receipts.
  Concurrent workers elect one owner; stale undispatched ownership can be reclaimed; unknown
  dispatch is not automatically repurchased. Saved upload/paid responses recover after failures.
  Empty paid output retains its seconds charge but releases the substantive-recording slot.
- Claims resolve transcript references on the server. Structuring receives source qualifications
  as context, not quotable evidence. Direct writes and remembered follow-up sources preserve
  references; invalid/unusable quotes stay annotated and unsafe. Audit reads pinned evidence,
  never buys retranscription. Repair creates a new version and marks old claims for recheck.
- Workspace reuse, job bindings, subject registration, retention, privacy tombstones and artifact
  purge propagate to canonical, raw and derived evidence. Expired evidence requires an explicit
  refresh; privacy-erased recordings cannot be refreshed. Reused evidence registers its later
  known consumer for erasure. Claim/index writes serialize with evidence availability.
- v3 retains v2 SMART company-scoped committee discovery, selected-profile handoff, independent
  email/phone enrichment and Exa-failure continuation. State/finalization report observed media
  work, unsearched discovery and gaps, including driver termination without normal finalization.

Migration: `213dea37b230`, parent `0ab01fe27c1e`, seven media tables plus artifact erasure reason,
scoped foreign keys and derived-data invalidation. Up/down/up completed on the disposable
`clue_media_test_462553b0c5` database. Exactly one Alembic head. No shared/runtime DB was migrated.

No frontend components or schema were changed. New diagnostic detail is carried by existing
claim markers and agent tool/finalization receipts; this work does not add visual quality badges.

## Offline verification

Provider responses are scripted fixtures, using the actual adapters, storage, SQL and tools.
These counts overlap; they are not additive or a live-quality measurement.

| Check | Result |
| --- | --- |
| Initial focused baseline | 239 passed |
| Consolidated core media/claims/tools/catalog/committee/launch/driver/evidence/settings run | 520 passed, 5 fixture failures out of 525 cases |
| Corrected affected media/launch/v2-v3 committee/driver suites, including new audio recovery cases | 94 passed |
| Media/parser/structuring/tools/storage/DSAR compatibility suites | 304 passed |
| Final shared parser, media and saved-response replay suite | 60 passed |
| Exa discovery reference → selected candidate → transcript → search/open → claim audit trace | 1 passed |
| Final completed-code acceptance suite (media, replay, Gemini and structuring) | 142 passed |
| Changed Python files Ruff and format | Passed |
| Dependency contracts | 28 kept, 0 broken |
| Migration up/down/up and one head | Passed |
| Historical catalog resource changes | None in account/person v1 or v2 |
| Settings/example/local parity | v2 selector and native video setting agree |

The five initial failures were test setup, not failures accepted into the implementation:
concurrency cleanup omitted alias deletion and contaminated two later global-count queries;
two legacy launch tests assumed v1 after the separately approved default had changed to v2.
Cleanup was corrected. The legacy fixture now explicitly selects v1; separate parameterized
launch, scripted-driver and full committee/channel handoff tests cover v2 and v3.

Key regression files:

- `tests/arv2/test_media_research.py`: identities, safe URL shapes, feed matches, descriptions,
  captions, redirects, ambiguous embeds, non-evidence qualifications, native request shape,
  Unicode chunks, loops/truncation and embedding dimension fallback.
- `tests/arv2/test_media_store_db.py`: actual Postgres ownership across independent connections,
  lease/CAS behavior, durable seconds, cross-job binding/reuse, transcript/claim/audit/repair/
  erasure, expiry refresh, hybrid retrieval, short/long audio and upload/paid-response recovery.
- `tests/arv2/test_committee_discovery_v2_db.py`: v2/v3 account/person launch and scripted driver,
  profile reuse, committee settlement, email/phone channels, replay and erasure.
- Existing storage, compliance, structuring, tools, launch, driver and evidence suites.

Repository-wide checks are **not fully green**, for unchanged failures outside this feature:

1. Ruff: `platform/api/clue_api/projections_app.py:18`, import ordering (`I001`).
2. Mypy: `platform/api/clue_api/design_leg_wiring.py:1627`, `Mapping` assigned to `dict`;
   canonical invocation checked 901 source files, with no media errors.
3. ARV2 quarantine test: `account_research_agent.py` imports `clue_api.langfuse_callbacks`, and
   `icp_authoring.py` imports `clue_api.project_library_refresh`. The other three guard tests pass.

The two pure shared URL/DNS safety modules used by media are narrowly admitted and documented;
no additional media import offender remains. The broader 28 dependency contracts pass.
No claim is made that the entire monorepo test suite or `make check` is green.

## Acceptance matrix

| Design cases | Offline evidence | Outstanding proof |
| --- | --- | --- |
| A01–A04 | Actual native request/parser, source-type refusal, captions, feeds, exact/ambiguous selection, redirects and enclosure acquisition | Configured provider availability; representative real public URLs and inaccessible cases |
| A05–A06 | Adaptive v3 guidance, discovery operation/candidate replay and honest empty states | Autonomous Nick/Cocktail Chemistry case and three unseen subjects, without seeded URLs |
| A07–A09 | Exact/hybrid retrieval, offsets/full reads, compatible dimensions, lexical fallback and version-bound cursors | Independently annotated 30-question Recall@8 ≥90%, paraphrase/start-middle-end comparison and real embedding route |
| A10–A13 | Runtime loop/truncation report, immutable repair, captions/null timing, quote qualifications, provenance and pinned audit | Saved Sanaz source and real multi-speaker/ASR accuracy assessment |
| A14–A17 | Real DB ownership/CAS, saved-upload and paid-response replay, source reuse, expiry/erasure and pinned-claim repair | Isolated live replay/erasure demonstration and production provider failure shapes |
| A18–A20 | Observed coverage, driver receipts, immutable v1/v2 resources and v3 committee/channel/privacy regressions | Frozen v2-v3 quality/cost/latency comparison and founder review |

These rows distinguish implemented contracts from measured real-world outcomes. Passing an
HTTP fixture is not proof of autonomous discovery, diarization, recall or provider compatibility.

## Implementation choices and live gates

1. The versioned first chunk recipe conservatively targets 400 UTF-8 bytes, maximum 800 and
   overlap 80. This also bounds byte-fallback tokens but is smaller than the proposed 400-token
   target. It avoids tokenizer downloads at runtime. Quality tuning must use the recall set;
   changing the recipe creates a distinct index contract, never mixes vectors in place.
2. Native-video usage and media seconds are retained; USD is explicitly marked unpriced.
   The historical dedicated-audio price is not applied to video. Reconcile actual billing
   before v3 activation.
3. Source and inferred speaker labels never automatically become evidence-backed personal voice.
   Untimed/uncertain material remains usable as appropriately qualified research evidence.
4. Explicit public source coverage is finite. No login, private/unlisted video, DRM, arbitrary
   HLS capture, native LinkedIn/X media or guessed podcast-host transformations are promised.
   A direct file needs known/probed duration; `ffprobe` is needed when source duration is absent.
5. Live tests remain founder-triggered: prepare an isolated runtime, exact source IDs/model pins,
   expected spend basis and frozen v2 comparison before calling providers. Include Probook,
   Zafran, Nick/Sanaz where currently suitable and unseen identities. Verify billed usage,
   source-backed novelty, false attribution, Recall@8, reuse and lifecycle behavior.
6. Select `CLUE_ARV2_RESEARCH_CATALOG_VERSION=v3` only for an explicitly authorized test/activation.
   The committed/default/example/local value remains `v2`. Existing jobs keep their original pins.

v3 bundle digests at review:

- Account: `49e2e476ed88dab10d854acf5b520243122c9af06fc66a53f86cbba234ea6254`.
- Person: `04fe279a71d65212978273209a1d9e1f82d85c77be00d98046184054f0869f19`.

No paid providers, shared services, deployment, push or PR were invoked. The original PoC/user
attachment directory remains untouched.

## Closing record

Implementation commit: `5d90cdbe3`. Final completed-code acceptance: **142 passed** in 4.74s.
The ownership test was additionally strengthened to use two different research jobs, each
on an independent committed database connection: **1 passed** in 0.90s. No runtime code changed after the 142-case acceptance run.

Before running this code in a test runtime, apply `alembic upgrade head` to that runtime's
explicitly selected isolated database. The implementation adds tables/columns required by the
new storage lifecycle; it does not migrate a running/shared service automatically. Keep the
v2 selector for the baseline, and explicitly select v3 only for the authorized media comparison.

## Observability follow-up — 2026-09-22

Audited against Doc R and the Lane 3 Langfuse and entity-tagging standards after the founder's
explicit observability instruction. Media continues using the existing agent callbacks,
`ProviderCaller`, artifact/ledger drain and provider-incident recorder. Postgres remains the
authority; no telemetry service, configuration flag or parallel cost ledger was added.

- Media stage spans carry workspace, project, run, job, item and operation references, and
  contain the existing provider observations. Raw/ledger links survive failure and replay.
- Structured `arv2.media.*` logs/events expose ownership decisions, stage outcomes, receipt
  links, embedding fallback, index coverage and tool outcomes including transcript reuse.
  Added logs carry identifiers/counts/codes, never transcript text, queries or source URLs.
  Ownership/receipt events observe transaction work; durable database state remains authoritative.
- Fixed an accounting defect: native-video `usd_unpriced` metadata previously became a zero-USD
  estimate. It now settles as `cost_source=unpriced`, `cost_usd=NULL`, retaining usage, model and
  provider request reference. The existing cost report counts it as unpriced. Langfuse receives
  no fabricated zero or automatic model-price estimate; the unpriced model remains metadata.
- Native Gemini `generateContent` is a generation observation. The integrated test also exposed
  an existing callback-context defect: async tool provider spans appeared under the job instead
  of under the tool. The shared Langfuse callback now runs inline, keeping OTel attach/detach in
  the caller's task. Concurrent tools and error exits restore their independent contexts.

Final affected-suite result: **145 passed in 6.73s** with scripted providers, in-memory Langfuse
export and the isolated disposable Postgres database. This includes tool → stage → generation
parentage, ledger/trace ID joins, report reconciliation, embedding failure with lexical fallback,
reuse without duplicate provider calls, logging discipline and shared-spend boundaries.
Touched Ruff/format and diff checks pass; import contracts **28 kept, 0 broken**. Full mypy
checks 902 files and retains only the previously recorded `design_leg_wiring.py:1627` failure.

Live acceptance still must verify API/worker export into the configured Langfuse project, entity
tags/retention, and real provider billing. No paid calls, shared-runtime restart, migration,
push or deployment were performed for this audit. AI Ark v2 stays default.


## Authorized live follow-up — September 22

The founder subsequently requested latest **v3 only**, compared with the saved PoC, using
Probook, Zafran and their historical people. This supersedes the fresh v2 control and unseen
subject requirement for this particular experiment; it does not claim those acceptance cases
passed. The original 13 jobs completed through real platform agents in an isolated database.
Native video/audio, embeddings, hybrid retrieval and saved-transcript reuse executed live.
Output-quality defects remain, including shared catalog contamination and low usable media
claim yield. A separate four-person on-demand recovery run completed, returning both channels for all four; original seeded-handoff outcomes remain qualified.

The [live comparison and trace report](2026-09-22-arv3-live-poc-comparison.md) records results,
exclusions, the measured bottlenecks, evidence handles and remaining gates. The earlier
"no paid providers" statement describes the implementation checkpoint above, not this later
founder-authorized test. Shared settings remain v2; no production v3 activation occurred.
