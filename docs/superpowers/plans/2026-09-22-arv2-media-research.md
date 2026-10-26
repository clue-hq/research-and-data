# ARV2 media research: implementation plan

**Status:** approved by founder 2026-09-22; offline implementation completed and verified; see the acceptance record. Live acceptance and activation remain separate.
**Design:** [media discovery and reusable transcript research](../specs/archive/2026-09-22-arv2-media-research-design.md).
**Base inspected:** `99253e5d4`; resolve the current branch/head again before implementation.
**Founder direction:** AI Ark v2 is the default account/person flow. Build media research on
that flow only; preserve old job pins for replay. The separate default-selector change is
authorized now. The founder authorized this plan's offline runtime/media implementation on 2026-09-22.

## 1. Deliverable

Connect adaptive recording discovery, actual public media ingestion, reusable transcript
search and evidence-aware claims inside the existing account/person agents. Ship one coherent
feature: wiring embeddings without passage tools, or adding YouTube transcription without
source reuse and attribution, does not satisfy the outcome.

The dependency order is contracts → storage/lifecycle → acquisition → retrieval → claims →
agent integration → regression → explicit live acceptance. Each checkpoint is a local commit;
no push or deployment is implied. Work in the named checkout on a feature branch. Preserve
the user's `.context/attachments/V4drO2/` and original PoC artifacts.

## 2. Work sequence

### Step 1 — Reconcile reviewed contracts and establish a baseline

**Read:** design §§1–14; ARV2 master plan; R2/R3 stop/identity rulings; AI Ark v2 design and
acceptance report; Doc A; storage/identity/DSAR and catalog authoring conventions.

- [x] Record the founder's review changes to the proposed scope, native-video route, reuse,
  retention, item accounting, attribution states and acceptance targets in the design.
- [x] Inspect branch/worktree changes, fetch/pull the authorized upstream without overwriting
  local work, and record the exact implementation base. Do not assume this planning snapshot
  is still current. Preserve default v2 and the approved email/phone/failure behavior.
- [x] Capture focused baseline tests and pre-existing failures. The preceding audit's 208 media/
  tool tests passed. The AI Ark implementation separately recorded an existing import-guard
  failure and a design-lane mypy failure; verify whether they still exist rather than copy status.
- [x] Enumerate v2 equality checks in launch, driver, tools, claims, committee fanout, privacy
  and SQL predicates. Define an explicit catalog-capability map before introducing v3.
- [x] Define typed contracts for media candidates, versions, references, passage bounds,
  quality, speaker/timing, index contracts and attempt outcomes. Keep source facts separate
  from project questions/interpretations.
- [x] Add an activation-scoped master-plan amendment naming precisely the old media rules
  superseded; preserve historical v1/v2 resource bytes and current AI Ark decisions.

**Exit:** one reviewed contract set and known baseline; no agent activation or provider spend.

### Step 2 — Durable media identity, transcript versions and replay

**Proposed new modules:** `platform/api/clue_api/arv2/media_types.py`, `media_store.py`,
`media_operations.py`. Reuse shared operation helpers rather than duplicate them.
**Modify:** `research_operations.py`, artifact/identity lifecycle seams where necessary.
**Migration:** generate a random revision from the then-current Alembic head; never reuse a
planned hash or the inspected `0ab01fe27c1e` as an assumed current head.

- [x] Implement design §8's recording, verified alias, immutable transcript, index/passages,
  per-job attempts and shared operation records with scoped foreign keys and named CHECKs.
- [x] Persist canonical text and segment metadata through the existing content-addressed
  artifact store; enforce offset/hash/canonicalization invariants and availability checks.
- [x] Implement source-level acquisition ownership, leases, stage receipts and consumer reuse.
  Keep the AI Ark job-scoped operation boundary intact. Journal unknown dispatch without
  automatic repurchase. Persist before returning any reusable reference.
- [x] Make media-second and person-item reservations durable, including crash/restart and
  known-failure release. Empty pages/failed resolution do not consume completed-item slots.
