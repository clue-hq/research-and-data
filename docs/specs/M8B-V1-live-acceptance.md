# M8B V1 — Live account-deep acceptance

- **Parent roadmap:** `M8B-exa-sumble-account-deep-integration-roadmap.md`, Slice V1
- **Attempted:** 2026-08-05
- **Branch:** `platform/c8-account-profiling-integration`
- **Code revision:** `c0661247bb7f`
- **Status:** **OPEN — live acceptance did not run and the release gate is not closed**

This record separates the current branch's passing mechanical evidence from the live provider and
agent-fleet evidence that M8B requires. A green offline suite, a reachable API, an exit-zero process,
or a provider contract fixture is not a successful V1 canary.

## 1. Required live outcome

V1 closes only after one bounded real account proves all of the following in one combined run:

1. a live Head-of-ABM model receives the current O3 steering context and confirmed A2 directive;
2. an explicit `launch_account_deep@1` invocation creates the immutable O2 launch and enqueues the
   existing detached fleet;
3. the existing `AccountDeepOrchestrator` makes one target-locked Exa Deep request for one or two
   registered fields, then materializes grounded, verification-governed account claims;
4. the same account passes S2D and makes bounded Sumble Teams and People calls without contact
   reveals, retaining credits, raw artifacts, identities, committee candidates, role/persona
   inferences, and coverage;
5. claims, evidence, target locks, receipts, cost/credits, run references, waits, projections, and
   provider request ids are inspectable from another process; and
6. a fresh-process replay makes zero Exa, Sumble, or model/provider-spend calls and preserves the
   same terminal state.

No authenticated provider request or live model call occurred in this attempt, so none of these
live conditions has been proved.

## 2. Preflight result

The checkout's effective environment was inspected by variable name and typed settings only;
secret values were neither printed nor copied.

| Requirement | Effective state | Result |
|---|---|---|
| `CLUE_EXA_API_KEY` | absent/blank | blocks Exa Deep |
| `CLUE_SUMBLE_API_KEY` | absent/blank | blocks Teams/People |
| `CLUE_OPENROUTER_API_KEY` | absent/blank | blocks the live Head agent and role/faithfulness calls |
| `CLUE_EXA_ACCOUNT_DEEP_ACQUISITION_ENABLED` | default `false` | correctly authorizes zero new Exa requests |
| `CLUE_SUMBLE_COMMITTEE_ACQUISITION_ENABLED` | default `false` | correctly authorizes zero Teams/People requests |
| `CLUE_GATEWAY_ALLOW_STUB` | `false` | production correctly refuses canned model output |
| account-agent routing | disabled | no governed live account-agent turn is selected |
| `CLUE_SUMBLE_CENTS_PER_CREDIT` | `0` | provider credits can be retained, but no honest monetary conversion is configured |
| Postgres | reachable at a branch-local endpoint | pass |
| Alembic | one head, `a83e52bebc7c` | pass |

The correct fail-closed result was zero authenticated provider calls, zero provider operation rows,
and zero `agent_model_call` rows. Enabling a feature without its corresponding credential is not an
acceptable workaround.

## 3. Mechanical acceptance rerun

A regex-bounded disposable database, `roseau_v1_9b3f7d2c4a61`, was created and migrated from an
empty database to `a83e52bebc7c`. The complete slice-owned surface was rerun against it:

| Slice | Exercised evidence | Result |
|---|---|---|
| A0 | Exa and Sumble strict/additive-tolerant request/response contracts | pass |
| A1 | additive deep handoff fixture, source authority, direct/composed paths | pass |
| A2 | durable human-confirmed directive, context, exact pins and replay | pass |
| E0 | bounded Exa structured request and grounded normalization | pass |
| E1 | durable coalescing, settlement, crash and HTTP classification | pass with recorded transport |
| E2 | exact snapshot materialization, source-plan binding and verification | pass with recorded transport |
| S2A | v9 Teams/People bounds, no-reveal selection and normalization | pass with recorded transport |
| S2B | async acquisition, polling, response-before-normalization, settlement and replay | pass with recorded transport |
| S2C | exact-account snapshot-backed committee candidates and identity admission | pass |
| S2D | every eligibility/governance denial creates zero paid operation rows | pass |
| O1 | provider-neutral wait/resume outside claim transactions | pass |
| O2 | immutable launch, Sumble preparation, Exa preparation and full-unit composition | pass mechanically |
| O3 | seven scripted non-linear conversations and steering-card materialization | pass mechanically |
| V0 | frozen 32-case fault manifest, migration round trip, concurrent and fresh-process replay | pass |

