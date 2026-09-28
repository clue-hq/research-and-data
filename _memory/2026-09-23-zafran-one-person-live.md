# Zafran advisory research — one person

- Founder requested a fresh Zafran-only live run capped at one person-research job, after the
  revision-six verification-deferral/display changes. Paid-provider authorization applies.
- Code pin: 251ad3e82. Explicit internal quality profile v4, resource revision six; global v2
  default untouched. Fresh isolated database on the existing test Postgres at port 59274.
- Private artifacts/harness: `.artifacts/arv4-zafran-advisory-one-person-20260923/`.
- Run e6f9ee90-452c-56aa-8209-7b507e608dff; account job e1f5c297-cc01-5d0d-b2d0-db0e4151665d.
- New database `clue_zafran_advisory_one_person_20260923`, separate blobs and agent workspaces.
  Copied seller/ICP/persona inputs only; zero target claims, contacts, sources or provider records.
- Platform account agent chooses the one person using the retained ICP/persona; committee_cap=1.
  Ten workers, each concurrency three; 200 shared model calls per job, 30-minute runtime ceiling.
  Langfuse installed. No fixture facts or historical target reports passed to research agents.
- Launch succeeded at 03:53 UTC. End-to-end result and quality remain unverified while running.

## Early observations

- Agent selected Vari Kaur as champion, citing the source-reported growth-marketing role and the
  ABM job reporting line. Exactly one person job exists. The person job waits for initial account
  settlement by current driver design (`g.initial_settled_at IS NOT NULL`); fleet slots cannot
  accelerate that dependency.
- Account Exa report, AI Ark company/role queries, pages and ATS sources have succeeded.
- Recoverable friction: two discovery argument failures then two successful role searches;
  parent attempted person-only lookup/enrichment and received subject-scope refusals.
- One media discovery persistence failure: a Vimeo result description contained gzip-like binary
  text including NUL, rejected by PostgreSQL JSONB. Three media reads refused. Retain original
  receipts; do not silently treat these as successful transcript ingestion or patch a running pin.

## Initial account failure

- At 04:03 UTC initial account job entered needs_review/runtime_error; one person job (Vari)
  and the durable account continuation started normally. No operator reset/relaunch performed.
- Trace shows repeated `record_research_finding` proposals reusing operation keys with different
  content. `submit_proposal` raises ValueError; governed tool-repair budget is exhausted; claims
  delegation then fails the parent. This is an operation-key/runtime-recovery failure, not a
  relationship verification refusal. Full originals retained in private logs.
- Before failure: 64 stored claims including 13 qualified; no rejected quality proposals. Context
  reached 165k input tokens and index reads repeated. These remain practical runtime bottlenecks.

## Live closeout

- Finished 04:24 UTC, both jobs needs_review/runtime_error; generation revision 101 reconciled as
  needs_review. Exactly one person job. Initial account and multiple account continuations failed
  on finding operation-key collisions; person claims specialist did too. Final account continuation
  exhausted the separate cumulative 30-minute runtime allowance (152/200 dispatch attempts).
- At 04:17:38 UTC re-offered the existing suspended person job with `DbWorkQueue.enqueue` and
  `reopen_terminal=True`: fleet item had incorrectly become done while job was suspended. Same
  job/checkpoint/allowance, no reset, no fresh provider research launch. Receipt saved privately.
- 99 saved findings (83 account, 16 person), 59 supported / 40 qualified. Both work-email and phone
  values saved. Zero narrative-specialist model calls and zero published narrative pages.
- Page projection still exposes all 99 claim IDs on account overview, insights AND person page,
  with no restricted sections. Visibility proof saved: zero missing IDs. Readout is usable as
  retained findings; it is NOT a completed narrative. Ordinary factual claim reader returns 59.
- Two unchanged Exa reports retained: account 13,860 chars; person 11,506 chars. 148 web snapshots,
  28 provider records, 8 acquisition gaps; zero stored media items/transcripts. Provider-ledger
  outcome=ok alone is insufficient: media wrapper/tool outcomes still include refusals.
- Exact collision proof from durable agent_plan_operation parameters: specialists reused one
  operation_key across multiple topics in a batch (e.g. whole-account key or job ID). Failed calls
  at the end of a turn do not necessarily appear in next-request-envelope audit; journal needed.
- 209 completed model receipts USD 11.654210; 36 provider result receipts USD 0.142000 plus
  8.1 AI Ark credits. Receipt totals, not invoice reconciliation. Largest input 177,664 tokens.
- 1,623 retained artifacts checked; all match recorded size and SHA256. Full DB dump preserved.
- Langfuse experienced export DNS/timeouts. Metadata export recovered 4,157 observations; initial
  exact join found 199/209 model receipt observation IDs. Local receipts/logs retained for all.
- All ten workers stopped cleanly (each exit 0). No source/app-code change, limit reset or push.
  New fixes and a successful paid acceptance remain outstanding. Preserve unrelated tracked edit.
- Final queue audit: 15 done task rows, 15,877 total claim attempts; a single continuation had
  6,469 attempts. These are rapid queue claims/re-offers, not provider purchases. Add coalescing/
  delayed retry to the next runtime correction. All final fleet rows are done.
- Public operational report: `docs/superpowers/plans/2026-09-23-zafran-one-person-live.md`.
  Private `ZAFRAN-RESEARCH.md` preserves the real empty narrative sections plus full visible
  findings; `RUN-REPORT.md` links the original reports, appendix and evidence. Cloud exact join
  is 199/209; do not claim complete remote tracing. The run is finished, not still running.
