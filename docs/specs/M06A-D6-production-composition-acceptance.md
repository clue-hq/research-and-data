# M06A D6 production-composition acceptance

- **Status:** `PASS` on 2026-08-03
- **Branch:** `platform/c8-exa-sumble-discovery`
- **Implementation commit:** `bddca66` (`feat(discovery): compose live Exa D6 acquisition`)
- **Migration head:** `3f41f54d6238`
- **Live database:** dedicated local `clue_d6_acceptance_20260803`
- **Regression database:** dedicated local `clue_d6_regression_20260803`

This record closes D6 only. It does not close targeted Exa import enrichment, Sumble gap filling,
buying-committee discovery, or the separate Exa Search tool.

## 1. Production path now composed

The fleet composition now has one continuous path:

```text
confirmed pinned ICP
  -> deterministic provider-neutral DiscoveryPlan
  -> stable closed DiscoveryBatch
  -> durable D2 Exa submit
  -> D3 poll/event/page reconciliation
  -> D4 identity admission + claim/field materialization
  -> D5 immutable seal
  -> committed SCORING phase with numeric scoring disabled
  -> Exa-criteria selected/hold/excluded decision
  -> durable human TIER_CHECKPOINT
  -> DEEP only for explicitly approved selected accounts
```

`DurableDiscoveryPhaseHandler` originates the batch only when production supplies a
`DiscoveryBatchStarter`. Provider I/O happens after the handler's database transaction closes.
Once the starter is present, an absent batch cannot fall through to the legacy empty-channel path.

The compiler reads the exact active ICP version pinned by the project run. For the D6 policy it
requires one company search, at most two rows, one to five must-have criteria, LinkedIn URL and
revenue-band enrichments, and the closed discovery-field envelope. Company email and phone remain
an explicit opt-in.

Plan id, generation-one batch id, observation window, and request fingerprint are stable functions
of workspace, run, ICP version, compiler version, and acquisition-policy version. PostgreSQL owns
replay. A process restart cannot silently create a different generation or repeat the paid submit.

## 2. Production spend controls

Two independent default-off deployment switches are required:

- `CLUE_EXA_WEBSETS_LIFECYCLE_ENABLED=true` starts reconciliation of durable operations.
- `CLUE_EXA_WEBSETS_ACQUISITION_ENABLED=true` authorizes new paid Webset creation.

Lifecycle may be enabled while acquisition remains disabled so an operator can drain existing work
without permitting new spend. Acquisition fails closed if lifecycle is disabled or the API key is
missing.

Default D6 preflight, with email and phone disabled:

- requested results: 2;
- ordinary enrichments per row: 2;
- maximum provider charge: 28 credits;
- internal allocated maximum: 12.572 cents;
- project-run remaining budget must cover the complete maximum before submission.

Email and phone require the explicit policy opt-in and reserve the full 48-credit / 21.552-cent
maximum. The live D6 run did not enable them.

## 3. Live provider evidence

The bounded live run used the Insight Health/Aura confirmed Stage-0 fixture.

| Durable object | Value |
|---|---|
| Workspace | `ws_fixture_insight_health_aura` |
| Project run | `957f34e1-f426-5d10-95db-75f7ce1187a7` |
| Discovery batch | `5f48fda5-c72e-546d-8699-fd90ee701356` |
| Operation | `e7d6a220-7468-4451-a0d2-4af24dc00b24` |
| Exa Webset | `webset_01kz3bczvnsh1svtzv4xg3psc8` |
| Request fingerprint | `acc9c2829c77650e70d3d8e36437895f097b248b2126d32495928cec2327159f` |
| Provider credits reserved / charged | `28 / 28` |
| Internal cents reserved / charged | `12.572 / 12.572` |
| Immutable seal | `08de49006f1c352762d44acffc5c3136a066ab7afcdaa80df6a578f056bd8625` |

