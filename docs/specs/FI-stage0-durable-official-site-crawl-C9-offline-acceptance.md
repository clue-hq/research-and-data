# FI Stage-0 durable official-site crawl — C9 offline acceptance

**Status:** implemented 2026-08-14

**Parent plan:** [FI-stage0-durable-official-site-crawl-plan.md](./FI-stage0-durable-official-site-crawl-plan.md)

**Executable matrix:** `tests/fixtures/official_site/c9_acceptance_matrix.json`

## 1. Slice boundary

C9 is the provider-free release gate over C0–C8. It proves the complete frozen §20 matrix against
real PostgreSQL while every network/provider boundary is a deterministic fake. It also performs
the migration, frontend, backend static/type/import, and critical-review gates.

C9 does not:

- make Firecrawl, Scrapling, OpenRouter, Clerk, or browser calls;
- change the default-off rollout or the fast Client-KB release rule;
- claim the ≤40-second live target, provider billing reconciliation, or browser/API/log/database
  correlation. C10 owns those live acceptance claims;
- repair unrelated repository-wide baseline defects merely because the monolithic suite exposes
  them. C9 records and independently reproduces them so they cannot be confused with crawl
  regressions.

## 2. Executable §20 matrix

The JSON manifest maps all 53 acceptance rows to executable pytest node IDs. A pure guard parses
the referenced Python modules with `ast`, verifies every file and function exists, enforces the
exact per-section cardinalities, and refuses an empty or malformed node list.

| Section | Cases | Primary subject |
|---|---:|---|
| §20.1 | 6 | frontier, dedupe, shorter path, later-run freshness |
| §20.2 | 7 | lease fencing and crash recovery |
| §20.3 | 8 | conservative URL/graph/sitemap policy |
| §20.4 | 5 | SSRF, DNS, robots, redirect, MIME, size, link safety |
| §20.5 | 7 | provider conformance, spend, reconciliation, receipt hygiene |
| §20.6 | 6 | content dedupe, URL provenance, grounding, retention reach |
| §20.7 | 8 | fast/background lifecycle, fairness, progress, partial recovery |
| §20.8 | 6 | bounded extraction, explicit empties, replay, model config, tier |

The same manifest separately names all nine C4/C5 crash boundaries:

1. prepared before dispatch;
2. dispatched with operation lookup;
3. dispatched without operation lookup;
4. provider success with a retained result;
5. provider success with a retrievable result;
6. provider success with no recoverable result;
7. persistence committed before page completion acknowledgement;
8. retryable confirmed-no-spend failure;
9. terminal policy/robots refusal.

The complete C0–C9 target is intentionally a superset of the manifest node IDs. This keeps the
contract fixtures, adapters, repositories, lifecycle, setup wiring, and C8 projection tests in the
same isolated-database gate rather than allowing a hand-selected C9 list to hide a predecessor
regression.

## 3. C9 hardening findings

The adversarial review found and closed four cross-slice defects.

### 3.1 Recovered results now pass coordinator safety

Previously, a normal `fetch_one` success passed redirect/DNS/domain/MIME/size/link validation, but
a success recovered through provider operation lookup went directly to acquisition persistence.
An external redirect or oversized recovered body could therefore bypass the C2 coordinator
boundary. `ConcurrentCrawlCoordinator` now wraps `ProviderOperationLookup` with the same shared
post-response validator used by ordinary fetches.

Tests prove a valid receipt is persisted without a new provider call, while external, oversized,
forged-request, and forged-provider results are quarantined with no snapshot.

### 3.2 Cold reconciliation carries the provider receipt identity

`provider_request_id` existed durably on the fetch-attempt row but was missing from the body-free
`FetchAttemptRef`; the coordinator consequently invoked lookup with `None`. The additive attempt
reference now carries the stored ID, the repository hydrates it, and reconciliation supplies it to
the lookup adapter. This permits a lookup-capable paid provider to reconcile the original charged
operation rather than issuing a second acquisition.

### 3.3 Provider evidence cannot forge coordinator-owned provenance

A provider result is evidence, not authority over which URL or provider Clue invoked. Successful
ordinary or recovered responses whose `requested_url` or `provider_key` differs from the
coordinator-owned request/capability are now refused. Before persistence, the refusal restores the
trusted request URL and provider key, drops bytes/links, and retains the spend metadata. This
prevents a malformed receipt from forging URL/provider provenance without hiding a possible
charge.

### 3.4 Retention reach covers the complete C1–C7 graph