- [x] Implement version repair/current-generation switching and dependent-claim lookup.
- [x] Integrate subject registration, 30-day proposed retention, expiry, erasure tombstones,
  two-phase purge, late-response handling and derived-index/cache cleanup. No privacy-erased
  item can be resurrected through another URL alias or another job.

**Tests:** new `test_media_store_db.py`, `test_media_operations_db.py`; extend existing
artifact/DSAR tests. Real isolated Postgres proves concurrent ownership and transaction/crash
boundaries. Unit doubles alone cannot establish these properties.
**Acceptance:** A14–A17 foundations. Single Alembic head and isolated up→down→up smoke.
**Checkpoint:** `feat(arv2): persist reusable media evidence and acquisition state`.

### Step 3 — Resolve public recordings and acquire actual transcripts

**Modify:** `media_feeds_client.py`, `gemini_media_client.py`, provider factory/composition.
**Proposed modules:** `media_resolution.py`, `media_acquisition.py`.

- [x] Normalize YouTube URLs/IDs and RSS episode identities; preserve verified aliases.
- [x] Resolve public episode/publisher pages via explicit feed links, metadata, supported
  Apple lookup, enclosures and embeds. Validate every redirect/derived URL through the shared
  fetch boundary; reject unsupported/private/walled routes with typed results.
- [x] Match exact episode identifiers first; support description-only guests and ambiguity
  responses. Continue alternate sources after a loaded-no-match feed or empty watch-page text.
- [x] Distinguish source transcripts from descriptions/page chrome; preserve partial/unknown
  completeness and source method. Keep page evidence without calling it speech.
- [x] Add the native public-YouTube operation and supported direct public audio/video route.
  Use the existing paid-call/raw/ledger/incident path. Add the video model setting with example/
  local parity and document the narrow native-Gemini exception. No unrelated model change.
- [x] Preserve actual duration/timing and bounded download behavior. No guessed-duration paid
  calls, implicit downloader bypass or browser-based video capture.
- [x] Call the loop detector and record truncation/empty/coverage annotations on every acquired
  transcript. Implement one explicit repair per version and save the replacement independently.
- [x] Preserve optional quote-mining verdicts/metadata; remove it as the full-transcript access
  bottleneck. Failure to mine quotes must not lose a successfully saved transcript.

**Tests:** extend offline media clients/resolution/acquisition suites using recorded fixtures;
do not execute `*_live.py` here. Test malformed feeds, MIME, redirects, namesakes and failures.
**Acceptance:** A01–A04, A10, A12–A13 offline behavior; exact-provider proofs remain Step 9.
**Checkpoint:** `feat(arv2): resolve and transcribe supported public recordings`.

### Step 4 — Build passage indexing, search and full-context reads

**Proposed module:** `media_retrieval.py`.
**Modify:** `gemini_media_client.py` embedding methods and media storage/index composition.

- [x] Implement deterministic speaker/sentence-aware chunks with exact offsets and neighboring
  segment refs. Bound tokens while preserving long-turn and multibyte text losslessly.
- [x] Extend the existing embedding adapter to accept prepared document chunks and queries.
  Record the actual model/dimension/format contract; test the dimensions fallback without
  allowing incompatible vectors in one retrieval operation. Do not duplicate a second client.
- [x] Store lexical and vector indexes in Postgres; enforce authorized source selection before
  ranking. Implement exact scoped cosine ranking and lexical/hybrid rank fusion.
- [x] Persist batch completion and replay. Missing/partial embeddings produce lexical results
  with explicit coverage; indexing failure never reacquires the recording.
- [x] Implement paged open/read, exact subspans, previous/next context and stable cursors tied
  to the immutable version/generation. Bound serialized UTF-8 receipts with cursor continuation.
- [x] Invalidate query/excerpt/index caches on expiry, erasure, version repair and contract
  changes. Different projects do not share private query text or conclusions.

