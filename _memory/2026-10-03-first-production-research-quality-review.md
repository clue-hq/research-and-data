# 2026-10-03 — Quality review of the first production account + person research

Run `8e80c2c7-2492-5124-ae7e-0c5248caeab1` (project "Start Garner Health ABM"; client Garner Health,
ICP `us-employer-core-new-logo v6`). Read-only review of production data at ~17:05 UTC.

## Accounts
| | Mortenson (`edce35a5`) | McKee Foods (`20ea09fe`) |
|---|---|---|
| Outcome | completed 16:17:44 (~53 min) | needs_review / workspace_conflict 16:32 (~67 min) — finalize-ordering bug, see slowness note |
| Spend | $6.75, 65 model calls, 179 tool calls | $7.97, 74 model calls, 215 tool calls |
| Sources recorded / never processed | 344 / 305 | 327 / 292 |
| Rated claims | 72: 38 qualified, 27 supported, 7 unresolved, 0 invalid | 65: 35 qualified, 24 supported, 5 unresolved, 1 invalid |
| Pages | overview + insights published | overview + insights published (despite needs_review) |

Accuracy check: every quoted string (54 McKee, 55 Mortenson) and every multi-digit number in every
finding was matched against the stored source bodies (artifact + original provider response).
All quotes were found. Two findings cite the wrong evidence item although the values exist in
other evidence of the same job (McKee "Form 5500 welfare-plan participants 2023"; Mortenson
"Form 5500 administrators named"). No fabricated value found. Paraphrases were not machine-checked.

Relevance: both found the facts Garner's motion needs — McKee: self-funded ERISA plan (6th Cir.
opinion, Apr 2026), MedImpact PBM, Premise-run onsite clinic, Teladoc, COE program, benefits
manager left Dec 2025 + vacancy. Mortenson: Plan 501 (4,492 actives, in ICP band), Unimerica
stop-loss, UHC, WTW broker comp, Spring Health/2nd.MD/Pelago/Kaia, documented traveling-workforce
in-network problem, Senior Manager of Benefits posting Aug 2026, new construction CFO Apr 2026.
Funding type for Mortenson honestly left unproven.

Weak spots: McKee champion Cindy Lyons nominated on an unverified identity (AI Ark title only; the
one LinkedIn found was a different person, flagged invalid by the agent); McKee's Mark Newsome
(HCI bio: VP HR incl. Total Rewards) not reconciled with Don Gladden (VP HR since Jun 2024);
rapport filler findings (CEO cycling, World Cup comment); ~89% of recorded sources never processed
(each one still paid the locked R2 recording cost); Mortenson had 8 tool calls rejected as
`invalid_acquisition_arguments`; project lacks a persona document (ICP persona_map used).

## Persons (10, all `in_progress` at 17:05)
Eight running 50–60 min with only 4–7 min of model time each (~$19 spent so far); drafts are
identity-correct and outreach-useful (company bios + LinkedIn, career history, recent posts).
Two McKee persons (Don Gladden Jr. `74eb5859`, Cindy Lyons `bc9bc12a`) never started: worker
batch1 claimed all five McKee person tasks (`CLUE_FLEET_WORKER_CONCURRENCY=10`) but runs at most
`CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS=4` research jobs, so two sit claimed (heartbeat refreshed)
while batch2 has been idle since 16:32. Claim-without-capacity defect.
