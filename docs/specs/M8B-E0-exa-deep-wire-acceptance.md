# M8B E0 — Exa Search Deep wire acceptance

- **Parent roadmap:** `M8B-exa-sumble-account-deep-integration-roadmap.md`, Slice E0
- **Contract authority:** `M8B-A0-account-deep-provider-contract-acceptance.md`
- **Recorded:** 2026-08-04
- **Status:** E0-R1 request correction accepted; overall E0 remains open pending E0-R2; no live
  provider call authorized or made
- **Endpoint:** `POST https://api.exa.ai/search`
- **Official reference:** `https://exa.ai/docs/reference/search-api-guide-for-coding-agents`

E0 replaces the old synchronous `type="neural"`/unstructured-highlights wire with a Search Deep
structured contract. The 2026-08-04 critical review reopened the original closure. E0-R1 corrects
the outbound provider request; E0-R2 still owns truthful response/evidence semantics. E0 stops
before durable acquisition, snapshots, settlement, claim materialization, production composition,
or live validation.

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

## 2. Provisional response and normalization boundary — E0-R2 remains open

E0-R1 changes provider field names to reversible aliases and decodes them before emitting the
provider-neutral field key. It does not close the response defects found in review: the untouched
golden response must normalize without test mutation, all-null paid misses must settle honestly,
and evidence selection must become field-faithful while preserving citations and validating values.
Those are binding E0-R2 gates; the response behavior below is descriptive, not an E0 closure claim.

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

## 4. E0-R1 exit-gate evidence

| E0-R1 gate | Executable evidence |
|---|---|
| Frozen request remains stable | compiler output equals the corrected `deep_request.json`; amended A0 SHA-256 test is green |
| Free text cannot inject a field | malicious intent/query test asserts only the admitted provider alias exists |
| Alias mapping is deterministic | round-trip tests prove every ASCII alias decodes to one field key, contains no path punctuation, and is pinned in the fixed prompt |
| Current content contract only | exact wire assertion contains bounded text/highlights and no deprecated highlight knobs; over-cap values fail validation |
| Provider schema budget | exact 10-property/two-level cases pass; property 11, level 3, unsafe names, and composition keywords fail before dispatch |
| Nullable schema is deterministic | nested/constrained schema tests prove input non-mutation, one type union, and explicit enum null semantics |
| Existing spend boundary remains intact | injected transport still asserts one call and `retries=0`; no credential or paid call is used in acceptance |

## 5. Remaining E0-R2 gates

- the unchanged golden response produces the expected grounded fields without rewriting highlights;
- a successful all-null/no-grounding response settles as a paid hard miss rather than
  `spend_unknown`;
- a field receives only a passage that actually supports that field, not the first highlight from
  a cited page;
- returned values validate against the admitted registry schema and all grounding citations remain
  durably attributable;
- resolver-time HTTP is hard-disabled before E1 production composition.

Verification commands are recorded in `_memory/2026-08-04-m8b-e0-r1-provider-request.md`. All
E0-R1 tests use frozen artifacts or provider doubles. The live canary remains V1 and requires
separate user authorization after E1/E2 integration.
