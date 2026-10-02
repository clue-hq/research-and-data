# Grok-4.6 account-run results — Millennium (2026-08-20, 00:33–01:56 IST)

Read-only forensic pass over the live DB (`clue@localhost:5432/clue`) for the two
Millennium Physician Group jobs driven under `x-ai/grok-4.6`
(`.context/live-restart-20260819/live-overrides.env` sets `CLUE_SYNTHESIS_MODEL=x-ai/grok-4.6`;
missoula fleet, integration_pilot posture). No code touched this session.

## Outcome (honest)

Neither Grok job settled. Both sit `queued` (paused after a raw worker error).

| job | run | started | spend | terminal-ish failure |
|---|---|---|---|---|
| `16e846d6` | `47c22cee` | 00:33 | $6.10 | GraphRecursionError ×2, then OpenRouter 404 encrypted-reasoning replay |
| `eea48931` | `1d39023a` | 01:28 | $2.50 | ResultIntegrityError → GovernedRejection ×2 → ToolException (01:56) |

## What Grok did well (model capability is NOT the blocker)

Both drives executed the intended sequence in ~80 s, unprompted:
`read_account_research_state` → `research_account_deep` (exa_deep) → `enrich_account`
(sumble_tech_stack) → `discover_buying_committee` (sumble_people) → `assess_account_coverage`.
It self-repaired from refusals in one turn each time (missing `evidence_refs`; the
1000-char `research_intent` cap; re-bundling after a rejected follow-up). Turn latency
~3–20 s. That is the behaviour the Terra-era journals never produced.

Product produced: **4 new tier-4 claims** at 00:34 (`account.resonance.culture`,
`.employee_sentiment`, `.attrition_signal`, `.eng_blog_tone`). Run 2 produced 0 new claims
(its one Exa result settled `account.total_funding` unsupported; the remaining bundle came
back `provider_terminally_unproductive`). **No coverage row, no finalization, no committee
member** for the account.

## Root cause #1 — cross-job operation reuse + job-scoped settlement fold = permanent pending work

`sumble-account-operation:89f64be2-…` (source `sumble_tech_stack`) was *caused* by job
`298f3dec` (Terra run `b3ad33b7`) yesterday 20:41 and got HTTP 402. Its settlement fold
(`entity_research_provider_settlement_fold`) is stamped with **that** `job_id`.

Both Grok jobs re-derived the same idempotent operation ref and recorded a
`replay_observation`. `_pending_refs`
(`platform/api/clue_api/account_entity_research.py:148`) releases an observation only if
the fold row carries **the same `job_id`** — so for the replaying jobs the operation is
pending forever, and `assess_account_coverage` / `finalize_account_research` are refused
with `dependent account decision has pending work` on every attempt.

Verified by running the predicate directly: exactly one pending ref per job, the same
`89f64be2` operation, in both.

Consequences observed:
- Run 1: the agent looped read-state ↔ assess (6 refusals) → LangGraph recursion limit 84.
- Run 2: the agent tried to clear the pending op via `read_research_result` with the
  *operation* ref → `reference_type_rejected`; the checkpoint replays that same bad call on
  every resume, so 01:38 / 01:48 / 01:56 are the identical failure three more times.

The pending predicate's own docstring claims case 2 covers "the live Sumble 402 livelock" —
it does, but only for the job that caused the operation.

## Root cause #2 — governed rejection still escapes on the replayed call

HEAD `85137024` did change the payload: at 01:56 the refusal is rendered as the structured
governed-rejection JSON (code/detail/guidance) instead of the bare message. But it still
surfaced as `execution_failed` (`worker_error:ToolException`) rather than becoming a tool
message the model reads. On a resumed checkpoint the offending call is replayed before the
model gets a turn, so the corrective guidance never reaches it. The fix works for
in-flight calls, not for checkpoint-replayed ones.

## Root cause #3 — encrypted reasoning pins a job to its model/endpoint

Job `16e846d6` last died with OpenRouter `404: Your request contains encrypted reasoning or
compaction content that was produced under a different model. Encrypted payloads can only be
replayed to the endpoint that produced them.` Grok (xai-responses-v1 reasoning blocks) is
persisted in the checkpoint, so a Grok-era job cannot be resumed under another model — and
apparently not reliably even under a re-routed Grok endpoint. Model swaps now invalidate
in-flight checkpoints; treat that as a migration constraint.

## Business blocker unchanged

`sumble_people` → HTTP 402 on every attempt (23:09, 00:34, 01:30). `sumble_tech_stack` → 402.
`sumble_teams` succeeds and is burning credits fast: remaining 431 → 333 → 173 → **64**.
So committee members cannot land regardless of model or code until the Sumble plan covers
/people and /techs.

## Suggested next actions (not done — awaiting founder decision)

1. Release pending on a `replay_observation` whose operation has a fold in **any** job of the
   same run/workspace (or write a per-job fold when joining a settled operation). One-line
   class of fix in `_pending_refs`; unblocks assess/finalize for every future replaying job.
2. Make a checkpoint-replayed governed rejection land as a tool message (channel-1) so a
   resumed job self-repairs instead of re-dying.
3. Decide the Sumble subscription question — it is now the only thing between us and a
   committee.
4. For job `eea48931`, a relaunch is cheaper than a resume (its checkpoint holds the poison
   call); `16e846d6` cannot be resumed at all under a different endpoint.
