# PB-B2 — Storage: durable artifacts, evidence snapshots, DSAR reach, millicredit groundwork

**Status:** built (2026-07-21) — all six issues implemented and gate-green on `platform/b2-storage`;
awaiting the B2→B3→B1 integration merge (treaty §4). Spec ratified 2026-07-21; worktree cut from
the treaty commit `e615e81` on `platform/workspace-restructure`.
**Phase:** B (see `PB-phase-b-platform-infra-core.md` §2 — the scope treaty; this spec refines the
B2 lane only and adds no architecture)
**Authority:** harness doc REQ-07 (§ Design/Acceptance), REQ-06 (downstream consumer), harness A7
(the eventual millicredit ledger — *not* built here), treaty §3 (shared surfaces), CLAUDE.md
migration conventions.

## Founder rulings (2026-07-21, this worktree)

1. **Claim ↔ artifact link:** an additive **nullable ref column on `claim`** (not a join table) —
   one claim derives from exactly one snapshot; existing claims stay NULL. This authorizes the
   additive `claim` migration + the matching append-only edits to the `core.Claim` model and the
   claimstore insert path (outside B2's treaty-listed surfaces; recorded here as ruled).
2. **DSAR × dedup:** **refcounted deletion.** Content-addressed keys are **workspace-scoped**
   (never dedup across tenants). On erase, the claim tombstone severs the person's link; the
   physical blob is deleted only when **zero live claims** still reference the artifact. The
   artifact *row* survives as audit (key/hash/size only — no personal content) with `erased_at`
   set when the blob is removed.
3. **Millicredit groundwork = (a) only:** a versioned rate-mapping table + a read path converting
   the M13.4 burn-down to integer millicredits. **No** ledger table now (guessing A7's shape wrong
   costs a migration later). Zero changes to `durable/budget.py`, `budget_event`, `cost_estimate`,
   or the `campaign_run`/`account_run` counters.
4. **S3 leg:** tested against **MinIO** (real S3 API; endpoint config covers R2/S3/MinIO). SDK:
   **aioboto3**, confined behind the S3 impl module by an import-linter contract.
5. **Snapshot boundary:** everything through the modality-adapter fetch seam (all scrape/fetch
   paths). Deterministic API resolvers (tier-1 JSON) are out of scope for B2. **Plus (founder
   addition): scrapling** as a second, credit-free `ScrapeBackend` implementation, selected via a
   `clue_config` setting (`CLUE_SCRAPE_BACKEND=firecrawl|scrapling`, default `firecrawl`).
6. **In-lane wiring:** `clue-storage` is a *lib*, so subsystem code may import its protocol and
   accept an optionally-injected backend (default `None` = no-op — the `Freshness` injection
   pattern). Composition-root (`clue_api`) injection still lands at integration, per the treaty.

## Goal & scope

Durable artifact storage so evidence stops rotting: today the raw bytes a scrape fetches exist for
one function call (`adapters/pipeline.py::_fetch_and_adapt`, between `adapter.fetch` and
`adapter.adapt`) and are then discarded — a claim's `evidence_span` is only groundable against the
*live* `source_url`, which rots. B2 stores those bytes as a content-addressed **artifact** at the
moment they exist, records it in an `artifact` table, stamps the producing artifact's key onto
every claim extracted from it, gives DSAR erasure reach into the blobs, and lays the millicredit
*read* groundwork over the cost ledger.

**Not here:** the A7 millicredit ledger (debit/credit/hold/402); signed-URL frontend serving
(presign is implemented but nothing consumes it yet); snapshotting tier-1 deterministic API
responses; re-verification flows that *read* snapshots (REQ-14, Phase C).

## Issues

### B2.1 — `libs/clue-storage`: the `StorageBackend` protocol + fs & S3 impls

- **Deliverables:** new workspace lib `clue-storage` (package `clue_storage`, layout mirrors
  `clue-spine`: `pyproject.toml`, `py.typed`, README).
  - `StorageBackend` protocol (async): `put(key, data, *, media_type) -> None` (idempotent —
    re-putting identical bytes at the same key is a no-op), `get(key) -> bytes`,
    `delete(key) -> None`, `exists(key) -> bool`, `presign(key, *, expires_in) -> str`.
  - Content addressing: `content_address(data) -> str` (sha256 hexdigest) and
    `artifact_key(workspace_id, sha256) -> str` — key layout `{workspace_id or "public"}/{sha256}`
    (workspace-scoped dedup, ruling 2; sibling of the `adapters/cache.py::content_key` precedent,
    which stays request-keyed — different job).
  - `FsStorage(root)` — files under `root/<key>`; `presign` returns a `file://` URI (documented
    placeholder until the frontend-serving phase). `S3Storage(bucket, endpoint_url, region,
    credentials)` — aioboto3, lazy-imported *only* inside `clue_storage/s3.py`.
  - `storage_from_settings(settings, secrets) -> StorageBackend` — the one selector
    (`CLUE_STORAGE_BACKEND=fs|s3`); nothing else reads storage settings.
- **Registration (treaty §3.4, append-only):** root `pyproject.toml` — ruff first-party, mypy
  files/`mypy_path`, importlinter `root_packages`, contracts: `clue_storage` imports only
  `clue_core`/`clue_db` (+ stdlib/3p); aioboto3 importable only from `clue_storage.s3`.
- **Acceptance:** the same protocol contract test-suite runs green against `FsStorage` **and**
  `S3Storage`-on-MinIO, selected by settings alone (the fs↔S3 exit gate); put→get is
  byte-identical; re-put of identical bytes creates no duplicate; presign returns a fetchable ref
  (fs: existing path; s3: URL MinIO honors).

### B2.2 — the `artifact` table + the claim ref (one migration)

- **Migration** (hash id off head `98422adaaa38`, hand-written, reversible):
  - `artifact`: `artifact_id uuid PK`, `storage_key text NOT NULL UNIQUE` (the content-addressed
    key — the natural, deterministic identity), `workspace_id text NULL` (NULL = public-footprint
    scope), `content_sha256 text NOT NULL`, `media_type text NOT NULL`, `size_bytes bigint NOT
    NULL CHECK (size_bytes >= 0)`, `source_key text NULL` (source-manifest link), `source_url
    text NULL`, `created_at timestamptz NOT NULL DEFAULT now()`, `erased_at timestamptz NULL`
    (blob physically deleted at this time; row stays as audit — ruling 2). REQ-07's column list
    verbatim, plus `erased_at`.
  - `claim.artifact_key text NULL REFERENCES artifact(storage_key)` (ruling 1). Keying the FK on
    `storage_key` (not the uuid) makes the stamp **deterministic from the bytes** — the sync
    pipeline can compute it before any DB write, and content-hash dedup can never orphan a stamp
    (no id-remap problem).
- **DAL** (in `clue_storage.artifacts` — the lib owns its table): `record_artifact(conn, …)`
  (upsert `ON CONFLICT (storage_key) DO NOTHING` — content-addressed identity), `get_artifact`,
  `live_claim_count(conn, storage_key)` (the ruling-2 refcount: non-superseded claims referencing
  the key), `mark_erased(conn, storage_key)`.
- **Acceptance:** `db-smoke` up→down→up green; inserting a claim with an unknown `artifact_key`
  fails (FK); two identical snapshots in one workspace yield one `artifact` row; the same bytes in
  two workspaces yield two rows (tenant-scoped dedup).

### B2.3 — evidence-snapshot wiring at fetch time

- **The seam problem:** `run_chain` (fetch→adapt→extract→materialize) is **sync**; storage and the
  `artifact` row are async. Solution — the `ArtifactCache` pattern: a sync, caller-owned
  **`SnapshotSink`** (`clue_storage.snapshot`) that `capture(raw, *, workspace_id, source_key)`s
  the fetched `RawArtifact` in memory and returns its deterministic `storage_key`; the async
  caller later `flush_snapshots(conn, storage, sink)`es — `storage.put` + `record_artifact` for
  each capture — **before** inserting the claims that reference the keys (FK order).
- **Wiring (all additive params, default `None` = exactly today's behavior):**
  - `run_chain`/`run_pipeline` gain `snapshots: SnapshotSink | None`; `_fetch_and_adapt` captures
    after `adapter.fetch` and returns the key; `_materialize` stamps `artifact_key` on every
    claim from that fetch.
  - `CachedArtifact` gains `artifact_key: str | None` (append-only) so a cache *hit* re-stamps
    the original snapshot's key instead of losing the ref.
  - `run_pipeline(persist=True)` flushes the sink before `_persist`.
  - Waterfall path: `resolve_field` gains `snapshots`/`storage` (optional); the firecrawl-style
    resolver holds the same sink instance (injected at construction, like its `extractor`), and
    the waterfall flushes captures before its `insert_claim` loop. Flush is idempotent
    (content-addressed put + upsert), so repeated flushes are safe.
  - `core.Claim` gains `artifact_key: str | None = None` (append-only contract-delta);
    `claimstore.insert_claim` writes it (ruling 1).
- **Acceptance (the snapshot round-trip exit gate):** store → content-address → retrieve
  byte-identical → the claim's `artifact_key` resolves to the artifact row and the blob; re-running
  the (pure) adapt stage over the retrieved snapshot re-derives a normalized text containing the
  claim's `evidence_span` — evidence resolves **offline**, no live URL. A cache-hit claim carries
  the same `artifact_key` as the original fetch.

### B2.4 — scrapling as a second `ScrapeBackend` (founder addition)

- The seam already exists: `adapters/seams.py::ScrapeBackend` ("Firecrawl → any crawler is a
  config swap"). Add `ScraplingScrapeBackend` beside `FirecrawlScrapeBackend` in
  `adapters/concrete.py`: scrapling's `Fetcher` (lazy import, exactly the firecrawl-SDK pattern —
  Rule 4) fetches the page, HTML → markdown via `markdownify` (also lazy), returns a
  `RawArtifact(media_type="text/markdown", metadata={"backend": "scrapling"})`. No API key.
- Selection: `Settings.scrape_backend: Literal["firecrawl", "scrapling"] = "firecrawl"`
  (`CLUE_SCRAPE_BACKEND`, append-only §3.2); a `default_scrape_backend()` factory maps the setting
  → backend; `register_scrape_resolver(scraper=None)` uses it. Tests keep injecting doubles.
- **Acceptance:** with `CLUE_SCRAPE_BACKEND=scrapling` the scrape path runs through the scrapling
  backend (double-driven test on the selection + a live-shaped unit test with a fake fetcher);
  firecrawl default unchanged; neither SDK imported at module import time.

### B2.5 — the DSAR hook: erasure reaches snapshots

- Every erasure path funnels through `compliance/dsar.py::_apply_tombstone`. After the audit row +
  supersede, the hook (optional injected `StorageBackend` + conn, ruling 6): read the erased
  claim's `artifact_key`; if set, `live_claim_count(key)` — **zero** → `storage.delete(key)` +
  `mark_erased`; **nonzero** → blob stays (other people's live evidence), nothing else to do —
  the erased person's link is already severed by the claim tombstone (ruling 2).
- `DataSubjectRightsImpl.__init__` / `RetentionSweep.__init__` gain `storage: StorageBackend |
  None = None` (default None = today's behavior; injected at integration).
- **Acceptance (the DSAR exit gate):** erase of the *only* claim referencing a snapshot deletes
  the blob (`exists` → False) and stamps `erased_at`; erase when a second live claim references
  the same artifact leaves the blob; erasing that second claim then deletes it (the Jane/Raj
  refcount scenario). `sweep_expired` and objection paths get the same coverage. The artifact
  row survives in both cases (audit; no personal content).

### B2.6 — millicredit groundwork (additive-only, ruling 3)

- **Migration** (may share B2.2's revision or chain after it): `millicredit_rate` —
  `rate_id uuid PK`, `workspace_id text NULL` (NULL = global default), `version int NOT NULL`,
  `cents_per_credit numeric NOT NULL CHECK (cents_per_credit > 0)`, `created_at timestamptz`;
  `UNIQUE (workspace_id, version) NULLS NOT DISTINCT` (the M9.1 NULL-slot gap, not repeated) with
  a deterministic loader tie-break.
- **Read path** — new file `review/millicredits.py` (additive; `review/` is nobody else's Phase-B
  lane): `load_millicredit_rate(conn, workspace_id)` (workspace override → global default),
  `to_millicredits(cents, rate) -> int` (Decimal in, integer millicredits out — 1 credit =
  `cents_per_credit` cents = 1000 millicredits; round half-up, exact Decimal arithmetic), and
  `millicredit_burn_down(conn, campaign_run_id, …)` wrapping the existing M13.4
  `CostBurnDown` reader — a *view over* `spent_cents`, touching none of the ledger machinery.
- **Acceptance:** conversion is exact/deterministic (Decimal, no float); workspace override beats
  global; duplicate `(NULL, version)` rows impossible (constraint test); reading burn-down in
  millicredits equals the cents burn-down converted; zero diffs under `durable/`.

## Shared-surface manifest (treaty §3)

- **Alembic head:** 1–2 new hash-id migrations off `98422adaaa38`. Expected to be one of three
  heads at integration; integrator merges.
- **`clue_config/settings.py`:** append `storage_backend`, `storage_fs_root`, `storage_s3_bucket`,
  `storage_s3_endpoint_url`, `storage_s3_region`, `scrape_backend`. `secrets.py`: append
  `storage_s3_access_key_id`, `storage_s3_secret_access_key` (SecretStr).
- **`clue_core`:** no new enums. Append-only contract-delta: `Claim.artifact_key` (B2.3).
- **Root `pyproject.toml` / composition root:** `clue-storage` registration (B2.1);
  **no `clue_api` edits** — integrator wires storage injection (DSAR + pipeline) at integration.
- **Ruled scope extensions beyond the treaty's owned list** (all additive, no other lane touches
  them): `claim` migration column + `core.Claim` field + `claimstore` insert path (ruling 1);
  `adapters/{seams,concrete,pipeline}.py` + `resolvers/firecrawl` additive params (rulings 5, 6);
  new file `review/millicredits.py` (ruling 3).

## Exit gates (= treaty B2 + rulings)

1. fs ↔ S3 swap via settings alone — the same storage suite green under both (MinIO for S3).
2. Snapshot round-trip: store → content-address → retrieve byte-identical → provenance carries
   the artifact ref → evidence span resolves offline from the snapshot.
3. DSAR erase removes the snapshot (refcounted; row survives as audit).
4. `make db-smoke` reversible; exactly one head on this branch.
5. Standing gates (treaty §5): `make check` green; full DB suite green + rerun-idempotent;
   scripts/01–06 stub-mode regression unchanged; `_memory/` session note.
