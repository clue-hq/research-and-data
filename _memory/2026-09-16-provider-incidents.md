# 2026-09-16 — Provider incidents (plan close-out)

Plan `docs/superpowers/plans/2026-09-16-provider-incidents.md`; spec
`docs/superpowers/specs/archive/2026-09-16-provider-incidents-design.md`. Branch `research-streaming`
(worktree san-salvador). Seven tasks, all landed; this note is Task 7 (live proof, contract notes,
memory).

## The problem it closes

A provider stopped serving us and nobody was told. On 2026-09-16 Exa Search answered
`402 NO_MORE_CREDITS`, Exa Websets halted a discovery run on `payment_required`, and OpenRouter
refused on a weekly key limit — accounts were left ungenerated and the only signal was a raw code
(`model_error`, `permission_denied_error`) or an empty section. Now: one durable incident per
outage, one Sentry event on open and one on close, and one honest sentence on every affected
surface.

## What landed (commits `2b0c8b977..9e01597d0`)

| commit | what |
| --- | --- |
| `de33ffff2`, `044f9dcf6` | T1 — `clue_core.provider_failures`: one pure classifier (`classify_http`, `classify_exception`, `failure_code`, `parse_failure_code`), seven reasons, message capped at 300 chars, no I/O and no provider SDK import; `_REASONS` pinned to the `FailureReason` alias by a drift guard |
| `db90f12e5`, `1fac411e2` | T2 — `provider_incident` table (migration `89791cb5949e`, reversible, single head) and `clue_api.provider_incidents`: `record_failure` / `record_success` / `open_incidents` / `incident_sentence`; partial unique index on `(provider, reason) WHERE closed_at IS NULL`; one Sentry event each way; the recorder never raises |
| `f4d4d03fb`, `c6fe99c30` | T3 — the ARV2 caller stamps the classification on the failing ledger row's `extras`; `drain_provider_calls` records incidents after the inserts on the same connection; a provider closes only when its **last word in the batch** was a success; onboarding rows count as onboarding |
| `8a03e6ae1` | T4 — a refused model round stamps its failure on the ledger row and the research job finishes with `provider_refused:<provider>:<reason>` |
| `d36f3616a`, `faa7838d6` | T5 — the chat turn's model-call handler classifies in `on_llm_error`, writes the code on the turn and records the incident after the receipt; a success closes; the incident work can never raise into a model callback |
| `9e01597d0` | T6 — the three inline readers: the research card's `incident` payload + sentence reasons, the empty overview section's `emptyMessage`, the failed chat turn through `designTurnFailureNotice` |
| this commit | T7 — the two frontend contract notes and this memory note |

## Rulings the build follows

- **Scope B** — refusals *and* repeated failures, not refusals alone.
- **User surface: inline only** — no global banner, no email, no user-triggered report.
- **Operator channel: Sentry only.**
- **Unit of notification: the incident** — one event on open, one on close; never one per failing call.
- **A 429 counts as a failure** toward the threshold, like a 5xx or a timeout (founder, 2026-09-16).

**Spec amendment recorded by the plan (§3.4 writers).** The spec named the model gateway as the
second writer through a root-installed hook. The writers are instead the **ARV2 ledger drain** and
the **chat turn's model-call handler** — the two places the platform already catches the failure
with a database connection in hand. `libs/clue-gateway` is untouched, which matters because the
design subsystem depends on it too.

## SDD rulings (controller, during execution)

- **PI-1** — T2's two-writer race test is a sequential proof (a second `record_failure` on the same
  `(provider, reason)` returns the same incident id and inserts nothing); one asyncpg connection
  cannot run two statements concurrently, and the cross-process guarantee is the partial unique index.
- **PI-2** — `clue_api.provider_incidents` is allowlisted in `tests/arv2/test_import_guard.py`
  ("platform incident recorder the lane reports into; no lane logic").
- **PI-3** — T1 uses an explicit `_REASONS: frozenset[str]` for the membership check rather than
  `FailureReason.__args__` (mypy would reject the latter).
