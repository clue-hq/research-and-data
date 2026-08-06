# M8D R10 — Cutover and live acceptance

> **Status:** implementation and database battery complete; credentialed canary pending.
> **Authority:** companion acceptance record for
> `M8D-entity-research-agents-and-shared-fleet-refactor-roadmap.md` R10 and §16.

## Cutover boundary

New account and contact research is separately launched through the active Head-of-ABM tools and
drained as `entity_research_job` work. Both subjects share one queue/lease/checkpoint/wait shell,
while immutable subject authority selects the account or contact `langchain.agents.create_agent()`
unit. The outer project `DEEP` phase remains quarantined and cannot auto-launch either fleet.

The active Head and research-specialist profiles no longer grant the retired account-gap-only or
contact-profile tools. Those addresses remain exact-replay-only for historical recipes; they are
not fallback composition. The inert `_account_agent_runtime_required` compatibility probe has been
deleted. Shared Exa/Sumble transports, immutable artifacts, durable operations, claims, costs,
verification, and historical recipe/profile resources remain intact.

The promoted source registry names `exa_deep` for the qualitative account/contact fields. It does
not manufacture a legacy `exa` or universal deterministic step. Sumble's account preflight accepts
an independently confirmed, exact running entity job even when the outer project is not in
`DEEP`; historical operations without that job authority retain the old phase gate.

## Executable release battery

`tests/fixtures/entity_research/r10_release_matrix.json` maps every numbered §16 criterion to its
executable evidence. The R10 test fails if a criterion or referenced evidence disappears. The
combined isolated-Postgres command is:

```bash
CLUE_DATABASE_URL=<isolated-dsn> .venv/bin/pytest -q \
  tests/unit/core/test_entity_research_r0_contracts.py \
  tests/agents/test_entity_research_runtime_r3.py \
  tests/agents/test_entity_research_tools_r4.py \
  tests/api/test_entity_research_tools_r4_db.py \
  tests/api/test_account_entity_research_r5_db.py \
  tests/api/test_account_research_fleet_composition_r6.py \
  tests/api/test_account_research_fleet_launch_r6_db.py \
  tests/api/test_account_research_fleet_r6_db.py \
  tests/api/test_contact_research_fleet_launch_r7_db.py \
  tests/api/test_contact_entity_research_r8_db.py \
  tests/api/test_entity_research_parallel_r9_db.py \
  tests/api/test_entity_research_cutover_r10.py \
  tests/contact_research/test_c6_contact_preparation.py
```

Current result: **126 passed** before the final R10 additions. The final count and static/migration
results will replace this sentence after the credentialed canary.

## Bounded credentialed canary

The retained acceptance harness is `scripts/13_m8d_r10_live_acceptance.py`. It refuses a non-fresh
database or absent explicit live-call acknowledgement. It seeds the synthetic prerequisite
handoff for the real `njbrainspine.com` target, confirms one directive, moves the outer project
away from `DEEP`, launches one account agent, waits/resumes through the exact wake seam, and then
requires control to return without contact research. It next records a separate human selection
for at most three strongly bound committee members and launches only those contact agents.

The hard authorization is 1,000 cents total: 700 for the account job and at most 300 for three
contacts. Sumble credits remain reported as native units when no honest cents-per-credit mapping is
configured; the report never invents a monetary conversion. Contact channel reveal is not run:
there is no concrete independent validator in production composition, and R10 explicitly forbids
an environment-toggle bypass. The offline battery proves this path fails closed.

The harness persists an acceptance JSON containing database/run identifiers, account and contact
fleet projections, provider/tool/result/evidence counts, native provider units, engine spend,
finalization/review outcomes, cold-resume count, and a fresh-composition replay comparison. It
does not copy secrets or raw personal/provider payloads into the report.

## Live-probe failure ledger and repairs (2026-08-06)

The first live canaries surfaced a defect ledger; every entry below is now repaired offline or
explicitly deferred. The Sumble wire contract itself is settled in
`M8D-R10-sumble-contract-decision.md` (v9 confirmed current; advanced-query grammar is
`EQ`+`AND` only; `/v9/teams` has no job-level query dimension; 4xx = validated zero-credit
rejection).

Repaired:

1. **Filter compiler** — the `job_function IN (...)`/`job_level IN (...)` compiler is deleted;
   committee Teams/People requests carry no advanced query; `SumbleAdvancedQuery` and the
   request builders enforce the documented grammar and per-endpoint dimensions at compile time.
   The committee plan's selectors remain durable authority for the local admission gate.
2. **Failure evidence** — a deterministic provider 4xx now persists as
   `FAILED_TERMINAL`/`NOT_CHARGED` with failure code
   `<source>_provider_rejected_http_<status>` plus a retained rejection-evidence artifact
   carrying the bounded provider error body; `spend_outcome_unknown` is reserved for genuinely
   ambiguous post-dispatch loss.