Reconciliation persisted 10 provider-page receipts, exhausted all cursors, and materialized two
raw item snapshots. The current Exa event-page payload was passed through the production webhook
ingestor with a valid local HMAC and routed to the owning operation; one signature-verified event
is durable. This proves signature, parsing, tenant routing, deduplication, and wake scheduling with
an actual provider event payload. It is not a claim that Exa delivered an Internet callback to the
local machine. Polling independently completed the Webset and pagination, so correctness does not
depend on webhook delivery.

Materialization produced:

- 2 admitted canonical accounts;
- 11 distinct claims in the sealed claim manifest;
- 14 required-field resolutions;
- 11 `resolved` and 3 honest `confirmed_missing` terminal field states;
- stable account and claim manifest artifact references; and
- zero duplicate claims on the D4 restart replay.

The D6 run also exposed and repaired a D5 manifest defect: provider-backed discovery-provenance
claims are linked directly to item artifacts rather than necessarily to a field-resolution edge.
Seal readiness now includes both field-resolution claims and item-artifact-linked claims for
admitted/merged candidates. A real PostgreSQL regression test preserves this invariant.

## 4. Scoring-bypass result

Numeric scoring was disabled exactly as planned:

- `scoring_mode=disabled`;
- `selection_mode=discovery_criteria`;
- numeric fit/intent claims written: 0.

Both live accounts received `yes` for all three required Exa criteria. Neither was made selectable
by ignoring its field gaps:

| Account | Exa criteria | Required-field result | Disposition |
|---|---|---|---|
| New Jersey Brain and Spine | 3/3 `yes` | industry and revenue confirmed missing | `hold` |
| Michigan Head and Spine Institute | 3/3 `yes` | industry confirmed missing; revenue resolved | `hold` |

The project is therefore durably paused at `TIER_CHECKPOINT` with distribution
`selected=0, hold=2, excluded=0`. No account was approved and none entered `DEEP`. This is the
correct fail-closed result. The later Sumble gap waterfall must resolve or corroborate the required
fields before a replacement/continued selection decision can promote an account.

The positive path is separately database-tested: a sealed account with every required Exa
criterion equal to `yes` and every required field resolved becomes `selected`; the checkpoint may
approve it; the tier decision is bound to the run and seal; zero numeric scores are manufactured;
and the run becomes `DEEP`-eligible. A held account cannot be approved.

## 5. Fresh-process replay

The acceptance runner was started again in a fresh process over the sealed generation. It returned:

- submit outcome `replayed`;
- the same two account ids;
- the same 11 claims and 14 field resolutions;
- the same account/claim manifests and seal;
- Exa create calls: 0;
- lookup calls: 0;
- poll calls: 0;
- item-page calls: 0; and
- event-page calls: 0.

The sanitized evidence report is stored locally at
`.context/discovery-fixtures/d6-acceptance/d6-replay-report.json`. It is a non-authoritative
inspection export; PostgreSQL and the content-addressed artifact store remain authoritative.

## 6. Verification

Changed-surface regression command, against the freshly migrated dedicated database:

```text
pytest -q
  tests/api/test_exa_websets_submit_d2.py
  tests/api/test_exa_websets_lifecycle_d3.py
  tests/api/test_exa_websets_materialization_d4.py
  tests/api/test_discovery_seal_d5.py
  tests/api/test_exa_websets_acquisition_d6.py
  tests/api/test_exa_websets_wiring_d3.py
  tests/discovery_scoring/test_discovery_criteria_selection.py
  tests/discovery_scoring/test_tier_checkpoint_phase.py
  tests/api/test_run_composition.py
```

Result: **87 passed**.

Additional gates:

- Ruff check over every tracked Python file: pass.
- Ruff format check over every D6-touched Python file: pass.
- mypy: 471 source files, no issues.
- import-linter: 24 contracts kept, 0 broken.
- Alembic upgrade from base to the single head `3f41f54d6238`: pass.
- live fresh-process replay: pass, zero provider calls.

### Post-adversarial repair supplement — 2026-08-03

Commit `3b7458a` closes the production-composition gaps found in the D6/E1 review:

- D6 creation now requires an active run still in `DISCOVERY` and reserves against the shared
  project-run cap, including every outstanding D6/E1 reservation.
