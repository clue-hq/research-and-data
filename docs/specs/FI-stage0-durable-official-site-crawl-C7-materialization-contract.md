# FI Stage-0 durable official-site crawl — C7 materialization contract

**Status:** implemented and verified, 2026-08-14

**Parent authority:**
[`FI-stage0-durable-official-site-crawl-plan.md`](./FI-stage0-durable-official-site-crawl-plan.md)

**Prior slice:**
[`FI-stage0-durable-official-site-crawl-C6-composition-contract.md`](./FI-stage0-durable-official-site-crawl-C6-composition-contract.md)

**Executable authority:** `clue_research.official_site.materialization`, migration
`a57463ec42ea`, and the C7 tests under `tests/official_site/`

**Next authority:** C8 owns progress/read surfaces and operator recovery; C9 and C10 retain the
full adversarial, browser, provider, and rollout gates.

## 1. Scope and outcome

C7 implements the boundary from one immutable official-site corpus checkpoint to ordinary,
append-only Client-KB claims. It does not fetch URLs, expand the crawl graph, choose Firecrawl or
Scrapling, expose browser progress, or turn the feature flag on globally.

The production path is now:

```text
immutable fast/background checkpoint
  -> verified workspace artifact reads
  -> deterministic category/field operations
  -> bounded concurrent OpenRouter calls
  -> exact snapshot + URL + evidence-span validation
  -> append-only client.* claims with source_key=official_site
  -> materialization result containing references and field outcomes only
```

The existing C6 lifecycle injects this materializer only in `authoritative` mode. `off` remains the
default, `shadow` continues to acquire/checkpoint without publishing C7 claims, and every enabled
mode still requires an explicit workspace allowlist.

## 2. Frozen extraction identity

The extraction contract pins:

| Dimension | C7 value |
|---|---|
| Prompt | `official-site-extraction-prompt-v1` |
| Schema | `official-site-extraction-schema-v1` |
| Corpus normalization/selection | `official-site-corpus-v1` |
| Default model | `openai/gpt-5.6-luna` |
| Alternative model | `openai/gpt-5.6-terra` |
| Logical claim source | `official_site` |
| Extraction concurrency | 4 by default, bounded 1–16 |
| Per-operation corpus cap | 80,000 characters, frozen in corpus-version semantics |

The operation identity covers workspace, checkpoint, claim run, category, field, requested model,
prompt/schema/corpus versions, and an input digest over the exact ordered snapshot IDs, content
hashes, and URLs. Concurrency is operational only and does not change semantic identity. The
corpus cap is deliberately not runtime-configurable: changing it without changing the corpus
version would make one identity observe different evidence.

## 3. Corpus reader and category policy

`OfficialSiteCorpusReader` fails closed unless all of the following are true:

- checkpoint, crawl run, recon run, workspace, and phase agree;
- every checkpoint snapshot exists in that exact workspace/run;
- returned membership exactly equals the immutable checkpoint snapshot set;
- every artifact exists, passes PB-B2 digest verification, and matches the snapshot hash.

All artifact reads finish before model concurrency begins. HTML normalization decodes bytes
deterministically, excludes `script`, `style`, `template`, `noscript`, and `svg` content, and never
executes page code.

Operations are grouped deterministically as:

- `product_value`: value proposition, product, and differentiator;
- `pricing_proof`: pricing posture and proof point;
- `customer_evidence`: customer, ICP evidence, delivered value, and market reputation;
- `company_context`: value proposition and differentiator evidence from company, founder, partner,
  integration, trust, and homepage categories.

A category with no eligible checkpoint page becomes terminal `empty` without a model call. C7 does
not manufacture new field definitions merely to preserve prose.

## 4. Grounding and hostile-page boundary

Page bytes and text are always untrusted data. The system prompt tells the extractor not to follow
page instructions, but correctness does not depend on prompt obedience. The validator accepts a
draft only when:

1. its snapshot ID belongs to the operation's checkpoint subset;
2. its URL exactly equals that trusted snapshot's final URL;
3. its non-empty quote occurs verbatim in that same snapshot's normalized text;
4. confidence is numeric and inside the frozen range; and
5. the value passes the existing field schema and claim-store admission path.

The platform—not the model—sets the artifact key, fetch-attempt reference, snapshot reference,
source URL, logical source, tier, run, workspace, entity, research mode, and reuse scope. A page or
model result can therefore contain forged headers, URLs, snapshot IDs, or instructions without
forging persisted provenance.

## 5. Durable operation protocol

Migration `a57463ec42ea` adds `official_site_extraction_operation` and tenant/run/checkpoint/entity/
artifact foreign-key anchors. Its state machine is:

```text
prepared -> dispatched -> response_retained -> materialized | empty | failed
                      \-> spend_unknown
prepared -> empty                 (no category pages; no call)
```

The worker commits `dispatched` before model egress. Exactly one worker can win that transition.
An observed live dispatch is awaited and then returned as pending; it is never called a second
time. A call exception or an unreconciled stale dispatch becomes `spend_unknown`. A successful raw
response is content-addressed and digest-verified before parsing. Replay reads that retained
response and performs persistence only.

Requested and answering model IDs are stored separately, with token usage, measured-or-zero cost,
response artifact/hash, exact snapshot IDs, claim IDs, and terminal failure code. Raw prompts,
page text, responses, tokens, credentials, and user data never enter logs.

