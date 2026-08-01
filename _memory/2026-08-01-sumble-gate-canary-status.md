# Sumble gate canary — status 2026-08-01 (in progress, one wiring gap left)

Branch `platform/clue-trial`, HEAD `14cd59a`. Server: `clue_api.trial_main` on :8010 (restart after
any new commit). Active trial: `trial-acceptance-aura-c2` (ws `s0-trial-acceptance-aura-c2-5da3502a`),
confirmed ICP `us_independent_neurosurgery_spine_practices` v1 (grounded, 3 stmt justifs), account
`d114d98a-198d-4dfa-aaa0-58998d349b67` (The Oregon Clinic, oregonclinic.com), phase `tier_checkpoint`.
Older trial `trial-acceptance-aura-c1` is POISONED for re-research: pre-F9 SUCCEEDED org receipt
replays a stale attributes-only payload → hard `SumbleSchemaDrift` (F9 re-review minor: acquisition
ledger key `sumble-acquisition-v1` is body-independent; bump to v2 or fold select-list version in).

## Landed fixes (all committed local, nothing pushed; total local commits eada407..HEAD = 33)

- F9 `52766a1`: Sumble select-list drift — live returns ONLY selected attributes ("free" = price,
  not delivery); select now id/name/url/sumble_url/employee_count; `SumbleSchemaDrift` raised when
  matched_count>=1 yields zero keyable rows; fixtures re-recorded; spine e2e asserts claims+fit.
  Re-review clean. Deferred minors: acquisition key not body-versioned; preview `maximum_credits: 2`
  hand-written in trial/coordinator.py:694 (not derived, untested); ambiguity branch still silent.
- F10 `14cd59a`: jobs `filter.query` must be v9 `Query` OBJECT `{"query": "<dsl>"}` not bare string
  (OpenAPI verified; live probe 200 @ 0 credits). Exact-body test pins it. Controller adjudicated:
  no reader re-review — live probe + RED/GREEN exact-body test is the stronger verification (ruling
  recorded here to avoid silent discard). Other Sumble bodies verified conformant vs OpenAPI
  (organizations POST, tech-stack GET); RESPONSE shapes not re-verified (flagged).

## Live progress this canary (spend so far: 2 Sumble credits total; caps honored)

- Acquire on c2 after F10: org matched id 21559 (2 credits, replayed receipt — no double spend),
  jobs 200 with 0 rows @ 0 credits (medical clinic, no Software Engineer postings — honest empty).
- BUT account claims are only discovery_provenance + scoring.fit/intent (0.0). NO
  `core.employee_count` claim despite the good snapshot. Server log shows ZERO
  waterfall/enrichment/resolver activity during scoring.

## OPEN — F11 (next agent's job): live scoring phase never runs Pass-A waterfall over snapshots

Hypothesis to verify: the fixture e2e (`tests/api/test_clue_trial_spine.py` — asserts
employee_count claim 120 + fit 0.24 + jobs body org id) composes/registers the Sumble
snapshot-backed resolvers into the waterfall/scoring path in-test, while the LIVE trial server
composition (`trial_main`/`trial_app`/`coordinator`/`run_composition`) does not invoke that leg
(echo of the old "register_deterministic_resolvers() has no production caller" caveat). Find where
the spine/scoring phase should consume `platform/api/clue_api/trial/sumble.py`'s archived snapshots
("hand the durable snapshot to the provider-neutral resolver registry" — module docstring step 5)
and wire/exercise it in the live composition. Fix + DB-backed regression that runs the LIVE
composition path (not test-composed) far enough to assert the employee_count claim; then on trial
c2: POST `/v1/trials/trial-acceptance-aura-c2/accounts/d114d98a-198d-4dfa-aaa0-58998d349b67:research`
`{"action":"acquire"}` (new idempotency key) should backfill claims OR re-scoring path per design;
then `{"action":"approve_direct_research"}` → handoff → C7 view should carry real statements.

## Acceptance criteria for closing the gate

Claims: core.employee_count=488 (verified path) for the account; fit scored over real values;
deep research + verification run; C7 research view non-empty with provenance; report + costs
exported under `.context/sumble-trials/trial-acceptance-aura-c2/`; total Sumble spend ≤ caps
(2-3 credits). Then summarize research quality for the user (that judgment is the whole point).
