# Stage-0 official-site crawl operations

This runbook inspects and recovers the C1–C8 durable official-site crawler. It never requires or
prints page bodies. PostgreSQL is authoritative; do not infer progress from a browser timer, worker
process lifetime, or the presence of a provider request alone.

## Preconditions

- Select one exact environment, workspace ID, and crawl-run ID.
- Use a read-capable database role for inspection. Use a separately approved write-capable role
  only for a recovery command.
- Confirm the database is on the single current Alembic head.
- Preserve the database and artifact root during an incident. Do not delete or edit artifacts.
- Do not place database URLs or output containing internal IDs in tickets or public chat.

Local inspection example:

```bash
uv run python scripts/18_official_site_c8_operator.py \
  --database-url postgresql+asyncpg://clue:clue@127.0.0.1:5432/clue_c8_acceptance \
  --workspace-id <workspace-id> \
  --crawl-run-id <crawl-run-id> \
  inspect
```

For production, obtain the database URL from the deployment secret manager and pass it only in the
operator's environment/approved shell. Do not paste it into logs. The output contains aggregate
state and bounded provider request IDs but no URLs, bodies, or provider receipts.

## Reading the report

| State | Interpretation | Next action |
|---|---|---|
| `queued` | Work is eligible or waiting for a proven-no-spend retry. | Verify workers and phase priority; do not mutate a healthy queue. |
| `leased` | A worker claimed work but has not dispatched. | Wait until lease expiry; reclaim only if the owner is gone. |
| `provider-active` | A paid/remote call may be running. | Never cancel/reclaim merely because UI progress looks slow. |
| `spend-unknown` | Dispatch may have charged but no authoritative success/no-spend verdict exists. | Reconcile by original operation/receipt; never issue a new acquisition. |
| `persisted` | At least one content-addressed artifact and URL snapshot committed. | Safe for checkpoint/extraction; retain URL-level provenance. |
| `extracted` | One or more checkpoint extraction operations exist. | Inspect terminal counts; empty is valid, failed/unknown needs review. |
| `partial` | Useful evidence exists with explicit gaps/refusals/failures. | Review the gap counts; do not describe it as complete coverage. |
| `completed` | The crawl run committed completion. | Verify checkpoint/extraction and release truth; no replay spend is expected. |

`recovery_required=true` takes precedence over the friendly message. `event_count=0` does not mean
the crawl did not happen: a pre-C8 retained run can have complete authoritative rows and no C8
events. Conversely, an event without matching rows cannot manufacture progress.

## Expired lease recovery

First run `inspect`. Confirm the listed lease is expired by DB time and the worker is no longer
healthy. Then repeat the exact crawl ID:

```bash
uv run python scripts/18_official_site_c8_operator.py \
  --database-url <approved-async-postgres-url> \
  --workspace-id <workspace-id> \
  --crawl-run-id <crawl-run-id> \
  reclaim-expired \
  --confirm-crawl-run-id <same-crawl-run-id>
```

Expected outcomes:

- `requeued_pre_dispatch`: safe to claim again because no dispatch committed;
- `moved_to_reconciliation_pending`: provider dispatch is ambiguous; no page refetch permitted;
- `released_persistence_pending`: retained success is eligible for artifact/snapshot-only replay.

Run `inspect` again. A zero result is a safe replay, not an instruction to broaden the command.

## Spend-unknown handling

1. Inspect the exact attempt and provider key.
2. Use the C4 provider-operation lookup/receipt path where supported. Reuse the original operation
   key and bounded request ID. Never invoke single-page acquisition again.
3. If lookup is unavailable or cannot resolve the ambiguity, obtain incident approval to
   quarantine. Ensure the page is unleased and copy the displayed lease generation.
4. Execute the fenced command:

```bash
uv run python scripts/18_official_site_c8_operator.py \
  --database-url <approved-async-postgres-url> \
  --workspace-id <workspace-id> \
  --crawl-run-id <crawl-run-id> \
  quarantine-spend-unknown \
  --fetch-attempt-id <attempt-id> \
  --expected-lease-generation <generation> \
  --confirm-fetch-attempt-id <same-attempt-id>
```

`changed=false` means the fence did not match. Stop and inspect again; do not weaken the generation,
change workspace scope, or manually update tables. A successful quarantine reports
`provider_called=false` and preserves the attempt/provenance row for cost reconciliation and DSAR.

An `extraction-ambiguity` item is different: it identifies a terminal C7 model-gateway operation,
not a crawl page lease. Record the operation/model/failure labels, reconcile billing with the
gateway traces, and leave the operation immutable. Its permitted action is
`review-billing-no-auto-retry`; there is deliberately no retry/quarantine command because the
gateway call may have spent and has no receipt-lookup contract. Preserve all materialized siblings.

## Metrics and logs

Primary metric prefix: `stage0.official_site.*`.

- frontier: `frontier.ready`, `frontier.leased`, `frontier.quarantined`;
- acquisition: `claim.latency_seconds`, `lease.contention_pages`, `provider.active`,
  `provider.concurrency`, `provider.latency_seconds`, `provider.outcomes`,
  `provider.cost_cents`, `spend_unknown`, `spend_unknown.age_seconds`,
  `stale_completion_rejections`;
- corpus: `pages.total`, `snapshots.total`, `blobs.unique`, `content.duplicate_ratio`,
  `checkpoints`, `fast_checkpoint.latency_seconds`, `fast_checkpoint.category_pages`,
  `background_completion.latency_seconds`;
- extraction: `extraction.terminal`, `extraction.failures`, `extraction.outcomes`;
- operations: `events.total`, `recovery.items`.

Correlate logs by workspace, recon, and crawl run. Page-level logs use `url_hash` plus host rather
than a query-bearing URL. Never increase log verbosity to include response bodies, extraction raw
output, headers, cookies, tokens, email addresses, Clerk subjects, or full receipts.

## Stalled-run decision sequence

1. Run `inspect` and retain its body-free output.
2. If provider-active with an unexpired lease, wait; do not interrupt a possibly paid call.
3. If lease expired, run the exact-id reclaim once and inspect again.
4. If spend-unknown, reconcile the original operation. Quarantine only with explicit approval.
5. If persistence-pending, allow the persistence-only worker to reuse retained bytes/artifact.
6. If extraction failed, preserve successful fields and inspect the specific extraction operation;
   never roll back materialized siblings.
7. If rows are progressing but events are absent, repair visibility separately. Do not rerun crawl.
8. Escalate with IDs, state counts, hashes, timestamps, provider key, and bounded outcome only.

## Acceptance and rollback posture

Run C8 against a fresh, named, isolated database. Keep live-provider evidence databases and artifact
roots until review. C8 has no schema migration to roll back; disabling the crawl rollout flag stops
new composition while preserving rows. Removing the additive `official_site` response field is not
required for old clients because they already ignore it and new clients treat absence as `null`.

Never delete crawl/attempt/snapshot/extraction rows to "unstick" a run. They are provenance,
financial reconciliation, and DSAR reach.