The focused surface passed **170/170 tests**. The complete repository suite collected 3,348 tests
and completed with **3,337 passed, 11 expected skips, 0 failures**. Mypy passed 515 source files;
all 24 import contracts were kept; and Ruff passed all 1,073 tracked Python files. A broad
`ruff check .` additionally inspected user-owned untracked `.claude/` and `.codex/` skill copies
and reported their intentional CLI `print` statements; those files are outside the repository and
were not changed.

The tests left no `external_research_operation`, `committee_acquisition_operation`,
`account_deep_launch`, `gate_decision`, or `agent_model_call` rows. Twelve fixture claims from
tests that deliberately commit were isolated inside the disposable database and are not live
research evidence.

## 4. Live blockers found

### 4.1 Credentials and spend switches are absent

This alone prevents every required live canary. `build_platform_gateway` correctly refuses to
start a production fleet worker without the OpenRouter key because stub output is default-off.
The Exa and Sumble production builders likewise keep paid acquisition unavailable under their
independent default-off switches.

### 4.2 The synthetic A1 account cannot be the live target

The only A1 account is `Cascade Gastroenterology Associates` at `cascade-gastro.example`, with
fixture-only Sumble ids, URLs, people, and discovery evidence. `.example` is deliberately
non-resolvable. Sending it to Exa or Sumble would not test target locking or real committee
coverage. V1 needs a real canonical account/domain plus a successful exact-account Sumble
organization identity snapshot before S2 can start.

### 4.3 No runnable production surface joins O3 conversation to O2 launch

The current pieces exist, but no shipped executable composes them into the V1 path:

- `Stage0Trial` is the only executable that runs `HeadOfAbmStage0Runtime`; its governed surface
  explicitly withholds `launch_account_deep` and all external account-deep acquisition.
- `fleet_main` composes the real Exa provider, Sumble preparer, `launch_account_deep` toolbelt,
  queue, driver, fleet, and orchestrator, but it does not expose or run the user-facing Head-of-ABM
  turn surface.
- `prepare_account_deep_steering_context` has no production caller. Repository search finds only
  its definition and `test_o3_account_deep_context.py`.
- the projections executable builds read/projection services; it is not a Head-agent launch
  endpoint and does not compose the full-unit committee capability.

Therefore the required `conversation -> directive -> explicit launch -> fleet` canary cannot be
invoked through one production-composed surface today, even after credentials are supplied. A
temporary direct-tool harness could test O2/fleet mechanics, but it would not close O3 or the V1
combined gate.

### 4.4 Sumble's mutable contract must be re-frozen before spend

The S2 acceptance pins the 2026-08-03 v9 OpenAPI SHA-256
`8eac8f9b74afb74f1bd4f593ee2baa4547d2ca80947feea581e91e551a97c887`. A non-authenticated fetch
on 2026-08-05 returned HTTP 200 for `https://api.sumble.com/openapi.json?version=v9`, but its raw
SHA-256 is now `c6f1324366a94844932ee3522caee6aa9f428f7d958a9956bea3425d18e2811c`.

The explicit v9 document still advertises `POST /v9/teams` and `POST /v9/people`, including the
bounded Teams request and async People `request_id`/status fields used locally. However, Sumble's
current public guide now presents a v3 synchronous `POST /v3/people/find` product surface. The raw
v9 digest change may contain additive unrelated changes, but the exact delta has not been accepted
against the frozen S2 source map. A0 requires this mutable provider boundary to be reviewed and
re-pinned, not guessed through a paid call.

## 5. Exact next acceptance run

Do not mark M8B complete yet. The next run requires:

1. configure the three credentials in this checkout without copying them from another worktree;
2. explicitly enable only account-deep Exa and no-reveal Sumble committee acquisition;
3. set an honest Sumble credit-to-money policy (or explicitly accept credit-only settlement);
4. re-review and pin the current v9 Teams/People subset;
5. seed one real, consented account with the synthetic upstream governance state and a real S1
   organization match;
6. expose one production-composed Head-of-ABM turn path that receives the O3 artifacts and can
   invoke the existing O2 launch; and
7. run the four V1 steps in increasing scope under explicit caps, then perform the fresh-process
   forbidden-transport replay and inspect every durable evidence surface.

Until all seven are satisfied and the combined canary produces non-empty verified account and
committee output, M8B remains **mechanically implemented but not live accepted**.