**Tests:** new `test_media_retrieval.py` and DB suite; compare gold exact/paraphrased queries,
start/middle/end passages, dimension mismatch, partial batches, lexical-only operation,
forged refs and zero cross-workspace results.
**Acceptance:** A07–A09, A15, A17.
**Checkpoint:** `feat(arv2): search and open versioned transcript passages`.

### Step 5 — Carry source references through claims and audits

**Modify:** `account_research_tools.py`, `account_research_claims.py`, `structuring_client.py`,
`claim_writer.py`, `person_compliance.py`, existing annotation and evidence projection seams.

- [x] Add the discriminated transcript-reference source input. Resolve full text/subspans on
  the server; validate exact offsets, availability and ownership. Model-supplied text cannot
  upgrade a source or replace the saved transcript.
- [x] Stamp artifact/version/span/attribution/timing/quality references into claims using the
  existing claim schema and typed markers. Preserve appropriate account/contact ownership.
- [x] Keep all quote verdicts and speaker evidence in tool returns and structuring inputs.
  Never convert metadata-only identity into verified segment attribution or safe personal voice.
- [x] Change media audit dispatch to compare pinned transcript evidence, preserving current
  web checks. Record missing/superseded/unavailable references precisely without refetching audio.
- [x] Permit null timestamps; label source-provided vs model-estimated timing. Preserve
  quality annotations and lenient writes without weakening current identity/sensitivity rules.
- [x] Mark dependent claims for recheck after repair; do not silently relink historical evidence.
  Treat legacy claims without transcript refs honestly; no automatic paid backfill.

**Tests:** known-invalid quote through tool→structure→write→audit; host/guest confusion;
repair/stale citations; offset integrity; pure spoken quotes absent from episode HTML;
voice/openers use restrictions; no-cost re-audit.
**Acceptance:** A11–A13, A17.
**Checkpoint:** `fix(arv2): preserve transcript evidence and attribution through claims`.

### Step 6 — Wire tools and adaptive guidance on the v2 foundation

**Modify:** `account_research_tools.py`, `account_research_catalog.py`, launch/driver/context/
store/progress/finalization modules, Settings, and explicit capability dispatch.
**Create:** immutable `platform/agents/catalog/entity-research/arv2-{account,person}/v3/` bundles.

- [x] Register `discover_media`, `read_media`, `search_transcripts`, `open_transcript` for the
  media-enabled catalog, replacing its legacy media tool. Share implementation between account
  and person jobs. Add media state to the existing read tools.
- [x] Use Exa search/contents through existing adapters and preserve source provenance; paginate
  stored discovery results rather than invent provider pagination or repeated paid searches.
- [x] Teach primary-source work, the Exa deep attempt, contextual media planning, inspect/read/
  search/open, useful follow-ups, contradictions and honest stopping. Do not promise unsupported
  hosts/transcription or impose the side conversation's suggested two-round policy.
- [x] Keep AI Ark role discovery after the account deep attempt and person email/phone parallel
  with depth. Failed Exa still permits committee discovery. Media is not a committee quality gate.
- [x] Resolve explicit catalog capabilities so v3 retains all v2 durable operations, provider
  identities, seeds, enrichment, selection/fanout recovery and privacy checks. Test every literal
  v2 branch/predicate identified in Step 1. Unknown versions still refuse.
- [x] Record both source reuse and project-specific investigation, and surface stage-specific
  coverage/gaps through current progress/finalization outputs.
- [x] Mint and verify resource manifests, admit v3 in the selector, retain default v2 during
  implementation. Existing jobs remain bound to their original versions; no automatic migration.

**Tests:** tools/catalog/context/launch/driver/fanout suites; v1 and v2 resume fixtures; v3 account
and on-demand person jobs; negative discovery, incomplete indexing and provider-halt cases.
**Acceptance:** A05–A06 behavior contracts, A18–A20.
**Checkpoint:** `feat(arv2): add adaptive media research to account and person agents`.

### Step 7 — Backend evidence/progress compatibility

- [x] Ensure current source/evidence projections retain the canonical source URL, exact quote,
  null/qualified timestamp and quality annotations. Do not silently hide failures behind a media
  appearance count or mark a job's media coverage complete because finalization ran.