- Terminal D6 reconciliation settles the realized internal charge into
  `project_run.spent_cents` transactionally and exactly once; replay adds zero spend.
- E1 is composed as a default-off Head-of-ABM spend tool plus a lifecycle-controlled fleet poller.
- `scripts/12_exa_websets_webhook_provision.py` supplies the missing idempotent team-webhook
  provisioning operation and writes a newly issued signing secret only to a mode-0600 file, never
  to stdout.
- The scoring-bypass estimate reports all sealed discovery rows as discovered while projecting
  expensive work only for selected rows.
- Hardening migration `fffa2a8ba17c` restores the workspace-composite D4 review-task lineage on
  long-lived databases that applied the older single-column contract.

The repaired D2-D6/E1 set is **81 passed**; mypy checks **481 files**; all **24** import contracts
hold; the single migration head is `fffa2a8ba17c`; and a clean throwaway database passed the full
`head -> base -> head` migration smoke before being removed. These repairs do not change the
already-completed live D6 provider evidence and do not repeat its paid Webset.

The repository-wide `make check` is not globally green for pre-existing reasons outside this D6
change. Fourteen untouched tracked files fail the repository formatter. The full suite initially
reported 11 failures; re-running those 11 in a clean environment removed four environment/order
failures and reproduced seven baseline failures:

- stale Stage-0 tool schema digest in the C6.4 agent-runtime fixture;
- three older recipe/fleet harnesses that attempt `TIER_CHECKPOINT -> DEEP` without persisting the
  approved checkpoint now required by the D5 database trigger;
- stale ICP compiler expectation that omits the already-configured `sumble_jobs` tier;
- a memory-layer import-boundary test against the existing Stage-0 runtime; and
- a pre-existing secret-shape fixture string in the Sumble resolver tests.

None imports or executes the new D6 acquisition compiler/starter, and the D2-D6 suite exercises the
same D5 trigger and production composition directly. These baseline failures are recorded rather
than edited as part of D6.

## 7. Gate verdict

`PASS` for D6:

- confirmed ICP compiles to a durable discovery plan;
- one paid Webset is submitted and exact replay cannot submit another;
- current provider webset/event/item payloads reconcile through polling and signed-event paths;
- pagination, snapshots, evaluations, references, enrichments, identities, fields, claims, costs,
  and artifacts reconcile;
- the immutable batch seal is committed only after every blocker is terminal;
- scoring reads the exact seal and uses Exa criteria without numeric scoring; and
- restart reproduces the exact result with zero provider calls.

The live accounts' `hold` status is not a D6 failure. It is the verified input to the next approved
waterfall slice and proves the system does not turn missing required data into a false positive.

## 8. P0-P3 pre-seal waterfall supplement — 2026-08-03

The later adversarial review found that the original order could not actually use Sumble to repair
a required discovery field: D4 terminalized the absence, D5 sealed it, and post-selection S1
required a human tier that a held account could never obtain. The repair keeps missing required
attempts pending, runs a durable required-field waterfall inside `DISCOVERY`, and makes D5 include
that work before sealing. Optional S1 remains post-selection.

A new dedicated live run began from the Insight Health/Aura Stage-0 handoff. Exa's deterministic
external id found the already-existing paid two-row Webset after a `409` create response and a
successful lookup; current polling, events, items, and D4 materialization were exercised again.
Two new Sumble v9 organization requests then resolved the missing industry for both accounts at
2 credits each. The sealed batch settled 32 provider units (28 Exa + 4 Sumble), 17 claims, 14
field-resolution rows, and 13 distinct claims linked by those rows. The result was
`selected=1, hold=1, excluded=0`; the selected account was
human-approved into `DEEP`, while the hold retained an honest missing-revenue reason.

Fresh-process replay returned the same two accounts and seal
`ec6cef9abd2dedd8077b9edf187090af156b09e76ff37032f7e03f065b58fc88` with zero Exa calls. Database
tests separately prove a sealed replay cannot invoke Sumble, concurrent resolvers dispatch once,
and a crash after possible Sumble dispatch becomes spend-unknown rather than retrying.