The C4 evidence-reach reader originally enumerated runs, attempts, snapshots, and page blobs only.
C9 extends it, workspace/run scoped, to:

- crawl pages;
- URL observations;
- graph edges and alias observations;
- fetch attempts and URL-level snapshots;
- immutable corpus checkpoints;
- extraction operations and retained model-response artifacts;
- ordinary official-site claims and their evidence artifacts.

Claim reach follows the claim's durable `source_operation_ref`, not only the extraction row's
eventually consistent `claim_ids_json`. A simulated crash after claim insertion but before the
terminal operation-summary update remains fully reachable. Declared claim IDs that cannot be
resolved within the same workspace fail closed. Identical content still has one blob and distinct
URL snapshots; a conflicting canonical hint with different bytes remains distinct.

Physical erasure remains owned by the existing workspace/claim/artifact lifecycle. C9 adds the
complete read-only dependency reach required to perform that lifecycle safely; it does not add a
new destructive purge path.

## 4. Acceptance evidence

### 4.1 Fresh official-site database

The final hardened run used the newly created database
`clue_c9_official_site_20260814_final_v2`. It was absent before creation, upgraded from an empty
database to the sole Alembic head `a57463ec42ea`, and then ran the complete C0–C9 target once:

```text
200 passed
```

The database remains retained for review. Provider fakes made every acquisition/model boundary
offline; no Firecrawl, Scrapling, OpenRouter, or browser traffic occurred.

### 4.2 Migration gate

- `alembic heads` returned exactly `a57463ec42ea (head)`.
- A separate fresh database, `clue_c9_official_site_20260814_v2`, completed
  `upgrade head -> downgrade base -> upgrade head`.
- The repository's three migration tests passed 3/3 in isolation on
  `clue_c9_migration_isolated_20260814`.
- The retained final acceptance database contains exactly one `alembic_version` row:
  `a57463ec42ea`.

### 4.3 Backend static/type/import gates

- Ruff format and lint: 1,392 files, green.
- mypy strict gate: 658 source files, zero issues.
- import-linter: 25 contracts kept, zero broken.
- Focused C9 adversarial module after final hardening: 13 passed.

### 4.4 Frontend gates

- Node test suite: 228 passed, zero failed.
- design-system token build: passed.
- ESLint: passed.
- Next.js production build and TypeScript: passed; all 19 static-generation units completed.

The first sandboxed Next.js build stopped making progress during optimization and was interrupted.
The same build outside the restricted sandbox compiled successfully. This is an execution-sandbox
constraint, not an application failure.

## 5. Repository-wide baseline separation

The monolithic backend suite was executed twice: first after the C9 target populated its database,
then on a separately created untouched database `clue_c9_backend_baseline_20260814`. The latter
still finished with 36 failures and 25 expected environment skips. None is caused by the C9 diff:

- Three independent baseline failures reproduce outside the monolithic run:
  1. an agent-registry test expects obsolete `.deepagent/skills/stage0-interview/v9/SKILL.md`;
  2. the logging-discipline scanner enters the root-config-excluded `subsystems/clue-design`
     tree and reports that subsystem's separate logging stack;
  3. one C6.3 context test fixture emits no `current_user_instruction`, while the current runtime
     correctly requires exactly one.
- The three destructive migration tests pass 3/3 alone, but fail inside the monolithic run while
  session-scoped database fixtures/connections from earlier modules are still active.
- The remaining 30 failures occur after that shared-schema failure and are registry/schema
  cascades. Representative errors are same-version source-manifest redefinitions and missing
  schema state. A Lane-D test from this set passes independently.
- Running the C9 matrix on a database previously used by another target also reproduced the
  source-manifest collision; the pristine C9 database eliminated it.

This is the plan's required separation: C9's isolated DB gate is green, the shared/global baseline
is red for independently reproduced pre-existing test-isolation/fixture defects, and there are no
unexplained failures attributed to the crawl implementation. Those global defects are not silently
weakened or repaired in this slice because they belong to agent-resource, design-union lint, and
test-harness ownership—not official-site crawling.

## 6. Critical/adversarial exit review

The final review checked lease generation on every worker publication, lookup safety parity,
provider/request identity, paid-call retry behavior, content-versus-provenance dedupe, cross-
workspace reads, claim/artifact reach after partial persistence, manifest completeness, migration
head count, diff whitespace, static types, and import direction.

All C9-owned P1/P2 findings were resolved before the last pristine run. No unresolved C9 P1/P2
finding remains. C10 is still required before enabling the feature or making live performance,
billing, browser, or provider-parity claims.
