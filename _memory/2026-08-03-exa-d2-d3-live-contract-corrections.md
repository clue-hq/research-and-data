# 2026-08-03 — Exa D2/D3 live contract corrections

## Scope and authority

- Branch: `platform/c8-exa-sumble-discovery`.
- This note supersedes the earlier D2/D3 notes only where they say the live gate is blocked by
  Websets entitlement. Historical 401/not-charged operations remain immutable evidence.
- No Sumble, D4 identity/materialization, or general Exa Search implementation was added.

## Live characterization

- A bounded two-result synchronous Exa `/search` probe reported USD 0.007 and returned additive
  production fields (`searchTime`, result `score`). Production accepted legacy `type=neural` even
  though the published OpenAPI enum has moved. Search remains a separate synchronous/dollar-billed
  contract from Websets.
- Search-only Webset `webset_01kz2b6wcyb25pzt3c83s7vhs2` completed with two search-sourced company
  items, three `yes` criteria per item, 20/20 credits, 8.980/8.980 cents Pro-allocation equivalent,
  and terminal zero-call D2/D3 replay.
- Enriched Webset `webset_01kz2bbfchtsxxqn8segpd6nkx` completed on its original durable operation
  `49f594bf-2714-421a-9fd4-0e3ee4e1e972`. It produced one search-sourced company item, three `yes`
  evaluations, completed URL/number/email/phone results, a terminal-null number result, and one
  email plus one phone. Settlement was exactly 24 credits: 10 search + 4 ordinary rows + 10 contact
  values; 10.776 cents Pro-allocation equivalent. Terminal replay made zero poll/item/event calls.
- Live enrichment definitions normalize email/phone formats to `text`; item results retain
  `email`/`phone`. Field-key metadata survives, but provider array order is not request order.

## Corrections delivered

- `9a10966`: pinned strict current Websets models and sanitized live-shaped fixtures; response
  matching is order-independent by criteria and logical field key; nullable enrichments and full
  events are accepted; company HQ/financial fields survive raw snapshots. D4 projection is limited
  to approved company fields and excludes `foundedYear` and `webTraffic`.
- `fa76836`: fail-closed item identity/source/entity/criteria/enrichment reconciliation; exact
  credit breakdown; pre-dispatch provider-unit and monetary reservations; team-level webhook
  provisioning/routing after global Webset resolution; multi-search batch barrier; current company
  projection coverage; and adversarial real-DB tests for the reviewed drift cases.
- Migration `fe7d6c0aee8a` adds provider-neutral `cost_cents_reserved` to operation and batch and is
  reversible.

## Verification state

- Adapter/wiring units: 18 passed.
- Final D0–D3 contract/unit/real-DB matrix: 57 passed; one D1 committed-gate test deliberately
  skipped because `CLUE_D1_COMMITTED_GATE=1` is allowed only on a throwaway database.
- Full mypy: 467 source files passed.
- Import contracts: 24 kept, 0 broken.
- Ruff on changed source/tests passed.
- Disposable migration database passed `head -> base -> head` and was dropped; it contained only
  migration-smoke data. The named `clue_discovery_fixture` database remains at head with both live
  terminal operations and artifacts.
- Repository-wide `make check` remains blocked before tests by 14 pre-existing Ruff-format failures
  in unrelated C7/research-view files. Those files were not changed. The Exa changed-file format,
  lint, type, contract, and targeted test gates are all green.

## Boundary after D3

- D3 ends at immutable raw item snapshots and an `identity_resolution` batch. D4 still owns
  normalization, identity admission/deduplication, typed claims, field dispositions, and the
  approved company-field projection.
- The monetary counters are a pinned subscription-credit allocation equivalent because Exa does
  not expose operation-level card charges. They must not be presented as external billing
  telemetry.