## 6. Concurrency, transaction isolation, and partial success

The materializer uses a bounded asyncio semaphore and moves the synchronous shared gateway call to
a worker thread. Every corpus query, operation transition, artifact verification, and claim write
opens its own transaction from the injected connection factory. No SQLAlchemy connection crosses
an extraction task or thread.

Each category/field pair is an independent durable operation. Invalid citations, malformed output,
schema-invalid values, empty results, and provider ambiguity affect only that operation. A valid
sibling field commits independently. The final result partitions the nine logical fields into
disjoint `filled_fields`, `empty_fields`, and `failed_fields`; if one category fills a field while a
second category fails, the logical field remains filled.

Claims use `source_key=official_site`, tier 2, the trusted page artifact and URL, exact extraction/
snapshot/fetch references, the existing Stage-0 claim run and Client-KB version, tenant-private
reuse, and ordinary append-only claim-store validation. Fetch/provider cost remains on durable
fetch attempts; model cost remains on extraction operations; derived claims do not duplicate it.

## 7. Source-key cutover boundary

C7 publishes new durable-path claims under the provider-neutral `official_site` source. It does
not rewrite historical `firecrawl_site`/`scrapling_site` claims.

The global legacy Client-KB `tier_plan` is intentionally unchanged in C7. Moving that global plan
now would disable the current default-off/shadow onboarding path before the C9/C10 rollout gates.
The provider-name removal and legacy resolver unbinding therefore occur atomically at the later
authoritative cutover. This is consistent with C0's ruling that the historical resolver is unbound
for the **new run path at authoritative cutover**, not during an earlier default-off slice.

## 8. Verification evidence

### 8.1 Static, unit, integration, and migration

- Ruff and mypy pass for C7 source, API composition, tests, migration, and live canary.
- Root import-linter passes all 25 contracts. C7 owns frozen materialization field keys and verifies
  the committed field registry instead of importing or seeding the sibling legacy Stage-0 worker.
- Pure grounding tests cover HTML active-content stripping, absent snapshots, forged URLs,
  paraphrased spans, forged result headers, and the real OpenRouter gateway shape through doubles.
- Both Luna and Terra model IDs pass unchanged through the OpenRouter Responses gateway double.
- Database tests prove 11 concurrent category/field operations across nine logical fields,
  independent live DB connections, strict workspace/checkpoint provenance, partial failure,
  spend-unknown quarantine, and exact replay with no new calls or claims.
- The complete C0–C7 official-site suite passes; the final official-site + API composition rerun
  passed 146 tests and the combined C0–C7/API/legacy Stage-0/settings gate passed 204 tests on a
  separate disposable database.
- Migration `a57463ec42ea` passes fresh upgrade and downgrade/upgrade and leaves one Alembic head.
- The legacy Stage-0 tests that first exposed premature global `tier_plan` cutover all pass after
  restoring the correct rollout boundary.

### 8.2 Retained live Firecrawl + OpenRouter acceptance

The bounded canary in `scripts/17_official_site_c7_live.py` ran against `insighthealth.ai` using:

- database `clue_c7_official_site_20260814_v2`;
- artifact root `/private/tmp/clue-c7-official-site-20260814-live-artifacts`;
- crawl run `be78aa55-874f-4808-aadf-31f0df3252aa`;
- requested and served model `openai/gpt-5.6-luna`.

Retained aggregate evidence:

| Measure | Result |
|---|---:|
| Page nodes / provider attempts / snapshots | 16 / 16 / 15 |
| Fast / background checkpoint snapshots | 7 / 15 |
| Extraction operations | 22 |
| Materialized / failed / spend-unknown operations | 19 / 2 / 1 |
| Provider-neutral official-site claims | 22 |
| Claims outside checkpoint provenance | 0 |
| Cold-replay provider-attempt delta | 0 |
| Cold-replay extraction-operation delta | 0 |
| Cold-replay claim delta | 0 |
| Cold-replay duration | 0.020 s |

The two failed operations were exact-citation validation failures for company-context value
proposition extraction; the same logical field was independently filled by the product/value
group. One fast ICP-evidence call ended in `GatewayError` and remains `spend_unknown`; its siblings
committed, and background later filled all nine logical fields.

The first live process also exposed a C8/C10 operational concern: pre-attempt page leases required
expiry/reclaim, so the retained run needed 17 bounded handler invocations and 135.656 seconds to
reach final background completion. C7 did not hide or bypass the leases and never duplicated a
completed page or model operation. This does not invalidate C7 grounding/idempotency, but it means
the ≤40-second product-release gate is **not yet proven** and remains explicitly open for C8
operator recovery and C10 live/browser acceptance.

## 9. Exit verdict and remaining gates

C7's implementation exit gate is accepted:

- an extractor cannot cite a URL or snapshot absent from its checkpoint;
- forged headers/page instructions cannot forge stored provenance;
- concurrent extraction shares no DB connection;
- Luna and Terra configuration pass through OpenRouter gateway doubles;
- same-checkpoint replay creates zero new provider/model work and zero duplicate claims;
- live Firecrawl + Luna acquisition/materialization/replay is retained and correlated.

This is not production cutover approval. C8 must add truthful progress and operator recovery;
C9 must run the full adversarial/fresh-database gate; C10 must prove browser identity through live
provider receipts and either meet the 40-second fast-release target or record a typed exception.