- **PI-4** — no in-memory failure window: the threshold counts the ledger rows that already exist,
  and each writer records *after* its durable row is written, so the query sees the current failure.
  A per-process counter would make the threshold depend on which of four workers saw the faults.
- **PI-5** — the recorder writes on the caller's connection, by design. A caller that rolls back
  *after* the Sentry open event left will re-open and re-notify on its retry — one duplicate open
  event in a rare settlement-rollback path, accepted for v1. An own-connection recorder would see
  incident rows before the ledger rows they count, which breaks the threshold read.

## Deferred minors (none blocking; each documented at its site)

- T1: `_BODY_MESSAGE_RE` stops at the first quote character, so a provider sentence containing an
  apostrophe is clipped there. `_CREDIT_WORDS` is tested before `_KEY_LIMIT_WORDS` on 401/403, so a
  key-limit body that also says "credit" reads `credits_exhausted` — both are refusals, same
  handling, only the label differs.
- T2: `failure_count` at open is stamped `FAILURE_THRESHOLD` even when the ledger burst was larger;
  `_RECENT_FAILURES` is unindexed (≈6k rows today) and runs on every sub-threshold failure.
- T3: a retried drain double-counts `failure_count` (the ledger insert is idempotent, the recorder
  increment is not) — same family as PI-5. `record_success` closing from any workspace is **by
  design**: a provider refusal is platform-wide (spec §3.3).
- T4/T5: the provider literal `"openrouter"` is hard-coded in the research agent, the chat handler
  and `clue_agents.runtime._error_code`, beside the row's own provider field.
- T5: `on_llm_end` opens a transaction and runs the close UPDATE on every model call (one indexed
  statement; the alternative read costs the same).
- T6: one extra indexed `open_incidents` SELECT per non-degraded page read; the Python and
  TypeScript label tables are duplicated with no drift guard; `_notified`'s rewrite is a
  prefix/suffix textual match (fails safe — an unrelated message is left alone).

## Live proof (2026-09-16, lane stack, real provider + real Sentry)

Stack restarted on the new code (`./scripts/dev_stack_san_salvador.sh down; up`) — frontend 3020,
design-api 8010, platform-api 8020, platform-api-2 8030, 4 fleet workers all UP. **Sentry went live
with that restart**, as the spec's §5 answer 1 predicted: `sentry.installed` in both
`clue-projections-api` and `clue-worker-fleet`, environment `lane-san-salvador` (it read
`sentry.not_installed` before).

**Deviation from the brief's probe, recorded.** The brief expected Exa Search to answer
`402 NO_MORE_CREDITS` for the lane key, so the probe would spend nothing. It no longer does — the
key has credits and answered `200` (`costDollars.total` $0.007). The refusal was produced instead by
a **real Exa `401 INVALID_API_KEY`** (a deliberately wrong key on the same live endpoint), which is a
genuine provider refusal through the real `ProviderCaller`, the real `drain_provider_calls`, and the
real recorder — nothing was faked and no row was hand-written. The reason is therefore
`auth_invalid` rather than `credits_exhausted`; both are refusals and take the identical
open-on-first-sight path.

Result — one full open → close cycle, twice (the first before Sentry was installed in the probe
process, the second with the production installer `install_production_sentry` loaded exactly as
`fleet_main` does it):

| incident | provider / reason / kind | count | open event | close event |
| --- | --- | --- | --- | --- |
| `b60d48b0-d960-438a-a8b5-c4fb47174751` | exa / auth_invalid / refusal | 1 | *(none — probe process had no Sentry yet)* | `a16de52895f84b0aae193475f46f58e0` |
| `22ba5d19-0623-4961-b42d-8ccd10e7b15d` | exa / auth_invalid / refusal | 1 | `fcae8f4611944dcfa322284cd8c91957` | `d05642357616426c9220025d183d110f` |

