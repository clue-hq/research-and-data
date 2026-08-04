# 2026-08-05 — M8B live provider, fleet, and replay remediation

## Input boundary

- Correct source DB: `clue_d6_acceptance_20260803`, a synthetic upstream handoff only.
- Its sealed discovery list contains `mhsi.com` and `njbrainspine.com`; no account profile,
  committee, contact, Exa receipt, or Sumble S2 snapshot was seeded.
- Live canary selected New Jersey Brain and Spine after layering only the deep ICP, confirmed
  directive, selection/tier, policy, budget, and launch prerequisites.

## Live evidence

- Exa: one Deep-Reasoning request for two fields; operation
  `ef813fa2-feb9-49a1-ad64-23caaf0ec5cb`, request id
  `deb08be7dcfe7393f52099ee69bcc280`, one attempt, 13 result artifacts, 1.800 cents reported and
  settled, two grounded claims.
- Sumble S2: operation `2a15b718-61f9-4db2-9665-a6e92eaad87f`; one Teams response (15 credits),
  one pending People submit (0), one successful People poll (48); six LinkedIn-bound candidates;
  no email/phone selection, value, reveal, or contact profiling.
- Live detached fleet clone `roseau_m8b_fleet_replay_20260805`: account run completed with two
  account refs, eighteen committee refs, six committee contacts; DEEP and VERIFICATION committed;
  REVIEW paused for human input; zero account failures.
- Live OpenRouter `openai/gpt-5.6-terra`: six role calls plus fourteen faithfulness judgments.
- Original live DB and fleet replay DB both retain Exa 1 op/1 attempt/1.800 cents and Sumble 1
  op/3 attempts/63 credits: provider replay added no call or spend.
- Verification was conservative: Exa claims flagged/rejected; role/persona hypotheses
  flagged/rejected. This proves the gate path, not promoted-output quality.

## Live-found fixes

1. Added durable due-committee-operation query and `SumbleCommitteeWakeWorker` to the fleet.
2. Bound the configured synthesis model into production role inference.
3. Enforced the directive candidate cap over combined People plus team-related candidates.
4. Threaded `contact_profiling_allowed` into `AccountSpec` and skipped disabled fan-out.
5. Added transaction-aware pre-spend-gate rebinding so newly admitted contacts are visible to the
   role gate and its decision is atomic with committee claims.
6. Aligned the stale S2 v9 OpenAPI pin with S1/current digest
   `c6f1324366a94844932ee3522caee6aa9f428f7d958a9956bea3425d18e2811c`, with a drift regression.

## Verification

- Full repository on a newly created empty migrated DB: 3,332 passed, 23 expected skips, 0
  failures. A prior rerun against a reused populated test DB failed migration downgrade and
  cascaded; that run was invalidated rather than counted.
- Focused S2/O2/orchestrator regression after digest alignment: pass.
- V0 standalone fresh-process/migration round trip: pass.
- Alembic one head `a83e52bebc7c`; mypy 516 files; 24/24 import contracts; changed-source Ruff pass.

## Remaining full V1 gate

- Live O3 user-facing conversation-to-launch surface was not executed; fleet started from the
  already durable directive/launch.
- The sample produced no promoted account or role/persona claim.
- Sumble credit-to-money and OpenRouter price configuration were zero, so credits and Exa dollars
  are exact but combined monetary cost is incomplete.
- Do not repeat the paid S2 operation merely for replay; close the remaining gates with one bounded
  conversational quality canary and forbidden-provider replay.