3. **Partial-provider failure policy** — engine policy, not an incidental exception path:
   model-repairable request violations and deterministic provider rejections surface to the
   agent as a typed `governed_research_rejection` error tool message (the job stays alive; the
   agent repairs, reroutes, or finalizes `NEEDS_REVIEW`); ambiguous spend and post-persistence
   integrity violations still suspend for the operator.
4. **Committee-plan authority** — the confirmed plan (functions, levels, teams, personas,
   candidate cap, questions) is projected into `read_account_research_state` and the initial
   task instruction, and the engine refuses a `buying_unit_scope` targeting functions outside
   the plan.
5. **Finalization looping** — a structural middleware guard refuses every governed tool call
   after the finalize tool returns its proposal; prompt guidance is no longer the only stop.
6. **Committee matching** — office/business-unit/function discriminators match provider-returned
   values only (never serialized JSON keys); the organization-wide rule matches the
   provider-returned employer organization name.
7. Mechanical: missing `UUID` import in `exa_contact_compiler`; stale authority/behavior tests
   updated to the promoted 48-tool surface and v2/v4 skills; `launch_account_research`/
   `launch_contact_research` gained real spend-gate model descriptions;
   `CLUE_AGENT_WORKSPACE_ALLOWLIST` parsing hardened; account-gap coordinator classification and
   harness env-isolation/contact-resume per the R5a hardening pass.

Deferred (documented in `_memory/2026-08-06-m8d-r10-adversarial-repairs.md`): whole-collection
multi-team evidence spans; `_select_row_evidence` duplicate-row hard failure; the reentrant
account lock's sibling-share semantics (the R9 wave admission is the operative guard); the
spend-guard `running`-state requirement versus a `waiting_external` resume — verify live.

**Whole-tree DB-enabled sweep (2026-08-06, first ever post-cutover):** running the entire test
tree against one isolated Postgres surfaced and fixed a suite hang (the E1 module drove the
quarantined `enrich_selected_accounts@1` address and parked forever on a dispatch event the
refusal could never set — converted to the preserved engine seam with a hang-proof wait), two
retired-flow acceptance tests (A1 full-production entry, O2 tool launch) converted to the
quarantine contracts, the `approve_contact_research_selection` @1→@2 name-default fallout in the
toolbelt matrix and the M8C C6 acceptance (now version-pinned), and the `exa`→`exa_deep`
tier-plan pins. Protocol note: the whole tree cannot share one database in a single invocation —
the M8D fleet tests commit durable rows by design (queue/lease semantics), after which older
modules' rollback-scoped fixture manifests collide on `(source_key, version)`; and the migration
smoke runs alembic down→up on `CLUE_DATABASE_URL`. Verification therefore runs each `tests/<dir>`
against its own freshly migrated disposable database, with `tests/db` on a dedicated throwaway.

## Live evidence

**ACCEPTED — 2026-08-07.** The full bounded live pass succeeded end to end in one fresh,
uninterrupted process (`scripts/13_m8d_r10_live_acceptance.py`, DB `clue_m8d_live9`, report
`.artifacts/m8d-r10-live/acceptance-live9.json`, `fresh_isolated: true`, target
`njbrainspine.com`):

- **Account fleet:** one live account job — Exa deep research + Sumble organization/committee
  acquisition (async People wait → durable suspend → wake → exact checkpoint resume; the drive
  survived **2 cold recompositions**) — terminal with an engine finalization receipt (honest
  `needs_review`: unresolved fields routed to review, never fabricated).
- **Committee → separate human contact selection:** one strongly-bound committee member selected
  under the C1 lineage trigger; `validator_bypass_used: false`.
- **Contact fleet:** the selected contact's job ran live Exa, completed
  `contact.facet.recent_post`, terminal `completed` with an engine finalization receipt. Zero
  unselected-contact requests; zero account-tool requests from the contact lane.
- **Ledger:** 4 live provider operations (2 Exa, 1 Sumble account, 1 Sumble committee @58
  credits), 9 result fields with 9 evidence rows, 6.1¢ Exa-reported spend against the 800¢
  authorized envelope (1000¢ hard cap). Journal: 2 proposals / 2 acceptances, **zero
  `tool_failed` events** — the runtime's deterministic post-finalization termination
  (`5f23b2fb`) held live.
- **Zero-spend replay:** both launch actions re-ran against a fully rebuilt composition, joined
  the same research runs, and the complete provider/spend ledger was byte-identical.

Prior live rounds (runs 1–8, DBs `clue_m8d_live1..8`) form the failure ledger above — eleven
live-only defects found and fixed across them; run 8 (`acceptance-live8-resume.json`) is the
corroborating pass on a second key with two contact jobs completed. Spend across the entire
campaign stayed within the authorized $10/provider budgets.