`open_incidents` returned `[('exa', 'auth_invalid', True)]` while the second incident was open —
`notified=True` — and `[]` after the closing success. `sample_message` = "Invalid API key",
`surfaces_json` = `{"search": 1}`, `workspaces_json` = the one lane workspace. Both rows are now
closed, so no spurious exa incident is left on the lane.

**Sentry UI not checked** — this run had no browser. The non-null `sentry_open_event_id` /
`sentry_close_event_id` columns above are the proof the events left the box (the recorder stamps the
id `sentry_sdk.capture_message` returned); the titles are the plan's fixed strings
("Discovery provider refused: API key rejected" / "Discovery provider recovered after …").

Two notes from the probe, neither a defect: passing an explicit `content-type` header to
`json_request` duplicates the one it already sets and Exa then answers `400 INVALID_REQUEST_BODY`
(correctly classified as **not** a provider failure — a 400 is our request, not their refusal); and a
`CallSpec` with no `cost_reader` lands `cost_usd = 0` on the ledger row even for a billed 200, which
is the probe's omission, not the caller's.

## What is owed

1. **The founder's browser walk (plan Step 4)** — not done here, no browser in this run. Three
   surfaces to check while an `openrouter` incident is open: (a) the research card's attention line
   reads the full sentence ending "Clue has been notified."; (b) an account overview (e.g. Capital
   Digestive Care) shows "Not generated: model provider refused (key limit exceeded). Retries
   automatically." under each empty section; (c) a chat turn refused by the model reads the sentence
   instead of `permission_denied_error`.
2. **An `openrouter` incident end to end** — the live proof above exercised the ARV2 drain writer
   (exa). The chat-turn writer (T5) and the two openrouter-fed readers are proven by tests, not yet
   by a live outage.
3. Re-running the probe is a one-liner if a provider outage needs re-proving; the script used is in
   the Task 7 report (`.superpowers/sdd/2026-09-16-provider-incidents/task-7-report.md`) — load the
   lane env with `set -a; source .env; set +a` first and run it with `uv run python - <<'EOF' … EOF`
   from the worktree root.

**Unrelated, pre-existing:** `tests/arv2/test_import_guard.py::test_the_arv2_package_imports_nothing_quarantined`
fails at this HEAD on two offenders that are **not** this plan's —
`arv2/account_research_agent.py → clue_api.langfuse_callbacks` (PR #56) and
`arv2/icp_authoring.py → clue_api.project_library_refresh` (lane 2). `clue_api.provider_incidents`
is allowlisted (PI-2) and is not among the offenders.

## Operator notes

- **Thresholds** (`clue_api.provider_incidents`): `FAILURE_THRESHOLD = 3`,
  `FAILURE_WINDOW = 5 minutes`. A **refusal** (`credits_exhausted`, `key_limit`, `auth_invalid`,
  `account_suspended`) opens on first sight; a **failure** (`rate_limited`, `server_error`,
  `timeout`) opens only after 3 classified failures for one provider inside the window. A 2xx, 400,
  404 or 422 is never a provider failure.
- **Historical rows keep their old codes.** Jobs and turns written before this plan still carry
  `model_error` / `permission_denied_error` and render exactly as they did — `parse_failure_code`
  returns `None` for them and every reader falls back to its previous behaviour. Nothing was
  backfilled.
- **`provider_incident` rows are never deleted.** A close sets `closed_at` (and the close event id);
  the row stays as the outage's durable record, and the partial unique index only constrains rows
  with `closed_at IS NULL`, so the same `(provider, reason)` can recur any number of times.
- **No new env flags.** Sentry uses the existing `CLUE_SENTRY_ENABLED` / `CLUE_SENTRY_DSN` /
  `CLUE_SENTRY_ENVIRONMENT`. A process that booted before the flag was set logs `sentry.not_installed`
  and notifies nothing — restart it.
- **One incident per `(provider, reason)` platform-wide**, not per workspace: a provider refusal is
  not one tenant's problem. The row counts affected workspaces and surfaces in its JSON columns.
