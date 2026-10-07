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
  saved evidence-tool results, paged) $10.58; `/evidence/…` $5.55; skill files (each read once per run, in 2–3 chunks: ~8 reads/run)
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

## Synthesis (five parallel reviews, key claims re-verified in code + Langfuse)
- Written up in `docs/superpowers/specs/2026-10-06-account-research-cost-and-speed-audit.md`
  (opinion, evaluation scorecard, 3-phase plan with estimates, decisions needed).
- Corrections recorded: skills are read once per run (2–3 chunks each), not re-read; end-to-end to
  final account pages is ~53–56 min (6 back-to-back account-page rewrites, 17:56–18:11, in traces
  outside the 12 `account-research.turn` ones).
- Verified in code: compaction trigger = window × 0.90 with grok-4.6 window 500k (never fires);
  worker-wide `_db_lock` (`account_research_driver.py:504`, used by `_connection` :1017-1020);
  `_drain` runs inside the provider semaphore (`account_research_tools.py:500/550`); person release
  needs the account import marker (`quality_person_release.py:89-92`); uncited findings dumped into
  Miscellaneous (`quality_pages.py:531+`); writer view passes caveats but not
  `agent_interpretation` (`page_writer_view.py:80-81`); master plan POC ≈ $0.17/account,
  $0.07–0.13/person, $0.05 display (`ARV2-MASTER-PLAN.md:131-132`).
- Founder decisions pending (doc §8). Production DB read access: a guarded read-only script exists
  at `~/.claude/scripts/clue-prod-readonly-sql.sh`; the founder has to add the allow rule themselves.

## Deeper audit (2026-10-07) → plan `docs/superpowers/plans/2026-10-06-account-research-v26-cost-and-speed-plan.md`
New findings, all verified against Langfuse tool I/O + code:
- Media never works in production: 9 discover_media, 6–7 read_media, 17 media GETs → 0 transcripts.
  2 crashed `FileNotFoundError: ffprobe` (`media_recording.py:103`; `docker/backend/Dockerfile:44-46`
  installs no ffmpeg); the rest `no_supported_recording_link`/`no_exact_episode_match`
  (`media_resolution.py` supports YouTube/direct audio/RSS only). Deepgram key empty locally, not in
  deploy templates. Governed receipt says `completed` for failed reads. Skills still demand 3–5
  podcast quotes (`person-depth-charter/v1:91`). Dialpad found a podcast with the FORMER CMO, never read.
- Error rounds ≈ $8 of $48 and ~25 min: 27 failed `save_dossier_section` (strict `Finding`/`Review`
  schema, `dossier_findings.py:16-47`; every run ≥1), the grep→search_evidence→finalize trap
  (`quality_workspace.py:135` → `quality_tools.py:358` → finalize refused in 7/12 runs), 60 refused
  ls/glob/grep.
- Exa deep report (52–60k chars) IS read, in 4–11 windows per run (33–61k chars), each re-sent after.
- Evidence created vs read: Dialpad ~964/89, Loopio ~994/113 (~90% never read).
- Cross-job exact query duplication is small (2 per account); person cost is structural (each person
  = full machine: own AI Ark lookup+enrich, own deep report, 5–14 searches).
- Launching chat turn: 240 s, $0.58, 5 model calls, 9 file reads (17:11:27 → jobs 17:15:25).
- Plan: W1 stop-the-bleeding (13 items), W2 evidence-path throughput, W3 v26 pipeline (code
  acquisition → cheap extraction with substring-verified quotes → bounded Grok judge ≤10 rounds →
  tiered persons starting at minute ~4 → per-section pages once), W4 media fix-or-off. Estimate
  ≈ $3–4 and 12–14 min per account+5 (today $25/55 min). Seven founder decisions D1–D7 in §7.
- Founder rulings 2026-10-07 (plan revised in place): NO light/deep tiers — every buying-committee
  contact (4–5 per account, not 45) gets full research; account + all contacts start together at
  approval (committee via AI Ark at t=0, contacts judged against the account's candidates, only
  contact PAGES wait for the account brief); fetch set fixed per subject (~20 account + ~15 per
  contact provider calls, pooled per account). Revised estimate ≈ $3–6 + credits and ≈ 8–10 min
  per account with 5 contacts (spread = Exa deep-report price, unknown until the ledger is read).