- [x] Check whether a new field requires a frontend schema change. If so, record the exact
  contract gap in the relevant `apps/frontend/docs/api-contracts/` file and implement at the
  repository adapter/schema seam only after that concrete flow is reviewed. No speculative UI.
- [x] Keep unknown/expired/erased evidence from being represented as a broken webpage or
  fabricated quote. Confirm reusable source titles/metadata do not expose another project's data.

**Exit:** backend receipts/evidence truthfully represent the new behavior; any frontend work is
explicitly scoped and separately recorded. A frontend redesign is not needed for research tools.

### Step 8 — Offline acceptance and release review

- [x] Run focused media, tools, claims, catalog, operation, launch, driver, fanout and privacy
  tests. Prove concurrency/replay/DSAR against a disposable per-branch Postgres database.
- [x] Run Ruff, mypy/import contracts, relevant API/projection suites, resource-manifest checks,
  and isolated migration up→down→up. Record baseline failures separately; do not claim full green
  from passing focused tests or skipped DB/provider tests.
- [x] Review the full diff against G01–G14 / A01–A20. Trace one recording from discovery ref to
  raw receipt, transcript, chunk, search hit, claim, audit, repair and erasure.
- [x] Write `docs/superpowers/plans/2026-09-22-arv2-media-acceptance.md` with exact commits,
  test counts, unresolved checks, and every outstanding live proof. Keep live status pending.
- [x] Update `_memory/` with choices, commands/failures, current state and remaining checks;
  commit coherent units locally. No source payloads or credentials in notes.

**Exit:** offline implementation is reviewable and default v2 remains intact; no live-quality claim.

### Step 9 — Explicit live provider and end-to-end acceptance

The founder initiates this step after reviewing implementation. Prepare the exact cases,
source IDs, expected spend basis, pinned catalogs/models and isolated runtime before requests.
Do not start a canary merely because a key exists.

- [ ] Prove configured native YouTube and direct-media routes, short/long audio behavior,
  saved transcript completeness and actual billed usage. Never infer current prices from PoC.
- [ ] Prove the OpenRouter embedding route's document/query inputs and dimensions, plus
  lexical fallback when the route is unavailable. Check real beginning/middle/end retrieval.
- [ ] Run a frozen current-v2 baseline and media-enabled comparison on the same subject/context
  set. Keep known-recording ingestion separate from autonomous discovery without supplied URLs.
- [ ] Cover Nick/Sanaz, current suitable Probook/Zafran material and unseen subjects. Record
  namesake/host/colleague exclusions, empty/inaccessible cases, runtime/allowance exhaustion,
  source-backed new findings, false attribution, latency and per-provider spend.
- [ ] Verify a second authorized job reuses a transcript with no new acquisition charge;
  perform isolated lifecycle/erasure verification without deleting shared customer evidence.
- [ ] Fill all A01–A20 evidence rows; founder reviews outcome quality and outstanding gaps.
  Only then explicitly select the media-enabled catalog for future launches.

**Exit:** live acceptance has evidence, not just passing stubs. Rollback changes only future
launch selection to v2; existing job pins, evidence history and privacy obligations survive.

## 3. Completion definition

Implementation is complete only when the integrated tool/evidence/lifecycle contracts are
implemented and their offline checks pass. Live acceptance and activation are separate states.
The feature's product acceptance is the spec's measurable research improvement with sound
identity/provenance, not a larger number of calls, media appearances, quotes or embeddings.

## Offline completion record

Runtime implementation is committed locally as `5d90cdbe3`. Evidence, baseline failures,
implementation choices, resource pins and remaining live checks are in
[the acceptance record](2026-09-22-arv2-media-acceptance.md). Step 9 remains unexecuted.
The founder clarified verification cadence during implementation: complete connected behavior
before acceptance/regression, with narrow earlier checks only for integrity, spend or lifecycle
risks. No requirement is relaxed merely to make an intermediate state green.
