# M8B E0 — Exa Search Deep wire acceptance

- **Parent roadmap:** `M8B-exa-sumble-account-deep-integration-roadmap.md`, Slice E0
- **Contract authority:** `M8B-A0-account-deep-provider-contract-acceptance.md`
- **Recorded:** 2026-08-04
- **Status:** mechanically accepted; no live provider call authorized or made
- **Endpoint:** `POST https://api.exa.ai/search`
- **Official reference:** `https://exa.ai/docs/reference/search`

E0 replaces the old synchronous `type="neural"`/unstructured-highlights wire with the accepted
Search Deep structured contract. It deliberately stops before durable acquisition, snapshots,
settlement, claim materialization, production composition, or live validation.

## 1. Implemented boundary

`clue_research.resolvers.exa.compile_exa_deep_request` receives:

1. one resolved `AccountEntity`;
2. one to eight admitted `ExaDeepFieldSpec` values containing an effective registry field key and
   its exact `value_schema`;
3. bounded research intent and zero to ten directional queries supplied as plain values;
4. an injected `ExaDeepConfig` policy.

It emits one immutable `ExaDeepSearchRequest` with:

- explicit `deep` or `deep-reasoning`, never `neural`;
- product-capped `numResults <= 50` and policy-capped `additionalQueries <= 10`;
- canonical name/domain and available alias/geography target-lock material;
- a deterministic, sorted, closed `outputSchema` compiled only from admitted registry fields;
- every requested field required but nullable so evidence misses are represented as `null`;
- constrained registry schemas preserved behind a schema union rather than weakened;
- source-URL, no-drift and leave-null instructions in `systemPrompt`;
- `contents.text`, highlights and `stream=false`.

Research intent and directional questions can change query strings only. They never contribute an
output key or schema. This is the explicit integration seam with the parallel A2 lane: E0 imports
no directive table/model and A2 need not import a provider type.

## 2. Accepted response and normalization

The additive response parser consumes the frozen A0 models and proves the returned structured
field set exactly equals the request field set. A settleable response requires `requestId`,
`costDollars.total`, results, structured content and field-level grounding whose citation URLs
resolve to retained results.

Normalization emits a provider-neutral `SynthesizedField` only when:

- the structured field value is non-null;
- that field has grounding;
- a cited retained result has a non-empty highlight;
- when result text is present, the evidence span occurs in that retained text;
- the configured grounding-confidence threshold passes.

Missing or unmatched URLs make the success non-settleable; a missing grounding row fails the
structured response; a spanless citation is omitted. Deprecated `resolvedSearchType`/`context`
and other additive response members do not control behavior. Reported dollars are converted for
the existing provider-neutral compatibility result but are not treated as a reservation or final
billing reconciliation.

## 3. Dispatch and failure boundary

The E0 compatibility backend exists only to keep the stable `SynthesisBackend` seam usable while
E1 is built. It requires the exact field schema before credential resolution and passes `retries=0`
to an injected transport. It never loops after a possibly paid dispatch.

| Condition | E0 classification | Dispatched |
|---|---|---|
| Missing schema, missing credential, invalid request | `hard` | no |
| Pre-dispatch transient classification | `retryable` | no |
| HTTP 402 | `budget` | as recorded by caller/transport |
| Post-dispatch timeout, 429 or 5xx | `spend_unknown` | yes |
| Malformed/non-JSON/missing-cost 2xx | `spend_unknown` | yes |
| Other hard 4xx | `hard` | yes |

E1 must own request fingerprinting, reservation, one-attempt durability, immutable raw artifacts,
provider request id, provisional settlement, reconciliation, quarantine and replay. E2 must own
snapshot-backed materialization, target-lock/verification, field-source-plan binding and production
composition. E0 creates no migration and edits no API composition module.

## 4. Exit-gate evidence

| E0 gate | Executable evidence |
|---|---|
| Frozen request remains stable | compiler output equals `deep_request.json`; A0 SHA-256 test remains green |
| Free text cannot inject a field | malicious intent/query test asserts the sole schema key remains the admitted registry field |
| Registry schema is deterministic and exact | reversed input order reproduces the golden; nested/constrained schema tests prove non-mutation and null union |
| Missing URL/grounding/span yields no candidate | strict unmatched-URL/missing-grounding tests plus spanless normalizer test |
| Additive/deprecated fields do not branch behavior | recorded response test adds both deprecated members and still normalizes by the accepted fields |
| Error/spend classification is honest | A0 status matrix plus E0 pre-dispatch and post-dispatch backend tests |
| No hidden retry/call | injected transport asserts one call and `retries=0` |
| Provider-neutral seams remain intact | Exa and Parallel resolver/waterfall tests retain distinct provider-neutral `SynthesisResult` inputs |

Verification commands are recorded in `_memory/2026-08-04-m8b-e0-exa-deep-wire.md`. All E0 tests
use frozen artifacts or injected doubles. The live canary remains V1 and requires separate user
authorization after E1/E2 integration.
