# Local production-chat stack

Use this runbook when the real Home/project chat surface, detached worker, and
Postgres are running together. The database and artifact backend form one
durability unit: retaining one while discarding the other leaves valid metadata
that points to bytes the platform cannot recreate.

## Required shared configuration

The API and every fleet worker must receive the same values:

```text
CLUE_DATABASE_URL=postgresql+asyncpg://.../clue_local_chat
CLUE_STORAGE_BACKEND=fs
CLUE_STORAGE_FS_ROOT=/absolute/persistent/path/clue-local-chat-artifacts
```

Use an absolute, non-disposable filesystem root for local work. Do not use a
per-process `mktemp` root with a database that will survive that process. Keep
the agent workspace separate: `CLUE_AGENT_WORKSPACE_ROOT` is ephemeral execution
space and must never be the artifact root.

At startup, both API and worker log `storage.backend.configured` with the
normalized filesystem root. Confirm those roots match before submitting a
message. In production, configure the same S3-compatible bucket/endpoint for
all processes, or use a proven shared persistent volume.

## Database cloning and browser verification

A cloned or reused chat database may be paired only with a complete copy of its
artifact root. For an isolated browser-verification stack, either:

1. clone both the database and artifact root and keep both for the test's
   lifetime; or
2. create a fresh database and a fresh root, and submit only new test data.

Never clone only Postgres and then start a worker against an empty artifact
directory. Before deleting an isolated root, stop its API and workers and drop
or retire the corresponding database so its queued tasks cannot be claimed by
a later stack.

## Missing historical bytes

If a transcript has an artifact row but the physical blob is absent, the API
returns that one message with:

```json
{
  "body": null,
  "body_unavailable_reason": "artifact_missing"
}
```

The remaining thread stays readable. A turn that needs the missing current or
historical input fails terminally with
`required_context_artifact_missing`; the model is not invoked and the next
queued turn is released. The user must resend in a new thread.

Recovery is valid only when the exact original bytes are found. Copy them under
the recorded storage key after confirming their SHA-256 equals the durable
digest. Do not reconstruct content from titles, logs, truncated labels, or a
similar prompt. A broad storage failure is instead returned as
`503 ARTIFACT_STORAGE_UNAVAILABLE` and should be treated as an operational
outage, not permanent message loss.
