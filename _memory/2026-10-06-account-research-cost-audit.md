# 2026-10-06 — Account research cost audit (branch shank-audit-account-research-cost-optimization)

Branch cut from origin/main 496956c98 in the winnipeg workspace. Goal: find why account research
burns credits and narrow it. No code changed yet — this entry records the data pull.

## Data pulled
- `.artifacts/account-research-cost-20261006/` (gitignored — local to the winnipeg workspace) — the founder's Dialpad + Loopio production runs
  (2 account + 10 person jobs, 17:15–17:39 UTC), from Langfuse **clue-prod** (US region) via the
  public API. README there has the full breakdown; CSVs are per run / per model call / per tool call
  / per file read. No prompt or result text is stored (results include research about real people).
- `.artifacts/research-model-evaluation-20260928/` was deleted in the working tree on
  head-of-abm-v2; restored on this branch — it holds the September per-model call logs.

## Findings (model spend, Langfuse)
- $47.88 agent model + $1.51 page writer/other = $49.39 of the founder's $50.59 tracked.
- 604 agent calls (= the "rounds" column), ~40–60 per run; context grows 16–18k → 170–205k tokens,
  never compacted. Cost split: cached re-reads 80%, new input 15%, output 5%.
- Prices fitted: grok-4.6 $2.00 new / $0.50 cached / $6.00 output per 1M; no long-context premium.
- File reads → ~50% of model cost over the run: `/research/operations/…` (agent re-reading its own
  saved evidence-tool results, paged) $10.58; `/evidence/…` $5.55; skill files re-read ~8×/run
  $3.53; `/research/capabilities/0.json` $1.39.

## Findings (time) — full report `.artifacts/account-research-cost-20261006/CALL-LOG.md`
- 276 run-minutes over 12 runs: model 41% (avg 11s/call), tools 40%, page writer 16% (~3.5 min per
  run, ~5.5 min for accounts), gaps 3%. Elapsed: Dialpad 45.9 min, Loopio 47.3 min, side by side.
- `acquire_research_evidence` avg 58s while the provider answers in ~2.5s (Exa search) / 0.3s (Exa
  contents): ~20s before dispatch and ~37s after the answer inside `operate` → `recover_acquisitions`.
  Worst in a run's first evidence calls (59s after the answer), i.e. runs queuing on each other.
- Only 4 evidence calls dispatch at once per job: positions 5 and 6+ in a batch wait 43s / 76s; a
  batch's results come back together 30–70s after the providers answered.
- Account runs nominate their 5 people at ~minute 15, but person jobs start only after the account
  dossier import (~minute 22–23): ~8 min gate (`quality_person_release.releases_after_import`).
- PR #91 (research slowness fixes) merged 2026-10-03 20:38 UTC; Langfuse carries no release tag, so
  whether production ran it on Oct 6 is unverified. Traces' service.name = `clue-worker-fleet`.

## Access notes
- Langfuse MCP is user-scoped with a headersHelper reading `CLUE_LANGFUSE_*` from this workspace's
  `.env` (the founder typed the keys). `CLUE_LANGFUSE_ENABLED` stays false locally.
- Railway CLI is linked to remarkable-vibrancy / production. Reading the production database was
  denied twice by the auto-mode classifier ("Production Reads"); the founder has not yet approved
  it. Provider spend (Exa, AI Ark, Apollo) therefore comes from the founder's own numbers, not here.
  Production Postgres exposes PGUSER/PGPASSWORD/PGDATABASE + RAILWAY_TCP_PROXY_DOMAIN/PORT, not a
  DATABASE_URL.
- Langfuse's v1 observations API rate-limits quickly; the v2 endpoint with `fields=` (no io) pulls
  metadata for a whole trace cheaply.

## Next
Decide optimizations with the founder: stop the agent reading its own saved results back into
context, stop re-reading skills, compaction/trimming, fewer rounds, model choice.
