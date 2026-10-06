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
