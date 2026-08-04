# M8B E0 — Exa Search Deep wire acceptance

- **Parent roadmap:** `M8B-exa-sumble-account-deep-integration-roadmap.md`, Slice E0
- **Contract authority:** `M8B-A0-account-deep-provider-contract-acceptance.md`
- **Recorded:** 2026-08-04
- **Status:** E0-R1 request correction and E0-R2 response correction accepted mechanically; no
  live provider call authorized or made
- **Endpoint:** `POST https://api.exa.ai/search`
- **Official reference:** `https://exa.ai/docs/reference/search-api-guide-for-coding-agents`

E0 replaces the old synchronous `type="neural"`/unstructured-highlights wire with a Search Deep
structured contract. The 2026-08-04 critical review reopened the original closure. E0-R1 corrects
the outbound provider request and E0-R2 closes truthful response/evidence semantics plus the
pre-E1 dispatch fence. E0 stops before durable acquisition, snapshots, final settlement, claim
materialization, production E1 composition, or live validation.

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
- reversible hex aliases for top-level provider properties, never dotted registry keys; the fixed
  `systemPrompt` pins each exact `alias=field_key` mapping so provider grounding paths and literal
  registry names cannot be confused;
- at most ten total declared properties and at most two named property levels, including nested
  object/array-item properties; unsafe names, unsupported schema composition, or an over-budget
  bundle fail before credential lookup or dispatch;
- every requested field required but nullable so evidence misses are represented as `null`;
- one standard `type: [T, "null"]` representation; constrained schemas remain intact and nullable
  enums gain an explicit `null` member without mutating the registry input;
- source-URL, no-drift and leave-null instructions in `systemPrompt`;
- `contents.text.maxCharacters=10000`, query-guided
  `contents.highlights.maxCharacters=2000`, and `stream=false`; these are explicit account-deep
  product budgets rather than claimed provider maxima, while deprecated `numSentences` and ignored
  `highlightsPerUrl` are structurally forbidden.

Research intent and directional questions can change query strings only. They never contribute an
output key or schema. This is the explicit integration seam with the parallel A2 lane: E0 imports
no directive table/model and A2 need not import a provider type. E1 must split/coalesce bundles
against these same schema budgets rather than bypassing the compiler.

## 2. Accepted response and normalization boundary

E0-R1 changes provider field names to reversible aliases and E0-R2 decodes them before emitting the
provider-neutral field key. The unchanged golden response now normalizes directly; no test rewrites
provider highlights to make evidence pass.

The additive response parser consumes the frozen A0 models and proves the returned structured
field set exactly equals the request field set. Every returned value is recursively checked against
its exact admitted request schema (type, enum, bounds, required/additional properties and bounded
arrays). A settleable response requires `requestId`, `costDollars.total`, structured content and,
for each non-null field, results plus field-level grounding whose citation URLs resolve to retained
results. An all-null result may return no results and omit grounding; it is a valid paid hard miss
that retains reported cost while emitting zero candidates.

Normalization emits a provider-neutral `SynthesizedField` only when:

- the structured field value is non-null;
- that field has grounding;
- a cited retained result has a highlight or text passage with conservative lexical support for
  that exact field value/key;
- the selected evidence span occurs in its retained highlight/text context;
- the configured grounding-confidence threshold passes.

Every grounding citation produces one immutable `ExaDeepCitationAttribution` carrying field, URL,
title, confidence and `selected`/`unsupported`/`below_confidence`/`null_field` disposition. Every
selected citation produces its own provider-neutral candidate; an unrelated first highlight cannot
win over a later supporting passage. Unsupported citations remain attributable in the normalized
record/raw response but do not become evidence. Missing or unmatched URLs make the success
non-settleable; a missing grounding row fails a non-null field. Deprecated
`resolvedSearchType`/`context` and other additive response members do not control behavior.
Reported dollars are converted for the provider-neutral result but are not treated as a reservation
or final billing reconciliation.

## 3. Dispatch and failure boundary

Production `register_exa_deep_resolver()` now binds `_ExaDeepAcquisitionRequiredBackend`, which
raises a typed hard/pre-dispatch failure before credential lookup or network access. The old live
`post_exa_deep_json` function and default transport were removed. The E0 response harness remains
available only when a caller explicitly injects a provider double; it requires the exact field
schema and passes `retries=0` to that double so response/failure contracts remain executable.

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
composition. E0 creates no migration. The API-root composition contract remains provider-neutral
and now binds the disabled Exa backend until E1 supplies durable acquisition.

## 4. E0 exit-gate evidence

| E0 gate | Executable evidence |
|---|---|
| Frozen request remains stable | compiler output equals the corrected `deep_request.json`; amended A0 SHA-256 test is green |
| Free text cannot inject a field | malicious intent/query test asserts only the admitted provider alias exists |
| Alias mapping is deterministic | round-trip tests prove every ASCII alias decodes to one field key, contains no path punctuation, and is pinned in the fixed prompt |
| Current content contract only | exact wire assertion contains bounded text/highlights and no deprecated highlight knobs; over-cap values fail validation |
| Provider schema budget | exact 10-property/two-level cases pass; property 11, level 3, unsafe names, and composition keywords fail before dispatch |
| Nullable schema is deterministic | nested/constrained schema tests prove input non-mutation, one type union, and explicit enum null semantics |
| Existing spend boundary remains intact | injected transport still asserts one call and `retries=0`; no credential or paid call is used in acceptance |
| Unchanged golden normalization | recorded response normalizes both fields without mutating returned highlights |
| Paid all-null hard miss | absent/empty grounding with all-null content returns zero candidates and the exact reported cost |
| Field-faithful evidence | unrelated first highlight loses to a later supporting passage; unrelated-only citations are attributed but not materialized |
| Exact value schema | invalid primitive, range and nested required-property values fail exchange validation |
| Citation preservation | multi-citation fixture emits one immutable attribution and one candidate per supported citation |
| No resolver-time HTTP | API-root registration binds a typed disabled backend; resolution fails hard with `dispatched=false` and no credential/network path |

Verification commands are recorded in `_memory/2026-08-04-m8b-e0-r2-response-semantics.md`. All E0
tests use frozen artifacts or provider doubles. The live canary remains V1 and requires separate
user authorization after E1/E2 integration.
