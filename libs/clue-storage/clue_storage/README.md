# clue-storage

Durable, content-addressed artifact storage — the Phase B2 slice of harness REQ-07.

- `protocol.py` — the async `StorageBackend` protocol (`put/get/delete/exists/presign`),
  `content_address` (sha256 of the bytes), and `artifact_key` (`{workspace|public}/{sha256}` —
  workspace-scoped dedup, never cross-tenant).
- `fs.py` — filesystem backend (atomic writes; `presign` returns a `file://` placeholder).
- `s3.py` — S3-compatible backend (AWS S3 / R2 / MinIO — the endpoint is config). `aioboto3` is
  lazy-imported here and nowhere else (import-linter enforced); install `clue-storage[s3]`.
- `factory.py` — `storage_from_settings`: the fs ↔ S3 swap is `CLUE_STORAGE_BACKEND` alone.
- `artifacts.py` — the `artifact` table DAL (rows for stored snapshots; the DSAR refcount).
- `snapshot.py` — the sync-capture / async-flush seam the modality-adapter pipeline uses.

Spec: `docs/specs/PB-B2-storage.md`. Consumers inject a `StorageBackend`; nothing outside
`factory.py` reads the storage settings, and no caller learns which backend it holds.
